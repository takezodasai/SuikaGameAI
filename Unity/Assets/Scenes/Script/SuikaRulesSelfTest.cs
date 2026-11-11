using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEngine;
using UnityEngine.SceneManagement;

// Opt-in owned Player tests. Never installs during ordinary play.
public sealed class SuikaRulesSelfTest : MonoBehaviour
{
    static string destination;
    [Serializable] class Report {public string status="running",error;public List<string> passed=new List<string>();public int predicted_merge_score,actual_merge_score;}
    readonly Report report=new Report();PlayerController player;GameManager manager;UDPCommunicatorUnity udp;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install()
    {
        var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-suikaRulesSelfTest");if(i<0)return;
        destination=args[i+1];new GameObject("Opt-in rule regression").AddComponent<SuikaRulesSelfTest>();
    }
    void Check(bool condition,string message){if(!condition)throw new Exception(message);report.passed.Add(message);}
    void Contacted(FruitEvolution f,bool value){typeof(FruitEvolution).GetProperty("HasCollided").GetSetMethod(true).Invoke(f,new object[]{value});}
    void ActualCheck(){typeof(GameManager).GetMethod("CheckGameOver",BindingFlags.NonPublic|BindingFlags.Instance).Invoke(manager,null);}
    FruitEvolution Spawn(int type,Vector3 position)
    {
        var obj=Instantiate(EvolutionDatabase.Instance.evolutionPrefabs[type],position,Quaternion.identity);
        var f=obj.GetComponent<FruitEvolution>();f.IsPreview=false;
        var b=obj.GetComponent<Rigidbody2D>();if(b==null)b=obj.AddComponent<Rigidbody2D>();PlayerController.ReleaseFruitBody(b);
        FruitColliderShape.Get(obj).isTrigger=false;obj.GetComponent<Danse>()?.InitializePhysicsMaterial();Physics2D.SyncTransforms();return f;
    }
    // Exercise real OnCollisionEnter2D callbacks before checking GO. Both originals
    // remain pending Destroy until end-of-frame, so this also guards merge priority.
    IEnumerator MergePriorityChecks()
    {
        var original=SceneManager.GetActiveScene();
        for(int test=0;test<6;test++)
        {
            manager.ResetGame("merge_go_"+test);
            var scene=SceneManager.CreateScene("OwnedMergeGoTest_"+test,new CreateSceneParameters(LocalPhysicsMode.Physics2D));
            SceneManager.SetActiveScene(scene);string error=null;
            try
            {
                bool vanished=test==4,distinct=test==2,unrelated=test==3,alreadyArmed=test==5;
                bool expected=test==1||distinct||unrelated;
                int type=vanished?10:0;float x=vanished?0:-1.4f;
                float first=manager.GameOverHeight+.05f;
                float second=manager.GameOverHeight+(test==1||distinct||vanished?.15f:-.15f);
                var a=Spawn(type,new Vector3(x,first,0));var b=Spawn(distinct?1:type,new Vector3(x,second,0));a.udpcomm=b.udpcomm=udp;a.mergeSound=b.mergeSound=null;
                if(alreadyArmed)Contacted(a,true);
                if(unrelated){var other=Spawn(2,new Vector3(1.5f,manager.GameOverHeight+.2f,0));other.udpcomm=udp;Contacted(other,true);other.GetComponent<Rigidbody2D>().gravityScale=0;}
                bool predicted;int predictedScore;UDPCommunicatorUnity.BoardFruit[] predictedBoard;
                using(var path=new SuikaPhysicsSimulator.PathSession(player,manager,udp.planningFloor))
                {path.WaitTicks(1);predicted=path.GameOver;predictedScore=path.Score;predictedBoard=path.Snapshot().fruits;}
                Check(ScoreManager.Instance.GetScore()==0,"merge priority "+test+": prediction does not change actual score");
                Check(predicted==expected,"merge priority "+test+": predicted GO matches post-merge rule");
                scene.GetPhysicsScene2D().Simulate(Time.fixedDeltaTime);
                Check(distinct||a.IsMerging&&b.IsMerging,"merge priority "+test+": both originals marked merging before Destroy");
                ActualCheck();
                Check(manager.isGameOver==expected,"merge priority "+test+": actual GO matches post-merge rule");
                Check(ScoreManager.Instance.GetScore()==predictedScore,"merge priority "+test+": actual/predicted merge score agrees");
                if(!distinct&&!vanished)
                {
                    FruitEvolution child=null;foreach(var o in scene.GetRootGameObjects()){var f=o.GetComponent<FruitEvolution>();if(f!=null&&!f.IsMerging&&f.fruitType==1)child=f;}
                    Check(child!=null&&child.HasCollided,"merge priority "+test+": merged fruit remains armed, no grace reset");
                    if(!unrelated)Check(child.CanTriggerGameOver(manager.GameOverHeight)==expected,"merge priority "+test+": merged fruit position decides GO");
                }
                if(vanished)Check(predictedBoard.Length==0,"watermelon pair disappears without a surviving GO candidate");
            }
            catch(Exception e){error=e.ToString();report.error=error;}
            foreach(var o in scene.GetRootGameObjects())o.SetActive(false);
            SceneManager.SetActiveScene(original);yield return SceneManager.UnloadSceneAsync(scene);
            if(error!=null)yield break;
        }
        manager.ResetGame("merge_go_done");
    }
    IEnumerator Start()
    {
        yield return null;yield return null;
        player=FindObjectOfType<PlayerController>();manager=FindObjectOfType<GameManager>();udp=FindObjectOfType<UDPCommunicatorUnity>();
        try
        {
            var milestone=new SuikaEpisodeEvents {Enabled=true};
            milestone.Drop(10,0,1);milestone.Drop(9,0,2);milestone.Drop(9,0,3);
            var moment=milestone.Read().learning;
            Check(moment.known&&moment.events.Length==3&&moment.events[2].kind=="watermelon_melon_two"&&moment.events[2].fixed_time==3,"learning milestones capture transient melon pair before its merge");
            milestone.Merge(9,10,55,4);milestone.Merge(10,-1,55,5);
            var complete=milestone.Read().learning;
            Check(complete.known&&complete.events.Length==5&&complete.events[4].kind=="double_watermelon"&&complete.melons_present==0&&complete.watermelons_present==0,"learning milestones update atomic merge counts and double event");
            milestone.Drop(10,55,6);milestone.Drop(9,55,7);milestone.Drop(9,55,8);milestone.Merge(9,10,110,9);milestone.Merge(10,-1,110,10);
            Check(milestone.Read().learning.events.Length==5,"learning milestones emitted once per goal per episode");
            milestone.Reset();Check(milestone.Read().learning.known&&milestone.Read().learning.events.Length==0,"learning milestones reset between episodes");
            milestone.Enabled=false;milestone.Drop(10,0,1);Check(!milestone.Read().learning.known&&milestone.Read().learning.events.Length==0,"disabled learning events remain unknown");
            Check(Math.Abs(manager.gameOverScreenRatio-.83f)<1e-6,"GO ratio remains .83");
            for(int type=0;type<EvolutionDatabase.Instance.evolutionPrefabs.Length;type++)
            {
                manager.ResetGame("rule_test");var fruit=Spawn(type,new Vector3(0,manager.GameOverHeight+5,0));fruit.GetComponent<Rigidbody2D>().gravityScale=0;
                Check(fruit.CompareTag("Fruit"),"type "+type+" prefab has canonical tag");
                Contacted(fruit,false);ActualCheck();Check(!manager.isGameOver,"type "+type+" uncontacted above line remains legal");
                Check(!SuikaPhysicsSimulator.Predict(player,manager,.5f,1).game_over,"type "+type+" prediction respects contact flag");
                Contacted(fruit,true);fruit.IsPreview=true;ActualCheck();Check(!manager.isGameOver,"type "+type+" preview excluded");
                fruit.IsPreview=false;fruit.transform.position=new Vector3(0,manager.GameOverHeight,0);Physics2D.SyncTransforms();
                Check(!fruit.CanTriggerGameOver(manager.GameOverHeight),"type "+type+" equality at GO line remains legal");
                fruit.transform.position=new Vector3(0,manager.GameOverHeight+5,0);Physics2D.SyncTransforms();
                Check(SuikaPhysicsSimulator.Predict(player,manager,.5f,1).game_over,"type "+type+" contacted prediction GO");
                ActualCheck();Check(manager.isGameOver,"type "+type+" contacted actual GO");
            }
            manager.ResetGame("apple_merge");
            Spawn(4,new Vector3(-.05f,udp.planningFloor.bounds.max.y+1,0));Spawn(4,new Vector3(.05f,udp.planningFloor.bounds.max.y+1,0));
            var prediction=SuikaPhysicsSimulator.Predict(player,manager,.5f,1);
            report.predicted_merge_score=prediction.score;
            Check(prediction.merges==1 && prediction.score==ScoreManager.Instance.evolutionScores[4],"prediction creates apple and adds existing type4 score");
            Check(ScoreManager.Instance.GetScore()==0 && ScoreManager.Instance.EpisodeMergeCount==0,"prediction leaves real score and merge telemetry untouched");
        }
        catch(Exception e){report.error=e.ToString();}
        if(report.error==null)
        {
            yield return new WaitForFixedUpdate();yield return null;
            try
            {
                report.actual_merge_score=ScoreManager.Instance.GetScore();
                Check(report.actual_merge_score==report.predicted_merge_score,"actual apple merge score agrees with prediction");
                Check(ScoreManager.Instance.EpisodeMergeCount==1 && ScoreManager.Instance.EpisodeMaxFruitType==5,"actual merge count and maximum type recorded once");
                FruitEvolution apple=null;foreach(var f in FindObjectsOfType<FruitEvolution>())if(f.Simulation==null&&!f.IsPreview&&f.fruitType==5)apple=f;
                Check(apple!=null&&apple.CompareTag("Fruit")&&apple.HasCollided,"merged apple inherits correct GO tag and contact eligibility");
                manager.ResetGame("telemetry_reset");Check(ScoreManager.Instance.EpisodeMergeCount==0&&ScoreManager.Instance.EpisodeMaxFruitType==-1,"episode telemetry reset independent of old episode");
            }catch(Exception e){report.error=e.ToString();}
        }
        if(report.error==null)yield return MergePriorityChecks();
        report.status=report.error==null?"passed":"failed";
        Directory.CreateDirectory(Path.GetDirectoryName(destination));using(var f=new StreamWriter(new FileStream(destination,FileMode.CreateNew)))f.Write(JsonUtility.ToJson(report,true));
        Debug.Log("RULE SELFTEST "+report.status+" "+report.error);Application.Quit(report.error==null?0:1);
    }
}
