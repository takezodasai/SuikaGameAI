# STEP 8-U：落下位置比較と実ゲームのスイカイベント（2026-10-25）

標準はlegacy/grid5/32回/深さ4の同期MCTSのまま。今回の128回は比較条件であり最適値ではない。旧8-Sは再開せず、自然GOの新9ゲームも実行していない。develop、commit/pushなし。

## 1. 旧8-Sの確定結果

最終監査でresult.json16件、元JSONLの自然GO終了16件、完全な対応8ペア。保存hash・得点/報酬・公開果物prefix・環境/binaryが一致し、各episodeのerrorsは空。最初の読み取りでは16番目のresult.jsonが見えなかったが、最終監査では存在しhashを検証できた。旧データの修復・追記は行っていない。未開始2ペア（759408/759409）は実行しない。途中attemptは集計しない。

|seed|32回最終得点|64回最終得点|64−32|
|---|---:|---:|---:|
|759400|1981|2037|+56|
|759401|1671|2612|+941|
|759402|1844|1455|-389|
|759403|1425|2138|+713|
|759404|1262|2533|+1271|
|759405|2140|2347|+207|
|759406|1507|2314|+807|
|759407|2507|1999|-508|

|探索回数|自然GO数|平均得点|中央値|最高|最低|平均判断ms（全手加重）|判断時間合計s|
|---|---:|---:|---:|---:|---:|---:|---:|
|32|8|1792.125|1757.5|2507|1262|604.64|954.73|
|64|8|2179.375|2226.0|2612|1455|1124.02|2037.85|

64回6勝、32回2勝。差の平均+387.25点、標本SD645.45点、ゲーム/seedペア単位bootstrap10000回の95%区間[-40.25,793.875]点。状態/操作を独立標本にしていない。8ペアは少なく、途中で停止した特定seed群の結果で、普遍的な優位を証明しない。64回の全手加重判断時間は約1.86倍、総探索時間は約2.13倍（ゲーム長も異なる）。探索内の予測得点ではなく、実ゲームの最終得点。

|seed|回数|落下回数|総判断計算s|平均判断ms|ゲーム実時間s|
|---|---:|---:|---:|---:|---:|
|759400|32|212|130.87|617.32|298.42|
|759400|64|214|236.94|1107.18|392.97|
|759401|32|198|126.51|638.94|278.78|
|759401|64|272|303.41|1115.46|507.69|
|759402|32|191|126.19|660.68|268.31|
|759402|64|161|211.41|1313.10|326.16|
|759403|32|173|87.21|504.09|213.48|
|759403|64|229|256.70|1120.97|420.33|
|759404|32|150|85.58|570.54|197.67|
|759404|64|253|279.43|1104.47|457.41|
|759405|32|224|124.30|554.93|294.94|
|759405|64|235|261.82|1114.13|443.06|
|759406|32|165|91.16|552.51|215.05|
|759406|64|234|255.66|1092.55|431.83|
|759407|32|266|182.90|687.61|386.83|
|759407|64|215|232.49|1081.33|407.00|

計算時間は各手のUnity探索wall時間の合計。物理待機などを含むゲーム実時間やOSのCPU時間とは別。旧8-Sのdouble達成回数は未記録であり、最大果物から成功を推測しない。

## 2. 比較方式

新規 `compare_placement_mcts.py` は既存profile/audit/paired bootstrap/ロック/原子的result保存を再利用する。legacy/grid9/wideningは同じ128反復・深さ4・sync・random rollout・legacy expansion・chance・index順・post25。差はcandidate_count=9またはmcts_widening=trueだけ。各seed内で条件順を巡回し、1Playerずつ実行する。
ゲーム乱数は起動時Unity Random.InitState(game seed)、探索乱数はmcts_seed=8191の別System.Random。探索回数/方式でゲームの果物列を消費しない。完了後に両方式の公開果物prefixを監査。ただし探索方式でchanceサンプルの消費順や物理盤面/実時間の空白は異なる。同じseedは同じ物理履歴を意味しない。
各ゲームをfsync JSONL、result.json/hashへ保存し、完了済みは検証してskip。中断は途中盤面からではなく新attemptで最初から再実行。旧attemptは保持する。再開は保存した設定・Pythonソースhash・exe/Assembly hashが一致する場合のみ。自然GO以外は自然GO得点統計から除外。

## 3. 固定盤面比較

正式結果 `fixed_quiet/analysis.json`。各条件2回、同seed8191。最初のfixed/は他のネイティブ回帰テストと一部重なったため速度比較に採用せず保持。正式測定中には別の検証を同時実行していない。探索統計は両repeat一致。別日の8-T速度との直接比較はしない。

|盤面|方式|選択x|判断ms 平均±SD|実反復|到達深さ|root候補|物理tick|非root訪問済edge|同edge再訪|探索内GOサンプル|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|dense_safe_fixture|legacy|0.5|3916.74 ± 22.51|128|4|5|22216|95|12|56|
|dense_safe_fixture|grid9|0.625|3962.69 ± 59.72|128|4|9|22568|89|0|62|
|dense_safe_fixture|widening|0.625|4093.27 ± 50.42|128|4|8|22746|91|3|62|
|early_fixture|legacy|0.25|919.13 ± 26.20|128|4|5|27434|99|7|0|
|early_fixture|grid9|0.25|914.29 ± 30.49|128|4|9|27666|85|0|0|
|early_fixture|widening|0.75|950.77 ± 13.77|128|4|8|27988|88|0|0|
|mid_fixture|legacy|0.25|2733.88 ± 63.78|128|4|5|26729|90|13|0|
|mid_fixture|grid9|0.5|2803.51 ± 114.77|128|4|9|27194|87|0|0|
|mid_fixture|widening|0.0|2789.86 ± 55.50|128|4|8|26949|87|3|0|

全3盤面で128回wideningはroot3候補を追加（128回時点のroot8候補）。今回の非root追加は0。条件を満たした非rootでも追加できる既存実装は維持したが、常に追加されるという意味ではない。閾値を勝手に下げていない。

|盤面|root座標（初期5→追加順）|対応訪問数|
|---|---|---|
|dense_safe_fixture|[0.0, 0.25, 0.5, 0.75, 1.0, 0.875, 0.125, 0.625]|[15, 10, 21, 24, 21, 1, 11, 25]|
|early_fixture|[0.0, 0.25, 0.5, 0.75, 1.0, 0.875, 0.125, 0.625]|[16, 16, 16, 16, 16, 16, 16, 16]|
|mid_fixture|[0.0, 0.25, 0.5, 0.75, 1.0, 0.875, 0.125, 0.625]|[18, 16, 15, 16, 14, 15, 17, 17]|

密集では.875/.125/.625を追加し、訪問1/11/25（再訪0/10/24）。.875は最初のGO/不成功評価後に安全候補より除外され、再訪が少ないことを単なる未探索バグとしない。追加位置.625を最終選択。非root同一edge再訪は固定5=12、固定9=0、widening=3。候補増加は深い統計蓄積を必ず改善しない。密集wideningは固定5比時間+約4.5%、tick+約2.4%。GOサンプル数は探索経路の結果で、実ゲームGO見逃し率ではない。
OS RSS sampled peakは正式診断processで約576〜578MiB。各方式別の常駐メモリではなく、複数の検索・ログ保持・破棄待ちを含む。Unity sampled peakもJSONへ保存。

## 4. 観測専用イベント

`SuikaEpisodeEvents` はゲームオブジェクト/Collider/Rigidbody/RNGを操作しない純粋なカウンタと履歴。既定OFF、worker起動 `--suika-events 1` でON。新比較CLIはON、既存run_parallel呼び出しは引数省略でOFF。
既存FruitEvolutionの `Simulation==null` 内のScoreManager.RecordMergeだけを観測する。予測Sceneの合体は実ゲームのcounterへ入らない。元のFruitEvolutionの合体処理自体は今回変更していない。ScoreManager.RecordDroppedFruitで実落下回数を記録し、ResetScoreで履歴を初期化する。
type9同士→type10生成は既存55点、type10同士→消滅は既存0点のまま。RecordMergeは既存の加点より直前に呼ばれるため、イベント得点は同じevolutionScoresによる加点後の値を読み取り計算するだけ。実際の加点は既存処理だけが行う。
保存イベント：watermelon_created、first_watermelon、second_watermelon、two_watermelons_present、watermelon_pair_disappeared、double_watermelon。第2個生成は累積生成2個目、同時存在は現存数が2未満→2以上、ダブル成功はtype10同士の消滅1回、と区別する。
各イベントにepisode内event_id、score、drop_count、fixed_time、累積生成数、現存数、ダブル回数。snapshotはsource=actual_game、version=step8u-events-v1、known=true。disabled/旧ログはunknownでありfalse成功失敗に置き換えない。
UDPのepisode_eventsは累積履歴で、再送/観測重複はevent_id+episodeで区別する。Pythonは履歴prefixの不変性、単調時刻/手数/score、生成/消滅カウンタ、実盤面のスイカ数との一致を監査し、各snapshotを合算して二重計上しない。各ゲームの最終得点・最大果物・自然GOは既存episode_endと結合。
実衝突テストはテスト専用local PhysicsScene2Dで本物のFruitEvolution（Simulation=null）を動かし、4メロン→2スイカ→ダブル消滅を再現。記録OFF/ONで得点110と各観測点の種類/位置/速度/回転/角速度のtraceが完全一致、7イベント/ダブル1。GOテストではなく、同じ初期条件の短い衝突列の一致。長時間の自然GO全履歴のON/OFF一致までは未確認。

## 5. テスト・互換性

Python全体255テスト合格。新しい10テストにイベント欠損/捏造/score/実盤面不整合拒否、任意起動設定、実double fixture、単一差分profile、中断再試行/skipを含む。
Unity既存MCTS861/rules84/path26/frames58、計1029チェック合格。新規実衝突ON/OFFテスト合格。新Step8U Windows Playerビルド成功。初回import時の一時的な型未検出ログ後、最終コンパイルとBuild成功し、実Playerの全テストで新クラスを実行確認。headlessのshader非対応警告は既存の描画省略によるもの。
従来32の全3固定盤面で、旧8-Tと全反復physics指標/state_digest/木統計/選択位置が一致。旧Step6/Step8T Player・互換ソースの411ファイルhash不変。保護ガードはStep6に加えて既存Step8Tも拒否し、新出力はBuilds/Step8U。旧比較フォルダは読み取りのみ。
新比較CLIの8手×3方式、同game seed761000：全て67点/5合体/正常落下8回。座標、得点/報酬、公開果物prefix、実反復128、物理tick、イベントdrop_count=8を監査。3件ともstep_limitで自然GO統計から除外。GO正例0なので見逃し性能は未評価。実スイカ生成は0なので、doubleの実例は上記ネイティブ衝突試験。実ゲーム平均判断msはlegacy1331.50/grid91326.03/widening1354.46、各総探索10.652/10.608/10.836秒。
同じスモークの--resumeで全3件skip、新しいUnity/attemptの作成なし。旧8-Sは再開していない。Viewer/音声/4並列のGUI再検証は未実施、既存Python・ネイティブテストは維持。

## 6. 将来の学習ログ

盤面種類/位置/速度/回転/接触/物理metadata、保持/公開NEXT、選択位置、候補別訪問/評価/GO、探索設定/実反復/時間、game/search seed、環境hash/rules version、実step/間隔報酬、自然GO/最終得点は既存JSONLとrun/environment metadataにある。新たに実スイカ/ダブル履歴を追加した。
不足・注意：旧ログのdoubleは復元不能。候補訪問分布は独立した実測教師ではない。各探索経路の完全な終端盤面が全て保存されるわけではない。イベント瞬間の完全な盤面・親子fruit IDは今回未保存で、近傍transitionの盤面とは時刻が異なる。solver接触cacheはJSONでは再現不能。
将来形式は既存のrun/environment/episode/transitionを維持し、episode_id/event_idでactual_eventsを対応。状態時点scoreと自然GO最終scoreから将来追加得点を作り、未選択候補に実測教師を付けない。探索統計は別のpolicy教師、実doubleは別の補助ラベル。snapshot時刻と意思決定受理時刻を混同しない。episode/seed/果物系列単位でTrain/Validation/Testを分割し、環境・モデル・入力schema・収集方針を固定する。今回は学習していない。

## 7. ユーザーの9ゲーム予備比較

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\placement_pilot_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_placement_mcts.py --profiles legacy grid9 widening --games 3 --seed 761100 --search-seed 8191 --iterations 128 --depth 4 --max-steps 3000 --base-port 39700 --output $out
```

ゲームseed761100/761101/761102、合計9ゲーム。新Step8Uを既定使用、逐次1ゲーム。同期MCTSなので画面停止は従来どおりで、録画/リアルタイム改善ではない。このコマンドはCodexでは実行していない。

再開（同じ$out、別PowerShellでは保存先を入力）：

```powershell
$out = Read-Host "再開するplacement_pilotのフォルダ（outputs\...）"
.\.venv\Scripts\python.exe .\compare_placement_mcts.py --resume --output $out
```

集計のみ（新しいreports番号へ保存。元ログは上書きしない）：

```powershell
.\.venv\Scripts\python.exe .\compare_placement_mcts.py --analyze-only --output $out
```

reports/<最新番号>/comparison.json、games.csv、pairs.csv、comparisons.csv、summary.csvに得点・自然GO・判断時間・ペア差/95%CI。actual_events.json/csvに各ゲームの実スイカ累積数/ダブル数と履歴。JSONの元planningに全候補訪問/追加履歴。中断ゲームは自然GO扱いしない。3seedは予備比較であり有意な高得点化の保証ではない。

## 8. 変更ファイル・関数・行番号

|ファイル|主要な変更関数/行|
|---|---|
|Unity/Assets/Scenes/Script/SuikaEpisodeEvents.cs|public void Reset:16 / void Created:18 / public void Drop:24 / public void Merge:25 / public Snapshot Read:29|
|Unity/Assets/Scenes/Script/ScoreManager.cs|public void RecordDroppedFruit:15 / public void RecordMerge:16 / private void Awake:26 / public void ResetScore:109|
|Unity/Assets/Scenes/Script/UDPStateProtocol.cs|observation.episode_events:100 / public SuikaEpisodeEvents.Snapshot:216|
|Unity/Assets/Scenes/Script/SuikaWorkerOptions.cs|EventsEnabled:13 / case "--suika-events":35|
|Unity/Assets/Scenes/Script/SuikaEpisodeEventProbe.cs|IEnumerator Start:14|
|Unity/Assets/Editor/SuikaWorkerBuild.cs|public static void BuildPlacement:17 / public static bool IsProtectedDestination:18|
|Python/src/suika_ai/parallel_play.py|def player_command:160 / def run_parallel:189|
|Python/episode_events.py|def audit_events:2|
|Python/compare_placement_mcts.py|def summary:11 / def run:22 / def main:44|
|Python/measure_placement_mcts.py|def summarize:11 / def main:24|
|Python/tests/test_episode_events.py|class EventTests:6 / def test_interrupted_retry:42|

docs/DEVELOPMENT_LOG.mdへ結果追記。ソース以外に新規C#の.metaはUnityが生成。Scene/Prefab/物理設定/ルール/出現確率/既存モデルは今回変更していない。

## 9. 採否と次の課題

新方式は比較用のまま。固定5より有望な位置を選べることと実最終得点の改善は別で、今回の固定盤面/8手では証明していない。まず9ゲームで得点/GO/時間/スイカイベントを確認し、その後にseed数や同時間予算を増やす。128回で非root wideningが発生せず、深いedge再訪が増えていないことは重要な制約。直ちに閾値やrolloutを同時変更せず、得点比較で候補配置の効果を分離する。GO/接触予測の既知誤差とUDP間の実tick差は今回改善しておらず、探索内GO数だけで実安全性を評価しない。
