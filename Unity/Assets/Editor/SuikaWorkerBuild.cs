using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

public static class SuikaWorkerBuild
{
    [MenuItem("Tools/Suika/Build STEP6 Windows Player %&F8")]
    public static void Build()
    {BuildAt("Builds/Step6/SuikaGameAI.exe");}
    [MenuItem("Tools/Suika/Build Presentation Prototype %&F9")]
    public static void BuildPreview() {BuildAt("Builds/Step6Preview/SuikaGameAI.exe");}
    [MenuItem("Tools/Suika/Build STEP8T Adaptive Player")]
    public static void BuildAdaptive() {BuildAt("Builds/Step8T/SuikaGameAI.exe");}
    [MenuItem("Tools/Suika/Build STEP8U Placement Player")]
    public static void BuildPlacement() {BuildAt("Builds/Step8U/SuikaGameAI.exe");}
    public static bool IsProtectedDestination(string destination) {
        string project=Directory.GetParent(Application.dataPath).FullName;
        return File.Exists(Path.GetFullPath(Path.Combine(project,"../Python/compat/step8s_20261024/version_manifest.json"))) &&
            (string.Equals(Path.GetFullPath(destination),Path.GetFullPath(Path.Combine(project,"Builds/Step6/SuikaGameAI.exe")),StringComparison.OrdinalIgnoreCase) || (File.Exists(Path.Combine(project,"Builds/Step8T/SuikaGameAI.exe")) && string.Equals(Path.GetFullPath(destination),Path.GetFullPath(Path.Combine(project,"Builds/Step8T/SuikaGameAI.exe")),StringComparison.OrdinalIgnoreCase)));
    }
    public static void CheckProtectedBuildGuard() {
        if(!IsProtectedDestination("Builds/Step6/SuikaGameAI.exe")||IsProtectedDestination("Builds/Step8U/SuikaGameAI.exe"))throw new InvalidOperationException("Protected Player guard failed");
        Debug.Log("STEP8S PROTECTED BUILD GUARD OK");
    }
    static void BuildAt(string destination)
    {
        if(IsProtectedDestination(destination))throw new InvalidOperationException("STEP8-S Player is protected for resume. Use Tools/Suika/Build STEP8T Adaptive Player.");
        if(EditorApplication.isPlaying) throw new InvalidOperationException("Stop Play before building");
        if(UnityEditor.SceneManagement.EditorSceneManager.GetActiveScene().isDirty)
            throw new InvalidOperationException("Save/review your Scene changes before building");
        string path=Path.GetFullPath(destination);
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        // Explicit scene list; do not alter the user's Build Settings or Scene.
        var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions {
            scenes=new[]{"Assets/Scenes/gameDisplay.unity"},locationPathName=path,
            target=BuildTarget.StandaloneWindows64,options=BuildOptions.None });
        if(report.summary.result!=BuildResult.Succeeded)
            throw new InvalidOperationException("STEP6 build failed: "+report.summary.result);
        Debug.Log("STEP6 BUILD OK: "+path+" seconds="+report.summary.totalTime.TotalSeconds);
    }
}
