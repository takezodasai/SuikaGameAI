using System;
using System.IO;
using System.Security.Cryptography;
using UnityEditor;
using UnityEditor.Build.Reporting;

public static class SuikaStandaloneDemoBuild {
    public static void Build(){
        BuildAt("Builds/StandaloneAiDemo_01");
    }
    public static void BuildReadable(){BuildAt("Builds/StandaloneAiDemo_02");}
    static void BuildAt(string folder){
        if(Directory.Exists(folder))throw new InvalidOperationException("Protect existing demo Player");
        string model=Path.GetFullPath("../Python/examples/portfolio/latest_policy.json");
        if(!File.Exists(model))throw new FileNotFoundException("Public frozen model missing",model);
        var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions{
            scenes=new[]{"Assets/Scenes/gameDisplay.unity"},
            locationPathName=Path.GetFullPath(folder+"/AI-Demo.exe"),
            target=BuildTarget.StandaloneWindows64,options=BuildOptions.None,
            extraScriptingDefines=new[]{"SUIKA_STANDALONE_DEMO"}
        });
        if(report.summary.result!=BuildResult.Succeeded)throw new Exception("Standalone AI demo build failed");
        File.Copy(model,folder+"/demo_policy.json");
        string sha;using(var h=SHA256.Create())sha=BitConverter.ToString(h.ComputeHash(File.ReadAllBytes(model))).Replace("-","").ToLowerInvariant();
        File.WriteAllText(folder+"/demo_policy.sha256",sha);
        File.Copy(Path.GetFullPath("../docs/AI_DEMO_START_HERE.txt"),folder+"/START_HERE.txt");
        File.Copy(Path.GetFullPath("../Python/examples/portfolio/latest_policy_provenance.json"),folder+"/model_provenance.json");
        // Upload remains a separate explicit action. Third-party rights review is outstanding.
    }
}
