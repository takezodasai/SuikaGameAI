using System;
using System.IO;
using System.Security.Cryptography;
using UnityEngine;

// Enabled only in the separate SUIKA_STANDALONE_DEMO build. Research Players stay opt-in.
public sealed class SuikaStandaloneDemo : MonoBehaviour {
    public static bool Active {
        get {
#if SUIKA_STANDALONE_DEMO
            return true;
#else
            return false;
#endif
        }
    }
    [Serializable] class Config {
        public string policy_model,output,mode="learned",final_selection="legacy";
        public bool normal_start=true,material_progress=true;
        public float mixture=.5f,max_seconds=14400,first_x=-1;
        public int game_seed,search_seed=8191,iterations=256,depth=4,max_drops=100000;
    }
    static SuikaStandaloneDemo instance;
    string folder,error,summary;
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)] static void Prepare(){
        if(!Active)return;
        Application.runInBackground=true;
        instance=new GameObject("Standalone AI demo startup").AddComponent<SuikaStandaloneDemo>();
        DontDestroyOnLoad(instance.gameObject);
    }
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] static void Launch(){
        if(!Active)return;
        foreach(var events in FindObjectsOfType<UnityEngine.EventSystems.EventSystem>())events.enabled=false;
        try {
            // Files in the ZIP are read-only; logs go into the user's own application data.
            string home=Path.GetFullPath(Path.Combine(Application.dataPath,".."));
            string model=Path.Combine(home,"demo_policy.json");
            string expected=File.ReadAllText(Path.Combine(home,"demo_policy.sha256")).Trim();
            string actual;
            using(var hash=SHA256.Create())actual=BitConverter.ToString(hash.ComputeHash(File.ReadAllBytes(model))).Replace("-","").ToLowerInvariant();
            if(actual!=expected)throw new Exception("Bundled model checksum mismatch. Extract the complete ZIP again.");
            new LearnedRolloutPolicy(model); // Fail before enabling play if model schema is invalid.
            instance.folder=Path.Combine(Application.persistentDataPath,"ai-demo",DateTime.Now.ToString("yyyyMMdd_HHmmss")+"_"+Guid.NewGuid().ToString("N").Substring(0,8));
            Directory.CreateDirectory(instance.folder);
            int seed;
            using(var rng=RandomNumberGenerator.Create()){var bytes=new byte[4];rng.GetBytes(bytes);seed=BitConverter.ToInt32(bytes,0)&int.MaxValue;}
            var cfg=new Config{game_seed=seed,policy_model=model,output=Path.Combine(instance.folder,"trace.jsonl")};
            var args=Environment.GetCommandLineArgs();
            int i=Array.IndexOf(args,"-aiDemoMaxDrops");
            if(i>=0){int n=int.Parse(args[i+1]);if(n<1||n>100000)throw new Exception("Invalid demo drop limit");cfg.max_drops=n;}
            string path=Path.Combine(instance.folder,"config.json");File.WriteAllText(path,JsonUtility.ToJson(cfg,true));
            File.WriteAllText(Path.Combine(instance.folder,"model.sha256"),actual);
            SuikaAudio.Initialize(false);
            SuikaRuntimeProbe.BeginDemo(Path.Combine(instance.folder,"runtime.jsonl"));
            SuikaPolicySelfPlayLab.BeginDemo(path);
        }catch(Exception e){instance.error=e.Message;Time.timeScale=0;Debug.LogException(e);}
    }
    public static void Finish(string reason,int score,int drops,int watermelons,int doubles){
        if(instance==null)return;
        string status=reason=="natural_go"?"ゲームオーバー":reason=="drop_limit"?"確認用の手数上限で停止":reason=="user_stop"?"ユーザー操作で停止":"停止理由: "+reason;
        instance.summary=status+"\n最終得点 "+score+"点 ｜ 落下 "+drops+"回\n新規スイカ "+watermelons+"個 ｜ ダブルスイカ "+doubles+"回\nEscまたはウィンドウを閉じて終了";
    }
    void Update(){if((error!=null||summary!=null)&&Input.GetKeyDown(KeyCode.Escape))Application.Quit();}
    GUIStyle resultText;
    void OnGUI(){
        if(error!=null||summary!=null){
            if(resultText==null){resultText=new GUIStyle(GUI.skin.box){fontSize=24,alignment=TextAnchor.MiddleCenter,wordWrap=true};resultText.font=Font.CreateDynamicFontFromOSFont(new[]{"Yu Gothic UI","Meiryo","Arial"},24);}
            GUI.Box(new Rect(20,Screen.height/2-100,Mathf.Max(300,Screen.width-40),200),
                error!=null?"AIデモを開始できませんでした\n"+error+"\nEscで終了。手動プレイは無効です。":summary,resultText);
        }
    }
}
