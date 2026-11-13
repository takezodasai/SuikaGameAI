using UnityEngine;                               // Unityエンジンの基本クラスを利用
using System.Net;                                // IPアドレス等のネットワーク機能を利用
using System.Net.Sockets;                        // ソケット通信のクラスを利用
using System.Text;                               // 文字列エンコード用
using System.Collections;                        // コルーチン利用のため
// ※ UnityEngine.JsonUtility を利用してJSONのシリアライズ／デシリアライズを行います

public partial class UDPCommunicatorUnity : MonoBehaviour  // UDP通信を管理するMonoBehaviourクラス
{
    public string pythonIP = "127.0.0.1";           // Python側の受信先IP（送信先）
    public int pythonPort = 7889;                   // Python側の受信ポート番号
    public int listenPort = 7773;                   // Unityが行動メッセージ受信用にリッスンするポート
    public float sendInterval = 0.001f;              // 観測データ送信間隔（秒）

    private UdpClient udpListener;                  // 行動受信用UDPクライアント
    private UdpClient udpSender;                    // 観測送信用UDPクライアント
    private IPEndPoint remoteEndPoint;              // Python側のエンドポイント

    // ゲーム内の各データを取得するための参照（Inspectorから設定）
    public GameObject player;             // プレイヤーのTransform
    GameObject currentFruit;         // 持っている果物のTransform（PlayerControllerから設定可能）
    GameObject nextFruitObject;              // NextFruitの情報が得られるオブジェクト

    private Texture2D screenTexture;
    public Camera mainCamera;  // メインカメラ
    public PlayerController playerController;
    public GameManager gameManager;


    void Start()                                   // Start()はゲーム開始時に1回呼ばれる
    {
        if(SuikaStandaloneDemo.Active){BeginEpisode("");return;} // Offline AI demo: no remote control/socket.
        if(SuikaWorkerOptions.Worker)
        {
            listenPort=SuikaWorkerOptions.ListenPort;pythonPort=SuikaWorkerOptions.PythonPort;
            pythonIP="127.0.0.1";RemoteControl=true;
        }
        SuikaVideo.StartIfConfigured(gameObject);
        udpListener = new UdpClient(listenPort);    // 指定したポートでUDPリスナーを初期化
        udpListener.Client.ReceiveTimeout = 1000;   // 受信タイムアウトを1秒に設定
        udpSender = new UdpClient();                // UDP送信用クライアントを初期化
        remoteEndPoint = new IPEndPoint(IPAddress.Parse(pythonIP), pythonPort);  // Python側のエンドポイントを設定
                                                                                 // 🔹 画面サイズに合わせて Texture2D を初期化
        screenTexture = new Texture2D(Screen.width, Screen.height, TextureFormat.RGB24, false);
        BeginEpisode("");
        StartCoroutine(SendObservations());         // 定期的に観測データを送信するコルーチンを開始
    }

    void Update()                                  // Update()は毎フレーム呼ばれる
    {
        UpdateFrameSearch();
        if (udpListener != null && udpListener.Available > 0)            // 受信バッファにデータがあるか確認
        {
            try                                   // 例外処理ブロック開始
            {
                IPEndPoint sender = new IPEndPoint(IPAddress.Any, 0);  // 受信元のエンドポイントを初期化
                byte[] data = udpListener.Receive(ref sender);         // UDPパケットを受信
                string json = Encoding.UTF8.GetString(data);           // 受信したバイト列をUTF-8文字列に変換
                ActionMessage actionMsg = JsonUtility.FromJson<ActionMessage>(json);  // JSONをActionMessage型に変換
                if (actionMsg != null) HandleCommand(actionMsg);
            }
            catch (SocketException e)                                 // ソケット例外をキャッチ
            {
                Debug.Log("SocketException: " + e);                   // エラーをログに出力
            }
            catch (System.ArgumentException e)
            {
                Debug.LogWarning("Invalid UDP JSON: " + e.Message);
            }
        }
    }

    public IEnumerator SendObservations()               // 観測データを定期的に送信するコルーチン
    {
        yield return null; // All Start methods (including fruit generation) must finish first.
        while (udpSender != null)                  // 通信停止後は定期送信を終了
        {
            Observation obs = new Observation();    // 観測データ用のObservationインスタンスを作成
            // プレイヤー位置を設定（存在しなければゼロ）
            obs.playerPos = player != null ? new Vector3Data(player.transform.position) : new Vector3Data(Vector3.zero);
            // 持っている果物位置を設定（存在しなければゼロ）
            obs.fruitPos = playerController.currentFruit != null ? new Vector3Data(playerController.currentFruit.transform.position) : new Vector3Data(Vector3.zero);
            // NextFruit情報として、オブジェクト名を設定（なければ空文字）
            obs.nextFruitInfo = playerController.nextFruitObject != null ? playerController.nextFruitObject.name : "";
            obs.imageData = RemoteControl ? "" : CaptureScreen();
            obs.score = ScoreManager.Instance.GetScore();                           // スコア（ここではプレースホルダー）
            obs.done = gameManager.isGameOver;
            obs.nashi = false;
            obs.peach=false;
            obs.pin = false;
            obs.melon = false;
            obs.waterMelon = false;

            SendPacket(obs);
            yield return new WaitForSecondsRealtime(sendInterval); // Also observe terminal states while paused.
        }
    }

    public void SendObservationsOnce()
    {
        // 停止後の通知は送信しない（Scene再読込後はStartで再初期化）。
        if (udpSender == null) return;

        if (playerController == null || gameManager == null)
        {
            Debug.LogError("PlayerController or GameManager is not assigned!");
            return;
        }

        Observation obs = new Observation();
        obs.playerPos = player != null ? new Vector3Data(player.transform.position) : new Vector3Data(Vector3.zero);
        obs.fruitPos = playerController.currentFruit != null ? new Vector3Data(playerController.currentFruit.transform.position) : new Vector3Data(Vector3.zero);
        obs.nextFruitInfo = playerController.nextFruitObject != null ? playerController.nextFruitObject.name : "";
        obs.imageData = RemoteControl ? "" : CaptureScreen();
        obs.score = ScoreManager.Instance.GetScore();
        obs.done = true;  // ゲームオーバーを通知
        obs.nashi = false;
        obs.peach = false;
        obs.pin = false;
        obs.melon = false;
        obs.waterMelon = false;


        SendPacket(obs);

        Debug.Log("Game Over Observation sent.");
    }

    public void SendObservationsNashi()
    {
        // 停止後の通知は送信しない（Scene再読込後はStartで再初期化）。
        if (udpSender == null) return;

        if (playerController == null || gameManager == null)
        {
            Debug.LogError("PlayerController or GameManager is not assigned!");
            return;
        }

        Observation obs = new Observation();
        obs.playerPos = player != null ? new Vector3Data(player.transform.position) : new Vector3Data(Vector3.zero);
        obs.fruitPos = playerController.currentFruit != null ? new Vector3Data(playerController.currentFruit.transform.position) : new Vector3Data(Vector3.zero);
        obs.nextFruitInfo = playerController.nextFruitObject != null ? playerController.nextFruitObject.name : "";
        obs.imageData = RemoteControl ? "" : CaptureScreen();
        obs.score = ScoreManager.Instance.GetScore();
        obs.done = false;  // ゲームオーバーを通知
        obs.nashi = true;
        obs.peach = false;
        obs.pin = false;
        obs.melon = false;
        obs.waterMelon = false;

        SendPacket(obs);

    }

    public void SendObservationsPeach()
    {
        // 停止後の通知は送信しない（Scene再読込後はStartで再初期化）。
        if (udpSender == null) return;

        if (playerController == null || gameManager == null)
        {
            Debug.LogError("PlayerController or GameManager is not assigned!");
            return;
        }

        Observation obs = new Observation();
        obs.playerPos = player != null ? new Vector3Data(player.transform.position) : new Vector3Data(Vector3.zero);
        obs.fruitPos = playerController.currentFruit != null ? new Vector3Data(playerController.currentFruit.transform.position) : new Vector3Data(Vector3.zero);
        obs.nextFruitInfo = playerController.nextFruitObject != null ? playerController.nextFruitObject.name : "";
        obs.imageData = RemoteControl ? "" : CaptureScreen();
        obs.score = ScoreManager.Instance.GetScore();
        obs.done = false;  // ゲームオーバーを通知
        obs.nashi = false;
        obs.peach = true;
        obs.pin = false;
        obs.melon = false;
        obs.waterMelon = false;

        SendPacket(obs);

    }

    public void SendObservationsPin()
    {
        // 停止後の通知は送信しない（Scene再読込後はStartで再初期化）。
        if (udpSender == null) return;

        if (playerController == null || gameManager == null)
        {
            Debug.LogError("PlayerController or GameManager is not assigned!");
            return;
        }

        Observation obs = new Observation();
        obs.playerPos = player != null ? new Vector3Data(player.transform.position) : new Vector3Data(Vector3.zero);
        obs.fruitPos = playerController.currentFruit != null ? new Vector3Data(playerController.currentFruit.transform.position) : new Vector3Data(Vector3.zero);
        obs.nextFruitInfo = playerController.nextFruitObject != null ? playerController.nextFruitObject.name : "";
        obs.imageData = RemoteControl ? "" : CaptureScreen();
        obs.score = ScoreManager.Instance.GetScore();
        obs.done = false;  // ゲームオーバーを通知
        obs.nashi = false;
        obs.peach = false;
        obs.pin = true;
        obs.melon = false;
        obs.waterMelon = false;

        SendPacket(obs);

    }
    public void SendObservationsMelon ()
    {
        // 停止後の通知は送信しない（Scene再読込後はStartで再初期化）。
        if (udpSender == null) return;

        if (playerController == null || gameManager == null)
        {
            Debug.LogError("PlayerController or GameManager is not assigned!");
            return;
        }

        Observation obs = new Observation();
        obs.playerPos = player != null ? new Vector3Data(player.transform.position) : new Vector3Data(Vector3.zero);
        obs.fruitPos = playerController.currentFruit != null ? new Vector3Data(playerController.currentFruit.transform.position) : new Vector3Data(Vector3.zero);
        obs.nextFruitInfo = playerController.nextFruitObject != null ? playerController.nextFruitObject.name : "";
        obs.imageData = RemoteControl ? "" : CaptureScreen();
        obs.score = ScoreManager.Instance.GetScore();
        obs.done = false;  // ゲームオーバーを通知
        obs.nashi = false;
        obs.peach = false;
        obs.pin = false;
        obs.melon = true;
        obs.waterMelon = false;

        SendPacket(obs);

    }

    public void SendObservationsWaterMelon()
    {
        // 停止後の通知は送信しない（Scene再読込後はStartで再初期化）。
        if (udpSender == null) return;

        if (playerController == null || gameManager == null)
        {
            Debug.LogError("PlayerController or GameManager is not assigned!");
            return;
        }

        Observation obs = new Observation();
        obs.playerPos = player != null ? new Vector3Data(player.transform.position) : new Vector3Data(Vector3.zero);
        obs.fruitPos = playerController.currentFruit != null ? new Vector3Data(playerController.currentFruit.transform.position) : new Vector3Data(Vector3.zero);
        obs.nextFruitInfo = playerController.nextFruitObject != null ? playerController.nextFruitObject.name : "";
        obs.imageData = RemoteControl ? "" : CaptureScreen();
        obs.score = ScoreManager.Instance.GetScore();
        obs.done = false;  // ゲームオーバーを通知
        obs.nashi = false;
        obs.peach = false;
        obs.pin = false;
        obs.melon = false;
        obs.waterMelon = true;

        SendPacket(obs);

    }


    // 受信した行動を処理する関数
    void ProcessAction(int action)
    {
        if (playerController != null && playerController.StepControlLocked) return;
        if (gameManager != null && gameManager.isGameOver) return;
        //Debug.Log("Received action: " + action);   // 受信した行動をログ出力

        if (playerController == null)
        {
            Debug.LogError("PlayerController is not assigned!");
            return;
        }

        switch (action)
        {
            case 0:
                playerController.MoveLeft();
                break;
            case 1:
                playerController.MoveRight();
                break;
            case 2:
                playerController.DropFruit();
                break;
            case 3:
                break;
            case 4:
                playerController.MoveLeft1();
                break;
            case 5:
                playerController.MoveRight1();
                break;
            /*case 6:
                playerController.MoveLeft01();
                break;
            case 7:
                playerController.MoveRight01();
                break;*/
            default:
                Debug.LogWarning("Unknown action received: " + action);
                break;
        }
    }


    string CaptureScreen()
    {
        if(SystemInfo.graphicsDeviceType==UnityEngine.Rendering.GraphicsDeviceType.Null) return "";
        int targetWidth = Screen.width / 32;  // 例: 1/4 の解像度
        int targetHeight = Screen.height / 32;

        RenderTexture rt = new RenderTexture(targetWidth, targetHeight, 24);
        mainCamera.targetTexture = rt;
        mainCamera.Render();

        RenderTexture.active = rt;
        Texture2D smallTexture = new Texture2D(targetWidth, targetHeight, TextureFormat.RGB24, false);
        smallTexture.ReadPixels(new Rect(0, 0, targetWidth, targetHeight), 0, 0);
        smallTexture.Apply();

        mainCamera.targetTexture = null;
        RenderTexture.active = null;
        Destroy(rt);

        // PNGに変換
        byte[] imageBytes = smallTexture.EncodeToPNG();
        Destroy(smallTexture);  // メモリ解放

        return System.Convert.ToBase64String(imageBytes);
    }


    // JSON変換用のクラス：ActionMessage
    [System.Serializable]
    public partial class ActionMessage
    {
        public int action;                         // 送受信する行動（整数）
    }

    // JSON変換用のクラス：Observation
    [System.Serializable]
    public partial class Observation
    {
        public Vector3Data playerPos;              // プレイヤーの位置情報
        public Vector3Data fruitPos;               // 持っている果物の位置情報
        public string nextFruitInfo;               // NextFruitの情報（例：名前）
        public string imageData;                   // 画像データの文字列（ここではプレースホルダー）
        public int score;                          // 現在のスコア
        public bool done;
        public bool nashi;
        public bool peach;
        public bool pin;
        public bool melon;
        public bool waterMelon;
    }

    // JSON変換用のクラス：Vector3Data
    [System.Serializable]
    public class Vector3Data
    {
        public float x;                            // X座標
        public float y;                            // Y座標
        public float z;                            // Z座標
        public Vector3Data(Vector3 v)              // Vector3から変換するコンストラクタ
        {
            x = v.x;
            y = v.y;
            z = v.z;
        }
    }

    public void StopCommunication()
    {
        CancelFrameSearch();
        if (udpListener != null)
        {
            udpListener.Close();
            udpListener = null;
        }
        if (udpSender != null)
        {
            udpSender.Close();
            udpSender = null;
        }
        Debug.Log("UDP communication stopped.");
    }

    void OnDestroy()
    {
        StopCommunication(); // Scene再読込でも受信ポートを解放する。
    }

    void OnApplicationQuit()                        // アプリケーション終了時の処理
    {
        StopCommunication();
    }
}
