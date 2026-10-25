using UnityEngine;

// Process-local presentation state. No random, physics, score or action bookkeeping.
public static class SuikaAudio
{
    public static bool Enabled { get; private set; } = true;
    public static long Revision { get; private set; }
    public static int Played { get; private set; }
    public static int Suppressed { get; private set; }
    public static void Initialize(bool enabled)
    { Revision=0; Played=Suppressed=0; Apply(enabled); }
    public static void Set(bool enabled,long revision)
    { if(revision<=Revision) return; Revision=revision; Apply(enabled); }
    static void Apply(bool enabled)
    {
        Enabled=enabled; AudioListener.pause=!enabled;
        // Stop existing one-shots immediately; do not touch other scene AudioSources.
        if(!enabled) foreach(var effect in Object.FindObjectsOfType<SuikaEffectSound>())
            if(effect!=null) Object.Destroy(effect.gameObject);
    }
    public static void PlayEffect(AudioClip clip,Vector3 position)
    {
        if(!Enabled) {Suppressed++; return;}
        if(clip==null) return;
        // Equivalent lifetime/spatial defaults to PlayClipAtPoint, with an owned marker.
        var go=new GameObject("Suika effect sound"); go.transform.position=position;
        go.AddComponent<SuikaEffectSound>();
        var source=go.AddComponent<AudioSource>(); source.clip=clip; source.spatialBlend=1;
        source.Play(); Played++; Object.Destroy(go,clip.length*Mathf.Max(Time.timeScale,.01f));
    }
}
