# 物理予測の信頼性と価値教師の検証（2026-10-28）

## 結論

新しい価値モデルを標準採用する結果ではない。旧ACモデルより独立Testの誤差が大きく、同一盤面内の順位診断も改善しなかった。物理予測には接触・処理順序に依存する差がある。物理・MCTS・GOルールは修正せず、観測機能と独立した学習実験だけを追加した。

成果物は `Python/outputs/value_reliability_01`。新Playerは `Unity/Builds/Reliability_02/SuikaGameAI.exe`。途中検証のReliability_01、従来Player、旧モデル、既存ログは保持した。収集プロセスの停止・再開はしていない。commit/pushなし。

## 1. 物理の実測

独立したPhysicsAuditProbeで、固定5候補それぞれについて、同じ初期盤面から予測と実ゲームを比較した。主試験は9条件×5候補＝45ケース（約105秒）。中盤、密集35果物、スイカ生成前、GO直前を含む。再構成した果物の生成順反転、実ゲームで5tick待ってからの予測も別条件とした。

`natural8` はseed99117でReset後に8落下を実行して得た元の物理世界であり、スナップショット再構成ではない。ただし、これは今回新しく作った短い自然進行例であり、過去の収集ゲームの接触状態を復元したものではない。

| 条件 | 最大位置差（world） | 最大速度差（world/s） | 予測heuristicの選択 / 実ゲームheuristicの選択 |
|---|---:|---:|---|
| 中盤・再構成 | 0.1622 | 2.4265 | 1 / 1 |
| 中盤・生成順反転 | 0.1976 | 2.2866 | 1 / 1 |
| 中盤・5tick経過 | 0.1965 | 2.8010 | 1 / 1 |
| 密集35・再構成 | 0.0335 | 0.7368 | .75 / .25 |
| 密集35・生成順反転 | 0.0180 | 0.6672 | .25 / .5 |
| 密集35・5tick経過 | 0.0528 | 1.4641 | .75 / .25 |
| スイカ生成前・再構成 | 0.3446 | 5.4378 | 0 / 0 |
| GO直前・再構成 | 0.0102 | 0.1572 | .25 / .25（安全候補のみ） |
| 自然8落下後 | 0.1355 | 2.5486 | .25 / .25 |

最大誤差は各条件の5候補・全比較tickから求めた。個々のtickの誤差や最終位置差とは異なる。位置差が小さい密集盤面でもargmaxが変わった。ただし、密集3条件の実測heuristic損失は、それぞれ0.0065、0.1212、0.0019点相当と小さい。全候補の即時得点は0であり、**得点を最大化する真の最善手が変わったことを証明した結果ではない**。微小なR差の順位も含む。

45/45で、窓終了時の得点増分・合体数・最終GOが一致。45/45で標準MCTSの該当root候補の即時予測（得点・GO・tick数）が独立PathSessionの結果と一致した。したがって、今回の誤差は診断専用の別物理モデルだけの問題ではなく、既存MCTSも共有する。

### 確定したことと、未確定の原因

- 全ケースのtick0で、比較対象の位置・速度・回転・角速度・質量・COM・慣性が一致した。初期値を記録・コピーしただけで完全再現とはいえない。
- 接触履歴を持つ実ゲームとcloneでは、tick0のcontact集合が既に異なる。5tick待った盤面とnatural8でも見られた。warm-start impulse、接触manifold、sleep継続時間は保存・再設定できていない。
- 両側をcold状態で再構成した中盤・密集盤面にもtick1から運動差がある。接触キャッシュだけを唯一の原因とは断定できない。果物の生成順を反転すると、同じ可視初期状態でも予測・実測の順位や誤差が変わった。native接触処理順・オブジェクト挿入順の影響を切り分ける必要がある。
- スイカ生成前では、tick1のcollision callback列の順序にも差がある。合体のcallbackとDestroy/予測側FlushRemovalの扱いはコード上異なるが、それぞれの寄与は未同定。
- tick34のCOM/慣性差の初回例は、type8の**合体済み・除去予定の2果物**だった。実ゲーム側はCOM=(0,0)、慣性=1、予測側は元のCOM≈(.00759,-.24370)、慣性≈.77313。これは削除過程の観測差であり、動作中の果物の慣性が間違っている証拠として扱わない。
- Transform同期後のtick0のbody値は一致した。重心・慣性やTransformを推測で書き換える修正はしていない。
- GO直前x=.5では、幾何・接触条件が成立したtickは両方7。一方、実ゲームはUpdateでGO確定するまで11tickまで進んだ。FixedUpdateが複数回走ってからUpdateが来る場合があり、予測の各Simulate直後判定と時相が違う。今回の最終GOは一致したが、一般に完全一致とは主張できない。他3危険候補もcommitted flagの観測位相差が1サンプルあった。安全候補はx=.25。

この試験で新しいGO見逃し・過剰予測は0/45だった。過去のGO見逃しが解消したという意味ではない。自然進行の危険盤面、多手継続、GO条件成立からUpdateまでの得点変化は追加検証が必要。

## 2. 判断開始時の観測

`--decision-capsules` を明示した同期planだけで、`game_00_decisions.jsonl` を別保存する。旧ログschemaを変更しない。Reliability_02以降が必要。デフォルトOFF。既存の収集への自動適用・Player差し替えは行わない。

保存するもの：

- episode/action ID、Player全体のFixedUpdate callback通算tick、ゲーム時刻・fixed時刻・render frame
- 落下前の位置・速度・回転・角速度、保持果物のY、公開NEXT、得点
- cooldown残量、次の合法落下時刻、移動速度、dt、要求された探索設定
- HasCollided、preview/merging/sleep、contact集合とimpulse、実効COM・慣性・質量
- 各bodyのgravity/drag/constraints/body type/simulated/useAutoMass等、各Colliderのenabled/trigger、形状profile、layer/scale
- build GUID、環境・Prefab物理設定、Unity Random.state、観測時の列挙順

RNGは再現性診断用であり、モデル入力・行動選択に使わない。NEXTの先の確定果物を列挙しない。列挙順と真のnative作成順は別物。

`native_checkpoint_exact=false`、`solver_cache_known=false`、`native_sleep_timer_known=false`、`automatic_com_history_known=false`、`creation_order_known=false` を明記。**スナップショットが増えてもnative physics checkpointにはならない**。要求された設定と、自動深さなど適用後の実探索設定は既存planning reportとIDで対応させる。

Unity内部のDestroy待ちキューそのものは取得しない。mergingフラグと除去イベントは記録できても、内部キューを再構築できたとは扱わない。v2の3ケースで観測読み取り計測最大9.6ms、行write最大.31ms。JSON化・初回環境書込等を含む全オーバーヘッドではない。物理設定を変更しなくても壁時計時間は増えるため、任意のリアルタイム実行のtick/Update位相まで不変と保証しない。

観測のための新GameObjectは作らず、Application.quittingに静的な終了処理を登録する。writerは各行flush。外部からPlayerを強制終了すると終了statsは残らないことがあるが、完了行は保持される。

Reliability_02でON/OFFの同じ3ケースを実測。予測のafterstateは3/3完全一致。自然8落下例は実ゲームの初期・終了状態も完全一致。cold中盤/密集例の実ゲームの終了浮動小数値は完全一致しなかったが、**OFF/OFFを再実行しても同じ2条件で不一致**が発生した。いずれも得点・合体・GO・tick数は一致。観測が物理状態を変更したと断定する証拠はないが、再構成盤面の別プロセス実行でbit一致を保証できたとも報告しない。

UDPの3手試験は成功。v2記録3件、通算tickは18→85→130、環境GO比率=.83、手数上限終了として保存し自然GOには含めない。

## 3. 自然GO教師と分割

`G_t = 実ゲームの自然GO最終得点 - 当該post-action状態の得点`。観測された行動方針の下での実現returnであり、最適可能得点ではない。6落下の打ち切り予測、未完了ゲーム、最終得点が不明なゲームをこの教師にしない。

旧ACデータとpolicy-successの分割履歴、最新収集の完了記録を突き合わせた。最新フォルダの自然GO・整合性検査済み25ゲームを固定したinventoryとして取り込んだ。旧AC以外のsource 86本を検証、旧ACの非Test packed配列を再利用。既存Test/historical Testの19 seed-groupは隔離し、新学習・評価には使わない。seedと初期8果物列の関連グループを分割間で分離した。

| 分割 | ゲーム | seed/初期系列グループ | post-action状態（terminalを含む） |
|---|---:|---:|---:|
| Train |132|82|28,570|
| Validation |30|19|6,591|
| 新しい独立Test |5|5|979|

新Testは結果を見ない割当で固定したseed405582781、405582785、405582792、405582794、405582801。評価計画を先に書き、Validationのgroup-macro MSEでcheckpointを選び、全3モデルをhashで固定してからTestを1回評価した。Test結果による再学習・閾値調整はしていない。

入力は既存ACと同じ：公開されている現在状態のfruit30特徴、global37特徴、geometry57特徴。seed、RNG、残り手数、最終得点、将来イベント、near-GOラベルは入力しない。終端GOが既知ならvalue=0の既存maskを維持。未来NEXTの50%マスク学習も維持する。候補比較時にrootで未公開の次果物は公開出現分布で平均化し、その確定値を使って候補を選ばない。

## 4. A/B/Cの小規模学習

共通：CPU1thread、同じ初期seed/抽出seed、groupとgameを均等化した抽出、最大10epoch・patience3、AdamW。既存の別盤面間ranking補助loss .05も維持。これは同一rootの候補順位学習Dではない。

- A：既存geometry43009パラメータ、自然GO return MSEで再学習。
- B：同じモデル、最後の4非終端観測（remaining_actions<5）のMSE重みを4倍。倍率は試験値であり最適値ではない。
- C：同じvalue部分に223パラメータの独立risk headを追加。`MSE + .05 ranking + .1 weighted BCE`。riskは「この行動方針のまま次の3観測遷移以内に自然GOになるか」。秒単位の危険率や各候補固有の真のGO確率ではない。pos_weightはTrain比率から上限20、確率出力時にlog-weight補正を行うが校正保証はない。

選ばれたepoch A=3/B=6/C=2。学習本体はそれぞれ18.2/27.0/15.7秒（特徴量前計算・評価等を除く）。ValidationでCを選択し固定した。

### 予測結果（単位：実ゲーム得点）

| モデル | Val MAE | 新Test MAE | 新Test GO直前の平均正の過大評価 |
|---|---:|---:|---:|
| 凍結した旧AC |350.9|**186.1**|220.4|
| A 通常再学習 |345.6|235.8|195.6|
| B GO直前4倍 |361.5|279.8|230.1|
| C 追加得点＋GO head |339.6|236.1|208.9|
| score/果物数の線形baseline |360.6|268.0|292.3|

MAEは既知terminalを除く。Testは974非終端状態だが独立ゲームは5件。GO直前は20状態/5群。Valは6,561非終端状態/19群、GO直前120状態。group-macro MAEでも旧AC187.1、A242.6、B291.1、C246.0と同じ傾向。状態数を独立サンプル数として優劣を断定しない。

Train→Val MAEはA258.1→345.6、B258.1→361.5、C271.5→339.6。Bの単純な重み付けは改善を確認できなかった。Cのrisk headは新Test ROC-AUC=.943、Brier=.01341（陽性15/974）。隣接観測が相関する5ゲームの結果であり、校正済みの安全判定として使用できるという意味ではない。

Valには最初のスイカ存在を観測できた9群があり、観測前5/観測後5状態ずつ45件。旧AC MAEは556.3/203.9、A532.9/205.2、B372.0/192.2、C536.5/190.7。これは最初の**観測**前後であり、一瞬の生成・消滅の全イベントを回復したものではない。新Testには観測スイカ例が0件で、独立Test上の生成前後性能は評価できない。

### 同一盤面の候補比較（参考診断）

以前の6盤面×6座標（固定5＋.37）×3未知果物系列を再利用。repeatは除外し、GO候補の除外条件を統一した。目的変数は6落下の予測Scene内続行得点であり、自然GOまでの正解ではない。

| 方法 | 順位一致（68比較ペア、同点予測は半点） | 最大6落下得点との差の盤面平均 |
|---|---:|---:|
| 旧AC |66.2%|7.39|
| 既存heuristic |57.4%|13.28|
| A |47.1%|18.56|
| B |45.6%|13.22|
| C |41.2%|22.94|

固定5候補だけの旧診断は旧AC55.8%・heuristic61.6%/43ペアであり、6候補の表と混同しない。6盤面・相関のあるペア・物理誤差を含む参考値。今回の再学習に候補順位の改善は見られない。短期順位が良い旧ACも実ゲームの最終得点を改善した証拠はない。

**Dは実施していない。** 信頼できる同一rootの実ゲーム自然GO counterfactual教師がないため。短期予測returnを自然GOラベルに格上げしなかった。

## 5. 互換性・テスト

- Python：374テスト成功（既存367＋新規7）。最終CLI変更後も再実行。
- 新Playerのnative self-test：MCTS861、rules127、path26成功。
- 従来SyncOptimized_03由来の32回診断結果と3固定盤面で、選択位置・全候補・全nodes・全iterationsが一致。時刻・GUID・計測メモリ等まで同一とは主張しない。
- UDP3手、metadata確認、.83確認、独立sidecar3件、得点保存、打ち切り区別を確認。
- 変更前保護hashで、MCTS本体・物理本体・旧モデル・旧Playerは不変。既存ファイルでは診断helperに公開入口を加えたCounterfactualProbeと、pre-plan観測呼出1行のUDPStepProtocolのみ今回のUnity既存差分。Python launcherはopt-in引数追加。既存の未commit最適化も保持。
- この試験は通常の同期MCTSと同じ得点・合体・GO条件を使用するが、.83という環境IDだけでnative状態の完全一致を保証しない。

主な変更：

| ファイル / 関数 | 内容 |
|---|---|
| `Unity/Assets/Scenes/Script/SuikaPhysicsAuditProbe.cs:45` Setup / Start | 冷間再構成・生成順反転・warm・自然prefixの分離、tick/判断誤差測定 |
| `Unity/Assets/Scenes/Script/SuikaCounterfactualProbe.cs:107` RestoreForAudit | 既存復元処理への診断入口 |
| `Unity/Assets/Scenes/Script/SuikaDecisionCapsules.cs:28` Capture | 既知/未知を分けた判断直前の観測 |
| `Unity/Assets/Scenes/Script/UDPStepProtocol.cs:94` | デフォルト無効の観測呼出1行 |
| `Unity/Assets/Editor/SuikaReliabilityBuild.cs` | 別フォルダへの新規build、上書き拒否 |
| `Python/src/suika_ai/parallel_play.py` run_parallel / `Python/play_parallel_ai.py` | opt-in起動引数 |
| `Python/run_physics_audit.py` | 1Player限定・timeout付きの独立診断 |
| `Python/value_reliability_data.py:25` build | 旧Test隔離、自然GO教師、監査manifest |
| `Python/value_reliability_train.py:58` train / :95 assess | A/B/C、Validation固定、Test再実行拒否 |
| `Python/analyze_value_reliability.py` | 物理誤差と参考候補順位の分析 |
| `Python/tests/test_value_reliability.py` | split、riskラベル、WM観測窓、terminal出力等の回帰検証 |

## 6. 次に実装するもの

新モデルをMCTS標準へ接続しない。まず、**自然プレイの判断開始capsuleを基準に、同じ公開状態からの候補を実ゲーム続行で検証する小規模な教師収集**を優先する。

snapshotをcold復元しただけでは正確な分岐とはいえない。新規の短いepisodeについて、resetからの行動・実落下tick・待機tick・RNG公開条件を記録し、prefix再生が元の盤面を許容誤差内で再現できるか先に確認する。満たさなければexact counterfactualというラベルを付けない。復元誤差・教師の続行方針・打ち切り有無を必ず保持する。

その後の限定的な比較AIは `即時実測/予測得点 + V(次の意思決定状態)` と、別のrisk出力を比較する形が候補。ただしGO headの閾値で自動排除したり、短い予測結果をもとに標準採用したりしない。候補内の自然GO return順位と選択regretを、同一公開状態・共通の未知果物分布で評価する。合格後にのみ独立Playerの少数自然GOゲームへ進む。

追加すべき独立データは、スイカ生成前後、自然GO直前、同一rootの複数候補の長期結果。現状は単一行動方針の状態returnが中心で、行動ごとの優劣を直接教えていない。単なるモデル大型化やGO直前の重み増加より、この不足を優先する。

### 観測をONにする短時間コマンド

```powershell
Set-Location C:\SuikaGameAI\Python
$tag = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8)
.\.venv\Scripts\python.exe .\play_parallel_ai.py `
  --exe ..\Unity\Builds\Reliability_02\SuikaGameAI.exe `
  --games 1 --episodes 1 --max-steps 3 --headless `
  --ai-mode mcts --mcts-iterations 32 --mcts-max-depth 4 `
  --seed 99117 --base-port 41960 --require-metadata --expected-go-ratio 0.83 `
  --episode-events --decision-capsules --output "outputs\decision_smoke_$tag"
```

これは打ち切り動作確認であり、最終自然GO returnの学習教師にはしない。既存の就寝中収集設定へは自動適用しない。
