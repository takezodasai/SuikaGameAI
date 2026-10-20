# STEP 2 UDPプロトコル v2

Unity受信 `127.0.0.1:7773`、Python受信 `127.0.0.1:7889`。既存のInspector/config値を維持。1 Unityにつき1クライアント。同じポートで旧main.pyと新クライアントを同時起動しない。

## 観測

既存のJSON（score, done, playerPos, fruitPos, nextFruitInfo, imageData, 合体通知フラグ）へ次のフィールドを追加する。

| フィールド | 意味 |
|---|---|
| protocol_version | 2 |
| stream_id | 通信コンポーネントの生存期間を識別するUUID。Playし直したら新クライアントで接続 |
| episode_id | 初期化/resetごとに更新するUUID |
| state_id | 同一stream内で増え続ける観測番号。resetで巻き戻らない |
| reset_request_id | 最後に完了したresetのrequest_id。以後の観測にも保持。手動resetでは空文字 |
| score | 現在の得点（既存と同じ） |
| game_over | ゲームオーバー。既存のdoneと同値 |
| fruits | 盤面上の全果物の配列。0個なら[] |
| fruits[].id | 生存中に変わらない連番。消滅後に再利用しない。stream_idと組み合わせて識別 |
| fruits[].type | 既存FruitEvolution.fruitTypeの整数 |
| fruits[].x, y | Rigidbody2Dのワールド座標。Unity単位、右が+X、上が+Y |
| fruits[].vx, vy | ワールド座標の速度、Unity単位/秒 |
| fruits[].angle | +Z軸まわりの角度、度。正は反時計回り。0〜360に正規化しない |
| fruits[].angular_velocity | 角速度、度/秒。正は反時計回り |
| current_fruit | 操作用果物。present（有無）、type、x。欠ける場合type=-1 |
| next_fruit_type | 現在NEXT欄に表示される1個の種類。それより先の乱数や果物は送らない |

種類の対応：0 cherry、1 storobary、2 grap、3 orange、4 kaki、5 apple、6 nashi、7 peach、8 painaple、9 melon、10 watermelon。既存Prefabの値を使用し、名前・タグから推定しない。

操作中/NEXTは生成時のRuntimeフラグと参照で除外する。合体中の消滅予定2個は除外し、進化後は新IDにする。物理計算の位置と速度を同期して取得するが、これは固定時間刻みのstep APIではない。

`{"command":"observe"}`で数値クライアントモードに入る。このモードでは画像キャプチャを省略しimageDataは空文字、ゲームオーバー後は自動再開を待たずPythonのresetを待つ。Enterによる再開は維持。モードはPlay停止まで継続する。既存main.pyのみを使う場合は従来どおり画像送信・2秒後の自動再開。

## 命令とreset確認

既存の `{"action":0}`〜`{"action":5}` は維持。ゲームオーバー中とstep処理中の旧行動命令は無視する。

```json
{"command":"reset","request_id":"unique-request-id","episode_id":"currently-observed-episode-id"}
```

同じrequest_idで再送する。最後に完了した要求の重複は再実行しない。episode_idが古い要求も無視し、遅延パケットが新しいゲームを消さないようにする。要求は直列に送る。

成功条件：新しいepisode_id、要求と同じreset_request_id、score=0、game_over=false、fruits=[]、current_fruit.present=true。ソケットは維持。旧果物を非アクティブ化してから破棄し、プレイヤー位置/速度/壁フラグ、得点、時間、操作果物、NEXTを初期化する。BEST SCOREは維持する。

Python側は同一streamでstate_idが増えた完全な観測だけを返す。UDPは配送保証がないので観測欠落時は次の完全な状態を使う。resetの確認が得られなければTimeoutErrorを返す。

60,000バイトを超える観測は切り捨てず、UTF-8バイト列を42,000バイトずつ分割し、`message_type=state_fragment, stream_id, state_id, index, count, data(Base64)`で送る。Pythonは順不同/重複を処理し、全片が揃った観測のみ返す。欠落片は2秒で失効。受信側は最大4096片・未完成8観測。通常の盤面は分割不要。旧DQNは分割観測非対応。

## Pythonの使用例

SuikaGameAi/SuikaAiを作業ディレクトリにし、`src`をPYTHONPATHに追加するか既存のPoetry環境でパッケージを読み込む。

```python
from suika_ai.unity_env import UnityEnv

with UnityEnv() as env:
    state = env.reset()
    env.send_action(2)  # 既存の落下操作
    state = env.receive_state()
    for fruit in state["fruits"]:
        print(fruit["id"], fruit["type"], fruit["x"], fruit["vy"])
```

再確認：UnityでPlayし、`python -B check_unity_state.py`で3回reset。`--play`を付けると最大90秒の落下/合体/終了/reset確認。Editorがバックグラウンドで停止する場合はUnityを前面に保つ。

## STEP 3：正規化X座標とstep

```python
with UnityEnv() as env:
    state = env.reset()
    while not state["game_over"]:
        state, reward, done, info = env.step(0.65)
```

wire形式（通常はUnityEnvが生成）：
```json
{"command":"step","stream_id":"current-stream","episode_id":"current-episode","action_id":1,"x":0.65}
```

- xは有限の0〜1。範囲外/NaN/無限/文字列/boolはPythonでValueError、Unity側でも数値範囲を検査。action_idはepisode内で1から順番に送る。
- 観測のdrop_rangeにvalid/error/min_x/max_x/left_wall_inner/right_wall_inner/fruit_left_extent/fruit_right_extent/clearanceを追加。
- 既存Wallタグの有効なBoxCollider2Dを、果物と高さが重なる左右1個ずつ検出。調査対象以外の回転壁や複数壁は拒否する。名前から壁を推定しない。
- 果物の現在のPolygonCollider2D.bounds（形状/スケール/回転/offset込み）から左右の張り出しを取得する。L=左壁内面+左張り出し+余白、R=右壁内面−右張り出し−余白。余白はUnity既存defaultContactOffsetの3倍（両Colliderの接触空間と追加余白）。実Collider距離判定の接触skinを避ける保守的な範囲であり、数学的な接線ぎりぎりは使わない。
- L/Rを既存Playerのワープ境界＋手元オフセット(-0.7)と交差させる。Player側に有効な非Trigger Colliderがある場合は、その張り出し制約も交差させる。対象SceneではPlayer Colliderは無効。
- 適用する果物中心XはL+x*(R-L)。従って0.5は「果物中心の安全区間の中点」で、ワールドX=0とは限らない。
- STEP 3.5以降、Playerと保持果物をFixedUpdateごとにMoveTowardsで移動する。各刻みはaiMoveSpeed*Time.fixedDeltaTime以内。毎回Physics2D.SyncTransforms後に全Wallとの有効なCollider2D.Distanceと内側boundsを検査する。重なり/無効距離なら直前の位置へ戻して拒否し、DropFruitは呼ばない。複数/未知の壁配置も安全側に拒否する。
- 移動中も盤面の物理は通常進行し、到着したときだけ既存DropFruitを1回呼ぶ。重力/摩擦/形状/出現確率等は変更しない。
- 完了は実際の落下後ceil(0.5 / Time.fixedDeltaTime)回以上のFixedUpdateを経たLateUpdate、またはゲームオーバーになったLateUpdate。通常25回。移動tickはこの25回に含めない。完全静止は待たない。完了後も物理は進行し、同期シミュレーターではない。
- step中はキー移動/Enterと旧UDP行動の混入を防ぐ。step外の既存キー操作は変更なし。resetは処理中stepを破棄して新episodeへ切り替える。
- 完了時の観測にstep_resultを付け、同じ観測をキャッシュする。infoはこのstep_resultで、action_id、requested_x（正規化入力）、applied_x（実ワールドX）、applied_normalized_x、min_x/max_x、drop_success、dropped_fruit_id、score_before、reward、physics_steps、statusを含む。rewardはUnity受理時から完了時のスコア差。
- 同じaction_idの再送は処理中でも再実行しない。完了後は保存した同一観測を返す。過去ID/古いepisode/別処理中の命令は拒否。同じIDで異なる座標も拒否する。IDは落下処理より前に確保し、途中例外で結果不明でも再送による二重落下を防ぐ。
- Pythonはaction_id/episode/streamを照合し、完了観測を返す。キャッシュ結果は一般観測よりstate_idが古くても待機中の命令に一致する場合のみ受け入れ、通常のstate_id高水位は巻き戻さない。
- step前に終了済みなら落下せず(state,0,True,info)を返す。処理中にUnityが拒否した場合はRuntimeError。timeoutは成功扱いせずTimeoutErrorとし、次のstep/旧actionは禁止、resetで回復する。1クライアントのreset/stepは直列に行う。

調査した既存操作の不整合：Trigger接触フラグ、速度減衰、中心付近でのフラグ解除により境界への食い込みがあり得る。STEP 3.5では、AI落下後により大きな保持果物が同じXに生成される場合、新規オブジェクトの初期位置だけを描画前に安全範囲へ補正する。移動中の既存果物を補正で瞬間移動させない。キーボード生成/移動のルールは変更していない。

短時間の再確認：UnityをPlayし`python -B check_unity_step.py`。9回の端点試行と最大28回の中央/ランダムstepを行い、各stepパケットを二重送信する。通常30秒程度。全種類/長時間/キーボード境界長押しの網羅テストは別途実施する。

## STEP 3.5：速度の調整と移動情報

- HierarchyのPlayer → InspectorのPlayer Controller → AI Step Movement → **AI Move Speed** を調整する。単位はUnityワールド単位/ゲーム秒、既定2.5。Play中の調整は停止時に戻るため、保存する設定はPlay停止中に変更してSceneを保存する。
- 既定値は既存キーボードのspeed=5×入力0.5を基準とした値で、公式速度の完全再現ではない。AIはフレーム数に依存する減衰を使わず一定速度。キーボード速度/減衰処理は従来のまま。
- 速度はstep受理時に確定し、途中でInspectorを変えた場合は次のstepから反映。0/負値/非有限の速度は拒否。
- 観測にai_move_speed、fixed_delta_time、time_scale、step_progressを追加。step_progressは進行中のStepResultで、statusはmoving/post_drop。通常観測と同時に受信できる。
- infoへmovement_start_x、target_x、current_x、movement_speed、movement_steps、planned_movement_steps、movement_secondsを追加。予定tickはceil(距離/(速度*fixedDeltaTime))で、浮動小数点により実測が1tick多くなることがある。physics_stepsは落下後の分のみ。
- 移動中にgame_overになれば落下せず完了観測を返す（done=true、drop_success=false、dropped_fruit_id=0）。rewardは移動中の合体も含むスコア差。途中resetは移動・待機を破棄し、旧episodeの命令を無視する。
- env.step(x, timeout=None)の既定待機は観測された距離・速度・time_scaleから算出し、落下後0.5秒と通信余裕を追加する。timeout=秒で明示指定も可能。処理中にEditorを一時停止した場合や外部からtime_scaleを変更した場合は依然タイムアウトし得る。結果不明時は従来どおりreset必須。
- 描画やアニメーションの完了イベントは使わず、固定物理更新と数値だけで移動・到着・落下を管理する。高速学習機能自体は未実装。
- 短時間検証は`python -B check_unity_smooth_step.py`。左右端・近距離・移動中の盤面更新・二重命令・途中resetを確認する。低速に設定した場合は相応に時間が延びる。

## STEP 4 experimental prediction / comparison

精度未達。探索入力として使用しないこと。結果は `status="experimental"`, `validated_for_search=false`。

Unity内部API（Play中、main thread、idle時のみ）：
```csharp
var prediction = SuikaPhysicsSimulator.Predict(playerController, gameManager, 0.65f);
// horizon指定は4番目にpostDropSteps。既定ceil(0.5/fixedDeltaTime)。
```
この呼び出しは既存盤面から独立Sceneで予測する。過去のJSONスナップショットを復元するAPIではない。予測用fruit idは、既存盤面の正idを維持し、新規落下/合体を予測世界内の負idで識別する。実ゲームで新規生成される正idとは比較時に対応付けが必要。

診断UDP命令は既存stepと同じfieldを使い、`command`だけ`compare_step`とする。同じUpdateで予測してから実際にも1個落とすため、これは予測専用命令ではない。重複action_idは予測/落下を再実行せず既存キャッシュを返す。通常の`env.step`の動作は変更していない。

完了観測の`prediction`に `initial_fruits`, `fruits`, `score`, `reward`, `game_over`, `drop_success`, `requested_x`, `applied_x`, `physics_steps`（移動と落下tickも含む総数）, `movement_steps`, `movement_seconds`, `post_drop_steps`, `fixed_delta_time`, `merges`, `elapsed_ms`, `source_unchanged`, `initial_contact_count`, `limitation` を追加。観測側`actual_total_physics_steps`と比較する。既存`step_result.physics_steps`は落下後のtickのみであり、総数と区別する。距離/速度/角度の単位は既存観測と同じ。

短時間再検証（Unityで対象SceneをPlayし、他のUDPクライアントを終了してからPythonプロジェクト内で実行）：
```powershell
python -B check_unity_prediction.py --output prediction_comparison.json
```
初期reset→同一x=.65を8回→左右端→reset。予測自体による実盤面/スコア/乱数の変化を検査する。比較不一致は非ゼロ終了、結果ファイルの`all_within_tolerance=false`となる。閾値は診断用で、公式に定められたゲームの許容誤差ではない。

精度制約：公開APIによるコピーでは接触solver履歴を移植していない。進行中の合体は拒否する。予測では合体元の削除/終了判定を各tick末に行うが、実ゲームは描画フレーム末/Updateで行うため複数tick/フレームでは時間差があり得る。現在見えていない将来NEXTは生成せず、UnityEngine.Random.stateを不変検査する。同期処理はmain threadを計算時間ぶん占有する。正確性はDEVELOPMENT_LOG.mdと測定JSONを参照。

調査資料：[Unity 2022.3 PhysicsScene2D.Simulate](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/PhysicsScene2D.Simulate.html)。ローカルSceneのみの演算であり、FixedUpdateは自動呼出しされないため移動の数値tickは予測側で明示的に実行する。

## 2026-10-20 更新単位の任意診断

compare_stepに `trace_physics: true` を指定すると、同じ盤面で診断なし予測→診断あり予測→実stepを各1回実行する。action_idの再送排除は従来どおり。通常stepに二重予測は追加しない。

`comparison_post_drop_steps` はcompare_step専用（0=従来、1..150=指定更新数、範囲外拒否）。通常stepは値を無視し、0.5秒以上の従来仕様を維持。

結果predictionへdiagnostics（initial/first mismatch snapshots、各tickの誤差、接触/合体/生成/削除イベント、打切りフラグ）とreference_*（同一状態の診断なし結果）、scene_create_ms/copy_ms/simulation_ms/cleanup_schedule_msを追加。diagnosticsは最大512更新。IDは元果物IDと合体元の系譜で対応付ける。内部接触状態を復元したわけではない。詳細と限界はSTEP4_DIAGNOSTICS.md参照。


## STEP 4-B evaluation metadata (2026-10-20)

compare_step keeps protocol_version=2 and existing action_id retry semantics. Diagnostic Report adds final_actual/final_prediction Frame (same post-physics phase and bounded Recorder). Result adds initial_next_fruit_type (visible NEXT only) and game_over_height, captured at Run start. No new command or normal step horizon change. Python/evaluate_unity_prediction.py uses trace_physics=true and comparison_post_drop_steps=1..150; ordinary step remains unchanged. Exact initial public snapshot is diagnostics.initial_actual; previous Python observation may be older. See STEP4B_EVALUATION.md for metrics, eligibility, JSONL persistence and exclusions.
