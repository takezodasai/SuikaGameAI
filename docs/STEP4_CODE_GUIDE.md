# STEP 4 実ソース解説（2026-10-20）

現在のdevelopの実ファイルから抜粋。行番号はこの版に対するもの。説明用の数値は実測ではなく、実測値は別紙STEP4_DIRECTION.mdに記す。今回、本番シミュレーターの計算は変更していない。

## 全体の役割とデータ

| ファイル | 主な関数・役割 | 入力 | 出力・連携 |
|---|---|---|---|
| SuikaPhysicsSimulator.cs | Predictが検査・寿命管理、Copyが複製、Runが固定刻み計算 | Unityの実オブジェクト、PlayerController、GameManager、正規化x、更新回数 | Result。別Sceneのローカル得点と果物配列 |
| PredictionDiagnostics.cs | Recorder.Captureで各更新の状態、Compareで差分 | Rigidbody・接触・合体イベント、2つのRecorder | 初期/最初の不一致の詳細、全更新の小さな誤差表 |
| FruitEvolution.cs | OnCollisionEnter2Dで実ゲームと予測が同じ進化規則を使用 | 衝突相手、fruitType、EvolutionDatabase | 進化した果物、ローカルまたは実スコア、削除要求 |
| UDPStepProtocol.cs | HandleStep、FixedUpdate、LateUpdate、CompleteStep | ActionMessage | 重複防止しつつ実ゲームの1手、比較時にはpredictionも返す |
| UDPStateProtocol.cs | HandleCommand、SendPacket、SendSnapshot | 受信要求、返却用Observation | JSON/必要時分割UDP。実盤面と予測盤面を別フィールドで格納 |
| check_unity_prediction.py | main、compare、summarize_trace | CLI条件、UnityEnvの受信状態 | 予測と実測の誤差・JSON報告 |

`Result`の`requested_x`は0〜1、`applied_x`はUnityワールド座標。`fruits`の位置はUnity単位、速度はUnity単位/秒、角度は度、角速度は度/秒。`reward=予測後score−初期score`。`physics_steps`は移動中も含む全更新数、`post_drop_steps`は落下した更新の次からの更新数。内部の新生成IDは負数、既存果物のIDは保持する。

現在の予測入力はPythonから送られたstate JSONそのものではない。Unity上のCollider・Rigidbody等を直接コピーする。JSONだけでは接触履歴や進行中の合体を完全に再構成できない。

## 1. 独立した物理世界の生成

**【ファイル名】** [SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:44)  
**【関数名】** `SuikaPhysicsSimulator`  
**【該当行】** 44〜55行

**【実際のコード】**

```csharp
    SuikaPhysicsSimulator(GameManager manager)
    {
        scores = (int[])ScoreManager.Instance.evolutionScores.Clone();
        score = ScoreManager.Instance.GetScore();
        gameOverHeight = manager.GameOverHeight;
        scene = SceneManager.CreateScene("SuikaPrediction_" + Guid.NewGuid().ToString("N"),
            new CreateSceneParameters(LocalPhysicsMode.Physics2D));
        physics = scene.GetPhysicsScene2D();
        staging = new GameObject("Inactive prediction staging");
        staging.SetActive(false);
        SceneManager.MoveGameObjectToScene(staging, scene);
    }
```

**【コードの説明】**

1. スコア表をCloneし、現在スコアとゲームオーバー高さを値で保存する。本物のScoreManagerは加点先にならない。
2. `CreateSceneParameters(LocalPhysicsMode.Physics2D)`で別の2D物理世界を持つSceneを作る。通常Sceneを追加するだけではdefault世界を共有する。
3. `GetPhysicsScene2D()`が後でSimulateする対象を返す。
4. 非アクティブのstagingを作り、`MoveGameObjectToScene`で所有先を予測Sceneにする。複製を準備してから有効化するための親になる。

**【入力と出力】**

入力は実GameManager。出力はコンストラクターで初期化された1回分のシミュレーター。説明例：実スコア15ならローカル初期スコアも15。

**【なぜ必要なのか】**

同じdefault物理世界を進めてしまうと本物も動く。Sceneとスコアを分離することが予測の土台。

## 2. Copy：複製前の安全確認と外見・スクリプト制御

**【ファイル名】** [SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:59)  
**【関数名】** `Copy`  
**【該当行】** 59〜76行

**【実際のコード】**

```csharp
        // Validate BEFORE Instantiate: unknown Awake/OnEnable could have global side effects.
        foreach (var script in source.GetComponentsInChildren<MonoBehaviour>(true))
            if (script == null || !(script is FruitEvolution || script is Danse ||
                script is Fruit || script is FruitCollisionHandler))
                throw new InvalidOperationException("Unsupported prediction script on " + source.name);
        if (source.GetComponentsInChildren<Joint2D>(true).Length != 0 || source.transform.childCount != 0)
            throw new InvalidOperationException("Prediction currently supports inspected flat collider objects only: " + source.name);
        var clone = Object.Instantiate(source, staging.transform);
        clone.transform.position = source.transform.position;
        clone.transform.rotation = source.transform.rotation;
        clone.transform.localScale = source.transform.lossyScale;
        owned.Add(clone);
        foreach (Renderer renderer in clone.GetComponentsInChildren<Renderer>(true)) renderer.enabled = false;
        foreach (var script in clone.GetComponents<MonoBehaviour>()) script.enabled = false;
        var fruit = clone.GetComponent<FruitEvolution>();
        if (fruit != null) { fruit.Simulation = this; fruit.enabled = true; }
        if (initializeMaterial)
        {
```

**【コードの説明】**

1. Instantiate前に既知の4種類以外のMonoBehaviourやMissing scriptを拒否する。未知のAwake/OnEnableによるグローバル副作用を避けるため。
2. Jointや子階層も、この版では未対応として拒否する。複雑な物理構造を不完全に複製しない。
3. InstantiateはPolygonColliderの頂点、Rigidbodyの保存対象設定、参照するマテリアル等を複製する。円へ置換しない。
4. 親座標系の影響を避け、実ワールドの位置・回転・lossyScaleを設定する。
5. Rendererと通常スクリプトを無効化。FruitEvolutionだけはSimulationをこのインスタンスに向けて有効化する。

**【入力と出力】**

入力sourceは床・壁・果物等の実GameObjectまたは進化Prefab。initializeMaterialは新生成時のみtrue。出力cloneは同じ形状を持ち、予測Sceneに属するGameObject。

**【なぜ必要なのか】**

外見だけ複製しても物理形状を再現できない。一方、全スクリプトをそのまま動かすと実スコア・通信・乱数に干渉し得る。

## 3. Copy：有効化後に実行時の物理状態を復元

**【ファイル名】** [SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:99)  
**【関数名】** `Copy`  
**【該当行】** 99〜118行

**【実際のコード】**

```csharp
        if (body != null)
        {
            body.position = originalBody.position;
            body.rotation = originalBody.rotation;
            body.velocity = originalBody.velocity;
            body.angularVelocity = originalBody.angularVelocity;
            // Runtime mass properties are not reliably serialized by Instantiate.
            if (body.bodyType == RigidbodyType2D.Dynamic)
            {
                body.mass = originalBody.mass;
                body.centerOfMass = originalBody.centerOfMass;
                body.inertia = originalBody.inertia;
            }
            // Changing mass/COM can itself change linear velocity (Box2D mass reset).
            body.velocity = originalBody.velocity;
            body.angularVelocity = originalBody.angularVelocity;
            if (originalBody.IsSleeping()) body.Sleep();
            if (body.position != originalBody.position ||
                Mathf.Abs(Mathf.DeltaAngle(body.rotation, originalBody.rotation)) > 0.0001f ||
                body.velocity != originalBody.velocity ||
```

**【コードの説明】**

1. stagingから外してSetActive(true)にする。このときRigidbodyの実行時速度がリセットされることがある。
2. その後、position/rotation/velocity/angularVelocityを再設定する。
3. Dynamicのmass・centerOfMass・inertiaも明示復元する。Instantiateのシリアライズ対象だけでは実行時値が残るとは限らない。
4. 質量・重心変更自体が速度に影響し得るので、さらに速度を復元する。
5. 後続行でSleepを復元し、姿勢・速度・質量・重力係数・減衰・拘束・bodyType・衝突モード等を検査。不一致は例外で中断する。KinematicにDynamicの慣性値を強制設定しない。

**【入力と出力】**

説明例：source.position=(1,-2)、velocity=(0,-3)、mass=1、inertia=0.056なら、cloneにもその値を設定する。出力はGameObjectで、接触履歴・solver内部キャッシュを含む完全スナップショットではない。

**【なぜ必要なのか】**

座標だけでは、動いている盤面の未来を予測できない。有効化より前だけの速度設定も消える可能性がある。

## 4. Predict：入力・時計の検査

**【ファイル名】** [SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:181)  
**【関数名】** `Predict`  
**【該当行】** 181〜196行

**【実際のコード】**

```csharp
    public static Result Predict(PlayerController player, GameManager manager, float x, int postDropSteps = -1)
    {
        if (!Application.isPlaying || manager.isGameOver || player.StepControlLocked)
            throw new InvalidOperationException("Prediction requires an idle, running game");
        if (float.IsNaN(x) || float.IsInfinity(x) || x < 0 || x > 1) throw new ArgumentOutOfRangeException("x");
        float dt = Time.fixedDeltaTime;
        if (postDropSteps == -1) postDropSteps = Mathf.CeilToInt(0.5f / dt);
        if (postDropSteps < 1 || postDropSteps > 5000 || dt <= 0 || Time.timeScale <= 0 ||
            player.aiMoveSpeed <= 0 || float.IsNaN(player.aiMoveSpeed) || float.IsInfinity(player.aiMoveSpeed))
            throw new InvalidOperationException("Invalid prediction horizon, speed or clock");
        var range = player.GetDropRange();
        if (!range.valid) throw new InvalidOperationException(range.error);
        var before = SourceSignature(player);
        var random = UnityEngine.Random.state;
        int initialScore = ScoreManager.Instance.GetScore(), best = GameScoreStatic.maxScore;
        var timer = Stopwatch.StartNew();
```

**【コードの説明】**

1. Play中・非終端・操作待ちの状態を要求する。
2. 正規化xのNaN/Infinity/範囲外を拒否する。
3. Time.fixedDeltaTimeをdtとし、省略時はceil(0.5/dt)回を落下後の計測区間にする。
4. 更新回数・時間倍率・AI速度の妥当性を確認し、実PlayerController.GetDropRangeで壁と果物の安全範囲を取得する。
5. 予測前の実盤面の署名・乱数状態・score/BESTを保持する。

**【入力と出力】**

説明例：x=0.65、dt=0.02秒、postDropSteps省略なら25。返り値はまだなく、後半でResultを作る。操作中やx=1.2は例外。

**【なぜ必要なのか】**

止まった時計や不正な入力で計算を続けること、不正な落下位置を予測することを防ぐ。

## 5. Predict：実行・後片付け・本物の不変確認

**【ファイル名】** [SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:198)  
**【関数名】** `Predict`  
**【該当行】** 198〜212行

**【実際のコード】**

```csharp
        var simulation = new SuikaPhysicsSimulator(manager);
        double createMs = timer.Elapsed.TotalMilliseconds;
        simulation.Trace = PredictionDiagnostics.Live != null ? new PredictionDiagnostics.Recorder() : null;
        try { result = simulation.Run(player, x, range, dt, postDropSteps); }
        finally { if(simulation.Trace!=null)simulation.Trace.recording=false; simulation.Dispose(); }
        result.scene_create_ms = createMs;
        result.trace = simulation.Trace;
        result.cleanup_schedule_ms = simulation.cleanupMs;
        result.elapsed_ms = timer.Elapsed.TotalMilliseconds;
        result.source_unchanged = before == SourceSignature(player) &&
            random.Equals(UnityEngine.Random.state) && ScoreManager.Instance.GetScore() == initialScore &&
            best == GameScoreStatic.maxScore;
        if (!result.source_unchanged) throw new InvalidOperationException("Prediction mutated live source");
        return result;
    }
```

**【コードの説明】**

1. Runをtry内で実行し、例外時もfinallyでDisposeする。
2. 診断Recorderは解放時のDestroyを測定イベントに混ぜないよう停止する。
3. Scene作成・後片付け要求・全体経過時間をResultへ記録する。
4. 実果物の署名、UnityEngine.Random.state、score、BESTが予測前と同じか検査する。
5. source_unchanged=falseなら成功として返さず例外にする。これは検査した公開状態の不変確認であり、不可視の全エンジン内部状態まで保証するものではない。

**【入力と出力】**

入力は前半で検査済みのplayer/manager/x/postDropSteps。出力Resultはfruits・score・ticks・計算時間等。本物がscore=10なら、予測score=16でも実scoreが10のままであることを確認する（説明例）。

**【なぜ必要なのか】**

予測失敗時のScene残留と、本物への副作用を黙って見逃すことを防ぐ。

## 6. Run：盤面・操作果物・見えているNEXTを分離

**【ファイル名】** [SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:254)  
**【関数名】** `Run`  
**【該当行】** 254〜273行

**【実際のコード】**

```csharp
            if (fruit.GetComponent<Rigidbody2D>() == null) throw new InvalidOperationException("Live fruit missing body");
            var liveBody = fruit.GetComponent<Rigidbody2D>();
            var contacts = new List<ContactPoint2D>();
            result.initial_contact_count += liveBody.GetContacts(contacts);
            var clone = Copy(fruit.gameObject, false).GetComponent<FruitEvolution>();
            ids.Add(clone, fruit.ObservationId);
        }
        result.initial_fruits = ReadBoard();
        var held = Copy(player.currentFruit, false);
        var heldEvolution = held.GetComponent<FruitEvolution>();
        heldEvolution.IsPreview = true;
        // Only the visible NEXT is copied. No new random fruit is sampled.
        var knownNext = Copy(player.nextFruitObject, false);
        knownNext.GetComponent<FruitEvolution>().IsPreview = true;
        var nextCollider = knownNext.GetComponent<PolygonCollider2D>();
        nextCollider.isTrigger = true;
        knownNext.SetActive(false);
        float target = Mathf.Lerp(range.min_x, range.max_x, x);
        int startScore = score, post = 0;
        bool dropped = false;
```

**【コードの説明】**

1. 実盤面のRigidbodyから既存接触数を数え、Copyする。ObservationIdは既存果物の対応付けに使う。
2. 初期盤面をReadBoardで保存する。
3. heldはIsPreview=trueとし、動的盤面配列と混同しない。
4. NEXTは既知の表示中のものだけをコピーし、Triggerとして落下までは非表示・非アクティブにする。未知の将来の乱数は引かない。
5. target=min_x+(max_x−min_x)*xで正規化座標をワールド位置に変換する。

**【入力と出力】**

説明例：範囲[-2,2]、x=0.65ならtarget=0.6。これは仮の数値で、実際の範囲は壁とPolygonの大きさから取得する。出力はRun内で準備されたローカル盤面と目標位置。

**【なぜ必要なのか】**

現在操作中の果物・NEXTを盤面の動的果物に混ぜると、衝突・終端判定・観測が変わる。先の乱数を予測入力に漏らさないことも必要。

## 7. Run：1更新ずつ滑らかに移動し、壁を検査

**【ファイル名】** [SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:284)  
**【関数名】** `Run`  
**【該当行】** 284〜302行

**【実際のコード】**

```csharp
        {
            if (!dropped)
            {
                float old = held.transform.position.x;
                var p = held.transform.position;
                p.x = Mathf.MoveTowards(old, target, player.aiMoveSpeed * dt);
                held.transform.position = p;
                Physics2D.SyncTransforms();
                var shape = held.GetComponent<PolygonCollider2D>();
                if (shape.bounds.min.x < range.left_wall_inner || shape.bounds.max.x > range.right_wall_inner)
                    throw new InvalidOperationException("Prediction movement outside wall bounds");
                foreach (var wall in walls)
                {
                    var distance = shape.Distance(wall);
                    if (wall.enabled && (!distance.isValid || distance.isOverlapped))
                        throw new InvalidOperationException("Prediction movement overlaps wall");
                }
                if (old != p.x) { result.movement_steps++; result.movement_seconds += dt; }
                if (p.x == target)
```

**【コードの説明】**

1. forは描画を待たずに固定回数進む。毎回dt秒のゲーム内時間に相当する。
2. 落下前のxをMoveTowardsで最大aiMoveSpeed*dtだけ目標へ近づける。
3. SyncTransformsでTransform変更を物理世界へ反映する。
4. Polygonのboundsが左右内壁の外に出ていないか確認する。
5. shape.Distance(wall)でも重なり・検査不能を拒否する。既存の壁、形状、接触設定は変更しない。

**【入力と出力】**

説明例：速度2.5単位/秒、dt=0.02秒なら1回最大0.05単位。1単位移動には20回=0.4ゲーム秒必要。画面アニメーションは省いても盤面の物理は毎回進む。

**【なぜ必要なのか】**

瞬間移動予測では移動中の盤面変化を無視してしまい、STEP 3.5の実行条件と異なる。

## 8. Run：到着後に落下し、Simulateで物理を進める

**【ファイル名】** [SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:303)  
**【関数名】** `Run`  
**【該当行】** 303〜322行

**【実際のコード】**

```csharp
                {
                    var body = held.GetComponent<Rigidbody2D>();
                    if (body == null) body = held.AddComponent<Rigidbody2D>();
                    body.gravityScale = 1;
                    shape.isTrigger = false;
                    heldEvolution.IsPreview = false;
                    ids.Add(heldEvolution, generatedId--);
                    result.applied_x = p.x;
                    result.drop_success = dropped = true;
                    knownNext.transform.position = held.transform.position;
                    knownNext.SetActive(true);
                    // STEP 3.5's new-preview clamp affects no dynamic body (trigger-only).
                }
            }
            else { post++; }
            Physics2D.SyncTransforms();
            if (!physics.Simulate(dt)) throw new InvalidOperationException("Local PhysicsScene2D.Simulate failed");
            if (Trace != null) Trace.Capture(score, IsGameOver(knownNext.activeSelf ? knownNext : held));
            FlushRemoval();
            result.physics_steps++;
```

**【コードの説明】**

1. 到着した更新でRigidbodyを追加（あれば再利用）し、gravityScale=1・Polygon非Triggerにする。
2. IsPreviewをfalseにして盤面IDを割り当て、applied_xとdrop_successを保存する。
3. 見えていたNEXTを操作位置に出す。予測内で未知の次NEXTは生成しない。
4. 既に落下済みだった更新だけpostを増やす。落下した更新そのものではpost=0。
5. physics.Simulate(dt)が移動/接触/衝突コールバックを進める。FruitEvolution.OnCollisionEnter2Dもこの呼び出し中に実行される。失敗は例外。
6. この直後に診断Capture→FlushRemoval→全更新数増加→終端またはpost回数判定の順。ReadBoardで結果を返す。

**【入力と出力】**

説明例：移動2更新目で落とし、postSteps=25なら合計27回（落下更新1回＋その後25回、落下前更新1回）。0.5秒「以上」であり、果物の完全静止は待たない。

**【なぜ必要なのか】**

落下前から0.5秒を数えたり、物理を進めず姿だけ動かしたりする誤りを避ける。なお予測はDropFruitそのものを呼ばず、その物理的変化を再現しているため、実DropFruitとの整合検証が必要。

## 9. CreateEvolved：進化Prefabをローカルに生成

**【ファイル名】** [SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:135)  
**【関数名】** `CreateEvolved`  
**【該当行】** 135〜145行

**【実際のコード】**

```csharp
    public GameObject CreateEvolved(GameObject prefab, Vector3 position)
    {
        var fruit = Copy(prefab, true);
        fruit.transform.position = position;
        fruit.transform.rotation = Quaternion.identity;
        ids.Add(fruit.GetComponent<FruitEvolution>(), generatedId--);
        merges++;
        return fruit;
    }
    public void AddScore(int type) { if (type >= 0 && type < scores.Length) score += scores[type]; }
    public void DeferRemoval(GameObject fruit) { pendingRemoval.Add(fruit); }
```

**【コードの説明】**

1. FruitEvolutionから渡されたEvolutionDatabaseの正しい進化PrefabをCopy(prefab,true)する。trueでDanseの共通マテリアル初期化を行う。
2. 合体位置とidentity回転を設定する。
3. 新生成の負IDを付け、mergesを増やして呼び出し元へ返す。
4. AddScoreは複製したscores表を使い、ローカルscoreだけを増やす。DeferRemovalは削除をキューに積む。
5. 呼び出し元FruitEvolutionがRigidbody/Polygonの落下設定を完成させる。

**【入力と出力】**

説明例：type=2同士ならnextType=3、生成位置は2つの中心平均、score表が6ならローカルscore+6。IDは-1,-2…で本物の新生成IDとは一致しない。

**【なぜ必要なのか】**

実スコアに加点せず、同じ進化Prefabと規則を予測内で使用するため。

## 10. Dispose：何度呼んでも安全な所有物の解放要求

**【ファイル名】** [SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:332)  
**【関数名】** `Dispose`  
**【該当行】** 332〜342行

**【実際のコード】**

```csharp
    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        var timer = Stopwatch.StartNew();
        foreach (var obj in owned) if (obj != null) obj.SetActive(false);
        foreach (var material in materials) if (material != null) Object.Destroy(material);
        if (scene.IsValid()) SceneManager.UnloadSceneAsync(scene);
        cleanupMs = timer.Elapsed.TotalMilliseconds;
    }
}
```

**【コードの説明】**

1. disposedフラグで重複解放を防ぐ。
2. ownedに記録した予測オブジェクトを非アクティブにし、次の計算に残らないようにする。
3. 新生成した予測専用マテリアルだけをDestroyする。既存の共有アセットを削除しない。
4. UnloadSceneAsyncで所有Sceneの解放を依頼する。
5. cleanupMsはこの要求までの時間。非同期Scene解放が完全に終わるまでの時間ではない。

**【入力と出力】**

入力なし、返り値なし。Predictのfinallyから必ず呼ばれる。再度呼んでも何もしない。

**【なぜ必要なのか】**

候補を繰り返し試す将来の処理で、オブジェクト・Sceneが増え続けることを避ける。

## 11. Recorder.Capture：接触インパルスを含む観測

**【ファイル名】** [PredictionDiagnostics.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/PredictionDiagnostics.cs:55)  
**【関数名】** `Recorder.Capture`  
**【該当行】** 55〜69行

**【実際のコード】**

```csharp
                var shape = fruit.GetComponent<PolygonCollider2D>();
                var contacts = new List<Contact>();
                if (body != null)
                {
                    var points = new List<ContactPoint2D>(); body.GetContacts(points);
                    foreach (var p in points)
                    {
                        var other = p.collider.gameObject == fruit.gameObject ? p.otherCollider : p.collider;
                        var otherFruit = other.GetComponent<FruitEvolution>();
                        contacts.Add(new Contact { other = otherFruit != null ? Alias(otherFruit) : other.name.Replace("(Clone)",""),
                            point = p.point, normal = p.normal, normal_impulse = p.normalImpulse, tangent_impulse = p.tangentImpulse });
                    }
                }
                contacts.Sort((a,b) => { int v=String.CompareOrdinal(a.other,b.other); return v!=0?v:a.point.x.CompareTo(b.point.x); });
                var material = shape != null ? shape.sharedMaterial : null;
```

**【コードの説明】**

1. 登録済み果物のRigidbody/Polygonを参照する。
2. Rigidbody.GetContactsで接触点・法線・法線/接線インパルスを読み取る。
3. 接触相手が果物なら診断用alias、壁ならオブジェクト名を保存する。
4. 記録比較を安定させるため並べ替える。この配列順はsolver内部の計算順を示さない。xが同じ重複点もあるため、インパルスの一対一比較には点/法線を含む対応付けが必要。
5. 後続で姿勢・速度・質量・慣性・重心・摩擦・反発・sleep等を保存する。最大513Frameで打ち切りを明示。

**【入力と出力】**

入力score/gameOverと登録した果物。出力はframesに蓄積するFrame、APIの戻り値はvoid。tick0は計算前、tick1以降は物理更新直後。

**【なぜ必要なのか】**

最終状態だけでは「いつ・何から差が出たか」が分からない。接触点が同じでもインパルスが異なる事実を分けて確認できる。

## 12. Compare：実測と予測の同じ更新を照合

**【ファイル名】** [PredictionDiagnostics.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/PredictionDiagnostics.cs:138)  
**【関数名】** `Compare`  
**【該当行】** 138〜154行

**【実際のコード】**

```csharp
    public static Report Compare(Recorder predicted) { return Compare(predicted, Live); }
    // Explicit recorders also support an isolated Editor fixture without global Live capture.
    public static Report Compare(Recorder predicted, Recorder actual)
    {
        if(actual==null || predicted==null)return null;
        var report=new Report { initial_actual=actual.frames[0],initial_prediction=predicted.frames[0],
            truncated=actual.truncated||predicted.truncated,predicted_ticks=predicted.frames.Count-1,actual_ticks=actual.frames.Count-1,actual_events=actual.history.ToArray(),predicted_events=predicted.history.ToArray() };
        var errors=new List<Error>();
        for(int i=0;i<Math.Min(actual.frames.Count,predicted.frames.Count);i++)
        {
            var a=actual.frames[i];var p=predicted.frames[i];
            var e=new Error { tick=i,actual_frame=a.render_frame,actual_count=a.fruits.Length,predicted_count=p.fruits.Length,
                score_match=a.score==p.score,game_over_match=a.game_over==p.game_over,
                events_match=String.Join("|",a.events)==String.Join("|",p.events) };
            if(a.fruits.Length!=p.fruits.Length)e.ids_types_match=false;
            var map=new Dictionary<string,FruitState>();foreach(var f in a.fruits)map[f.id]=f;
            foreach(var f in p.fruits)
```

**【コードの説明】**

1. 従来のCompare(predicted)はLiveをactualにして2引数版へ委譲する。今回追加した2引数版は独立した実験のRecorderも比較できる。
2. 初期状態、記録長、イベント履歴、打ち切りフラグをReportに入れる。
3. 同じtickのFrameを取り出す。render_frameは診断情報であり、手動計算と実時間の対応キーではない。
4. 果物数、score、game_over、イベントを比較する。
5. この後aliasで果物を照合して最大位置/速度/角度/角速度誤差を算出し、最初の数値差と最初の許容差超過を記録する。contacts_matchは現在、接触数と相手aliasだけの粗い判定。点/法線/インパルスの完全一致とは別。

**【入力と出力】**

入力2つのRecorder。出力Report。position誤差はsqrt((dx)^2+(dy)^2)、角度差はDeltaAngleで±180度内の最短差。数値差閾値は位置1e-6、速度1e-5、角度1e-4、角速度1e-3。

**【なぜ必要なのか】**

別世界の生成IDは直接一致しないため、元IDと合体親から作るaliasを使う。記録長が違う場合は比較された共通区間だけで成功と判断しない。

## 13. FruitEvolution：合体規則を共有する

**【ファイル名】** [FruitEvolution.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/FruitEvolution.cs:39)  
**【関数名】** `OnCollisionEnter2D`  
**【該当行】** 39〜49行

**【実際のコード】**

```csharp
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
```

**【コードの説明】**

1. 診断の衝突イベントを記録する。
2. isMergingなら二重合体を止める。
3. 相手がFruitEvolutionを持ち、同じSimulation参照（両方nullなら本物）で、合体処理中でないことを要求する。
4. 同じfruitTypeのときだけ両者にisMergingを立てる。
5. 生成位置を中心座標の平均とする。後半でnextType=fruitType+1、EvolutionDatabaseからPrefabを取る。type10同士は既存仕様どおり消滅し加点しない。

**【入力と出力】**

入力Collision2D。説明例：(0,-2)と(0.4,-2)のtype2なら生成位置(0.2,-2)、進化先type3。出力は新果物生成等の副作用で、戻り値はない。

**【なぜ必要なのか】**

実ゲームと予測で別々の合体表を持つと、進化や得点規則がずれる。二重衝突コールバックによる重複生成も防ぐ。

## 14. FruitEvolution：生成先の分離と削除時期

**【ファイル名】** [FruitEvolution.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/FruitEvolution.cs:76)  
**【関数名】** `OnCollisionEnter2D`  
**【該当行】** 76〜89行

**【実際のコード】**

```csharp
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
```

**【コードの説明】**

1. 本物ならInstantiate、予測ならSimulation.CreateEvolvedを使う。後者は本物Sceneに新果物を出さない。
2. 両方で同じRigidbody2D設定（必要時追加・gravityScale=1）とPolygon有効/非Triggerを適用する。
3. 後続でtype/音を設定し、診断Mergeを記録する。
4. 加点先はSimulation.AddScoreまたは実ScoreManager.AddScoreForEvolution。
5. RemoveFruitは本物でDestroy、予測でDeferRemoval。本物Destroyは通常フレーム末、予測はSimulate後のFlushRemovalで非アクティブ化。1描画フレームに複数FixedUpdateがあると、この差が追加誤差になり得る。今回の単体実験には合体/削除がなく、今回の62回目の差の原因ではない。

**【入力と出力】**

入力はnextTypeのPrefabと平均位置。出力GameObjectを共通設定に使う。スコアを本物とローカルに分離するが、削除タイミングまで完全同一とは主張できない。

**【なぜ必要なのか】**

世界分離とルール共有を同時に成立させる。ただしライフサイクル差は検証対象として残す。

## 15. HandleStep：比較要求だけ予測を先に実行

**【ファイル名】** [UDPStepProtocol.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/UDPStepProtocol.cs:70)  
**【関数名】** `HandleStep`  
**【該当行】** 70〜87行

**【実際のコード】**

```csharp
        if (message.command == "compare_step")
        {
            try
            {
                // Paired A/B uses the SAME live board; prediction never advances it.
                var reference = message.trace_physics
                    ? SuikaPhysicsSimulator.Predict(playerController, gameManager, message.x, comparisonTicks == 0 ? -1 : comparisonTicks) : null;
                if (message.trace_physics) PredictionDiagnostics.Begin(playerController, gameManager);
                pendingPrediction = SuikaPhysicsSimulator.Predict(playerController, gameManager, message.x, comparisonTicks == 0 ? -1 : comparisonTicks);
                if (reference != null)
                {
                    pendingPrediction.reference_elapsed_ms = reference.elapsed_ms;
                    pendingPrediction.reference_fruits = reference.fruits;
                    pendingPrediction.reference_score = reference.score;
                    pendingPrediction.reference_game_over = reference.game_over;
                }
            }
            catch (Exception e) { PredictionDiagnostics.Stop(); StepError(message, "prediction_rejected:" + e.Message); return; }
```

**【コードの説明】**

1. compare_stepだけ任意の診断用horizonを使い、通常stepは既定0.5秒を保つ。
2. trace_physics=trueなら、同じ本物盤面から診断なしreference予測を実行する。
3. Beginで実ゲームの記録を開始し、診断付き予測を実行する。本物の物理時間はこの同期関数の間進まない。
4. 診断なし/ありの予測差を、異なる初期盤面のせいにせず比較できる。
5. この後、実ゲームのStepControlLockedを立て、action_idを予約して移動を開始する。compare_stepは予測専用APIではなく、本物も1手進める。

**【入力と出力】**

入力はcommand、stream_id、episode_id、action_id、x等。x=0.65の1要求で予測の後に本物を1回落とす。同一action_id・x再送は結果再送または待機で、再落下しない。

**【なぜ必要なのか】**

公平な初期状態と通信再送の安全性が必要。Pythonから予測だけ31候補を要求する機能は現在未実装。

## 16. FixedUpdate：本物の移動も同じ固定刻み

**【ファイル名】** [UDPStepProtocol.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/UDPStepProtocol.cs:120)  
**【関数名】** `FixedUpdate`  
**【該当行】** 120〜138行

**【実際のコード】**

```csharp
    void FixedUpdate()
    {
        if (activeStep == null || gameManager.isGameOver) return;
        actualTotalPhysicsSteps++;
        if (activeStep.status == "dropping") return; // Unexpected exception: outcome unknown until reset.
        if (activeStep.drop_success) { physicsTicks++; return; }
        if (playerController.currentFruit == null) { FailMovement("no_current_fruit"); return; }
        PlayerController.DropRange range = playerController.GetDropRange();
        if (!range.valid || Mathf.Abs(range.min_x - movementRange.min_x) > 0.00001f ||
            Mathf.Abs(range.max_x - movementRange.max_x) > 0.00001f)
        { FailMovement("movement_range_changed"); return; }
        float oldX = playerController.currentFruit.transform.position.x;
        float nextX = Mathf.MoveTowards(oldX, activeStep.target_x, activeStep.movement_speed * Time.fixedDeltaTime);
        string error;
        if (!playerController.TryMoveHeldTo(nextX, movementRange, out error))
        { FailMovement(error); return; }
        activeStep.current_x = nextX;
        if (nextX != oldX)
        {
```

**【コードの説明】**

1. 処理中で非終端の場合だけ全物理更新数を増やす。
2. drop_success後はpost用physicsTicksを増やして以降はUnityの通常物理に任せる。
3. 移動中は果物と安全範囲が変わっていないか検査する。
4. MoveTowards(oldX,target,speed*fixedDeltaTime)で同じ移動距離を計算し、TryMoveHeldToの壁検査を通す。
5. 到着すると後続のTryDropAtが既存DropFruitを1回呼ぶ。実際のapplied_xを記録し、physicsTicks=0にする。LateUpdateで必要回数後または終端時にCompleteStepするため、1描画内に複数物理更新がある場合は余分に進むことがある。

**【入力と出力】**

入力はHandleStepが作ったactiveStep。出力は本物の移動/落下とactiveStepの更新。説明例：速度2.5・dt.02なら1回.05移動。

**【なぜ必要なのか】**

予測だけ固定速度にしても、本物の移動時刻が違えば比較できない。

## 17. UDPStateProtocol：本物の観測を返却パケットへ追加

**【ファイル名】** [UDPStateProtocol.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/UDPStateProtocol.cs:60)  
**【関数名】** `SendPacket`  
**【該当行】** 60〜77行

**【実際のコード】**

```csharp
    void SendPacket(Observation observation)
    {
        if (udpSender == null) return;
        observation.protocol_version = 2;
        observation.stream_id = streamId;
        observation.episode_id = episodeId;
        observation.state_id = ++stateId;
        observation.reset_request_id = resetRequestId;
        observation.game_over = gameManager.isGameOver;
        observation.done = observation.game_over;
        observation.score = ScoreManager.Instance.GetScore();
        GameObject held = playerController.currentFruit;
        observation.current_fruit = new ControlledFruit {
            present = held != null, type = GetFruitType(held),
            x = held != null ? held.transform.position.x : 0
        };
        observation.next_fruit_type = GetFruitType(playerController.nextFruitObject);
        observation.drop_range = playerController.GetDropRange();
```

**【コードの説明】**

1. 受け取ったObservationにprotocol/stream/episode/state_id等を設定する。state_idはresetでも巻き戻さない。
2. game_overとscoreは実GameManager/ScoreManagerから読む。prediction.scoreとは別。
3. 操作果物はtypeとx、NEXTも見えているtypeだけ保存する。
4. 後続で実盤面果物をRigidbodyから列挙し、IsPreview/IsMerging/held/NEXTを除外する。
5. SendSnapshotがJsonUtility.ToJson→UTF8→UDP送信を行う。60000bytes超では分割し、Pythonは完成したsnapshotだけ組み立てる。

**【入力と出力】**

入力はCompleteStepが作るObservation（step_result、predictionを含み得る）。出力はUDP。新しいepisode_idとaction_id、古いstate_idを使って古い応答を識別する。

**【なぜ必要なのか】**

予測結果と実測結果を同じ応答に載せつつ区別し、古い観測を新しい操作結果と誤認しないようにする。

## 18. Python：要求の差し替えと1手実行

**【ファイル名】** [check_unity_prediction.py](C:/SuikaGameAI/Python/check_unity_prediction.py:89)  
**【関数名】** `main`  
**【該当行】** 89〜106行

**【実際のコード】**

```python
            if message.get('command') == 'step':
                message = dict(message, command='compare_step', trace_physics=args.trace, comparison_post_drop_steps=args.post_drop_steps)
            original_send(message)
        env._send = send
        results = []
        targets = (0.65, 0.65) if args.merge_case else (0.65, 0.65, 0.65, 0.65, 0.65, 0.65, 0.65, 0.65, 0, 1)
        for x in targets:
            try:
                state, reward, done, info = env.step(x, timeout=20)
            except (RuntimeError, TimeoutError) as error:
                results.append({'error': str(error), 'within_tolerance': False})
                break
            prediction = state['prediction']
            assert prediction['source_unchanged'], 'Prediction changed real state/RNG/score'
            row = compare(prediction, state)
            row.update(x=x, reward=reward, predicted_reward=prediction['reward'],
                       merges=prediction['merges'], elapsed_ms=prediction['elapsed_ms'],
                       initial_contacts=prediction['initial_contact_count'],
```

**【コードの説明】**

1. 元のUnityEnv._sendを保存する。
2. 診断スクリプト内だけ、通常step要求をcompare_stepへ変換し、trace/horizonを追加する。
3. env.stepはaction_id等を管理した既存APIとして使い、1つずつ応答を待つ。
4. 戻りstate["prediction"]が予測、state["fruits"]等が本物。source_unchangedも検査する。
5. 通常のUnityEnv.stepにはこの差し替えがないため予測は走らない。UnityEnv.simulate(state,x)のような公開APIはまだない。

**【入力と出力】**

入力CLI --trace等。出力は実測比較JSON。現在通常ケースは10手、merge-caseは見えているNEXTが同種の2手で、探索AIではない。

**【なぜ必要なのか】**

既存環境APIを全面改造せず短い比較を行うための診断用ラッパー。

## 19. Python：果物の対応と誤差の算出

**【ファイル名】** [check_unity_prediction.py](C:/SuikaGameAI/Python/check_unity_prediction.py:38)  
**【関数名】** `compare`  
**【該当行】** 38〜50行

**【実際のコード】**

```python
            errors.append((math.hypot(a['x']-p['x'], a['y']-p['y']),
                           math.hypot(a['vx']-p['vx'], a['vy']-p['vy']),
                           abs((a['angle']-p['angle']+180) % 360-180),
                           abs(a['angular_velocity']-p['angular_velocity'])))
    return dict(types_match=types_match, count=len(actual),
                score_match=prediction['score']==state['score'],
                game_over_match=prediction['game_over']==state['game_over'],
                ticks_match=prediction['physics_steps']==state['actual_total_physics_steps'],
                max_position_error=max((e[0] for e in errors), default=0 if types_match else None),
                max_velocity_error=max((e[1] for e in errors), default=0 if types_match else None),
                max_angle_error=max((e[2] for e in errors), default=0 if types_match else None),
                max_angular_velocity_error=max((e[3] for e in errors), default=0 if types_match else None))

```

**【コードの説明】**

1. 既存果物は正の安定IDを優先して対応付ける（前半）。新生成/合体果物は世界ごとにIDが違うので同種の最小総位置差の順列で対応付ける。
2. 位置と速度は2次元ユークリッド距離、角度は±180度内、角速度は絶対差で比較する。
3. types_matchは種類の多重集合で個数も見る。score・game_over・全physics_stepsも独立に比較する。
4. 最大値を返すが種類不一致なら誤差Noneとし、欠けた果物を誤差0として成功扱いしない。
5. 同種の新果物が多いと順列が増えるため、診断用に1種類8個までに制限。合体の親の正しさは位置対応だけでは確定せず、診断イベント履歴も必要。

**【入力と出力】**

説明例：予測(1,2)、実測(1.003,2.004)なら位置差0.005。出力辞書はtypes_match、score_match、最大誤差等。許容差判定はmeets_tolerance、途中経過はsummarize_trace。

**【なぜ必要なのか】**

生成IDの違いだけで不合格にせず、物理差とゲーム結果差を分けて測る。

## 実際のPython→Unity→Pythonの順序

1. `check_unity_prediction.py:main`が`UnityEnv.reset()`で開始状態を取得し、`_send`をこのスクリプト内だけ差し替える。
2. `UnityEnv.step(x)`が既存stream/episode/action_idと正規化xを含む要求を作る。`UnityEnv._send`がJSON/UTF8のUDPをUnity受信ポート7773へ送る。
3. `UDPCommunicatorUnity.cs:Update`が`Receive`→UTF8→`JsonUtility.FromJson<ActionMessage>`→`HandleCommand`を呼ぶ。
4. `UDPStateProtocol.cs:HandleCommand`が`compare_step`を`UDPStepProtocol.cs:HandleStep`へ渡す。古いepisode、busy、重複action等を先に検査。
5. `SuikaPhysicsSimulator.Predict`が本物の今のUnityオブジェクトからsnapshotを取り、コンストラクターで独立Sceneを生成。
6. `Run→Copy`で壁/床/盤面/操作果物/既知NEXTを分離して複製する。
7. `Run`でMoveTowards→到着時Dynamic化→Simulate(dt)。Simulate中の衝突で`FruitEvolution.OnCollisionEnter2D`→`CreateEvolved`/ローカル`AddScore`/`DeferRemoval`。戻ってCapture→FlushRemoval。
8. 規定回数後ReadBoard→Result、finallyでDispose。本物の署名/乱数/score不変を確認する。
9. **ここではまだ応答しない。本物のFixedUpdateで同じ移動とDropFruitを実行する。** LateUpdateでCompleteStepとなり、必要時Compare診断を付ける。
10. `UDPStateProtocol.SendPacket→SendSnapshot`で予測と本物の結果をPython受信ポート7889へ送信。`UnityEnv.receive_state`がJSON/分割応答を処理し、`UnityEnv.step`がstate/reward/done/infoを返す。
11. `check_unity_prediction.py:compare`と`summarize_trace`が物理誤差・ゲーム結果・時系列差を報告する。

`compare_step`は本物を進める比較命令である。現在の一般公開APIに予測だけを返すものはなく、Pythonから任意JSONを渡してその状態だけを予測する機能もない。

## 用語と数式（今回のコードとの対応）

- **PhysicsScene2D**：2D剛体・接触を所有して計算する物理世界。SceneManager.CreateSceneのlocalPhysicsModeで別世界を作り、そのGetPhysicsScene2DをSimulateする。
- **Rigidbody2D**：位置だけでなく、質量m・速度v・角速度ω・慣性I等を持つ剛体。Copyは公開されている実行時値も復元する。
- **PolygonCollider2D**：多角形の当たり判定。見た目と同じ輪郭を近似する多数の頂点/内部形状を持ち得る。今回の果物には複数の接触点が生じる。Copyは元形状をそのまま複製し円にはしない。
- **Simulate(dt)**：指定した物理世界の時間をdt進める。全MonoBehaviourのFixedUpdate/Startや描画フレーム末を一緒に再生する関数ではない。そのため移動、合体後の初期化、削除待ちを別途扱っている。
- **FixedUpdate**：Unityが固定のゲーム時間刻みで呼ぶゲーム側コールバック。通常はこの後に物理更新がある。描画1回につき0回/複数回あり得る。UDPStepProtocolは移動をここで行い、PredictionDiagnosticsはPhysics2DFixedUpdate直後に観測する。
- **Impulse（力積J）**：短時間に加わる力の積分。Δv=J/m。説明例：m=1、鉛直J=2なら鉛直速度が2単位/秒変わる。角速度変化はΔω=(r×J)/I（この式のωはラジアン/秒、Unity観測は度/秒なので変換が必要）。角度誤差は接触位置と力積の違いからも増える。
- **Contact Solver**：接触点のめり込み・法線速度・摩擦等の拘束条件を反復して解き、各剛体へ力積を適用する処理。有限回の反復では、形状・拘束の並びや内部状態が結果に影響し得る。今回、登録順序だけを変えると最初の衝突結果が変わることを実測したが、Unity内部のどの並びが変わったかは未確認。
- **Warm Starting**：前の更新で求めた接触力積を次の初期推定に再利用して収束を助ける手法。位置・速度をコピーしても接触キャッシュは作り直しになる。今回の初回衝突は過去の接触がないため、これだけを唯一の原因とはできない。
- **Instantiate**：GameObject/Prefabの複製。アセット/コンポーネントの保存対象はコピーするが、物理エンジン内部世界の完全複製ではない。Copyが実行時値を追加復元する理由。
- **Destroy**：Unityオブジェクトの削除要求。本物の合体で用いる。即時消去ではなくフレーム末の遅延があり、予測側の毎tick非アクティブ化との差を考慮する。
- **Dispose**：このC#クラスが定義する後片付け契約。Unity APIの自動魔法ではない。Predictのfinallyから呼び、所有SceneのUnloadSceneAsyncと専用マテリアルDestroyを依頼する。

自由落下の概念はv(t+dt)≈v(t)+g*dt、p(t+dt)≈p(t)+v(t+dt)*dt。ただしこれは説明用の単純化であり、接触・回転・減衰・連続衝突等を含むUnity全体の公式ではない。実コードは自前積分ではなくUnityのSimulateに任せる。

API仕様： [Unity 2022.3 PhysicsScene2D.Simulate](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/PhysicsScene2D.Simulate.html)。Warm Starting/逐次力積の原理：[Box2D作者の解説](https://box2d.org/files/ErinCatto_SequentialImpulses_GDC2006.pdf)。Box2Dの一般理論はUnity 2022.3内部実装の特定を意味しない。

## 今回追加：Build

**【ファイル名】** [SingleCollisionProbe.cs](C:/SuikaGameAI/Unity/Assets/Editor/SingleCollisionProbe.cs:85)  
**【関数名】** `Build`  
**【該当行】** 85〜101行

**【実際のコード】**

```csharp
    static World Build(GameObject floor,GameObject prefab,Vector3 position,bool local,bool reverse)
    {
        var world=new World();
        world.scene=SceneManager.CreateScene("SingleCollisionProbe_"+Guid.NewGuid().ToString("N"),
            new CreateSceneParameters(local?LocalPhysicsMode.Physics2D:LocalPhysicsMode.None));
        world.physics=world.scene.GetPhysicsScene2D();
        world.staging=new GameObject("Probe inactive staging");world.staging.SetActive(false);
        SceneManager.MoveGameObjectToScene(world.staging,world.scene);
        try
        {
            GameObject fruit;
            if(reverse) { fruit=Clone(prefab,world,position,true,local);Clone(floor,world,floor.transform.position,false,local); }
            else { Clone(floor,world,floor.transform.position,false,local);fruit=Clone(prefab,world,position,true,local); }
            world.recorder.Watch(fruit.GetComponent<FruitEvolution>(),"fruit");
            return world;
        }
        catch { SceneManager.UnloadSceneAsync(world.scene);throw; }
```

**【コードの説明】**

localだけを切り替える比較と、reverseだけを切り替える比較を同じfactoryで構成する。Noneはdefault世界、Physics2Dは独立世界。reverseでCloneの呼出順のみを交換する。

**【入力と出力】**

Buildの入力は床/Prefab/位置/local/reverseで、出力はWorld。AfterPhysics/Cleanupは引数も返り値もなく、専用記録/Sceneを更新する。具体的な実測値はSTEP4_DIRECTION.md参照。

**【なぜ必要なのか】**

変更前にはこの実験は存在しなかった。ゲーム本体の規則や物理設定を変えず、最小構成で登録順序の影響を区別するために追加した。Editor外のビルドには含まれない。

## 今回追加：AfterPhysics

**【ファイル名】** [SingleCollisionProbe.cs](C:/SuikaGameAI/Unity/Assets/Editor/SingleCollisionProbe.cs:150)  
**【関数名】** `AfterPhysics`  
**【該当行】** 150〜166行

**【実際のコード】**

```csharp
        if(!running)return;
        try
        {
            worlds[0].recorder.Capture(0,false);
            if(++ticks<Ticks)return;
            output.actual_impact_window=ImpactWindow(worlds[0].recorder);
            output.same_order_impact_window=ImpactWindow(worlds[1].recorder);
            output.reversed_order_impact_window=ImpactWindow(worlds[2].recorder);
            output.same_order=PredictionDiagnostics.Compare(worlds[1].recorder,worlds[0].recorder);
            output.reversed_order=PredictionDiagnostics.Compare(worlds[2].recorder,worlds[0].recorder);
            output.local_vs_local=PredictionDiagnostics.Compare(worlds[2].recorder,worlds[1].recorder);
            string path=Path.GetFullPath(Path.Combine(Application.dataPath,"../../Python/single_collision_probe.json"));
            File.WriteAllText(path,JsonUtility.ToJson(output,true));
            Debug.Log("Single collision probe complete: first differing ticks same="+output.same_order.first_numeric_tick+
                ", reversed="+output.reversed_order.first_numeric_tick+", local-vs-local="+output.local_vs_local.first_numeric_tick+"; "+path);
            Cleanup();
        }
```

**【コードの説明】**

default世界の通常物理更新直後にCaptureし、120回で比較。計算前/接触前/接触/直後/最後を保存する。ここではdefaultを手動Simulateしていない。JSONは専用の新規診断結果。

**【入力と出力】**

Buildの入力は床/Prefab/位置/local/reverseで、出力はWorld。AfterPhysics/Cleanupは引数も返り値もなく、専用記録/Sceneを更新する。具体的な実測値はSTEP4_DIRECTION.md参照。

**【なぜ必要なのか】**

変更前にはこの実験は存在しなかった。ゲーム本体の規則や物理設定を変えず、最小構成で登録順序の影響を区別するために追加した。Editor外のビルドには含まれない。

## 今回追加：Cleanup

**【ファイル名】** [SingleCollisionProbe.cs](C:/SuikaGameAI/Unity/Assets/Editor/SingleCollisionProbe.cs:176)  
**【関数名】** `Cleanup`  
**【該当行】** 176〜193行

**【実際のコード】**

```csharp
    static void Cleanup()
    {
        running=false;
        var loop=PlayerLoop.GetCurrentPlayerLoop();Remove(ref loop);PlayerLoop.SetPlayerLoop(loop);
        foreach(var world in worlds)
        {
            world.recorder.recording=false;
            if(world.scene.IsValid())
            {
                foreach(var root in world.scene.GetRootGameObjects())root.SetActive(false);
                SceneManager.UnloadSceneAsync(world.scene);
            }
            if(world.material!=null)Object.Destroy(world.material);
        }
        worlds.Clear();
        foreach(var root in disabledRoots)if(root!=null)root.SetActive(true);
        disabledRoots.Clear();
    }
```

**【コードの説明】**

observerは自分の型だけ取り除き、専用Sceneを非アクティブ化してUnload。専用マテリアルだけDestroyし、元のrootを戻す。通常プレイ継続用の完全な実行状態復元ではないので、診断後はPlayを停止する。

**【入力と出力】**

Buildの入力は床/Prefab/位置/local/reverseで、出力はWorld。AfterPhysics/Cleanupは引数も返り値もなく、専用記録/Sceneを更新する。具体的な実測値はSTEP4_DIRECTION.md参照。

**【なぜ必要なのか】**

変更前にはこの実験は存在しなかった。ゲーム本体の規則や物理設定を変えず、最小構成で登録順序の影響を区別するために追加した。Editor外のビルドには含まれない。
