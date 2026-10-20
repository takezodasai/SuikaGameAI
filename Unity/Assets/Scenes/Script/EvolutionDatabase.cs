using UnityEngine;

public class EvolutionDatabase : MonoBehaviour
{
    public static EvolutionDatabase Instance { get; private set; }

    [Tooltip("進化順に並べる。例：0=サクランボ, 1=いちご, 2=ぶどう, 3=みかん, 4=かき, 5=リンゴ, 6=なし, 7=桃, 8=パイナップル, 9=メロン, 10=スイカ")]
    public GameObject[] evolutionPrefabs;

    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        // シーン切り替え時にも残す場合は以下を有効化
        // DontDestroyOnLoad(gameObject);
    }
}
