using TMPro;
using UnityEngine;

public class ScoreManager : MonoBehaviour
{
    public static ScoreManager Instance { get; private set; }

    public int[] evolutionScores = new int[] { 1, 3, 6, 10, 15, 21, 28, 36, 45, 55 };

    public int totalScore = 0;
    // Observation-only episode counters; prediction worlds never call these.
    public int EpisodeMergeCount {get;private set;}
    public int EpisodeMaxFruitType {get;private set;} = -1;
    public void RecordDroppedFruit(int type) {EpisodeMaxFruitType=Mathf.Max(EpisodeMaxFruitType,type);}
    public void RecordMerge(int fromType,int createdType)
    {EpisodeMergeCount++;EpisodeMaxFruitType=Mathf.Max(EpisodeMaxFruitType,Mathf.Max(fromType,createdType));}

    private TextMeshProUGUI scoreText; // 現在のスコアを表示するTextMeshProUGUI
    private TextMeshProUGUI maxScoreText; // 最大スコアを表示するTextMeshProUGUI

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        LoadMaxScore(); // 最大スコアをロード
    }

    private void Start()
    {
        AttachUIElements(); // TextMeshProUGUI を取得
        UpdateScoreUI();    // UIを更新
    }

    private void AttachUIElements()
    {
        GameObject scoreObject = GameObject.Find("Score");
        GameObject maxScoreObject = GameObject.Find("MaxScore");

        if (scoreObject != null)
        {
            scoreText = scoreObject.GetComponent<TextMeshProUGUI>();
        }
        else
        {
            Debug.LogError("ScoreManager: Scoreオブジェクトが見つかりません！");
        }

        if (maxScoreObject != null)
        {
            maxScoreText = maxScoreObject.GetComponent<TextMeshProUGUI>();
        }
        else
        {
            Debug.LogError("ScoreManager: MaxScoreオブジェクトが見つかりません！");
        }
    }

    public void AddScoreForEvolution(int currentFruitType)
    {
        if (currentFruitType >= 0 && currentFruitType < evolutionScores.Length)
        {
            totalScore += evolutionScores[currentFruitType];
            UpdateScoreUI();
        }
        else
        {
            Debug.LogWarning("不正な果物タイプです: " + currentFruitType);
        }
    }

    private void UpdateScoreUI()
    {
        if (scoreText != null)
        {
            scoreText.text = totalScore.ToString();
        }

        if (totalScore > GameScoreStatic.maxScore)
        {
            GameScoreStatic.maxScore = totalScore;
        }

        if (maxScoreText != null)
        {
            maxScoreText.text = GameScoreStatic.maxScore.ToString();
        }
    }

    private int LoadMaxScore()
    {
        return GameScoreStatic.maxScore;
    }

    public int GetScore()
    {
        return totalScore;
    }

    public void ResetScore()
    {
        totalScore = 0;
        EpisodeMergeCount=0;EpisodeMaxFruitType=-1;
        UpdateScoreUI();
    }
}

public static class GameScoreStatic
{
    public static int maxScore = 0;  // 最大スコアを static にしてシーン間で共有
}
