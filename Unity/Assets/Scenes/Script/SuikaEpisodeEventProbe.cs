using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.SceneManagement;
// Opt-in test only. Simulates actual FruitEvolution callbacks in an owned local scene.
public sealed class SuikaEpisodeEventProbe:MonoBehaviour {
    static string output; List<string> trace=new List<string>(); string baseline; bool failed;
    [Serializable] class Result {public bool passed;public string error,physics_trace;public SuikaEpisodeEvents.Snapshot actual_events;}
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Install(){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,"-suikaEventProbe");if(i>=0){output=a[i+1];new GameObject("Event parity probe").AddComponent<SuikaEpisodeEventProbe>();}}
    FruitEvolution Spawn(int type,float x,Scene scene){var o=Instantiate(EvolutionDatabase.Instance.evolutionPrefabs[type],new Vector3(x,-100,0),Quaternion.identity);SceneManager.MoveGameObjectToScene(o,scene);var f=o.GetComponent<FruitEvolution>();f.mergeSound=null;f.udpcomm=FindObjectOfType<UDPCommunicatorUnity>();var b=o.GetComponent<Rigidbody2D>();if(b==null)b=o.AddComponent<Rigidbody2D>();PlayerController.ReleaseFruitBody(b);FruitColliderShape.Get(o).isTrigger=false;return f;}
    string State(Scene scene){var rows=new List<string>();foreach(var o in scene.GetRootGameObjects()){var f=o.GetComponent<FruitEvolution>();var b=o.GetComponent<Rigidbody2D>();if(f==null||f.IsMerging||b==null)continue;rows.Add(f.fruitType+":"+b.position.ToString("R")+":"+b.velocity.ToString("R")+":"+b.rotation.ToString("R")+":"+b.angularVelocity.ToString("R"));}rows.Sort(StringComparer.Ordinal);return ScoreManager.Instance.GetScore()+"|"+string.Join(";",rows);}
    IEnumerator Start(){yield return null;yield return null;var score=ScoreManager.Instance;var original=SceneManager.GetActiveScene();SuikaEpisodeEvents.Snapshot recorded=null;
        for(int pass=0;pass<2;pass++){
            score.ResetScore();score.EpisodeEvents.Enabled=pass==1;trace.Clear();
            var scene=SceneManager.CreateScene("Event parity "+pass,new CreateSceneParameters(LocalPhysicsMode.Physics2D));SceneManager.SetActiveScene(scene);
            Spawn(9,100,scene);Spawn(9,100.01f,scene);Spawn(9,110,scene);Spawn(9,110.01f,scene);
            var physics=scene.GetPhysicsScene2D();physics.Simulate(Time.fixedDeltaTime);trace.Add(State(scene));SceneManager.SetActiveScene(original);yield return null;
            var watermelons=new List<FruitEvolution>();foreach(var o in scene.GetRootGameObjects()){var f=o.GetComponent<FruitEvolution>();if(f!=null&&!f.IsMerging&&f.fruitType==10)watermelons.Add(f);}
            if(watermelons.Count!=2){failed=true;break;}
            for(int i=0;i<2;i++){watermelons[i].GetComponent<Rigidbody2D>().position=new Vector2(100+i*.01f,-100);}
            SceneManager.SetActiveScene(scene);physics.Simulate(Time.fixedDeltaTime);trace.Add(State(scene));SceneManager.SetActiveScene(original);yield return null;
            string signature=string.Join("\n",trace);if(pass==0)baseline=signature;else{recorded=score.EpisodeEvents.Read();failed=signature!=baseline||recorded.watermelons_created!=2||recorded.watermelons_present!=0||recorded.double_watermelons!=1||recorded.events.Length!=7||score.GetScore()!=110;}
            yield return SceneManager.UnloadSceneAsync(scene);
        }
        SceneManager.SetActiveScene(original);var result=new Result {passed=!failed,error=failed?"Actual merge/event parity failed":"",physics_trace=baseline,actual_events=recorded};using(var f=new StreamWriter(new FileStream(output,FileMode.CreateNew)))f.Write(JsonUtility.ToJson(result));Application.Quit(failed?2:0);
    }
}
