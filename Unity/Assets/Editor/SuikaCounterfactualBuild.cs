using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;

public static class SuikaCounterfactualBuild {
    public static void Build() {
        const string path="Builds/Counterfactual_03/SuikaGameAI.exe";
        if(Directory.Exists("Builds/Counterfactual_03"))throw new InvalidOperationException("Preserve existing diagnostic Player");
        var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions {scenes=new[]{"Assets/Scenes/gameDisplay.unity"},locationPathName=Path.GetFullPath(path),target=BuildTarget.StandaloneWindows64,options=BuildOptions.None});
        if(report.summary.result!=BuildResult.Succeeded)throw new Exception("Diagnostic build failed");
    }
}
