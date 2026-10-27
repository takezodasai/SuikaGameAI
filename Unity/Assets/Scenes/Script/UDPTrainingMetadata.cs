using System;
using System.Collections.Generic;
using UnityEngine;

// Read-only collection telemetry. No Simulate, SyncTransforms, collision or RNG writes.
public partial class UDPCommunicatorUnity
{
    bool trainingMetadataEnabled, requestedEnvironment;
    readonly Dictionary<int,string> fruitProfileCache = new Dictionary<int,string>();
    readonly Dictionary<string,PhysicsProfile> physicsProfiles = new Dictionary<string,PhysicsProfile>();
    readonly List<Collider2D> observationContacts = new List<Collider2D>();

    [Serializable] public class ShapeDescription
    {
        public string shape, capsule_direction;
        public Vector2 offset, size;
        public float radius, edge_radius, density, friction, restitution;
        public bool trigger, material_known;
        public Vector3 scale;
    }
    [Serializable] public class PhysicsProfile
    {
        public string id, body_type, collision_detection, interpolation, constraints, sleep_mode;
        public bool body_known, simulated, use_auto_mass;
        public float mass, inertia, gravity_scale, linear_drag, angular_drag;
        public Vector2 center_of_mass;
        public ShapeDescription[] colliders;
    }
    [Serializable] public class StaticShape
    {
        public string role;
        public Vector3 position,scale;
        public float angle;
        public ShapeDescription[] colliders;
        public Vector3 bounds_min,bounds_max;
    }
    [Serializable] public class FruitAsset
    { public int type; public string physics_profile_id,game_object_tag; public bool is_prefab_asset = true; }
    [Serializable] public class TrainingEnvironment
    {
        public int schema_version = 1;
        public string rules_version = "step8e-all-fruit-go-v2";
        public string unity_version, application_version, build_guid, simulation_mode;
        public string game_over_rule = "Update: live Fruit tag, !preview, !merging, HasCollided, center.y > game_over_y";
        public string units = "world units, seconds, degrees, kg; Unity 2D inertia kg*world_unit^2";
        public string limitation = "No solver/contact impulse cache or Unity Random.state. Prefab profiles are asset values; runtime profile IDs describe effective instantiated settings.";
        public float game_over_screen_ratio,game_over_y,fixed_delta_time,maximum_delta_time,drop_cooldown_seconds,ai_move_speed,keyboard_speed;
        public Vector3 held_offset;
        public Vector2 gravity;
        public int velocity_iterations,position_iterations;
        public float default_contact_offset,velocity_threshold,max_translation_speed,max_rotation_speed,linear_sleep_tolerance,angular_sleep_tolerance,time_to_sleep;
        public bool auto_sync_transforms;
        public StaticShape[] boundaries;
        public FruitAsset[] fruit_assets;
        public PhysicsProfile[] physics_profiles;
        public int[] evolution_scores;
        public string[] layer_collision_masks;
    }
    public partial class Observation
    {
        public string environment_request_id;public bool metadata_request_ids_supported=true;public bool collection_budget_supported=true;public int collection_time_limit_seconds=240;
        public int prediction_scenes,prediction_pending_unloads;
        public int metadata_schema_version=1, merging_fruit_count;
        public bool episode_statistics_known;
        public int episode_merge_count,episode_max_fruit_type;
        public bool training_metadata_known;
        public double snapshot_fixed_time,snapshot_game_time,snapshot_realtime;
        public string snapshot_phase;
        public TrainingEnvironment environment;
    }
    public partial class BoardFruit
    {
        public bool observation_metadata_known,touching,sleeping,is_merging;
        public string physics_profile_id;
        public float half_width,half_height,collider_offset_x,collider_offset_y;
        public bool collider_measurement_known;
    }
    public partial class ControlledFruit { public float y; public bool y_known; }

    ShapeDescription[] DescribeShapes(GameObject source)
    {
        var values=new List<ShapeDescription>();
        foreach(var c in source.GetComponents<Collider2D>())
        {
            if(!c.enabled) continue;
            var material=c.sharedMaterial;
            var shape=new ShapeDescription {shape=c.GetType().Name,offset=c.offset,trigger=c.isTrigger,
                scale=c.transform.lossyScale,density=c.density,material_known=material!=null,
                friction=material!=null?material.friction:0,restitution=material!=null?material.bounciness:0};
            if(c is CircleCollider2D circle) shape.radius=circle.radius;
            else if(c is CapsuleCollider2D capsule) {shape.size=capsule.size;shape.capsule_direction=capsule.direction.ToString();}
            else if(c is BoxCollider2D box) {shape.size=box.size;shape.edge_radius=box.edgeRadius;}
            // Unknown shapes keep their actual type, never masquerade as a circle.
            values.Add(shape);
        }
        return values.ToArray();
    }
    string RegisterPhysicsProfile(GameObject source)
    {
        var body=source.GetComponent<Rigidbody2D>();
        var profile=new PhysicsProfile {colliders=DescribeShapes(source),body_known=body!=null};
        if(body!=null)
        {
            profile.mass=body.mass;profile.inertia=body.inertia;profile.center_of_mass=body.centerOfMass;
            profile.gravity_scale=body.gravityScale;profile.linear_drag=body.drag;profile.angular_drag=body.angularDrag;
            profile.body_type=body.bodyType.ToString();profile.collision_detection=body.collisionDetectionMode.ToString();
            profile.interpolation=body.interpolation.ToString();profile.constraints=body.constraints.ToString();
            profile.sleep_mode=body.sleepMode.ToString();profile.simulated=body.simulated;profile.use_auto_mass=body.useAutoMass;
        }
        string json=JsonUtility.ToJson(profile);
        // Profile IDs describe settings, not fruit identity or future spawn information.
        string id=Hash128.Compute(json).ToString();
        if(!physicsProfiles.ContainsKey(id)) {profile.id=id;physicsProfiles.Add(id,profile);}
        return id;
    }
    void FillFruitMetadata(BoardFruit value,FruitEvolution fruit,Rigidbody2D body)
    {
        if(!trainingMetadataEnabled) return;
        MeasureFruit(value,fruit,body,observationContacts);
        // Settings are constant during this collection. Clear instance cache on Reset.
        int key=fruit.GetInstanceID();
        if(!fruitProfileCache.TryGetValue(key,out string profile))
        {
            profile=RegisterPhysicsProfile(fruit.gameObject);
            var active=FruitColliderShape.Get(fruit.gameObject);
            if(active!=null && active.sharedMaterial!=null) fruitProfileCache.Add(key,profile);
        }
        value.physics_profile_id=profile;
    }
    // The identical read-only measurements are used in both physics scenes.
    public static void MeasureFruit(BoardFruit value,FruitEvolution fruit,Rigidbody2D body,List<Collider2D> contacts)
    {
        value.observation_metadata_known=true;value.sleeping=body.IsSleeping();value.is_merging=fruit.IsMerging;
        contacts.Clear();value.touching=body.GetContacts(contacts)>0;
        var c=FruitColliderShape.Get(fruit.gameObject);
        if(c!=null)
        {
            value.collider_measurement_known=true;
            value.half_width=c.bounds.extents.x;value.half_height=c.bounds.extents.y;
            Vector3 offset=c.transform.TransformVector(c.offset);
            value.collider_offset_x=offset.x;value.collider_offset_y=offset.y;
        }
    }
    StaticShape DescribeBoundary(string role,Collider2D collider)
    {
        if(collider==null) return new StaticShape {role=role,colliders=new ShapeDescription[0]};
        return new StaticShape {role=role,position=collider.transform.position,scale=collider.transform.lossyScale,
            angle=collider.transform.eulerAngles.z,colliders=DescribeShapes(collider.gameObject),
            bounds_min=collider.bounds.min,bounds_max=collider.bounds.max};
    }
    TrainingEnvironment CaptureTrainingEnvironment()
    {
        var assets=new List<FruitAsset>();
        var database=EvolutionDatabase.Instance;
        if(database!=null)
            for(int i=0;i<database.evolutionPrefabs.Length;i++)
                if(database.evolutionPrefabs[i]!=null) assets.Add(new FruitAsset {type=i,physics_profile_id=RegisterPhysicsProfile(database.evolutionPrefabs[i]),game_object_tag=database.evolutionPrefabs[i].tag});
        var walls=new List<StaticShape>();
        // Match the controller's existing Wall-tag scan; retain all wall geometry.
        walls.Add(DescribeBoundary("floor",planningFloor));
        foreach(var c in FindObjectsOfType<Collider2D>())
            if(c.enabled && c.CompareTag("Wall") && c.gameObject.scene==gameObject.scene) walls.Add(DescribeBoundary("wall",c));
        var masks=new string[32];for(int i=0;i<32;i++) masks[i]=((uint)Physics2D.GetLayerCollisionMask(i)).ToString("X8");
        return new TrainingEnvironment {
            unity_version=Application.unityVersion,application_version=Application.version,build_guid=Application.buildGUID,
            game_over_screen_ratio=gameManager.gameOverScreenRatio,game_over_y=gameManager.GameOverHeight,
            fixed_delta_time=Time.fixedDeltaTime,maximum_delta_time=Time.maximumDeltaTime,
            gravity=Physics2D.gravity,velocity_iterations=Physics2D.velocityIterations,position_iterations=Physics2D.positionIterations,
            simulation_mode=Physics2D.simulationMode.ToString(),auto_sync_transforms=Physics2D.autoSyncTransforms,
            default_contact_offset=Physics2D.defaultContactOffset,velocity_threshold=Physics2D.velocityThreshold,
            max_translation_speed=Physics2D.maxTranslationSpeed,max_rotation_speed=Physics2D.maxRotationSpeed,
            linear_sleep_tolerance=Physics2D.linearSleepTolerance,angular_sleep_tolerance=Physics2D.angularSleepTolerance,time_to_sleep=Physics2D.timeToSleep,
            drop_cooldown_seconds=playerController.dropCooldownSeconds,ai_move_speed=playerController.EffectiveAIMoveSpeed,
            keyboard_speed=playerController.speed,held_offset=playerController.heldFruitOffset,boundaries=walls.ToArray(),
            fruit_assets=assets.ToArray(),physics_profiles=new List<PhysicsProfile>(physicsProfiles.Values).ToArray(),
            evolution_scores=(int[])ScoreManager.Instance.evolutionScores.Clone(),layer_collision_masks=masks
        };
    }
    void FillTrainingSnapshot(Observation observation)
    {
        observation.prediction_scenes=PredictionLifecycle.RetainedScenes;observation.prediction_pending_unloads=PredictionLifecycle.Pending;
        observation.training_metadata_known=trainingMetadataEnabled;
        observation.snapshot_fixed_time=Time.fixedTimeAsDouble;observation.snapshot_game_time=Time.timeAsDouble;
        observation.snapshot_realtime=Time.realtimeSinceStartupAsDouble;
        observation.snapshot_phase="SendPacket main-thread; may be inside collision callback, not guaranteed settled";
        if(requestedEnvironment) {requestedEnvironment=false;observation.environment=CaptureTrainingEnvironment();}
    }
}
