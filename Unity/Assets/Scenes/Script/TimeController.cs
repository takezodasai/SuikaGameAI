using UnityEngine;

public class TimeController : MonoBehaviour
{
    [Range(0.1f, 10f)]
    public float timeMultiplier = 1f; // Inspector で変更可能な時間倍率

    void Update()
    {
        Time.timeScale = timeMultiplier; // ゲーム全体の時間の進行速度を設定
    }

    void OnValidate()
    {
        Time.timeScale = timeMultiplier; // Inspector上で変更した時にも即時反映
    }
}
