using TMPro;
using UnityEngine;
using UnityEngine.SceneManagement;
using System.Collections;

public class GameManager : MonoBehaviour
{
    [Header("Game Over Settings")]
    [Tooltip("画面の下からの割合でゲームオーバーとなる高さ (例: 0.9なら画面上から10%の位置)")]
    public float gameOverScreenRatio = 0.9f;
    public TextMeshProUGUI gameOverText; // ゲームオーバー表示用UI
    public TextMeshProUGUI scoreText;    // スコア表示用UI
    public UDPCommunicatorUnity udpcomm;

    public bool isGameOver = false;
    private float gameOverHeight;
    public float GameOverHeight { get { return gameOverHeight; } }

    void Start()
    {
        if (gameOverText != null)
            gameOverText.gameObject.SetActive(false);

        // オーソグラフィックカメラの場合、画面高さは 2 * orthographicSize です。
        Camera cam = Camera.main;
        float screenHeight = 2 * cam.orthographicSize;
        float bottomY = cam.transform.position.y - cam.orthographicSize;
        gameOverHeight = bottomY + screenHeight * gameOverScreenRatio;
    }

    void Update()
    {
        if (!isGameOver)
        {
            CheckGameOver();
        }
        else if (Input.GetKeyDown(KeyCode.Return)) // Enterキーで即リセット
        {
            RestartGameImmediately();
        }
    }

    void CheckGameOver()
    {
        GameObject[] fruits = GameObject.FindGameObjectsWithTag("Fruit");

        foreach (GameObject fruit in fruits)
        {
            if (fruit.transform.position.y > gameOverHeight)
            {
                
                GameOver();
                break;
            }
        }
    }

 

    void GameOver()
    {
        isGameOver = true;

        if (gameOverText != null)
            gameOverText.gameObject.SetActive(true);
        if (scoreText != null)
            scoreText.text = "Score: " + ScoreManager.Instance.GetScore();

        Time.timeScale = 0; // ゲームを停止

        // ゲームオーバー時の観測データを送信
        udpcomm.SendObservationsOnce();

        // Keep receiving reset commands at game over. Legacy manual play still auto-restarts.
        if (!udpcomm.RemoteControl)
            StartCoroutine(RestartGameCoroutine());
    }


    IEnumerator RestartGameCoroutine()
    {
        yield return new WaitForSecondsRealtime(2f); // 2秒待機（タイムスケールの影響を受けない）
        if (!udpcomm.RemoteControl) ResetGame("");
    }

    void RestartGameImmediately()
    {
        ResetGame("");
    }

    public void ResetGame(string requestId)
    {
        StopAllCoroutines();
        // Deactivate before deferred Destroy, so no old physics objects enter the new state.
        foreach (FruitEvolution fruit in FindObjectsOfType<FruitEvolution>())
        {
            fruit.gameObject.SetActive(false);
            Destroy(fruit.gameObject);
        }
        isGameOver = false;
        Time.timeScale = 1;
        if (gameOverText != null) gameOverText.gameObject.SetActive(false);
        ScoreManager.Instance.ResetScore();
        udpcomm.playerController.ResetForEpisode();
        Physics2D.SyncTransforms();
        udpcomm.BeginEpisode(requestId);
    }
}
