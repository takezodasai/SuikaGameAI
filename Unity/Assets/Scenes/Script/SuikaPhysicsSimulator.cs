using System;
using System.Collections.Generic;
using System.Diagnostics;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

// Main-thread, synchronous prediction. Never simulates the default physics scene.
// One instance owns one local world; Dispose disables it before asynchronous scene unload.
public sealed class SuikaPhysicsSimulator : IDisposable
{
    [Serializable] public class Result
    {
        public string status = "experimental", limitation;
        public bool validated_for_search = false;
        public int initial_contact_count;
        public UDPCommunicatorUnity.BoardFruit[] initial_fruits;
        public UDPCommunicatorUnity.BoardFruit[] fruits;
        public int score, reward, physics_steps, movement_steps, post_drop_steps, merges;
        public bool game_over, drop_success, source_unchanged;
        public float requested_x, applied_x, movement_seconds, fixed_delta_time;
        public double elapsed_ms;
    }
    readonly Scene scene;
    readonly PhysicsScene2D physics;
    readonly GameObject staging;
    readonly List<GameObject> owned = new List<GameObject>();
    readonly List<GameObject> pendingRemoval = new List<GameObject>();
    readonly List<PhysicsMaterial2D> materials = new List<PhysicsMaterial2D>();
    readonly Dictionary<FruitEvolution, long> ids = new Dictionary<FruitEvolution, long>();
    readonly int[] scores;
    readonly float gameOverHeight;
    int score, merges;
    long generatedId = -1;
    bool disposed;

    SuikaPhysicsSimulator(GameManager manager)
    {
        scores = (int[])ScoreManager.Instance.evolutionScores.Clone();
        score = ScoreManager.Instance.GetScore();
        gameOverHeight = manager.GameOverHeight;
        scene = SceneManager.CreateScene("SuikaPrediction_" + Guid.NewGuid().ToString("N"),
            new CreateSceneParameters(LocalPhysicsMode.Physics2D));
        physics = scene.GetPhysicsScene2D();
        staging = new GameObject("Inactive prediction staging");
        staging.SetActive(false);
        SceneManager.MoveGameObjectToScene(staging, scene);
    }

    GameObject Copy(GameObject source, bool initializeMaterial)
    {
        // Validate BEFORE Instantiate: unknown Awake/OnEnable could have global side effects.
        foreach (var script in source.GetComponentsInChildren<MonoBehaviour>(true))
            if (script == null || !(script is FruitEvolution || script is Danse ||
                script is Fruit || script is FruitCollisionHandler))
                throw new InvalidOperationException("Unsupported prediction script on " + source.name);
        if (source.GetComponentsInChildren<Joint2D>(true).Length != 0 || source.transform.childCount != 0)
            throw new InvalidOperationException("Prediction currently supports inspected flat collider objects only: " + source.name);
        var clone = Object.Instantiate(source, staging.transform);
        clone.transform.position = source.transform.position;
        clone.transform.rotation = source.transform.rotation;
        clone.transform.localScale = source.transform.lossyScale;
        owned.Add(clone);
        foreach (Renderer renderer in clone.GetComponentsInChildren<Renderer>(true)) renderer.enabled = false;
        foreach (var script in clone.GetComponents<MonoBehaviour>()) script.enabled = false;
        var fruit = clone.GetComponent<FruitEvolution>();
        if (fruit != null) { fruit.Simulation = this; fruit.enabled = true; }
        if (initializeMaterial)
        {
            var danse = clone.GetComponent<Danse>();
            if (danse != null)
            {
                var material = danse.InitializePhysicsMaterial();
                if (material != null) materials.Add(material);
            }
        }
        var originalBody = source.GetComponent<Rigidbody2D>();
        var body = clone.GetComponent<Rigidbody2D>();
        if (body != null)
        {
            body.position = originalBody.position;
            body.rotation = originalBody.rotation;
            body.velocity = originalBody.velocity;
            body.angularVelocity = originalBody.angularVelocity;
        }
        clone.transform.SetParent(null, true); // Already belongs to the local scene via staging.
        clone.SetActive(true);
        // Enabling a previously inactive Rigidbody resets its runtime velocity.
        // Restore AFTER activation, not just after Instantiate/while under staging.
        if (body != null)
        {
            body.position = originalBody.position;
            body.rotation = originalBody.rotation;
            body.velocity = originalBody.velocity;
            body.angularVelocity = originalBody.angularVelocity;
            // Runtime mass properties are not reliably serialized by Instantiate.
            if (body.bodyType == RigidbodyType2D.Dynamic)
            {
                body.mass = originalBody.mass;
                body.centerOfMass = originalBody.centerOfMass;
                body.inertia = originalBody.inertia;
            }
            // Changing mass/COM can itself change linear velocity (Box2D mass reset).
            body.velocity = originalBody.velocity;
            body.angularVelocity = originalBody.angularVelocity;
            if (originalBody.IsSleeping()) body.Sleep();
            if (body.position != originalBody.position ||
                Mathf.Abs(Mathf.DeltaAngle(body.rotation, originalBody.rotation)) > 0.0001f ||
                body.velocity != originalBody.velocity ||
                Mathf.Abs(body.angularVelocity - originalBody.angularVelocity) > Mathf.Max(0.0001f, Mathf.Abs(originalBody.angularVelocity) * 0.000001f) ||
                body.mass != originalBody.mass || body.inertia != originalBody.inertia ||
                body.gravityScale != originalBody.gravityScale || body.drag != originalBody.drag ||
                body.angularDrag != originalBody.angularDrag || body.constraints != originalBody.constraints ||
                body.bodyType != originalBody.bodyType || body.collisionDetectionMode != originalBody.collisionDetectionMode)
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

    public GameObject CreateEvolved(GameObject prefab, Vector3 position)
    {
        var fruit = Copy(prefab, true);
        fruit.transform.position = position;
        fruit.transform.rotation = Quaternion.identity;
        ids.Add(fruit.GetComponent<FruitEvolution>(), generatedId--);
        merges++;
        return fruit;
    }
    public void AddScore(int type) { if (type >= 0 && type < scores.Length) score += scores[type]; }
    public void DeferRemoval(GameObject fruit) { pendingRemoval.Add(fruit); }
    void FlushRemoval()
    {
        // Simulate invokes collision callbacks synchronously; retain original colliders until
        // this tick finishes, like Destroy at the end of a one-physics-tick rendered frame.
        foreach (var fruit in pendingRemoval) fruit.SetActive(false);
        pendingRemoval.Clear();
    }
    bool IsGameOver(GameObject nextHeld)
    {
        foreach (var pair in ids)
            if (pair.Key.gameObject.activeSelf && pair.Key.CompareTag("Fruit") &&
                pair.Key.transform.position.y > gameOverHeight) return true;
        return nextHeld != null && nextHeld.CompareTag("Fruit") && nextHeld.transform.position.y > gameOverHeight;
    }
    UDPCommunicatorUnity.BoardFruit[] ReadBoard()
    {
        var result = new List<UDPCommunicatorUnity.BoardFruit>();
        foreach (var pair in ids)
        {
            var fruit = pair.Key;
            if (!fruit.gameObject.activeSelf || fruit.IsMerging || fruit.IsPreview) continue;
            var body = fruit.GetComponent<Rigidbody2D>();
            if (body == null) throw new InvalidOperationException("Prediction board fruit has no body");
            result.Add(new UDPCommunicatorUnity.BoardFruit { id = pair.Value, type = fruit.fruitType,
                x = body.position.x, y = body.position.y, vx = body.velocity.x, vy = body.velocity.y,
                angle = body.rotation, angular_velocity = body.angularVelocity });
        }
        result.Sort((a,b) => a.id.CompareTo(b.id));
        return result.ToArray();
    }

    public static Result Predict(PlayerController player, GameManager manager, float x, int postDropSteps = -1)
    {
        if (!Application.isPlaying || manager.isGameOver || player.StepControlLocked)
            throw new InvalidOperationException("Prediction requires an idle, running game");
        if (float.IsNaN(x) || float.IsInfinity(x) || x < 0 || x > 1) throw new ArgumentOutOfRangeException("x");
        float dt = Time.fixedDeltaTime;
        if (postDropSteps == -1) postDropSteps = Mathf.CeilToInt(0.5f / dt);
        if (postDropSteps < 1 || postDropSteps > 5000 || dt <= 0 || Time.timeScale <= 0 ||
            player.aiMoveSpeed <= 0 || float.IsNaN(player.aiMoveSpeed) || float.IsInfinity(player.aiMoveSpeed))
            throw new InvalidOperationException("Invalid prediction horizon, speed or clock");
        var range = player.GetDropRange();
        if (!range.valid) throw new InvalidOperationException(range.error);
        var before = SourceSignature(player);
        var random = UnityEngine.Random.state;
        int initialScore = ScoreManager.Instance.GetScore(), best = GameScoreStatic.maxScore;
        var timer = Stopwatch.StartNew();
        Result result;
        using (var simulation = new SuikaPhysicsSimulator(manager))
            result = simulation.Run(player, x, range, dt, postDropSteps);
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
                sleeping = body != null && body.IsSleeping(), merging = fruit.IsMerging }));
        }
        values.Sort(StringComparer.Ordinal);
        return string.Join("|", values) + player.transform.position.ToString("R");
    }
    [Serializable] class SourceBody { public Vector3 p; public Quaternion q; public Vector2 v; public float w; public bool sleeping, merging; }

    Result Run(PlayerController player, float x, PlayerController.DropRange range, float dt, int postSteps)
    {
        var result = new Result { requested_x = x, score = score, fixed_delta_time = dt,
            limitation = "Cold contact cache; merges retired per tick; game-over checked per tick, live per rendered Update. Not bit-exact for arbitrary active contacts or multi-tick frames." };
        var liveFruits = Object.FindObjectsOfType<FruitEvolution>();
        // Collider scripts and active merges cannot be reconstructed from STEP 2 JSON.
        foreach (var fruit in liveFruits)
            if (fruit.Simulation == null && fruit.IsMerging)
                throw new InvalidOperationException("Prediction unavailable during pending merge destruction; retry next frame");
        var copied = new HashSet<GameObject>();
        foreach (var collider in Object.FindObjectsOfType<Collider2D>())
        {
            if (!collider.enabled || !collider.gameObject.activeInHierarchy ||
                collider.GetComponent<FruitEvolution>() != null || !copied.Add(collider.gameObject)) continue;
            Copy(collider.gameObject, false);
        }
        foreach (var fruit in liveFruits)
        {
            if (fruit.Simulation != null || fruit.IsPreview) continue;
            if (fruit.GetComponent<Rigidbody2D>() == null) throw new InvalidOperationException("Live fruit missing body");
            var liveBody = fruit.GetComponent<Rigidbody2D>();
            var contacts = new List<ContactPoint2D>();
            result.initial_contact_count += liveBody.GetContacts(contacts);
            var clone = Copy(fruit.gameObject, false).GetComponent<FruitEvolution>();
            ids.Add(clone, fruit.ObservationId);
        }
        result.initial_fruits = ReadBoard();
        var held = Copy(player.currentFruit, false);
        var heldEvolution = held.GetComponent<FruitEvolution>();
        heldEvolution.IsPreview = true;
        // Only the visible NEXT is copied. No new random fruit is sampled.
        var knownNext = Copy(player.nextFruitObject, false);
        knownNext.GetComponent<FruitEvolution>().IsPreview = true;
        var nextCollider = knownNext.GetComponent<PolygonCollider2D>();
        nextCollider.isTrigger = true;
        knownNext.SetActive(false);
        float target = Mathf.Lerp(range.min_x, range.max_x, x);
        int startScore = score, post = 0;
        bool dropped = false;
        var walls = new List<Collider2D>();
        foreach (var obj in owned)
            if (obj.CompareTag("Wall")) walls.AddRange(obj.GetComponents<Collider2D>());
        int maxTicks = Mathf.CeilToInt(Mathf.Abs(target - held.transform.position.x) / (player.aiMoveSpeed * dt)) + postSteps + 2;
        if (maxTicks > 10000) throw new InvalidOperationException("Prediction exceeds 10000-tick synchronous budget");
        for (int i = 0; i < maxTicks; i++)
        {
            if (!dropped)
            {
                float old = held.transform.position.x;
                var p = held.transform.position;
                p.x = Mathf.MoveTowards(old, target, player.aiMoveSpeed * dt);
                held.transform.position = p;
                Physics2D.SyncTransforms();
                var shape = held.GetComponent<PolygonCollider2D>();
                if (shape.bounds.min.x < range.left_wall_inner || shape.bounds.max.x > range.right_wall_inner)
                    throw new InvalidOperationException("Prediction movement outside wall bounds");
                foreach (var wall in walls)
                {
                    var distance = shape.Distance(wall);
                    if (wall.enabled && (!distance.isValid || distance.isOverlapped))
                        throw new InvalidOperationException("Prediction movement overlaps wall");
                }
                if (old != p.x) { result.movement_steps++; result.movement_seconds += dt; }
                if (p.x == target)
                {
                    var body = held.GetComponent<Rigidbody2D>();
                    if (body == null) body = held.AddComponent<Rigidbody2D>();
                    body.gravityScale = 1;
                    shape.isTrigger = false;
                    heldEvolution.IsPreview = false;
                    ids.Add(heldEvolution, generatedId--);
                    result.applied_x = p.x;
                    result.drop_success = dropped = true;
                    knownNext.transform.position = held.transform.position;
                    knownNext.SetActive(true);
                    // STEP 3.5's new-preview clamp affects no dynamic body (trigger-only).
                }
            }
            else { post++; }
            Physics2D.SyncTransforms();
            if (!physics.Simulate(dt)) throw new InvalidOperationException("Local PhysicsScene2D.Simulate failed");
            FlushRemoval();
            result.physics_steps++;
            result.game_over = IsGameOver(knownNext.activeSelf ? knownNext : held);
            if (result.game_over || (dropped && post >= postSteps)) break;
        }
        result.post_drop_steps = post;
        result.fruits = ReadBoard(); result.score = score; result.reward = score - startScore;
        result.merges = merges;
        return result;
    }
    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        foreach (var obj in owned) if (obj != null) obj.SetActive(false);
        foreach (var material in materials) if (material != null) Object.Destroy(material);
        if (scene.IsValid()) SceneManager.UnloadSceneAsync(scene);
    }
}
