using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEngine;

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
    IEnumerator Start()
    {
        yield return null;yield return null;
        player=FindObjectOfType<PlayerController>();manager=FindObjectOfType<GameManager>();udp=FindObjectOfType<UDPCommunicatorUnity>();
        try
        {
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
        report.status=report.error==null?"passed":"failed";
        Directory.CreateDirectory(Path.GetDirectoryName(destination));using(var f=new StreamWriter(new FileStream(destination,FileMode.CreateNew)))f.Write(JsonUtility.ToJson(report,true));
        Debug.Log("RULE SELFTEST "+report.status+" "+report.error);Application.Quit(report.error==null?0:1);
    }
}
