using UnityEngine;
using UnityEngine.EventSystems;  // 必要なら利用

public partial class PlayerController : MonoBehaviour
{
    public float speed = 5f;                      // プレイヤーの移動速度
    private Rigidbody2D rb;                       // プレイヤーのRigidbody2D
    public GameObject[] fruits;                   // 果物のPrefab配列（Inspectorから設定）
    public GameObject currentFruit;               // 現在保持している果物（外部から参照可能にpublicにしています）
    public GameObject nextFruitObject;            // 次に出る果物のオブジェクト（外部から参照可能にpublicにしています）
    private Transform hand;                       // プレイヤーの手元位置（通常は自分自身のTransformを利用）
    private Vector3 nextFruitPosition = new Vector3(5.948f, 2.177f, 0.0f); // NEXT欄の位置

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
        rb.velocity = new Vector2(moveDirection * speed, rb.velocity.y);
        // 減衰処理：命令後も徐々に移動が止まるようにする
        moveDirection *= decayRate;
        if (Mathf.Abs(moveDirection) < 0.01f) moveDirection = 0f;

        // 持っている果物は、プレイヤーの手元に追従させる
        if (currentFruit != null)
        {
            // ここでオフセットを調整して、プレイヤーの手元に果物を配置
            hand = this.transform;
            Vector3 fruitPosition = new Vector3(hand.position.x - 0.7f, hand.position.y - 0.39f, hand.position.z - 1.0f);
            currentFruit.transform.position = fruitPosition;
        }

        // 一定範囲を超えたらワープ
        if (transform.position.x < eftWarpThreshold || transform.position.x > rightWarpThreshold)
        {
            transform.position = new Vector3(spawnPosition.x, transform.position.y, transform.position.z);
            rb.velocity = Vector2.zero; // 速度リセット
        }

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
        if (isFruitCollidingWithWallLeft==false)
        {
            moveDirection = -0.5f;
        }
    }

    // エージェントが右移動命令を出す場合に呼ばれる
    public void MoveRight()
    {
        // 壁に衝突している方向が「右」でなければ右移動可能
        if (isFruitCollidingWithWallRight == false)
        {
            moveDirection = 0.5f;
            //Debug.Log("MoveRight command received.");
        }
    }

    public void MoveLeft1()
    {
        if (isFruitCollidingWithWallLeft == false)
        {
            moveDirection = -1.5f;
        }
    }

    // エージェントが右移動命令を出す場合に呼ばれる
    public void MoveRight1()
    {
        // 壁に衝突している方向が「右」でなければ右移動可能
        if (isFruitCollidingWithWallRight == false)
        {
            moveDirection = 1.5f;
            //Debug.Log("MoveRight command received.");
        }
    }

    public void MoveLeft01()
    {
        if (isFruitCollidingWithWallLeft == false)
        {
            moveDirection = -0.1f;
        }
    }

    // エージェントが右移動命令を出す場合に呼ばれる
    public void MoveRight01()
    {
        // 壁に衝突している方向が「右」でなければ右移動可能
        if (isFruitCollidingWithWallRight == false)
        {
            moveDirection = 0.1f;
            //Debug.Log("MoveRight command received.");
        }
    }

    // エージェントが果物落下命令を出す場合に呼ばれる
    public void DropFruit()
    {
        if (currentFruit == null)
        {
            //Debug.LogError("DropFruit() was called, but currentFruit is null!");
            return;
        }

        if (dropSound != null)
        {
            AudioSource.PlayClipAtPoint(dropSound, currentFruit.transform.position);
        }

        // 落下時に果物のRigidbody2Dを取得し、重力を有効にする
        Rigidbody2D rbFruit = currentFruit.GetComponent<Rigidbody2D>();
        if (rbFruit == null)
        {
            rbFruit = currentFruit.AddComponent<Rigidbody2D>();
        }
        rbFruit.gravityScale = 1;

        // 落下時は、衝突判定を有効にするため、コライダーのisTriggerをOFFにする
        PolygonCollider2D pc = currentFruit.GetComponent<PolygonCollider2D>();
        if (pc != null)
        {
            pc.isTrigger = false;
        }
        else
        {
            Debug.LogWarning("PolygonCollider2D is not attached to the current fruit.");
        }

        currentFruit.GetComponent<FruitEvolution>().IsPreview = false;
        currentFruit = null;  // 保持中の果物をクリア
        SpawnFruit();         // 次の果物を生成
        if (StepControlLocked) InitializeStepPreview();
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
            Vector3 spawnPosition = new Vector3(hand.position.x - 0.7f, hand.position.y - 0.39f, hand.position.z - 1.0f);
            GameObject nextPrefab = nextFruitObject.GetComponent<Fruit>().originalPrefab;
            currentFruit = Instantiate(nextPrefab, spawnPosition, Quaternion.identity);
            currentFruit.GetComponent<FruitEvolution>().IsPreview = true;

            // 持っている間は、衝突判定を無効にするためにisTriggerをONにする
            PolygonCollider2D pc = currentFruit.GetComponent<PolygonCollider2D>();
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
            ChooseNextFruit();  // 次の果物を決定
        }
        else
        {
            Debug.LogError("No fruit prefabs assigned to the fruits array.");
        }
    }

    public void ResetForEpisode()
    {
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
