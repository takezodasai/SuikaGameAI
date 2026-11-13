using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
public static class SuikaMaterialViewBuild {
    public static void Build(){
        BuildAt("Builds/MaterialView_01");
    }
    public static void BuildAiNotice(){
        BuildAt("Builds/MaterialView_02");
    }
    static void BuildAt(string folder){
        if(Directory.Exists(folder))throw new InvalidOperationException("Protect existing Player");
        var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=new[]{"Assets/Scenes/gameDisplay.unity"},
            locationPathName=Path.GetFullPath(folder+"/SuikaGameAI.exe"),target=BuildTarget.StandaloneWindows64,options=BuildOptions.None});
        if(report.summary.result!=BuildResult.Succeeded)throw new Exception("Material GUI build failed");
    }
}
