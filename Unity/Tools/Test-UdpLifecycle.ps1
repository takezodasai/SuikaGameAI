# Unity Editor不要。実際の通信クラスを最小スタブとともにコンパイルする。
$ErrorActionPreference = 'Stop'
$source = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot '../Assets/Scenes/Script/UDPCommunicatorUnity.cs')
$source += "`n" + (Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot '../Assets/Scenes/Script/UDPStateProtocol.cs')) -replace '(?m)^using (System;|System.Collections.Generic;|System.Text;|UnityEngine;)\r?\n', ''
$source += "`n" + (Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot '../Assets/Scenes/Script/UDPStepProtocol.cs')) -replace '(?m)^using (System;|UnityEngine;)\r?\n', ''
# Re-add common imports at the start (partial source files share one compilation unit).
$source = "using System; using System.Collections.Generic; using System.Text; using UnityEngine;`n" + $source
$stubs = @'
namespace UnityEngine {
 public class MonoBehaviour {
  protected object StartCoroutine(System.Collections.IEnumerator e) { return null; }
  protected static void Destroy(object o) {}
  protected static T[] FindObjectsOfType<T>() { return new T[0]; }
 }
 public class GameObject {
  public Transform transform = new Transform(); public string name = "fruit";
  public T GetComponent<T>() where T:new() { return new T(); }
 }
 public class FruitEvolution {
  public bool IsPreview, IsMerging, HasCollided; public int fruitType; public long ObservationId;
  public GameObject gameObject = new GameObject();
  public T GetComponent<T>() where T:new() { return new T(); }
 }
 public class Rigidbody2D { public Vector3 position,velocity; public float rotation, angularVelocity; }
 public class Transform { public Vector3 position; }
 public struct Vector3 {
  public float x,y,z; public static Vector3 zero { get { return new Vector3(); } }
  public static bool operator ==(Vector3 a,Vector3 b) { return a.Equals(b); }
  public static bool operator !=(Vector3 a,Vector3 b) { return !a.Equals(b); }
  public override bool Equals(object o) { return base.Equals(o); }
  public override int GetHashCode() { return base.GetHashCode(); }
 }
 public class Texture2D {
  public Texture2D(int w,int h,TextureFormat f,bool m) {}
  public void ReadPixels(Rect r,int x,int y) {} public void Apply() {}
  public byte[] EncodeToPNG() { return new byte[0]; }
 }
 public enum TextureFormat { RGB24 }
 public class RenderTexture { public RenderTexture(int w,int h,int d) {} public static RenderTexture active; }
 public class Camera { public RenderTexture targetTexture; public void Render() {} }
 public struct Rect { public Rect(int x,int y,int w,int h) {} }
 public static class Screen { public static int width=640,height=480; }
 public class WaitForSeconds { public WaitForSeconds(float s) {} }
 public class WaitForSecondsRealtime { public WaitForSecondsRealtime(float s) {} }
 public static class Time { public static float timeScale=1, fixedDeltaTime=0.02f; public static double timeAsDouble, fixedTimeAsDouble; }
 public static class Mathf {
  public static int Max(int a,int b) { return System.Math.Max(a,b); }
  public static int CeilToInt(float x) { return (int)System.Math.Ceiling(x); }
  public static float Abs(float x) { return System.Math.Abs(x); }
  public static float Lerp(float a,float b,float x) { return a+(b-a)*x; }
  public static float MoveTowards(float a,float b,float d) { return System.Math.Abs(b-a)<=d ? b : a+System.Math.Sign(b-a)*d; }
  public static float InverseLerp(float a,float b,float x) { return (x-a)/(b-a); }
 }
 public static class Debug {
  public static void Log(object o) {} public static void LogWarning(object o) {}
  public static void LogError(object o) { throw new System.Exception("Unexpected error: " + o); }
 }
 public static class JsonUtility {
  public static string ToJson(object o) { return "{}"; }
  public static T FromJson<T>(string s) where T:new() { return new T(); }
 }
}
// Only the optional diagnostic entry point is stubbed; real physics is tested in Unity.
public class SuikaPhysicsSimulator {
 public class Result { public object trace,fruits,reference_fruits; public PredictionDiagnostics.Report diagnostics; public double elapsed_ms,reference_elapsed_ms; public int score,reference_score; public bool game_over,reference_game_over; }
 public static Result Predict(PlayerController p,GameManager g,float x,int ticks=-1) { return new Result(); }
}
public static class PredictionDiagnostics {
 public static void Begin(PlayerController p,GameManager g) {} public static void Stop() {}
 public class Report { public bool actual_completion_game_over, predicted_completion_game_over; }
 public static Report Compare(object trace) { return new Report(); }
}
public class PlayerController {
 public bool StepControlLocked; public bool CanDropFruit=true;
 public float EffectiveAIMoveSpeed { get { return aiMoveSpeed; } }
 public float aiMoveSpeed=2.5f, moveDirection, dropCooldownSeconds=.4f, DropCooldownRemaining;
 public int DropCalls;
 public bool ThrowAfterDrop;
 public class DropRange { public bool valid=true; public string error=""; public float min_x=-2,max_x=2; }
 public DropRange GetDropRange() { return new DropRange(); }
 public bool TryMoveHeldTo(float x,DropRange range,out string error) {
  currentFruit.transform.position.x=x; error=""; return true;
 }
 public bool TryDropAt(float x,out float applied,out long id,out DropRange range,out string error) {
  DropCalls++; if(ThrowAfterDrop) throw new System.InvalidOperationException("Injected post-drop failure");
  applied=-2+4*x; id=DropCalls; range=new DropRange(); error=""; return true;
 }
 public UnityEngine.GameObject currentFruit = new UnityEngine.GameObject();
 public UnityEngine.GameObject nextFruitObject = new UnityEngine.GameObject();
 public void MoveLeft() {} public void MoveRight() {} public void DropFruit() {}
 public void MoveLeft1() {} public void MoveRight1() {}
}
public class GameManager { public bool isGameOver; public void ResetGame(string id) {} }
public class ScoreManager { public static ScoreManager Instance = new ScoreManager(); public int score; public int GetScore() { return score; } }
'@
Add-Type -TypeDefinition ($source + "`n" + $stubs) -IgnoreWarnings -WarningAction SilentlyContinue
$flags = [Reflection.BindingFlags]'Instance,NonPublic'
function Invoke-Private($instance, $name) {
    $instance.GetType().GetMethod($name, $flags).Invoke($instance, @()) | Out-Null
}
function Assert($condition, $message) { if (-not $condition) { throw $message } }
function New-Communicator($port) {
    $c = [UDPCommunicatorUnity]::new()
    $c.listenPort = $port
    $c.player = [UnityEngine.GameObject]::new()
    $c.playerController = [PlayerController]::new()
    $c.gameManager = [GameManager]::new()
    $c.mainCamera = [UnityEngine.Camera]::new()
    return $c
}
$receiver = [Net.Sockets.UdpClient]::new(0)
$receiver.Client.ReceiveTimeout = 2000
$c = New-Communicator 0
$replacement = $null
$stepper = $null
try {
    $c.pythonPort = ([Net.IPEndPoint]$receiver.Client.LocalEndPoint).Port
    Invoke-Private $c 'Start'
    $listener = $c.GetType().GetField('udpListener', $flags).GetValue($c)
    $port = ([Net.IPEndPoint]$listener.Client.LocalEndPoint).Port
    $routine = $c.SendObservations()
    Assert ($routine.MoveNext()) 'Initial Start-order yield missing'
    Assert ($routine.MoveNext()) 'Active periodic sender did not run'
    $peer = [Net.IPEndPoint]::new([Net.IPAddress]::Any, 0)
    Assert ($receiver.Receive([ref]$peer).Length -gt 0) 'No UDP packet received'
    $c.StopCommunication()
    $c.StopCommunication()
    Invoke-Private $c 'Update'
    Assert (-not $routine.MoveNext()) 'Periodic sender continued after stop'
    foreach ($name in @('SendObservationsOnce','SendObservationsNashi','SendObservationsPeach','SendObservationsPin','SendObservationsMelon','SendObservationsWaterMelon')) {
        $c.$name()
    }
    Assert ($receiver.Available -eq 0) 'Packet sent after stop'
    Invoke-Private $c 'OnDestroy'
    Invoke-Private $c 'OnApplicationQuit'
    # Scene再読込相当：新しいインスタンスが同じ受信ポートを使用できる。
    $replacement = New-Communicator $port
    $replacement.pythonPort = $c.pythonPort
    Invoke-Private $replacement 'Start'
    $replacement.SendObservationsOnce()
    Assert ($receiver.Receive([ref]$peer).Length -gt 0) 'Replacement sender failed'
    Invoke-Private $replacement 'Update'
    Invoke-Private $replacement 'OnDestroy'
    $probe = [Net.Sockets.UdpClient]::new($port)
    $probe.Close()
    Write-Output 'PASS: UDP send, repeated stop, stopped Update/notifications/coroutine, lifecycle cleanup, port reuse and replacement send'
    $stepper = New-Communicator 0
    Invoke-Private $stepper 'Start'
    $stream = $stepper.GetType().GetField('streamId', $flags).GetValue($stepper)
    $episode = $stepper.GetType().GetField('episodeId', $flags).GetValue($stepper)
    $handler = $stepper.GetType().GetMethod('HandleStep', $flags)
    $command = [UDPCommunicatorUnity+ActionMessage]::new()
    $command.stream_id=$stream; $command.episode_id=$episode; $command.action_id=1; $command.x=0.5
    $handler.Invoke($stepper, @($command)) | Out-Null
    $handler.Invoke($stepper, @($command)) | Out-Null
    Assert ($stepper.playerController.DropCalls -eq 0) 'Drop occurred before fixed movement update'
    $command.action_id=2
    $handler.Invoke($stepper, @($command)) | Out-Null
    Assert ($stepper.playerController.DropCalls -eq 0) 'Busy command dropped a fruit'
    Invoke-Private $stepper 'FixedUpdate'
    Assert ($stepper.playerController.DropCalls -eq 1) 'Arrival did not drop once'
    for ($i=0; $i -lt 26; $i++) { Invoke-Private $stepper 'FixedUpdate' }
    Invoke-Private $stepper 'LateUpdate'
    $cached = $stepper.GetType().GetField('completedStep', $flags).GetValue($stepper)
    Assert ($cached.step_result.physics_steps -ge 25) 'Completed before physics window'
    $command.action_id=1
    $handler.Invoke($stepper, @($command)) | Out-Null
    Assert ($stepper.playerController.DropCalls -eq 1) 'Completed retry dropped twice'
    $command.action_id=2; $command.x=1.1
    $handler.Invoke($stepper, @($command)) | Out-Null
    Assert ($stepper.playerController.DropCalls -eq 1) 'Invalid coordinate dropped a fruit'
    $command.x=1
    $handler.Invoke($stepper, @($command)) | Out-Null
    for ($i=0; $i -lt 40; $i++) { Invoke-Private $stepper 'FixedUpdate' }
    # Floating point accumulation can require one additional tick to arrive.
    for ($i=0; $i -lt 2; $i++) { Invoke-Private $stepper 'FixedUpdate' }
    Assert ($stepper.playerController.DropCalls -eq 2) 'Next sequential action failed'
    $command.action_id=1; $command.x=0.5
    $handler.Invoke($stepper, @($command)) | Out-Null
    Assert ($stepper.playerController.DropCalls -eq 2) 'Old action re-executed'
    $stepper.BeginEpisode('test-reset')
    $command.action_id=1
    $handler.Invoke($stepper, @($command)) | Out-Null
    Assert ($stepper.playerController.DropCalls -eq 2) 'Old episode action re-executed'
    $command.episode_id=$stepper.GetType().GetField('episodeId', $flags).GetValue($stepper)
    $stepper.gameManager.isGameOver=$true
    $handler.Invoke($stepper, @($command)) | Out-Null
    Assert ($stepper.playerController.DropCalls -eq 2) 'Terminal action dropped a fruit'
    $stepper.gameManager.isGameOver=$false
    $stepper.playerController.ThrowAfterDrop=$true
    $stepper.playerController.currentFruit.transform.position=[UnityEngine.Vector3]::zero
    $handler.Invoke($stepper, @($command)) | Out-Null
    try { Invoke-Private $stepper 'FixedUpdate'; throw 'Expected injected failure' }
    catch [System.Management.Automation.MethodInvocationException] { }
    $handler.Invoke($stepper, @($command)) | Out-Null
    Invoke-Private $stepper 'FixedUpdate'
    Assert ($stepper.playerController.DropCalls -eq 3) 'Unknown-outcome retry dropped twice'
    $stepper.playerController.ThrowAfterDrop=$false
    $stepper.BeginEpisode('cancel-moving')
    $command.episode_id=$stepper.GetType().GetField('episodeId', $flags).GetValue($stepper)
    $command.action_id=1; $command.x=1
    $handler.Invoke($stepper, @($command)) | Out-Null
    Invoke-Private $stepper 'FixedUpdate'
    Assert ($stepper.playerController.DropCalls -eq 3) 'Movement dropped before arrival'
    $progress=$stepper.GetType().GetField('activeStep', $flags).GetValue($stepper)
    Assert ($progress.movement_steps -eq 1 -and $progress.movement_seconds -gt 0) 'Movement not measured'
    $stepper.BeginEpisode('reset-during-movement')
    for ($i=0; $i -lt 50; $i++) { Invoke-Private $stepper 'FixedUpdate' }
    Assert ($stepper.playerController.DropCalls -eq 3) 'Reset did not cancel movement'
    $command.episode_id=$stepper.GetType().GetField('episodeId', $flags).GetValue($stepper)
    $handler.Invoke($stepper, @($command)) | Out-Null
    Invoke-Private $stepper 'FixedUpdate'
    $stepper.gameManager.isGameOver=$true
    Invoke-Private $stepper 'LateUpdate'
    $terminal=$stepper.GetType().GetField('completedStep', $flags).GetValue($stepper)
    Assert (-not $terminal.step_result.drop_success) 'Game over during movement dropped a fruit'
    $stepper.gameManager.isGameOver=$false
    foreach ($dt in @(0.01,0.04)) {
        [UnityEngine.Time]::fixedDeltaTime=$dt
        $stepper.BeginEpisode('fixed-time-check')
        $stepper.playerController.currentFruit.transform.position=[UnityEngine.Vector3]::zero
        $command.episode_id=$stepper.GetType().GetField('episodeId', $flags).GetValue($stepper)
        $command.action_id=1; $command.x=1
        $handler.Invoke($stepper, @($command)) | Out-Null
        for ($i=0; $i -lt 200; $i++) {
            Invoke-Private $stepper 'FixedUpdate'
            Invoke-Private $stepper 'LateUpdate'
            $active=$stepper.GetType().GetField('activeStep', $flags).GetValue($stepper)
            if ($null -eq $active) { break }
        }
        $timed=$stepper.GetType().GetField('completedStep', $flags).GetValue($stepper)
        Assert ($timed.step_result.movement_seconds -ge 0.799 -and
                $timed.step_result.movement_seconds -le (0.801+$dt)) 'Movement time depends on tick frequency'
        Assert (($timed.step_result.physics_steps*$dt) -ge 0.499) 'Post-drop timer included movement'
    }
    [UnityEngine.Time]::fixedDeltaTime=0.02
    $stepper.BeginEpisode('diagnostic-horizon')
    $command.episode_id=$stepper.GetType().GetField('episodeId', $flags).GetValue($stepper)
    $command.action_id=1; $command.x=0.5; $command.command='compare_step'; $command.comparison_post_drop_steps=100
    $handler.Invoke($stepper, @($command)) | Out-Null
    Assert ($stepper.GetType().GetField('targetTicks', $flags).GetValue($stepper) -eq 100) 'Diagnostic horizon ignored'
    $stepper.BeginEpisode('normal-horizon')
    $command.episode_id=$stepper.GetType().GetField('episodeId', $flags).GetValue($stepper)
    $command.command='step'
    $handler.Invoke($stepper, @($command)) | Out-Null
    Assert ($stepper.GetType().GetField('targetTicks', $flags).GetValue($stepper) -eq 25) 'Diagnostic horizon changed normal step'
    $stepper.BeginEpisode('invalid-horizon')
    $command.episode_id=$stepper.GetType().GetField('episodeId', $flags).GetValue($stepper)
    $command.command='compare_step'; $command.comparison_post_drop_steps=151
    $handler.Invoke($stepper, @($command)) | Out-Null
    Assert (-not $stepper.playerController.StepControlLocked) 'Invalid horizon locked player'
    $stepper.BeginEpisode('cooldown-wait')
    $command.episode_id=$stepper.GetType().GetField('episodeId', $flags).GetValue($stepper)
    $command.command='step'; $command.action_id=1; $command.x=0.5
    $stepper.playerController.currentFruit.transform.position=[UnityEngine.Vector3]::zero
    $stepper.playerController.CanDropFruit=$false
    $dropsBefore=$stepper.playerController.DropCalls
    $handler.Invoke($stepper, @($command)) | Out-Null
    for ($i=0; $i -lt 3; $i++) { Invoke-Private $stepper 'FixedUpdate' }
    $handler.Invoke($stepper, @($command)) | Out-Null
    Assert ($stepper.playerController.DropCalls -eq $dropsBefore) 'Cooldown wait or retry released fruit early'
    $stepper.playerController.CanDropFruit=$true
    Invoke-Private $stepper 'FixedUpdate'
    $handler.Invoke($stepper, @($command)) | Out-Null
    Invoke-Private $stepper 'FixedUpdate'
    Assert ($stepper.playerController.DropCalls -eq ($dropsBefore+1)) 'Cooldown completion did not drop exactly once'
    Write-Output 'PASS: AI waits through cooldown and drops once after release, including command retry'
    Write-Output 'PASS: diagnostic horizon, normal horizon unchanged, invalid horizon rejected'
    Write-Output 'PASS: step retries, busy rejection, completion window, coordinate rejection, stale/terminal commands'
} finally {
    $c.StopCommunication()
    if ($null -ne $replacement) { $replacement.StopCommunication() }
    if ($null -ne $stepper) { $stepper.StopCommunication() }
    $receiver.Close()
}
# スタブはUnityのコルーチンスケジューラー・Scene・JSON変換を検証しない。

# Compile and exercise the REAL ledger code with deterministic score/time boundaries.
$ledger=New-Object UDPCommunicatorUnity
[ScoreManager]::Instance.score=0
[UnityEngine.Time]::timeAsDouble=0
[UnityEngine.Time]::fixedTimeAsDouble=0
$ledger.BeginEpisode('ledger-test')
$begin=$ledger.GetType().GetMethod('BeginRewardStep',$flags)
$end=$ledger.GetType().GetMethod('EndRewardStep',$flags)
$read=$ledger.GetType().GetMethod('ReadRewardAccounting',$flags)
[ScoreManager]::Instance.score=7
[UnityEngine.Time]::timeAsDouble=1
$begin.Invoke($ledger,@([long]1,[int]7))|Out-Null
[ScoreManager]::Instance.score=10
[UnityEngine.Time]::timeAsDouble=2
$end.Invoke($ledger,@([int]10))|Out-Null
$one=$read.Invoke($ledger,@([int]10))
Assert ($one.conserved -and $one.step_reward_total -eq 3 -and $one.between_steps_reward_total -eq 7) 'Gap or step score lost'
$again=$read.Invoke($ledger,@([int]10))
Assert ($again.step_reward_total -eq 3 -and $again.between_steps_reward_total -eq 7) 'Repeated observation double-counted rewards'
[ScoreManager]::Instance.score=15
[UnityEngine.Time]::timeAsDouble=3
$open=$read.Invoke($ledger,@([int]15))
Assert ($open.conserved -and $open.open_interval.phase -eq 'between_steps' -and $open.open_interval.reward -eq 5) 'Thinking-time score not visible'
$begin.Invoke($ledger,@([long]2,[int]15))|Out-Null
[ScoreManager]::Instance.score=18
[UnityEngine.Time]::timeAsDouble=4
$end.Invoke($ledger,@([int]18))|Out-Null
$two=$read.Invoke($ledger,@([int]18))
Assert ($two.conserved -and $two.step_reward_total -eq 6 -and $two.between_steps_reward_total -eq 12 -and $one.step_reward_total -eq 3) 'Intervals overlap or cached result mutated'
$ledger.CaptureEpisodeRewardSummary()
[ScoreManager]::Instance.score=0
$ledger.BeginEpisode('ledger-reset')
$reset=$read.Invoke($ledger,@([int]0))
Assert ($reset.conserved -and $reset.step_reward_total -eq 0 -and $reset.between_steps_reward_total -eq 0) 'Reset leaked prior reward'
$saved=$ledger.GetType().GetField('previousEpisodeRewards',$flags).GetValue($ledger)
Assert ($saved.episode_score -eq 18 -and $saved.conserved) 'Reset lost previous episode summary'
Write-Output 'PASS: disjoint step/gap rewards, thinking-time open interval, repeated reads, immutable completion, conservation and reset summary'
