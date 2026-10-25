using System;
using System.Collections.Generic;
using UnityEngine;

public sealed partial class SuikaPhysicsSimulator
{
    sealed class PathState
    {
        public GameObject held,next;
        public readonly List<Collider2D> walls=new List<Collider2D>();
        public float dt,speed,cooldown;
        public double nextTick,allowed;
        public int initialContacts;
        public bool terminal;
    }
    GameObject MakeFuturePreview(PlayerController player,int prefabIndex)
    {
        if(prefabIndex<0 || prefabIndex>=player.fruits.Length || player.fruits[prefabIndex]==null)
            throw new ArgumentOutOfRangeException("prefabIndex");
        // A declared chance outcome, never Unity Random or the live hidden NEXT.
        var fruit=Copy(player.fruits[prefabIndex],true);
        fruit.GetComponent<FruitEvolution>().IsPreview=true;
        PlayerController.PreparePreviewBody(fruit,true);FruitColliderShape.Get(fruit).isTrigger=true;
        fruit.SetActive(false);return fruit;
    }
    // A native world is the continuation state. Solver cache cannot be serialized to JSON.
    public sealed class PathSession : IDisposable
    {
        readonly SuikaPhysicsSimulator owner;
        readonly PlayerController player;
        readonly Collider2D floor;
        readonly PathState state;
        bool closed;
        public int Score {get {return owner.score;}}
        public bool GameOver {get {return state.terminal;}}
        public bool CanAcceptAction {get {return !closed && !state.terminal && state.held!=null && state.held.activeInHierarchy && state.next!=null;}}
        public double GameTime {get {return state.nextTick-state.dt;}}
        public int TotalTicks {get;private set;}
        public int BoundaryWaitTicks {get;private set;}
        public int BoundaryWaitReward {get;private set;}
        public int BoundaryWaitMerges {get;private set;}
        public int SceneHandle {get {return owner.scene.handle;}}
        public PathSession(PlayerController player,GameManager manager,Collider2D floor)
        {
            if(!Application.isPlaying || manager.isGameOver || player.currentFruit==null || player.nextFruitObject==null)
                throw new InvalidOperationException("Path root requires a running live board");
            if(Time.fixedDeltaTime<=0 || player.EffectiveAIMoveSpeed<=0 || float.IsNaN(player.EffectiveAIMoveSpeed) || float.IsInfinity(player.EffectiveAIMoveSpeed)) throw new InvalidOperationException("Invalid path clock/speed");
            this.player=player;this.floor=floor;owner=new SuikaPhysicsSimulator(manager);
            try {state=owner.InitializePath(player,Time.fixedDeltaTime);}
            catch {owner.Dispose();throw;}
        }
        // Rebuild a cold native root from this frozen native state, never from a live
        // board which may advance between iterator resumes. Solver caches remain a
        // documented limitation, identical to the existing root-copy limitation.
        public Collider2D LocalFloor { get { return owner.sourceCopies[floor.gameObject].GetComponent<Collider2D>(); } }
        public PathSession Fork(GameManager manager) { if(closed)throw new ObjectDisposedException("PathSession");return new PathSession(this,manager); }
        PathSession(PathSession source,GameManager manager)
        {
            using(MctsPerformance.Measure("path_fork")) {
            player=source.player;floor=source.LocalFloor;owner=new SuikaPhysicsSimulator(manager);
            try {
                owner.score=source.owner.score;owner.generatedId=source.owner.generatedId;
                foreach(var obj in source.owner.owned)
                    if(obj.activeInHierarchy && obj.GetComponent<FruitEvolution>()==null)owner.Copy(obj,false);
                foreach(var pair in source.owner.ids)
                    if(pair.Key.gameObject.activeInHierarchy && !pair.Key.IsPreview && !pair.Key.IsMerging)
                        owner.RegisterFruit(owner.Copy(pair.Key.gameObject,false).GetComponent<FruitEvolution>(),pair.Value);
                state=new PathState {held=owner.Copy(source.state.held,false),next=source.state.next==null?null:owner.Copy(source.state.next,false),
                    dt=source.state.dt,speed=source.state.speed,cooldown=source.state.cooldown,
                    nextTick=source.state.nextTick,allowed=source.state.allowed,terminal=source.state.terminal,initialContacts=source.state.initialContacts};
                if(state.next!=null)state.next.SetActive(false);
                foreach(var obj in owner.owned)if(obj.activeInHierarchy && obj.CompareTag("Wall"))state.walls.AddRange(obj.GetComponents<Collider2D>());
                Physics2D.SyncTransforms();
            } catch {owner.Dispose();throw;}
            }
        }
        public Dictionary<long,string> CaptureIdAliases()
        {var map=new Dictionary<long,string>();foreach(var pair in owner.ids)if(pair.Key.gameObject.activeInHierarchy)map[pair.Value]=owner.Trace.Alias(pair.Key);return map;}
        public PredictionDiagnostics.Frame CaptureFrame()
        {
            if(owner.Trace==null)throw new InvalidOperationException("Enable aliases before capture");
            owner.Trace.frames.Clear();owner.Trace.Capture(Score,GameOver);return owner.Trace.frames[0];
        }
        public void EnableTrace()
        {
            owner.Trace=new PredictionDiagnostics.Recorder(owner.gameOverHeight);
            foreach(var pair in owner.ids)owner.Trace.Watch(pair.Key,"f"+pair.Value);
            owner.Trace.Watch(state.held.GetComponent<FruitEvolution>(),"f"+player.currentFruit.GetComponent<FruitEvolution>().ObservationId);
        }
        // Diagnostic alias matching only; does not restore or modify physical state.
        public void EnableContinuationTrace(ValueSnapshot actual,long heldId)
        {
            if(owner.Trace!=null)owner.Trace.recording=false;
            owner.Trace=new PredictionDiagnostics.Recorder(owner.gameOverHeight);
            var remaining=new List<UDPCommunicatorUnity.BoardFruit>(actual.fruits);
            foreach(var pair in owner.ids)
            {
                var f=pair.Key;if(!f.gameObject.activeInHierarchy||f.IsPreview||f.IsMerging)continue;
                UDPCommunicatorUnity.BoardFruit best=null;float distance=float.PositiveInfinity;
                foreach(var a in remaining)
                {
                    if(a.type!=f.fruitType)continue;
                    if(pair.Value>0){if(a.id==pair.Value){best=a;break;}continue;}
                    float d=Vector2.SqrMagnitude((Vector2)f.transform.position-new Vector2(a.x,a.y));if(d<distance){distance=d;best=a;}
                }
                if(best!=null){owner.Trace.Watch(f,"f"+best.id);remaining.Remove(best);}
            }
            owner.Trace.Watch(state.held.GetComponent<FruitEvolution>(),"f"+heldId);
        }
        public Result Advance(float x,int postDropSteps=25,int upcomingPrefabIndex=-1)
        {return AdvanceSearch(x,postDropSteps,upcomingPrefabIndex,true,true,true);}
        internal Result AdvanceSearch(float x,int postDropSteps,int upcomingPrefabIndex,bool captureState,bool captureEvaluation,bool captureInitial)
        {
            if(!CanAcceptAction) throw new InvalidOperationException("No legal continuation: terminal or unknown visible NEXT");
            if(float.IsNaN(x)||float.IsInfinity(x)||x<0||x>1 || postDropSteps<1||postDropSteps>150 || upcomingPrefabIndex< -1 || upcomingPrefabIndex>=player.fruits.Length)
                throw new ArgumentOutOfRangeException("Invalid path action/horizon/chance outcome");
            var range=player.GetDropRangeForFruit(state.held,state.walls);
            if(!range.valid) throw new InvalidOperationException(range.error);
            var timer=System.Diagnostics.Stopwatch.StartNew();
            var result=owner.Run(player,x,range,state.dt,postDropSteps,floor,state,upcomingPrefabIndex,captureState,captureEvaluation,captureInitial);
            TotalTicks+=result.physics_steps;result.trace=owner.Trace;result.elapsed_ms=timer.Elapsed.TotalMilliseconds;
            result.limitation="Continuous native world across this path; cold root contacts; per-tick GO vs live per-render Update. NEXT outcome is explicitly hypothetical.";
            return result;
        }
        internal IEnumerator<Result> AdvanceSearchTicks(float x,int postDropSteps,int upcomingPrefabIndex,bool captureState,bool captureEvaluation,bool captureInitial)
        {
            if(!CanAcceptAction)throw new InvalidOperationException("No legal continuation");
            if(float.IsNaN(x)||float.IsInfinity(x)||x<0||x>1 || postDropSteps<1||postDropSteps>150 || upcomingPrefabIndex< -1 || upcomingPrefabIndex>=player.fruits.Length)
                throw new ArgumentOutOfRangeException("Invalid path action/horizon/chance outcome");
            var range=player.GetDropRangeForFruit(state.held,state.walls);
            if(!range.valid)throw new InvalidOperationException(range.error);
            var timer=System.Diagnostics.Stopwatch.StartNew();
            using(var work=owner.RunTicks(player,x,range,state.dt,postDropSteps,floor,state,upcomingPrefabIndex,captureState,captureEvaluation,captureInitial))
                while(work.MoveNext()) {
                    var result=work.Current;
                    if(result!=null) {
                        TotalTicks+=result.physics_steps;result.trace=owner.Trace;result.elapsed_ms=timer.Elapsed.TotalMilliseconds;
                        result.limitation="Continuous native world across this path; cold root contacts; per-tick GO vs live per-render Update. NEXT outcome is explicitly hypothetical.";
                    }
                    yield return result;
                }
        }
        public void WaitTicks(int ticks)
        {using(var work=WaitTickFrames(ticks))while(work.MoveNext()){} }
        internal IEnumerator<bool> WaitTickFrames(int ticks)
        {
            if(closed || ticks<0 || ticks>500) throw new ArgumentOutOfRangeException("ticks");
            int before=Score,mergesBefore=owner.merges;
            for(int i=0;i<ticks && !state.terminal;i++)
            {
                using(MctsPerformance.Measure("wait_tick")) {
                    Physics2D.SyncTransforms();
                    using(MctsPerformance.Measure("native_physics")) if(!owner.physics.Simulate(state.dt)) throw new InvalidOperationException("Path wait simulation failed");
                    owner.FlushRemoval();state.terminal=owner.IsGameOver(state.held);
                    state.nextTick+=state.dt;TotalTicks++;BoundaryWaitTicks++;
                }
                yield return true;
            }
            BoundaryWaitReward+=Score-before;BoundaryWaitMerges+=owner.merges-mergesBefore;
        }
        internal DropCandidateGenerator.Set DropCandidates() {
            var range=player.GetDropRangeForFruit(state.held,state.walls);
            var shapes=new List<DropCandidateGenerator.Shape>();
            foreach(var pair in owner.ids) {
                var f=pair.Key;if(!f.gameObject.activeInHierarchy||f.IsPreview||f.IsMerging)continue;
                var bounds=FruitColliderShape.Get(f.gameObject).bounds;
                shapes.Add(new DropCandidateGenerator.Shape {type=f.fruitType,center_x=bounds.center.x,min_x=bounds.min.x,max_x=bounds.max.x,top_y=bounds.max.y});
            }
            return DropCandidateGenerator.Generate(range,state.held.GetComponent<FruitEvolution>().fruitType,FruitColliderShape.Get(state.held).bounds.min.y,shapes);
        }
        // Cheap vertical-envelope proposal only; never simulates physics or reads NEXT.
        internal string PublicFruitKey(bool ignoreNext=false) {
            int held=state.held.GetComponent<FruitEvolution>().fruitType;
            int next=ignoreNext||state.next==null?-1:state.next.GetComponent<FruitEvolution>().fruitType;
            return held+":"+next;
        }
        internal float[] RolloutScores(float[] xs) {
            var range=player.GetDropRangeForFruit(state.held,state.walls);
            if(!range.valid)throw new InvalidOperationException(range.error);
            var hb=FruitColliderShape.Get(state.held).bounds;
            var shapes=new List<DropCandidateGenerator.Shape>();
            foreach(var pair in owner.ids) {
                var f=pair.Key;if(!f.gameObject.activeInHierarchy||f.IsPreview||f.IsMerging)continue;
                var b=FruitColliderShape.Get(f.gameObject).bounds;
                shapes.Add(new DropCandidateGenerator.Shape {type=f.fruitType,center_x=b.center.x,min_x=b.min.x,max_x=b.max.x,top_y=b.max.y});
            }
            float floorTop=owner.sourceCopies[floor.gameObject].GetComponent<Collider2D>().bounds.max.y;
            return RolloutGeometryScores(xs,range,state.held.GetComponent<FruitEvolution>().fruitType,hb.extents.x,hb.extents.y,
                hb.center.x-state.held.transform.position.x,hb.center.y-state.held.transform.position.y,floorTop,owner.gameOverHeight,shapes);
        }
        public ValueSnapshot Snapshot()
        {
        using(MctsPerformance.Measure("snapshot")) {

            var range=player.GetDropRangeForFruit(state.held,state.walls);
            return new ValueSnapshot {fruits=owner.ReadBoard(true),current_fruit=new UDPCommunicatorUnity.ControlledFruit {
                present=state.held!=null && state.held.activeSelf,type=state.held.GetComponent<FruitEvolution>().fruitType,
                x=state.held.transform.position.x,y=state.held.transform.position.y,y_known=true},
                next_fruit_type=state.next==null?-1:state.next.GetComponent<FruitEvolution>().fruitType,
                score=Score,game_over=GameOver,drop_cooldown_remaining=(float)Math.Max(0,state.allowed-GameTime),
                ai_move_speed=state.speed,fixed_delta_time=state.dt,
                geometry=floor!=null?new[]{range.left_wall_inner,range.right_wall_inner,owner.sourceCopies[floor.gameObject].GetComponent<Collider2D>().bounds.max.y,owner.gameOverHeight}:null};
        
        }
}
        public HeuristicEvaluator.Features EvaluationFeatures()
        {return owner.ReadEvaluationFeatures(floor,player.GetDropRangeForFruit(state.held,state.walls));}
        public string StateSignature()
        {
        using(MctsPerformance.Measure("prefix_signature")) {
return JsonUtility.ToJson(Snapshot());
        }
}
        public void Dispose() {if(closed)return;closed=true;owner.Dispose();}
    }
    internal static float[] RolloutGeometryScores(float[] xs,PlayerController.DropRange range,int type,float halfWidth,float halfHeight,float offsetX,float offsetY,float floorTop,float go,List<DropCandidateGenerator.Shape> shapes) {
        var scores=new float[xs.Length];float band=.15f*(go-floorTop);
        if(band<=0)throw new InvalidOperationException("Invalid rollout geometry");
        for(int i=0;i<xs.Length;i++) {
            float center=Mathf.Lerp(range.min_x,range.max_x,xs[i])+offsetX,top=floorTop,alignment=0;
            foreach(var f in shapes) {
                if(f.max_x<=center-halfWidth||f.min_x>=center+halfWidth)continue;
                float a=f.type==type?Mathf.Clamp01(1-Mathf.Abs(center-f.center_x)/(halfWidth+(f.max_x-f.min_x)*.5f)):0;
                if(f.top_y>top){top=f.top_y;alignment=a;}else if(f.top_y==top)alignment=Mathf.Max(alignment,a);
            }
            float risk=Mathf.Clamp01((top+halfHeight-offsetY-(go-band))/band);
            scores[i]=alignment-risk;
        }
        return scores;
    }
    public static string LiveSignature(PlayerController player) {return SourceSignature(player);}
}
