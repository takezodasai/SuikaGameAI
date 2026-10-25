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
    // Runtime episode state: only a physical collision after release arms game over.
    public bool HasCollided { get; private set; }

    // Instantiate does not copy runtime-only properties. Pending merges are rejected by Predict.
    internal void CopyPredictionStateFrom(FruitEvolution source)
    {
        IsPreview = source.IsPreview;
        HasCollided = source.HasCollided;
    }

    public bool CanTriggerGameOver(float height)
    {
        return gameObject.activeInHierarchy && !IsPreview && !isMerging &&
            HasCollided && transform.position.y > height;
    }
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
        using(MctsPerformance.Measure("collision_callbacks")) CollisionCore(collision);
    }
    void CollisionCore(Collision2D collision)
    {
        if (IsPreview) return; // Held/NEXT trigger contacts must never arm this fruit.
        HasCollided = true;
        PredictionDiagnostics.Collision(this, collision);
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
                    SuikaAudio.PlayEffect(mergeSound, mergePosition);
                }

                // スイカ同士の場合は消滅（得点加算はしない）
                if (fruitType == 10)
                {
                    PredictionDiagnostics.Merge(this, otherFruit, null);
                    if(Simulation==null && ScoreManager.Instance!=null)ScoreManager.Instance.RecordMerge(fruitType,-1);
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

                    Collider2D shape = FruitColliderShape.Get(evolvedFruit);
                    if (shape != null) shape.isTrigger = false;
                    else Debug.LogError("Evolved fruit has no enabled Collider2D: " + evolvedFruit.name);

                    // 新たな果物に進化情報を設定
                    FruitEvolution fe = evolvedFruit.GetComponent<FruitEvolution>();
                    if (fe != null)
                    {
                        fe.fruitType = nextType;
                        fe.mergeSound = mergeSound;
                        // The new fruit was produced by a physical contact; do not
                        // reset game-over eligibility until its next collision.
                        fe.HasCollided = true;
                    }
                    else
                    {
                        Debug.LogError("Evolved prefab does not have a FruitEvolution component.");
                    }

                    PredictionDiagnostics.Merge(this, otherFruit, fe);
                    if(Simulation==null && ScoreManager.Instance!=null)ScoreManager.Instance.RecordMerge(fruitType,nextType);

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
    void OnDestroy() { PredictionDiagnostics.Removed(this, "destroyed"); }

    void RemoveFruit(FruitEvolution fruit)
    {
        PredictionDiagnostics.Removed(fruit, "remove_requested");
        if (Simulation == null) Destroy(fruit.gameObject);
        else Simulation.DeferRemoval(fruit.gameObject);
    }

}
