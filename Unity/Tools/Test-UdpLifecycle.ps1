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
  public bool IsPreview, IsMerging; public int fruitType; public long ObservationId;
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
 public static class Time { public static float timeScale=1, fixedDeltaTime=0.02f; }
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
 public class Result {}
 public static Result Predict(PlayerController p,GameManager g,float x) { return new Result(); }
}
public class PlayerController {
 public bool StepControlLocked;
 public float aiMoveSpeed=2.5f, moveDirection;
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
public class ScoreManager { public static ScoreManager Instance = new ScoreManager(); public int GetScore() { return 0; } }
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
    Write-Output 'PASS: step retries, busy rejection, completion window, coordinate rejection, stale/terminal commands'
} finally {
    $c.StopCommunication()
    if ($null -ne $replacement) { $replacement.StopCommunication() }
    if ($null -ne $stepper) { $stepper.StopCommunication() }
    $receiver.Close()
}
# スタブはUnityのコルーチンスケジューラー・Scene・JSON変換を検証しない。
