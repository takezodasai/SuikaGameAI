using System;
using System.Collections.Generic;
using System.Diagnostics;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

// Main-thread, synchronous prediction. Never simulates the default physics scene.
// Each owner gets a fresh native world; disposal completes before the next iteration.
public sealed partial class SuikaPhysicsSimulator : IDisposable
{
    [Serializable] public class Result
    {
        public string status = "experimental", limitation;
        public bool validated_for_search = false;
        public int initial_contact_count;
        public HeuristicEvaluator.Features evaluation_features;
        public int movement_reward,cooldown_wait_reward,post_drop_reward,score_at_drop,drop_tick=-1,game_over_tick=-1;
        public UDPCommunicatorUnity.ControlledFruit current_fruit;
        public PlayerController.DropRange drop_range;
        public ValueSnapshot value_state;
        public int initial_next_fruit_type;
        public float game_over_height;
        public UDPCommunicatorUnity.BoardFruit[] initial_fruits;
        public UDPCommunicatorUnity.BoardFruit[] fruits;
        public int score, reward, physics_steps, movement_steps, post_drop_steps, merges, cooldown_wait_steps;
        public bool game_over, drop_success, source_unchanged;
        public float requested_x, applied_x, movement_seconds, fixed_delta_time, drop_cooldown_seconds, initial_cooldown_remaining;
        public double elapsed_ms, scene_create_ms, copy_ms, simulation_ms, cleanup_schedule_ms;
        public PredictionDiagnostics.Report diagnostics;
        public double reference_elapsed_ms = -1;
        public UDPCommunicatorUnity.BoardFruit[] reference_fruits;
        public int reference_score;
        public bool reference_game_over;
        [NonSerialized] public PredictionDiagnostics.Recorder trace;
    }
    public PredictionDiagnostics.Recorder Trace { get; private set; }
    readonly Scene scene;
    readonly PhysicsScene2D physics;
    readonly GameObject staging;
    readonly List<GameObject> owned = new List<GameObject>();
    readonly Dictionary<GameObject, GameObject> sourceCopies = new Dictionary<GameObject, GameObject>();
    readonly List<GameObject> pendingRemoval = new List<GameObject>();
    readonly List<PhysicsMaterial2D> materials = new List<PhysicsMaterial2D>();
    readonly Dictionary<FruitEvolution, long> ids = new Dictionary<FruitEvolution, long>();
    struct GoCandidate {public FruitEvolution fruit;public Transform transform;}
    readonly List<GoCandidate> goCandidates=new List<GoCandidate>();
    readonly List<MonoBehaviour> copyScripts=new List<MonoBehaviour>();
    readonly List<Renderer> copyRenderers=new List<Renderer>();
    readonly List<Joint2D> copyJoints=new List<Joint2D>();
    void RegisterFruit(FruitEvolution fruit,long id)
    {
        ids.Add(fruit,id);
        // These private clones never change tag. Preserve the legacy uppercase tag rule.
        if(fruit.CompareTag("Fruit"))goCandidates.Add(new GoCandidate {fruit=fruit,transform=fruit.transform});
    }
    readonly int[] scores;
    readonly float gameOverHeight;
    int score, merges;
    long generatedId = -1;
    bool disposed,simulating;
    bool SimulateNative(float dt) {if(disposed||simulating)throw new InvalidOperationException("Invalid prediction simulation lifetime");simulating=true;try{return physics.Simulate(dt);}finally{simulating=false;}}

    SuikaPhysicsSimulator(GameManager manager)
    {
        using(MctsPerformance.Measure("scene_create")) {

        scores = (int[])ScoreManager.Instance.evolutionScores.Clone();
        score = ScoreManager.Instance.GetScore();
        gameOverHeight = manager.GameOverHeight;
        scene = SceneManager.CreateScene("SuikaPrediction_" + Guid.NewGuid().ToString("N"),
            new CreateSceneParameters(LocalPhysicsMode.Physics2D));
        PredictionLifecycle.Register(scene);
        physics = scene.GetPhysicsScene2D();
        staging = new GameObject("Inactive prediction staging");
        staging.SetActive(false);
        SceneManager.MoveGameObjectToScene(staging, scene);

        }
}

    GameObject Copy(GameObject source, bool freshPrefab)
    {
        using(MctsPerformance.Measure("object_copy")) {

        // Validate BEFORE Instantiate: unknown Awake/OnEnable could have global side effects.
        // Reuse only enumeration buffers, never physics objects or solver state.
        if(MctsPerformance.ExactOptimizations)source.GetComponentsInChildren<MonoBehaviour>(true,copyScripts);
        var sourceScripts=MctsPerformance.ExactOptimizations?copyScripts:(IEnumerable<MonoBehaviour>)source.GetComponentsInChildren<MonoBehaviour>(true);
        foreach (var script in sourceScripts)
            if (script == null || !(script is FruitEvolution || script is Danse ||
                script is Fruit || script is FruitCollisionHandler))
                throw new InvalidOperationException("Unsupported prediction script on " + source.name);
        if(MctsPerformance.ExactOptimizations)source.GetComponentsInChildren<Joint2D>(true,copyJoints);
        if ((MctsPerformance.ExactOptimizations?copyJoints.Count:source.GetComponentsInChildren<Joint2D>(true).Length) != 0 || source.transform.childCount != 0)
            throw new InvalidOperationException("Prediction currently supports inspected flat collider objects only: " + source.name);
        var clone = Object.Instantiate(source, staging.transform);
        clone.transform.position = source.transform.position;
        clone.transform.rotation = source.transform.rotation;
        clone.transform.localScale = source.transform.lossyScale;
        owned.Add(clone);
        if(!freshPrefab) sourceCopies[source]=clone;
        if(MctsPerformance.ExactOptimizations){clone.GetComponentsInChildren<Renderer>(true,copyRenderers);clone.GetComponents<MonoBehaviour>(copyScripts);}
        foreach (Renderer renderer in MctsPerformance.ExactOptimizations?copyRenderers:(IEnumerable<Renderer>)clone.GetComponentsInChildren<Renderer>(true)) renderer.enabled = false;
        foreach (var script in MctsPerformance.ExactOptimizations?copyScripts:(IEnumerable<MonoBehaviour>)clone.GetComponents<MonoBehaviour>()) script.enabled = false;
        var fruit = clone.GetComponent<FruitEvolution>();
        if (fruit != null)
        {
            fruit.Simulation = this; fruit.enabled = true;
            if (!freshPrefab) fruit.CopyPredictionStateFrom(source.GetComponent<FruitEvolution>());
        }
        if (freshPrefab)
        {
            var danse = clone.GetComponent<Danse>();
            if (danse != null)
            {
                var material = danse.InitializePhysicsMaterial();
                if (material != null) materials.Add(material);
            }
        }
        if (fruit != null && Trace != null && PredictionDiagnostics.Live != null && PredictionDiagnostics.Live.aliases.ContainsKey(source.GetComponent<FruitEvolution>()))
            Trace.Watch(fruit, PredictionDiagnostics.Live.Alias(source.GetComponent<FruitEvolution>()));
        var originalBody = source.GetComponent<Rigidbody2D>();
        var body = clone.GetComponent<Rigidbody2D>();
        bool inactivePreview=fruit!=null && fruit.IsPreview && (!source.activeInHierarchy || (originalBody!=null && !originalBody.simulated));
        if (body != null && !freshPrefab)
        {
            body.position = originalBody.position;
            body.rotation = originalBody.rotation;
            body.velocity = originalBody.velocity;
            body.angularVelocity = originalBody.angularVelocity;
        }
        clone.transform.SetParent(null, true); // Already belongs to the local scene via staging.
        clone.SetActive(true);
        // Prefab assets have no solved runtime inertia/COM (grape reports inertia=0).
        // A new merged fruit must use native mass properties from the instantiated
        // enabled shape, like the real Instantiate path, not overwrite them with zeros.
        // Enabling a previously inactive Rigidbody resets its runtime velocity.
        // Restore AFTER activation, not just after Instantiate/while under staging.
        if (body != null && !freshPrefab)
        {
            body.position = originalBody.position;
            body.rotation = originalBody.rotation;
            body.velocity = originalBody.velocity;
            body.angularVelocity = originalBody.angularVelocity;
            // Runtime mass properties are not reliably serialized by Instantiate.
            if (body.bodyType == RigidbodyType2D.Dynamic)
            {
                // A NEXT is inactive or unsimulated: native getters return zero mass/inertia.
                // Its serialized component settings, already copied by Instantiate,
                // must survive until it becomes the held fruit.
                if(!inactivePreview)body.mass = originalBody.mass;
                // Held/next trigger bodies have placeholder COM/inertia. Explicitly
                // assigning them disables native recomputation when DropFruit turns
                // the shape solid (grape: inertia 1 -> actual solid 0.0963074).
                // Keep the cloned automatic properties for previews; solved board
                // bodies retain their exact runtime mass properties as before.
                if(fruit==null || !fruit.IsPreview)
                {
                    body.centerOfMass = originalBody.centerOfMass;
                    body.inertia = originalBody.inertia;
                }
            }
            // Changing mass/COM can itself change linear velocity (Box2D mass reset).
            body.velocity = originalBody.velocity;
            body.angularVelocity = originalBody.angularVelocity;
            if (originalBody.IsSleeping()) body.Sleep();
            if (body.position != originalBody.position ||
                Mathf.Abs(Mathf.DeltaAngle(body.rotation, originalBody.rotation)) > 0.0001f ||
                body.velocity != originalBody.velocity ||
                Mathf.Abs(body.angularVelocity - originalBody.angularVelocity) > Mathf.Max(0.0001f, Mathf.Abs(originalBody.angularVelocity) * 0.000001f) ||
                (!inactivePreview && (body.mass != originalBody.mass || body.inertia != originalBody.inertia)) ||
                body.gravityScale != originalBody.gravityScale || body.drag != originalBody.drag ||
                body.angularDrag != originalBody.angularDrag || body.constraints != originalBody.constraints ||
                body.bodyType != originalBody.bodyType || body.collisionDetectionMode != originalBody.collisionDetectionMode ||
                body.simulated != originalBody.simulated)
                throw new InvalidOperationException("Rigidbody clone state mismatch: " + source.name +
                    " mass=" + body.mass + "/" + originalBody.mass +
                    " inertia=" + body.inertia + "/" + originalBody.inertia +
                    " pos=" + body.position.ToString("R") + "/" + originalBody.position.ToString("R") +
                    " velocity=" + body.velocity.ToString("R") + "/" + originalBody.velocity.ToString("R") +
                    " rotation=" + body.rotation + "/" + originalBody.rotation +
                    " angular=" + body.angularVelocity + "/" + originalBody.angularVelocity);
        }
        return clone;

        }
}

    public GameObject CreateEvolved(GameObject prefab, Vector3 position)
    {
        var fruit = Copy(prefab, true);
        fruit.transform.position = position;
        fruit.transform.rotation = Quaternion.identity;
        RegisterFruit(fruit.GetComponent<FruitEvolution>(), generatedId--);
        merges++;
        return fruit;
    }
    public void AddScore(int type) { if (type >= 0 && type < scores.Length) score += scores[type]; }
    public void DeferRemoval(GameObject fruit) { pendingRemoval.Add(fruit); }
    void FlushRemoval()
    {
        using(MctsPerformance.Measure("retire_merges")) {

        // Simulate invokes collision callbacks synchronously; retain original colliders until
        // this tick finishes, like Destroy at the end of a one-physics-tick rendered frame.
        foreach (var fruit in pendingRemoval)
        {
            PredictionDiagnostics.Removed(fruit.GetComponent<FruitEvolution>(), "deactivated");
            fruit.SetActive(false);
            var evolution=fruit.GetComponent<FruitEvolution>();
            for(int i=goCandidates.Count-1;i>=0;i--)if(goCandidates[i].fruit==evolution)goCandidates.RemoveAt(i);
        }
        pendingRemoval.Clear();

        }
}
    bool IsGameOver(GameObject nextHeld)
    {
        using(MctsPerformance.Measure("go_check")) {

        if(MctsPerformance.Optimized)
        {
            foreach(var entry in goCandidates) {var fruit=entry.fruit;
                // Same conjunction as CanTriggerGameOver; cheap managed exclusions first.
                if(fruit.HasCollided && !fruit.IsPreview && !fruit.IsMerging &&
                    (MctsPerformance.ExactOptimizations?entry.transform:fruit.transform).position.y>gameOverHeight && fruit.gameObject.activeInHierarchy) return true;
            }
        }
        else foreach (var pair in ids)
            if (pair.Key.CompareTag("Fruit") && pair.Key.CanTriggerGameOver(gameOverHeight)) return true;
        // Held/NEXT objects are previews, never game-over candidates.
        return false;

        }
}
    UDPCommunicatorUnity.BoardFruit[] ReadBoard(bool metadata=false)
    {
        using(MctsPerformance.Measure("read_board")) {

        var result = new List<UDPCommunicatorUnity.BoardFruit>();
        var measured=metadata && MctsPerformance.Optimized?new List<Collider2D>():null;
        foreach (var pair in ids)
        {
            var fruit = pair.Key;
            if (!fruit.gameObject.activeSelf || fruit.IsMerging || fruit.IsPreview) continue;
            var body = fruit.GetComponent<Rigidbody2D>();
            if (body == null) throw new InvalidOperationException("Prediction board fruit has no body");
            // Read each native vector once; no simulation/callback occurs here.
            var position=MctsPerformance.ExactOptimizations?body.position:Vector2.zero;
            var velocity=MctsPerformance.ExactOptimizations?body.velocity:Vector2.zero;
            var value=new UDPCommunicatorUnity.BoardFruit { id = pair.Value, type = fruit.fruitType,
                x = MctsPerformance.ExactOptimizations?position.x:body.position.x, y = MctsPerformance.ExactOptimizations?position.y:body.position.y,
                vx = MctsPerformance.ExactOptimizations?velocity.x:body.velocity.x, vy = MctsPerformance.ExactOptimizations?velocity.y:body.velocity.y,
                angle = body.rotation, angular_velocity = body.angularVelocity, has_collided = fruit.HasCollided };
            if(measured!=null)UDPCommunicatorUnity.MeasureFruit(value,fruit,body,measured);
            result.Add(value);
        }
        if(metadata && !MctsPerformance.Optimized)
        {
            var contacts=new List<Collider2D>();
            foreach(var value in result)
                foreach(var pair in ids) if(pair.Value==value.id)
                    UDPCommunicatorUnity.MeasureFruit(value,pair.Key,pair.Key.GetComponent<Rigidbody2D>(),contacts);
        }
        result.Sort((a,b) => a.id.CompareTo(b.id));
        return result.ToArray();

        }
}

    public static Result Predict(PlayerController player, GameManager manager, float x, int postDropSteps = -1, Collider2D evaluationFloor = null)
    {
        if (!Application.isPlaying || manager.isGameOver || player.StepControlLocked)
            throw new InvalidOperationException("Prediction requires an idle, running game");
        if (float.IsNaN(x) || float.IsInfinity(x) || x < 0 || x > 1) throw new ArgumentOutOfRangeException("x");
        float dt = Time.fixedDeltaTime;
        if (postDropSteps == -1) postDropSteps = Mathf.CeilToInt(0.5f / dt);
        if (postDropSteps < 1 || postDropSteps > 5000 || dt <= 0 || Time.timeScale <= 0 ||
            player.EffectiveAIMoveSpeed <= 0 || float.IsNaN(player.EffectiveAIMoveSpeed) || float.IsInfinity(player.EffectiveAIMoveSpeed))
            throw new InvalidOperationException("Invalid prediction horizon, speed or clock");
        var range = player.GetDropRange();
        if (!range.valid) throw new InvalidOperationException(range.error);
        var before = SourceSignature(player);
        var random = UnityEngine.Random.state;
        int initialScore = ScoreManager.Instance.GetScore(), best = GameScoreStatic.maxScore;
        var timer = Stopwatch.StartNew();
        Result result;
        var simulation = new SuikaPhysicsSimulator(manager);
        double createMs = timer.Elapsed.TotalMilliseconds;
        simulation.Trace = PredictionDiagnostics.Live != null ? new PredictionDiagnostics.Recorder(manager.GameOverHeight) : null;
        try { result = simulation.Run(player, x, range, dt, postDropSteps, evaluationFloor); }
        finally { if(simulation.Trace!=null)simulation.Trace.recording=false; simulation.Dispose(); }
        result.scene_create_ms = createMs;
        result.trace = simulation.Trace;
        result.cleanup_schedule_ms = simulation.cleanupMs;
        result.elapsed_ms = timer.Elapsed.TotalMilliseconds;
        result.source_unchanged = before == SourceSignature(player) &&
            random.Equals(UnityEngine.Random.state) && ScoreManager.Instance.GetScore() == initialScore &&
            best == GameScoreStatic.maxScore;
        if (!result.source_unchanged) throw new InvalidOperationException("Prediction mutated live source");
        return result;
    }

    static string SourceSignature(PlayerController player)
    {
        var values = new List<string>();
        foreach (var fruit in Object.FindObjectsOfType<FruitEvolution>())
        {
            if (fruit.Simulation != null) continue;
            var body = fruit.GetComponent<Rigidbody2D>();
            values.Add(fruit.GetInstanceID() + ":" + JsonUtility.ToJson(new SourceBody {
                p = fruit.transform.position, q = fruit.transform.rotation,
                v = body != null ? body.velocity : Vector2.zero,
                w = body != null ? body.angularVelocity : 0,
                sleeping = body != null && body.IsSleeping(), merging = fruit.IsMerging,
                preview = fruit.IsPreview, contacted = fruit.HasCollided, simulated = body != null && body.simulated,
                gravity = body != null ? body.gravityScale : 0,
                mass = body != null ? body.mass : 0, inertia = body != null ? body.inertia : 0 }));
        }
        values.Sort(StringComparer.Ordinal);
        return string.Join("|", values) + player.transform.position.ToString("R") + ":" + player.NextDropAllowedAt.ToString("R") + ":" + player.dropCooldownSeconds.ToString("R");
    }
    [Serializable] class SourceBody { public Vector3 p; public Quaternion q; public Vector2 v; public float w; public bool sleeping, merging, preview, contacted, simulated; public float gravity, mass, inertia; }

    double cleanupMs;

    PathState InitializePath(PlayerController player,float dt)
    {
        using(MctsPerformance.Measure("root_initialize")) {

        var path=new PathState {dt=dt,speed=player.EffectiveAIMoveSpeed,cooldown=player.dropCooldownSeconds,
            nextTick=Time.fixedTimeAsDouble+dt,allowed=player.NextDropAllowedAt};
        var liveFruits = Object.FindObjectsOfType<FruitEvolution>();
        // Collider scripts and active merges cannot be reconstructed from STEP 2 JSON.
        foreach (var fruit in liveFruits)
            if (fruit.Simulation == null && fruit.IsMerging)
                throw new InvalidOperationException("Prediction unavailable during pending merge destruction; retry next frame");
        var copied = new HashSet<GameObject>();
        foreach (var collider in Object.FindObjectsOfType<Collider2D>())
        {
            if (!collider.enabled || !collider.gameObject.activeInHierarchy ||
                collider.gameObject.scene!=player.gameObject.scene || collider.GetComponent<FruitEvolution>() != null || !copied.Add(collider.gameObject)) continue;
            Copy(collider.gameObject, false);
        }
        foreach (var fruit in liveFruits)
        {
            if (fruit.Simulation != null || fruit.IsPreview) continue;
            if (fruit.GetComponent<Rigidbody2D>() == null) throw new InvalidOperationException("Live fruit missing body");
            var liveBody = fruit.GetComponent<Rigidbody2D>();
            var contacts = new List<ContactPoint2D>();
            path.initialContacts += liveBody.GetContacts(contacts);
            var clone = Copy(fruit.gameObject, false).GetComponent<FruitEvolution>();
            RegisterFruit(clone, fruit.ObservationId);
        }
        path.held = Copy(player.currentFruit, false);
        var held=path.held;
        var heldEvolution = held.GetComponent<FruitEvolution>();
        heldEvolution.IsPreview = true;
        PlayerController.PreparePreviewBody(held, false);
        // Only the visible NEXT is copied. No new random fruit is sampled.
        path.next = Copy(player.nextFruitObject, false);
        var knownNext=path.next;
        knownNext.GetComponent<FruitEvolution>().IsPreview = true;
        PlayerController.PreparePreviewBody(knownNext, true);
        var nextCollider = FruitColliderShape.Get(knownNext);
        nextCollider.isTrigger = true;
        knownNext.SetActive(false);
        foreach(var obj in owned) if(obj.CompareTag("Wall")) path.walls.AddRange(obj.GetComponents<Collider2D>());
        return path;

        }
}



    Result Run(PlayerController player, float x, PlayerController.DropRange range, float dt, int postSteps, Collider2D evaluationFloor, PathState path=null, int upcomingPrefab=-1, bool captureState=true, bool captureEvaluation=true, bool captureInitial=true)
    {
        using(MctsPerformance.Measure("advance"))
        using(var work=RunTicks(player,x,range,dt,postSteps,evaluationFloor,path,upcomingPrefab,captureState,captureEvaluation,captureInitial)) {
            Result result=null;while(work.MoveNext())if(work.Current!=null)result=work.Current;
            return result;
        }
    }
    IEnumerator<Result> RunTicks(PlayerController player, float x, PlayerController.DropRange range, float dt, int postSteps, Collider2D evaluationFloor, PathState path=null, int upcomingPrefab=-1, bool captureState=true, bool captureEvaluation=true, bool captureInitial=true)
    {

        var copyTimer = Stopwatch.StartNew();
        var result = new Result { requested_x = x, score = score, fixed_delta_time = dt,
            drop_cooldown_seconds = player.dropCooldownSeconds, initial_cooldown_remaining = player.DropCooldownRemaining,
            initial_next_fruit_type = -1, game_over_height = gameOverHeight,
            limitation = "Cold contact cache; merges retired per tick; game-over checked per tick, live per rendered Update. Not bit-exact for arbitrary active contacts or multi-tick frames." };
        path=path??InitializePath(player,dt);
        var held=path.held;var knownNext=path.next;
        // Owned clones retain components while held. Only isTrigger changes on release.
        var heldTransform=held.transform;Collider2D cachedHeldShape=null;
        if(path.terminal || knownNext==null) throw new InvalidOperationException("Path is terminal or visible NEXT is unknown");
        result.drop_cooldown_seconds=path.cooldown;
        result.initial_contact_count=path.initialContacts;
        if(captureInitial) result.initial_fruits=ReadBoard();
        result.initial_next_fruit_type=knownNext.GetComponent<FruitEvolution>().fruitType;
        result.initial_cooldown_remaining=(float)Math.Max(0,path.allowed-(path.nextTick-dt));
        var heldEvolution=held.GetComponent<FruitEvolution>();
        int initialMerges=merges;
        float target = Mathf.Lerp(range.min_x, range.max_x, x);
        int startScore = score, post = 0;
        bool dropped = false;GameObject futurePreview=null;
        var walls=path.walls;
        // The next live FixedUpdate observes fixedTime + dt, not the rendered Update clock.
        double firstTickTime = path.nextTick;
        int waitBudget = (int)Math.Ceiling(Math.Max(0, path.allowed - firstTickTime) / dt);
        int maxTicks = Mathf.CeilToInt(Mathf.Abs(target - (MctsPerformance.ExactOptimizations?heldTransform:held.transform).position.x) / (path.speed * dt)) + waitBudget + postSteps + 2;
        if (maxTicks > 10000) throw new InvalidOperationException("Prediction exceeds 10000-tick synchronous budget");
        using(MctsPerformance.Measure("sync_transforms")) Physics2D.SyncTransforms();
        if (Trace != null) Trace.Capture(score, false);
        result.copy_ms = copyTimer.Elapsed.TotalMilliseconds;
        var simulateTimer = Stopwatch.StartNew();
        for (int i = 0; i < maxTicks; i++)
        {
            using(MctsPerformance.Measure("physics_tick")) {
            int tickScore=score; bool movedThisTick=false;
            if (!dropped)
            {
                float old = (MctsPerformance.ExactOptimizations?heldTransform:held.transform).position.x;
                var p = (MctsPerformance.ExactOptimizations?heldTransform:held.transform).position;
                p.x = Mathf.MoveTowards(old, target, path.speed * dt);
                (MctsPerformance.ExactOptimizations?heldTransform:held.transform).position = p;
                using(MctsPerformance.Measure("sync_transforms")) Physics2D.SyncTransforms();
                var shape = MctsPerformance.ExactOptimizations&&cachedHeldShape!=null?cachedHeldShape:FruitColliderShape.Get(held);
                if(MctsPerformance.ExactOptimizations)cachedHeldShape=shape;
                if (shape.bounds.min.x < range.left_wall_inner || shape.bounds.max.x > range.right_wall_inner)
                    throw new InvalidOperationException("Prediction movement outside wall bounds");
                foreach (var wall in walls)
                {
                    var distance = shape.Distance(wall);
                    if (wall.enabled && (!distance.isValid || distance.isOverlapped))
                        throw new InvalidOperationException("Prediction movement overlaps wall");
                }
                if (old != p.x) { movedThisTick=true; result.movement_steps++; result.movement_seconds += dt; }
                if (p.x == target && firstTickTime + i * (double)dt < path.allowed)
                    result.cooldown_wait_steps++; // Physical time advances even while waiting at the target.
                if (p.x == target && firstTickTime + i * (double)dt >= path.allowed)
                {
                    var body = held.GetComponent<Rigidbody2D>();
                    if (body == null) body = held.AddComponent<Rigidbody2D>();
                    result.score_at_drop=score; result.drop_tick=i+1;
                    PlayerController.ReleaseFruitBody(body);
                    shape.isTrigger = false;
                    heldEvolution.IsPreview = false;
                    RegisterFruit(heldEvolution, generatedId--);
                    result.applied_x = p.x;
                    result.drop_success = dropped = true;
                    if(upcomingPrefab>=0)futurePreview=MakeFuturePreview(player,upcomingPrefab);
                    knownNext.transform.position = (MctsPerformance.ExactOptimizations?heldTransform:held.transform).position;
                    knownNext.SetActive(true);
                    // NEXT is a frozen display body. The real SpawnFruit creates a
                    // held (simulated, gravity-free) body and clamps a larger fruit.
                    PlayerController.PreparePreviewBody(knownNext, false);
                    using(MctsPerformance.Measure("sync_transforms")) Physics2D.SyncTransforms();
                    var nextRange = player.GetDropRangeForFruit(knownNext, walls);
                    if (nextRange.valid)
                    {
                        var nextPosition = knownNext.transform.position;
                        nextPosition.x = Mathf.Clamp(nextPosition.x, nextRange.min_x, nextRange.max_x);
                        knownNext.transform.position = nextPosition;
                        using(MctsPerformance.Measure("sync_transforms")) Physics2D.SyncTransforms();
                    }
                }
            }
            else { post++; }
            // A still-held movement/wait tick already synced immediately after its
            // only Transform write. Bounds/Distance checks above are read-only and
            // no Simulate/yield occurs between the two sites. Drop/post-drop ticks
            // retain their original sync. Never skip a physical update.
            if(!MctsPerformance.ExactOptimizations || dropped)
                using(MctsPerformance.Measure("sync_transforms")) Physics2D.SyncTransforms();
            using(MctsPerformance.Measure("native_physics"))
                if (!SimulateNative(dt)) throw new InvalidOperationException("Local PhysicsScene2D.Simulate failed");
            int gain=score-tickScore;
            if(dropped) result.post_drop_reward+=gain;
            else if(movedThisTick) result.movement_reward+=gain;
            else result.cooldown_wait_reward+=gain;
            if (Trace != null) Trace.Capture(score, IsGameOver(knownNext.activeSelf ? knownNext : held));
            FlushRemoval();
            result.physics_steps++;
            result.game_over = IsGameOver(knownNext.activeSelf ? knownNext : held);
            if(result.game_over) result.game_over_tick=i+1;
            } // Merge retirement and GO complete before yielding.
            if (result.game_over || (dropped && post >= postSteps)) break;
            yield return null;
        }
        GameObject nextControl = dropped ? knownNext : held;
        result.current_fruit = new UDPCommunicatorUnity.ControlledFruit {
            present = nextControl != null && nextControl.activeSelf,
            type = nextControl.GetComponent<FruitEvolution>().fruitType,
            x = nextControl.transform.position.x, y=nextControl.transform.position.y, y_known=true
        };
        result.drop_range = player.GetDropRangeForFruit(nextControl, walls);
        result.simulation_ms = simulateTimer.Elapsed.TotalMilliseconds;
        result.post_drop_steps = post;
        if(captureState) result.fruits = ReadBoard(true); result.score = score; result.reward = score - startScore;
        result.merges = merges-initialMerges;
        if(result.reward!=result.movement_reward+result.cooldown_wait_reward+result.post_drop_reward)
            throw new InvalidOperationException("Prediction reward phases do not conserve score");
        double endTickTime=firstTickTime+(result.physics_steps-1)*(double)dt;
        double nextAllowed=dropped?firstTickTime+(result.drop_tick-1)*(double)dt+path.cooldown:path.allowed;
        path.held=nextControl;path.nextTick=endTickTime+dt;path.allowed=nextAllowed;path.terminal=result.game_over;
        if(dropped) path.next=futurePreview;
        if(evaluationFloor!=null && captureEvaluation)
        {
            result.evaluation_features=ReadEvaluationFeatures(evaluationFloor,range);
            double endTime=firstTickTime+(result.physics_steps-1)*(double)dt;
            double allowed=dropped?firstTickTime+(result.drop_tick-1)*(double)dt+path.cooldown:path.allowed;
            result.value_state=new ValueSnapshot {fruits=result.fruits,current_fruit=result.current_fruit,
                next_fruit_type=dropped?(path.next!=null?path.next.GetComponent<FruitEvolution>().fruitType:-1):result.initial_next_fruit_type,score=score,game_over=result.game_over,
                drop_cooldown_remaining=(float)Math.Max(0,allowed-endTime),ai_move_speed=path.speed,
                fixed_delta_time=dt,geometry=new[]{range.left_wall_inner,range.right_wall_inner,result.evaluation_features.floor_y,gameOverHeight}};
        }
        yield return result;
}
    HeuristicEvaluator.Features ReadEvaluationFeatures(Collider2D floor,PlayerController.DropRange range)
    {
        using(MctsPerformance.Measure("heuristic_features")) {

        var features=new List<HeuristicEvaluator.FruitFeature>();
        var localFloor=sourceCopies[floor.gameObject].GetComponent<Collider2D>();
        foreach(var pair in ids)
        {
            var f=pair.Key;
            if(!f.gameObject.activeInHierarchy || f.IsPreview || f.IsMerging) continue;
            var shape=FruitColliderShape.Get(f.gameObject);
            var contacts=new List<ContactPoint2D>();
            f.GetComponent<Rigidbody2D>().GetContacts(contacts);
            bool touching=false;
            foreach(var contact in contacts)
            {
                var other=contact.collider.gameObject==f.gameObject?contact.otherCollider:contact.collider;
                if(other==null || !other.enabled || other.isTrigger || !other.gameObject.activeInHierarchy) continue;
                var fruit=other.GetComponent<FruitEvolution>();
                if(fruit!=null && (fruit.IsPreview || fruit.IsMerging)) continue;
                if(fruit!=null || other.CompareTag("Wall") || other.gameObject==localFloor.gameObject) touching=true;
            }
            features.Add(new HeuristicEvaluator.FruitFeature { id=pair.Value,contacted=touching,has_collided=f.HasCollided,
                min_x=shape.bounds.min.x,max_x=shape.bounds.max.x,top_y=shape.bounds.max.y,center_y=f.transform.position.y });
        }
        return new HeuristicEvaluator.Features {fruits=features.ToArray(),floor_y=localFloor.bounds.max.y,go_y=gameOverHeight,
            left_x=range.left_wall_inner,right_x=range.right_wall_inner};

        }
}
    public void Dispose()
    {
        using(MctsPerformance.Measure("cleanup_schedule")) {

        if (disposed) return;
        if(simulating)throw new InvalidOperationException("Prediction disposal during physics callbacks is forbidden");
        disposed = true;
        var timer = Stopwatch.StartNew();
        foreach (var obj in owned) if (obj != null) obj.SetActive(false);
        if(PredictionLifecycle.Legacy) {
            foreach (var material in materials) if (material != null) Object.Destroy(material);
            PredictionLifecycle.Release(scene);
        } else {
            PredictionLifecycle.Release(scene);
            // Only freshly allocated prediction materials: never shared prefab/live assets.
            foreach (var material in materials) if (material != null) Object.DestroyImmediate(material);
            owned.Clear();materials.Clear();sourceCopies.Clear();pendingRemoval.Clear();ids.Clear();goCandidates.Clear();Trace=null;
        }
        copyScripts.Clear();copyRenderers.Clear();copyJoints.Clear(); // Do not retain destroyed component wrappers.
        cleanupMs = timer.Elapsed.TotalMilliseconds;

        }
}
}
