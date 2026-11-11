using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
public static class SuikaFrozenPairBuild {
    public static void Build(){const string folder="Builds/FrozenVPair_01";if(Directory.Exists(folder))throw new InvalidOperationException("Preserve existing Player");var r=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=new[]{"Assets/Scenes/gameDisplay.unity"},locationPathName=Path.GetFullPath(folder+"/SuikaGameAI.exe"),target=BuildTarget.StandaloneWindows64,options=BuildOptions.None});if(r.summary.result!=BuildResult.Succeeded)throw new Exception("Frozen V pair build failed");}
}
