using System;
using UnityEngine;

// Per-process startup only; never changes fixedDeltaTime, timeScale or physics settings.
public static class SuikaWorkerOptions
{
    public static string GameId { get; private set; } = "single";
    public static bool Worker { get; private set; }
    public static int ListenPort { get; private set; } = 7773;
    public static int PythonPort { get; private set; } = 7889;
    public static int Seed { get; private set; }
    public static bool AudioEnabled = true;
    public static bool EventsEnabled {get;private set;}
    public static string VideoMap = "";
    public static bool HasSeed { get; private set; }
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
    static void Initialize()
    {
        GameId="single";Worker=false;ListenPort=7773;PythonPort=7889;HasSeed=false;
        AudioEnabled=true; VideoMap="";EventsEnabled=false;
        string[] args=Environment.GetCommandLineArgs();
        for(int i=0;i<args.Length;i++)
        {
            string key=args[i];
            if(!key.StartsWith("--suika-",StringComparison.Ordinal)) continue;
            Worker=true;
            if(i+1>=args.Length) throw new ArgumentException("Missing worker option value: "+key);
            string value=args[++i];
            switch(key)
            {
                case "--suika-game-id": GameId=value; break;
                case "--suika-listen-port": ListenPort=Port(value); break;
                case "--suika-python-port": PythonPort=Port(value); break;
                case "--suika-seed": Seed=int.Parse(value);HasSeed=true;break;
                case "--suika-events": EventsEnabled=value=="1"?true:value=="0"?false:throw new ArgumentException("events must be 0/1");break;
                case "--suika-audio": AudioEnabled=value=="1" ? true : value=="0" ? false : throw new ArgumentException("audio must be 0/1"); break;
                case "--suika-video-map": VideoMap=value; break;
                default: throw new ArgumentException("Unknown worker option: "+key);
            }
        }
        if(string.IsNullOrEmpty(GameId) || GameId.Length>128 || ListenPort==PythonPort)
            throw new ArgumentException("Invalid game ID/worker ports");
        SuikaAudio.Initialize(AudioEnabled && System.Array.IndexOf(args,"-nographics")<0);
        if(HasSeed) UnityEngine.Random.InitState(Seed);
        if(Worker) Application.runInBackground=true;
    }
    static int Port(string value)
    {
        int port=int.Parse(value);
        if(port<1024 || port>65535) throw new ArgumentOutOfRangeException("port");
        return port;
    }
}
