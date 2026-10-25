using UnityEngine;
using UnityEngine.EventSystems;  // 必要なら利用

public partial class PlayerController : MonoBehaviour
{
    public float speed = 7.5f;                      // プレイヤーの移動速度
    private Rigidbody2D rb;                       // プレイヤーのRigidbody2D
    public GameObject[] fruits;                   // 果物のPrefab配列（Inspectorから設定）
    public GameObject currentFruit;               // 現在保持している果物（外部から参照可能にpublicにしています）
    public GameObject nextFruitObject;            // 次に出る果物のオブジェクト（外部から参照可能にpublicにしています）
    private int heldBaseSortingOrder;
    private Transform hand;                       // プレイヤーの手元位置（通常は自分自身のTransformを利用）
    private Vector3 nextFruitPosition = new Vector3(5.948f, 2.177f, 0.0f); // NEXT欄の位置

    [Header("NEXT display (background image coordinates)")]
    public RectTransform nextPreviewBackground;
    [Tooltip("Normalized image position, left/bottom = 0. Centre of the NEXT circle.")]
    public Vector2 nextPreviewAnchor = new Vector2(1625f / 1920f, 1f - 290f / 1080f);

    [Header("Held fruit position (world-space offset)")]
    public Vector3 heldFruitOffset = new Vector3(-0.7f, -0.42f, -1f);

    [Header("Drop interval")]
    [Min(0f), Tooltip("Minimum game seconds between successful drops.")]
    public float dropCooldownSeconds = 0.4f;
    private double nextDropAllowedAt;
    internal double NextDropAllowedAt { get { return nextDropAllowedAt; } }
    public float DropCooldownRemaining { get { return (float)System.Math.Max(0, nextDropAllowedAt - Time.timeAsDouble); } }
    public bool CanDropFruit { get { return currentFruit != null && Time.timeScale > 0 && Time.timeAsDouble >= nextDropAllowedAt; } }

    public AudioClip dropSound;                   // 果物を落とす際の効果音

    // 移動制御用：エージェントからの命令により連続的に移動させる（-1:左, 1:右, 0:停止）
    public float moveDirection = 0f;
    public float decayRate = 0.9f;                // 移動入力の減衰率（命令後、徐々に0に近づく）

    // 壁との衝突判定用フラグ
    public bool isFruitCollidingWithWallLeft = false;
    public bool isFruitCollidingWithWallRight = false;
    private float Distance = 1.5f;   // "left" または "right"
    private Vector3 spawnPosition; // スポーン地点を保持
    public float eftWarpThreshold = -3.3f; // ワープする境界
    public float rightWarpThreshold = 3.8f;

    void Start()
    {
        rb = GetComponent<Rigidbody2D>();         // Rigidbody2Dを取得
        hand = this.transform;                      // 自身のTransformを手元位置として使用
        spawnPosition = transform.position; // 初期位置を記録
        ChooseNextFruit();                          // 次の果物を決定
        SpawnFruit();                               // 最初の果物を生成
    }

    void Update()
    {
        // エージェントからの命令に基づいて移動（連続的な入力をmoveDirectionで管理）
        rb.velocity = new Vector2(0, rb.velocity.y); // Horizontal movement uses the shared safe range in FixedUpdate.
        // 減衰処理：命令後も徐々に移動が止まるようにする
        moveDirection *= decayRate;
        if (Mathf.Abs(moveDirection) < 0.01f) moveDirection = 0f;

        // 持っている果物は、プレイヤーの手元に追従させる
        if (currentFruit != null)
        {
            // ここでオフセットを調整して、プレイヤーの手元に果物を配置
            hand = this.transform;
            Vector3 fruitPosition = GetHeldWorldPosition();
            currentFruit.transform.position = fruitPosition;
        }

        // Clamp before rendering or accepting a manual drop; do not warp at fixed X.
        if (currentFruit != null) EnsureHeldWithinRange(out _);

        if (!StepControlLocked && (Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow)))
        {
            MoveLeft();
        }
        else if (!StepControlLocked && (Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow)))
        {
            MoveRight();
        }

        if (!StepControlLocked && Input.GetKeyDown(KeyCode.Return))
        {
            DropFruit();
        }

        if (Distance > Mathf.Abs(transform.position.x))
        {
            isFruitCollidingWithWallLeft = false;
            isFruitCollidingWithWallRight = false;
        }

    }

    // エージェントが左移動命令を出す場合に呼ばれる
    public void MoveLeft()
    {
        if (!StepControlLocked) moveDirection = -NormalMoveInput;
    }

    // エージェントが右移動命令を出す場合に呼ばれる
    public void MoveRight()
    {
        if (!StepControlLocked) moveDirection = NormalMoveInput;
    }

    public void MoveLeft1()
    {
        if (!StepControlLocked) moveDirection = -1.5f;
    }

    // エージェントが右移動命令を出す場合に呼ばれる
    public void MoveRight1()
    {
        if (!StepControlLocked) moveDirection = 1.5f;
    }

    public void MoveLeft01()
    {
        if (!StepControlLocked) moveDirection = -0.1f;
    }

    // エージェントが右移動命令を出す場合に呼ばれる
    public void MoveRight01()
    {
        if (!StepControlLocked) moveDirection = 0.1f;
    }

    // エージェントが果物落下命令を出す場合に呼ばれる
    public void DropFruit()
    {
        if (currentFruit == null)
        {
            //Debug.LogError("DropFruit() was called, but currentFruit is null!");
            return;
        }

        if (!CanDropFruit || !EnsureHeldWithinRange(out string placementError))
            return; // Never release an overlapping fruit or bypass a paused game.

        if (dropSound != null)
        {
            SuikaAudio.PlayEffect(dropSound, currentFruit.transform.position);
        }

        // 落下時に果物のRigidbody2Dを取得し、重力を有効にする
        Rigidbody2D rbFruit = currentFruit.GetComponent<Rigidbody2D>();
        if (rbFruit == null)
        {
            rbFruit = currentFruit.AddComponent<Rigidbody2D>();
        }
        ReleaseFruitBody(rbFruit);
        var droppedRenderer = currentFruit.GetComponent<SpriteRenderer>();
        if (droppedRenderer != null) droppedRenderer.sortingOrder = heldBaseSortingOrder;

        // 落下時は、衝突判定を有効にするため、コライダーのisTriggerをOFFにする
        Collider2D pc = FruitColliderShape.Get(currentFruit);
        if (pc != null)
        {
            pc.isTrigger = false;
        }
        else
        {
            Debug.LogWarning("Enabled Collider2D is not attached to the current fruit.");
        }

        currentFruit.GetComponent<FruitEvolution>().IsPreview = false;
        if(ScoreManager.Instance!=null)ScoreManager.Instance.RecordDroppedFruit(currentFruit.GetComponent<FruitEvolution>().fruitType);
        nextDropAllowedAt = Time.timeAsDouble + Mathf.Max(0f, dropCooldownSeconds);
        currentFruit = null;  // 保持中の果物をクリア
        SpawnFruit();         // 次の果物を生成

        //Debug.Log("DropFruit command executed.");
    }

    // UDPやその他から参照されるため、PlayerControllerが保持しているcurrentFruit, nextFruitObjectはpublicなプロパティとして使用しています
    // ChooseNextFruit: 次の果物オブジェクトを決定し、生成する
    void ChooseNextFruit()
    {
        if (fruits.Length > 0)
        {
            int randomIndex = Random.Range(0, fruits.Length);
            GameObject nextFruitPrefab = fruits[randomIndex];

            if (nextFruitObject != null)
            {
                Destroy(nextFruitObject);
            }

            nextFruitObject = Instantiate(nextFruitPrefab, nextFruitPosition, Quaternion.identity);
            nextFruitObject.GetComponent<FruitEvolution>().IsPreview = true;
            var nextRenderer = nextFruitObject.GetComponent<SpriteRenderer>();
            if (nextRenderer != null) nextRenderer.sortingOrder = 30;
            PreparePreviewBody(nextFruitObject, true);
            PositionNextFruit();
            // Fruitスクリプトを追加して、元のPrefab情報を保持させる
            nextFruitObject.AddComponent<Fruit>().originalPrefab = nextFruitPrefab;
        }
        else
        {
            Debug.LogError("No fruit prefabs assigned to the fruits array.");
        }
    }

    // SpawnFruit: 現在の果物を生成して保持する
    void SpawnFruit()
    {
        if (fruits.Length > 0)
        {
            Vector3 spawnPosition = GetHeldWorldPosition();
            GameObject nextPrefab = nextFruitObject.GetComponent<Fruit>().originalPrefab;
            currentFruit = Instantiate(nextPrefab, spawnPosition, Quaternion.identity);
            currentFruit.GetComponent<FruitEvolution>().IsPreview = true;
            var heldRenderer = currentFruit.GetComponent<SpriteRenderer>();
            if (heldRenderer != null)
            {
                heldBaseSortingOrder = heldRenderer.sortingOrder;
                heldRenderer.sortingOrder = 31; // Keep the held fruit visible in front of Player.
            }
            PreparePreviewBody(currentFruit, false);
            // Collision state belongs only to this new held object.
            isFruitCollidingWithWallLeft = false;
            isFruitCollidingWithWallRight = false;

            // 持っている間は、衝突判定を無効にするためにisTriggerをONにする
            Collider2D pc = FruitColliderShape.Get(currentFruit);
            if (pc != null)
            {
                pc.isTrigger = true;
            }

            // 持っている果物と壁の衝突を検出するためのスクリプトを追加する
            if (currentFruit.GetComponent<FruitCollisionHandler>() == null)
            {
                currentFruit.AddComponent<FruitCollisionHandler>().playerController = this;
            }

            //Debug.Log("Fruit spawned at position: " + spawnPosition);
            InitializeStepPreview(); // All input paths clamp the new, possibly larger fruit.
            ChooseNextFruit();  // 次の果物を決定
        }
        else
        {
            Debug.LogError("No fruit prefabs assigned to the fruits array.");
        }
    }

    public Vector3 GetHeldWorldPosition() { return transform.position + heldFruitOffset; }

    void FixedUpdate()
    {
        if (rb == null || currentFruit == null || StepControlLocked) return;
        rb.velocity = new Vector2(0, rb.velocity.y);
        currentFruit.transform.position = GetHeldWorldPosition();
        DropRange range = GetDropRange();
        if (!range.valid) { moveDirection = 0; return; }
        float input = moveDirection;
        float oldX = currentFruit.transform.position.x;
        float target = Mathf.Clamp(oldX + input * speed * Time.fixedDeltaTime, range.min_x, range.max_x);
        bool moved = TryMoveHeldTo(target, range, out _);
        moveDirection = moved && target != oldX ? input : 0;
    }

    // Existing rigidbodies (e.g. grape) must not accumulate falling velocity in previews.
    public static void PreparePreviewBody(GameObject fruit, bool displayOnly)
    {
        var body = fruit.GetComponent<Rigidbody2D>();
        if (body == null) return;
        body.velocity = Vector2.zero;
        body.angularVelocity = 0;
        body.gravityScale = 0;
        // Held colliders still need simulation for wall trigger notifications.
        body.simulated = !displayOnly;
    }

    public static void ReleaseFruitBody(Rigidbody2D body)
    {
        body.velocity = Vector2.zero;
        body.angularVelocity = 0;
        body.gravityScale = 1;
        body.simulated = true;
    }

    void LateUpdate() { PositionNextFruit(); }

    public void PositionNextFruit()
    {
        if (nextFruitObject == null) return;
        Vector3 target = nextFruitPosition;
        if (nextPreviewBackground != null)
        {
            Rect rect = nextPreviewBackground.rect;
            target = nextPreviewBackground.TransformPoint(new Vector3(
                rect.xMin + rect.width * nextPreviewAnchor.x,
                rect.yMin + rect.height * nextPreviewAnchor.y, 0));
            target.z = nextFruitPosition.z;
        }
        // Sprite pivots differ by fruit; align the visible bounds, not the pivot.
        var sprite = nextFruitObject.GetComponent<SpriteRenderer>();
        Vector3 center = sprite != null ? sprite.bounds.center : nextFruitObject.transform.position;
        Vector3 offset = target - center;
        offset.z = target.z - nextFruitObject.transform.position.z;
        nextFruitObject.transform.position += offset;
    }

    public void ResetForEpisode()
    {
        nextDropAllowedAt = 0;
        currentFruit = null;
        nextFruitObject = null;
        transform.position = spawnPosition;
        rb.position = new Vector2(spawnPosition.x, spawnPosition.y);
        rb.velocity = Vector2.zero;
        rb.angularVelocity = 0;
        moveDirection = 0;
        isFruitCollidingWithWallLeft = false;
        isFruitCollidingWithWallRight = false;
        ChooseNextFruit();
        SpawnFruit();
    }

    // 壁との衝突状態を更新するための関数（FruitCollisionHandlerから呼ばれる）  
    public void SetFruitCollidingWithWallLeft(bool isColliding)
    {
        isFruitCollidingWithWallLeft = isColliding;
        //Debug.Log("Fruit collision with wall: " + (isColliding ? direction : "none"));
    }
    public void SetFruitCollidingWithWallRight(bool isColliding)
    {
        isFruitCollidingWithWallRight = isColliding;
        //Debug.Log("Fruit collision with wall: " + (isColliding ? direction : "none"));
    }
}
