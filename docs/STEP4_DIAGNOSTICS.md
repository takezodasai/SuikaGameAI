# STEP 4 物理更新ごとの誤差調査（2026-10-20）

作業先 C:\SuikaGameAI、ブランチdevelop。コミット・Pushなし。物理演算の挙動を変える修正は実施していない。今回は原因の切り分けと比較機能の改善。STEP 4は未完了、STEP 5未着手。

## 確認した事実と限界

- 初回10手診断：3件合格/7件不合格。初期の位置・速度・回転・角速度・質量・慣性・重心・摩擦・反発・睡眠・preview/merging属性は一致。
- 接触中の第4ケース：更新0は全数値誤差0。更新1（0.02秒後）で位置差0.00284991、速度差0.0674381、角度差0.616608度。合体・生成・削除はまだなく、同じ描画フレーム内に複数更新する条件でもない。
- この果物の実世界には更新0で53接触点/normalImpulse合計30.7451があるが、コピー側には0接触点。更新1は両側47接触点、実側は継続接触、予測側は新規enterイベント。接触の内部状態をコピーしていない事実を確認。
- 別の自由落下→最初の床衝突ケース：更新74は全数値誤差0、更新75で位置差0.0143752・角度差7.79013度。落下X差0、接触点19個と法線は全て完全一致。それでもnormalImpulseの対応点ごとの最大差12.15802が生じた。**接触履歴の欠落だけでは説明できない**。
- 同じ接触点でも接触インパルスが異なることまでは確認済み。ネイティブの拘束解決順、body/fixture作成順、island等の内部状態のうちどれが支配的かは未確定。推測を根拠に物理パラメーターや作成順を変更する試行はしない。
- 更新ごとの採取位置はPhysics2DFixedUpdate直後。予測もSimulate直後・FlushRemoval前に採取し、両側を同じフェーズで比較する。ContactPoint一覧は比較用に並べ替えており、native solverの実行順を観測できたわけではない。
- 「最初の数値差」は位置1e-6/速度1e-5/角度1e-4/角速度1e-3を超えた更新。厳密比較の閾値（位置1e-3/速度1e-2/角度0.5/角速度1）は以前と同じ。ビット単位の一致とは区別する。

## 候補別の切り分け

| 候補 | 確認結果 |
|---|---|
| ① 接触履歴 | 更新0の接触点・normalImpulseがコピーされていない。継続接触が予測側でenterになる。影響候補だが単独の根因とは断定できない。 |
| ② 更新タイミング | A/B10ケースで各tickと総tick一致。最初の接触誤差は同じ更新1に発生。LateUpdateで複数tick分進んでから完了する問題は別途存在し得る。 |
| ③ 衝突・合体順 | 接触イベントの順に差がある。ただし初回不一致は合体前。単一果物の床衝突でも差があり、合体処理の順だけが原因ではない。 |
| ④ Destroy | 合体ケースは両側59更新目で合体・生成・削除要求、60の採取前までに実側Destroy/予測側無効化。接触更新1の誤差を説明しない。複数tick/描画フレームでの影響は未検証。 |
| ⑤ 初期化 | 初期数値と、最初の床衝突の接触点/法線・摩擦/反発・質量/慣性は一致。合体生成物のDanse.Startが実側では後に走る一方、予測側は直ちに初期化するコード差は残る。複数tick/フレームでの影響は未確定。 |
| ⑥ 内部状態 | 接触点の一致と反力の不一致を実測。solver拘束順等の個別要因は公開情報だけで一意に切り分けていない。 |

## 誤差の時間推移

初回診断の第4ケース。単位はUnity単位、Unity単位/秒、度。

| 物理更新 | 経過秒 | 最大位置差 | 最大速度差 | 最大角度差 |
|---:|---:|---:|---:|---:|
| 0 | 0 | 0 | 0 | 0 |
| 1 | .02 | .00284991 | .0674381 | .616608 |
| 5 | .10 | .000966081 | .00938726 | .754486 |
| 10 | .20 | .00248886 | .0197189 | 1.29056 |
| 25 | .50 | .0245461 | .160767 | 9.76318 |
| 28 | .56 | .0370649 | .0945625 | 12.5117 |

誤差は単調増加ではない。一度小さくなっても再衝突で増幅する。初回診断の全ケース・全tickでは最大位置差0.272233、速度差2.04409。

## 同じ初期盤面での変更前後比較

`trace_physics=true`時だけ、診断なし予測→診断あり予測→実stepを同じUpdateで実行する。2予測それぞれで実盤面・スコア・RNGの不変を検査。2予測間に実世界の物理tickは挟まない。

- A/B10ケース：診断なし/ありの予測後の位置・速度・角度・角速度・種類・スコア・終了状態は全10件同一。診断の追加による予測精度の改善はない。
- A/B10ケースは4合格/6不合格。実側との種類/個数・スコア・総tick・非終了状態は10件一致。最大の最終位置差0.0829872、速度差0.963758、角度差24.7773度、角速度差177.089度/秒。途中の最大速度差は2.63721。
- 合体ケースは見えているcurrentとNEXTが同じ種類になるまで最大10回通常resetを行い、同じXへ2個落とす。比較用に落下後100更新（2秒）を指定。2個目は両側59更新目にブドウ(2)+ブドウ(2)→デコポン(3)、6点加点。生成/削除要求のtickも一致し、終了時の種類・個数・得点は一致。最大最終位置差は0.0352193で完全一致ではない。
- 全ケースが非ゲームオーバー。終端の一致・長時間連鎖・高密度盤面・スイカ消滅を保証する検証はしていない。
- `prediction_trace_before.json`は初回調査データ、`prediction_trace_paired.json`は同一盤面A/B、`prediction_trace_merge.json`は合体ケース。初回とA/Bは乱数で盤面が異なり、誤差の大小を改善率として比較しない。

## 計算時間

| 対象 | 平均ms |
|---|---:|
| 前回報告（異なる盤面条件） | 11.43 |
| 今回A/Bの診断なし | 13.08263 |
| 同じ盤面で診断あり | 16.61295 |
| 診断追加分 | 3.53032 |
| 診断ありScene生成 | .06353 |
| 診断ありコピー/初期採取 | 1.18375 |
| 診断あり物理/毎tick採取 | 15.29616 |
| 無効化・解放予約 | .05874 |

前回との速度差は同条件の比較ではない。今回の物理ループは変更していない。解放はUnloadSceneAsyncなので、`cleanup_schedule_ms`は要求にかかった時間であり、解放完了までの時間ではない。測定値は初回JIT/Editor負荷を含み、統計的ベンチマークではない。

## 次に必要な調査

1. 今回の「履歴なし・最初の床衝突」のケースを固定した独立fixtureにし、body/Collider/fixtureの登録順と接触インパルスの再現性を1要因ずつ調べる。形状は既存Polygonを維持する。
2. 2つのローカルScene間、default Scene対local Sceneを分け、物理ソルバー内部順の差と接触履歴の差を区別する。
3. 複数tick/描画フレームでの合体元の残存とDanse.Start適用時点を重点検証し、終端ケースも加える。
4. STEP 5へは、上記を踏まえ合体・加点・終端・候補順位に必要な許容精度を定義してから進む。今回は探索/評価関数を実装しない。

エピソード再生は実装していない。履歴長N tickに対し再計算量は少なくともO(N)となり、初期fixture作成順まで合わせる難しさがある。今回「接触履歴のない初回衝突」でも差を確認したため、再生だけで解消するとは判断できない。必要性・精度効果を確認する前に大規模化しない。

## 変更コードの説明

行番号はこの調査完了時点。物理設定/Scene/Prefab/得点/進化ルールには差分なし。

### [PredictionDiagnostics.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/PredictionDiagnostics.cs:7)

- 関数/対象：新規。Recorder.Capture、Begin、InsertAfterPhysics、AfterPhysics、Collision、Merge、Removed、Compare、Stop
- 変更前後・理由：以前は最終状態のみ。物理直後に最大512更新を記録し、最初の差/接触/合体/寿命を比較。合体IDは親IDから作り、生成IDの違いによる誤対応を防ぐ。

```
systems.Insert(i+1,new PlayerLoopSystem { type=typeof(PredictionDiagnostics), updateDelegate=AfterPhysics });
```

### [SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:57)

- 関数/対象：Copy / Predict / Run / FlushRemoval / Dispose
- 変更前後・理由：以前は最終BoardFruitと総時間のみ。コピーの共通ID、Simulate直後の採取、Run後の記録凍結、生成/コピー/計算/解放予約の時間を追加。計算式や物理更新処理は維持。

```
if (Trace != null) Trace.Capture(score, IsGameOver(knownNext.activeSelf ? knownNext : held));
FlushRemoval();
```

### [FruitEvolution.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/FruitEvolution.cs:37)

- 関数/対象：OnCollisionEnter2D / RemoveFruit / 新規OnDestroy
- 変更前後・理由：以前はゲーム処理だけ。衝突、合体元/生成先、削除要求、実Destroyを観測。通知呼出しは読み取り/記録のみで、元の合体条件・加点・Destroy順序を維持。

```
PredictionDiagnostics.Merge(this, otherFruit, fe);
PredictionDiagnostics.Removed(fruit, "remove_requested");
```

### [UDPStateProtocol.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/UDPStateProtocol.cs:142)

- 関数/対象：ActionMessage（DTO。関数の変更なし）
- 変更前後・理由：以前は診断スイッチ/時間指定なし。trace_physicsとcomparison_post_drop_stepsを追加。通常stepでは指定を使わない。

```
public bool trace_physics;
public int comparison_post_drop_steps;
```

### [UDPStepProtocol.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/UDPStepProtocol.cs:48)

- 関数/対象：HandleStep / CompleteStep / ClearStepForReset
- 変更前後・理由：以前はcompare_stepで予測1回。指定時だけ同じ盤面で診断なし/ありを2回計算し、実stepは1回。CompleteStepで各tick比較を添付、reset/失敗/完了で記録を停止。比較専用ホライズン0=従来、1〜150=指定tick。範囲外拒否。

```
if (message.trace_physics) PredictionDiagnostics.Begin(playerController, gameManager);
pendingPrediction.diagnostics = PredictionDiagnostics.Compare(pendingPrediction.trace);
```

### [check_unity_prediction.py](C:/SuikaGameAI/Python/check_unity_prediction.py:59)

- 関数/対象：main / 新規summarize_trace
- 変更前後・理由：以前は最終比較だけ。--trace/--merge-case/--post-drop-stepsを追加。同一状態A/B、途中の最大誤差、打切り・更新数差を保存。CLI以外のUnityEnv.stepの実装は変更なし。

```
row['diagnostic_summary'] = summarize_trace(diagnostics)
row['reference_error'] = compare(reference, state)
```

### [test_prediction_comparison.py](C:/SuikaGameAI/Python/tests/test_prediction_comparison.py:20)

- 関数/対象：test_transient_divergence_not_hidden_by_final_agreement / test_trace_truncation_and_tick_mismatch_are_visible
- 変更前後・理由：以前は最終の対応付けテストのみ。途中で差が発生して最後に一致するケースと、記録打切り/更新数差が見えることを追加。

```
self.assertEqual(summary['max_position_over_time'],0.1)
```

### [Test-UdpLifecycle.ps1](C:/SuikaGameAI/Unity/Tools/Test-UdpLifecycle.ps1:235)

- 関数/対象：診断用スタブ / 診断ホライズンの回帰（PowerShellスクリプト）
- 変更前後・理由：既存テストへ診断クラスのスタブを追加し、比較100tick、通常25tick維持、151tick拒否を検証。Physics精度を検証するテストではない。

```
Assert ($stepper.GetType().GetField('targetTicks', $flags).GetValue($stepper) -eq 25) 'Diagnostic horizon changed normal step'
```

## SuikaPhysicsSimulatorの主要関数（前回実装も含む）

| 関数 | 役割 |
|---|---|
| [SuikaPhysicsSimulator](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:44) | 独立Scene/PhysicsScene2Dを生成し、得点表と終了高さを読み取る。 |
| [GameObject Copy](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:57) | 既知のコンポーネントだけを非アクティブな親下で複製。描画/補助スクリプトを止め、実bodyの数値を有効化後に復元する。 |
| [public GameObject CreateEvolved](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:135) | 既存進化PrefabをローカルSceneに生成。FruitEvolutionが通常と同じ進化/物理設定を適用する。 |
| [public void AddScore](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:144) | 予測専用スコアに既存得点表の値を足す。 |
| [public void DeferRemoval](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:145) | 衝突中の削除要求を予測側の待機リストへ入れる。 |
| [void FlushRemoval](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:146) | そのSimulateが終わった後で元果物を無効化する。実GameObjectを変更しない。 |
| [bool IsGameOver](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:157) | 既存のFruitタグとGameManagerの高さ条件を予測用オブジェクトへ適用。 |
| [BoardFruit[] ReadBoard](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:164) | preview/mergingを除いた予測bodyの数値を返す。 |
| [public static Result Predict](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:181) | 入力・idle検査、実盤面/RNG不変検査、予測環境生成〜解放を管理する入口。 |
| [static string SourceSignature](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:214) | 実果物の位置/姿勢/速度/睡眠等の署名で予測による変更がないか確認。 |
| [Result Run](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:234) | 盤面/保持/NEXTをコピーし、MoveTowards→到着後落下→固定dt物理→合体削除のループを実行する。 |
| [public void Dispose](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:332) | コピーを全て無効化し、専用マテリアル破棄とScene解放を予約する。 |

## 検証と再実行

Python自動テスト19件、C#通信・重複排除・停止・reset・比較ホライズン回帰は成功。Unity 2022.3.21f1で短時間Play/22手比較/reset確認済み。最終Console例外0（途中の診断クラス宣言のコンパイルエラーは修正済み）。Play停止済み。履歴変更・コミット・Pushなし。

UnityでgameDisplayをPlayし、Pythonフォルダから以下を実行する。他のUDPクライアントは終了する。

```powershell
python -B check_unity_prediction.py --trace --output prediction_trace_paired.json
python -B check_unity_prediction.py --trace --merge-case --post-drop-steps 100 --output prediction_trace_merge.json
```

比較不合格は非ゼロ終了する。通常プレイ/学習用のUnityEnv.stepへ診断の二重予測コストは加えていない。計測したJSONは初期/最初の差の詳細と更新別の誤差値に限定し、全オブジェクト全tickの完全ログやConsoleへの毎tick出力はしていない。

参考：[Unity Physics2DFixedUpdate](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/PlayerLoop.FixedUpdate.Physics2DFixedUpdate.html)。ネイティブ更新を置き換えず、その直後に観測処理だけを追加する。
