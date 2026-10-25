using System;
using System.Collections;
using System.IO.MemoryMappedFiles;
using UnityEngine;
using UnityEngine.Rendering;

// One-process video prototype: latest frame only, separate from gameplay UDP.
public sealed class SuikaVideo : MonoBehaviour
{
    public const int Width=640,Height=360,Header=128,Capacity=Header+Width*Height*4;
    public static SuikaVideo Instance { get; private set; }
    public bool Capturing { get; private set; }
    public long Revision { get; private set; }
    public int Frames { get; private set; }
    public int Dropped { get; private set; }
    public int RenderTextures { get { return (full!=null?1:0)+(small!=null?1:0); } }
    public int Readbacks { get; private set; }
    public double CaptureMs { get; private set; }
    public double PublishMs { get; private set; }
    public string LastError { get; private set; }="";
    MemoryMappedFile map; MemoryMappedViewAccessor view; MemoryMappedViewStream pixels;
    RenderTexture full,small; bool pending,closing; long sequence; byte[] bytes;
    double nextCapture;
    static long UtcMs() {return DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();}
    public static void StartIfConfigured(GameObject owner)
    {
        if(string.IsNullOrEmpty(SuikaWorkerOptions.VideoMap)) return; // No component/resources when OFF by default.
        var video=owner.AddComponent<SuikaVideo>();
        video.Set(true,1);
    }
    void Awake() {Instance=this; StartCoroutine(CaptureLoop());}
    public void Set(bool enabled,long revision)
    {
        if(revision<=Revision) return; Revision=revision;
        if(enabled && (SystemInfo.graphicsDeviceType==GraphicsDeviceType.Null || !SystemInfo.supportsAsyncGPUReadback))
        {LastError="Video requires a graphics Player and AsyncGPUReadback"; enabled=false;}
        Capturing=enabled;
        if(!enabled && !pending) Release();
    }
    IEnumerator CaptureLoop()
    {
        var end=new WaitForEndOfFrame();
        while(true)
        {
            yield return end;
            if(!Capturing || Time.realtimeSinceStartupAsDouble<nextCapture) continue;
            nextCapture=Time.realtimeSinceStartupAsDouble+1.0/15;
            if(pending) {Dropped++;continue;}
            try {Capture();}
            catch(Exception e) {LastError=e.GetType().Name+": "+e.Message;Capturing=false;Release();}
        }
    }
    void Capture()
    {
        if(full==null || full.width!=Screen.width || full.height!=Screen.height)
        {
            Release();
            full=new RenderTexture(Screen.width,Screen.height,0,RenderTextureFormat.ARGB32);full.Create();
            small=new RenderTexture(Width,Height,0,RenderTextureFormat.ARGB32);small.Create();
            bytes=new byte[Width*Height*4];
            map=MemoryMappedFile.CreateOrOpen(SuikaWorkerOptions.VideoMap,Capacity);
            view=map.CreateViewAccessor();
            pixels=map.CreateViewStream(Header,Width*Height*4);
        }
        var watch=System.Diagnostics.Stopwatch.StartNew();
        long captured=UtcMs();int score=ScoreManager.Instance!=null?ScoreManager.Instance.GetScore():0;
        var gm=FindObjectOfType<GameManager>();bool go=gm!=null&&gm.isGameOver;
        ScreenCapture.CaptureScreenshotIntoRenderTexture(full);
        Graphics.Blit(full,small);
        CaptureMs=watch.Elapsed.TotalMilliseconds; pending=true;Readbacks++;
        AsyncGPUReadback.Request(small,0,TextureFormat.RGBA32,request=>
        {
            pending=false;
            if(closing || !Capturing) {Release();return;}
            if(request.hasError) {LastError="GPU readback failed";Capturing=false;Release();return;}
            try
            {
                double callbackMs=watch.Elapsed.TotalMilliseconds;
                var publish=System.Diagnostics.Stopwatch.StartNew();
                request.GetData<byte>().CopyTo(bytes);
                // Aligned sequence is odd during write, even after publication. Reader never waits.
                view.Write(0,++sequence); System.Threading.Thread.MemoryBarrier();
                view.Write(8,1);view.Write(12,Width);view.Write(16,Height);
                view.Write(24,captured);view.Write(32,UtcMs());view.Write(40,score);
                view.Write(44,go?1:0);view.Write(48,++Frames);view.Write(52,1);
                view.Write(56,CaptureMs);pixels.Position=0;pixels.Write(bytes,0,bytes.Length);
                PublishMs=publish.Elapsed.TotalMilliseconds;
                view.Write(64,callbackMs);view.Write(72,PublishMs);
                System.Threading.Thread.MemoryBarrier();view.Write(0,++sequence);
                if(SuikaRuntimeProbe.Instance!=null)SuikaRuntimeProbe.Instance.RecordVideo(CaptureMs,callbackMs,PublishMs);
            }
            catch(Exception e) {LastError=e.GetType().Name+": "+e.Message;Capturing=false;Release();}
        });
    }
    void Release()
    {
        if(pending) return;
        if(pixels!=null) {pixels.Dispose();pixels=null;}
        if(view!=null) {view.Dispose();view=null;} if(map!=null) {map.Dispose();map=null;}
        if(full!=null) {full.Release();Destroy(full);full=null;}
        if(small!=null) {small.Release();Destroy(small);small=null;}
        bytes=null;
    }
    void OnDestroy() {closing=true;Capturing=false;Release();if(Instance==this)Instance=null;}
}
