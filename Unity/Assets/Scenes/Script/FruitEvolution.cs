using UnityEngine;

public class FruitEvolution : MonoBehaviour
{
    [Tooltip("0:サクランボ, 1:イチゴ, 2:ブドウ, 3:デコポン, 4:みかん, 5:リンゴ, 6:梨, 7:桃, 8:パイナップル, 9:メロン, 10:スイカ")]
    public int fruitType;
    // Null in the real game. Prediction redirects only side effects, not merge rules.
    public SuikaPhysicsSimulator Simulation { get; set; }

    public AudioClip mergeSound;
    public UDPCommunicatorUnity udpcomm;
    private bool isMerging = false;
    // Runtime-only observation role. Never infer a fruit's role from its name/tag.
    public bool IsPreview { get; set; }
    public bool IsMerging { get { return isMerging; } }
    private static long nextObservationId;
    private long observationId;
    public long ObservationId
    {
        get { if (observationId == 0) observationId = ++nextObservationId; return observationId; }
    }


    private void Start()
    {
        if (Simulation != null) return;
        if (udpcomm == null)
        {
            udpcomm = FindObjectOfType<UDPCommunicatorUnity>();
            if (udpcomm == null)
            {
                Debug.LogError("UDPCommunicatorUnity がシーン内に存在しません！");
            }
        }
    }

    private void OnCollisionEnter2D(Collision2D collision)
    {
        if (isMerging) return;

        FruitEvolution otherFruit = collision.gameObject.GetComponent<FruitEvolution>();
        if (otherFruit != null && otherFruit.Simulation == Simulation && !otherFruit.isMerging)
        {
            if (otherFruit.fruitType == this.fruitType)
            {
                isMerging = true;
                otherFruit.isMerging = true;
                Vector3 mergePosition = (transform.position + otherFruit.transform.position) / 2;

                // 合体時の効果音
                if (Simulation == null && mergeSound != null)
                {
                    AudioSource.PlayClipAtPoint(mergeSound, mergePosition);
                }

                // スイカ同士の場合は消滅（得点加算はしない）
                if (fruitType == 10)
                {
                    RemoveFruit(otherFruit);
                    RemoveFruit(this);
                    if (Simulation == null) udpcomm.SendObservationsWaterMelon();
                    return;
                }
                else
                {
                    int nextType = fruitType + 1;
                    GameObject[] evolutionPrefabs = EvolutionDatabase.Instance.evolutionPrefabs;
                    if (nextType >= evolutionPrefabs.Length || evolutionPrefabs[nextType] == null)
                    {
                        Debug.LogError($"No evolution prefab available for fruitType {fruitType} (nextType: {nextType}). Check your EvolutionDatabase's evolutionPrefabs array.");
                        return;
                    }

                    // 進化先のPrefabを生成
                    GameObject evolvedFruit = Simulation == null
                        ? Instantiate(evolutionPrefabs[nextType], mergePosition, Quaternion.identity)
                        : Simulation.CreateEvolved(evolutionPrefabs[nextType], mergePosition);

                    // 物理コンポーネントを追加
                    Rigidbody2D rb = evolvedFruit.GetComponent<Rigidbody2D>();
                    if (rb == null) rb = evolvedFruit.AddComponent<Rigidbody2D>();
                    rb.gravityScale = 1;

                    PolygonCollider2D polyCollider = evolvedFruit.GetComponent<PolygonCollider2D>();
                    if (polyCollider == null) polyCollider = evolvedFruit.AddComponent<PolygonCollider2D>();
                    polyCollider.enabled = true;
                    polyCollider.isTrigger = false;

                    // 新たな果物に進化情報を設定
                    FruitEvolution fe = evolvedFruit.GetComponent<FruitEvolution>();
                    if (fe != null)
                    {
                        fe.fruitType = nextType;
                        fe.mergeSound = mergeSound;
                    }
                    else
                    {
                        Debug.LogError("Evolved prefab does not have a FruitEvolution component.");
                    }

                    // 得点加算：進化する前の fruitType を使ってスコアを加算（例：サクランボ→イチゴの場合は fruitType=0 なので 1点）
                    if (Simulation != null) Simulation.AddScore(fruitType);
                    else if (ScoreManager.Instance != null)
                    {
                        ScoreManager.Instance.AddScoreForEvolution(fruitType);
                        
                    }

                    // 元の果物を削除
                    RemoveFruit(otherFruit);
                    RemoveFruit(this);
                    if (fruitType == 6)
                    {
                        if (Simulation == null) udpcomm.SendObservationsNashi();
                    }
                    if (fruitType == 7)
                    {
                        if (Simulation == null) udpcomm.SendObservationsPeach();
                    }
                    if (fruitType == 8)
                    {
                        if (Simulation == null) udpcomm.SendObservationsPin();
                    }
                    if (fruitType == 9)
                    {
                        if (Simulation == null) udpcomm.SendObservationsMelon();
                    }
                }
            }
        }
    }
    void RemoveFruit(FruitEvolution fruit)
    {
        if (Simulation == null) Destroy(fruit.gameObject);
        else Simulation.DeferRemoval(fruit.gameObject);
    }

}
