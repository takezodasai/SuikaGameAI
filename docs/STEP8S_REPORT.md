# STEP 8-S：探索回数と実ゲーム得点の比較基盤（2026-10-24）

## 実装と採否

既存同期MCTSをそのまま使用し、32/64/128/256回・深さ4を比較する環境を用意した。標準の32回は変更しない。探索回数以外は固定5候補、random rollout、従来UCT/chance/reward、post25、GO比率0.83、環境rules `step8e-all-fruit-go-v2`。coverage/Open-loop/追加展開/shuffle/Coarse-to-Fine/common-chanceは全て無効の従来設定。Value Networkは使用しない。

Unity/Pythonの入力検査の上限が128だったため、受け付け上限だけ256へ拡張した。MctsPlannerの処理・ゲームルール・物理・Collider・確率・GO判定は変更していない。Player再ビルド成功。追加ライブラリの導入なし。develop維持、commit/pushなし。

## 固定盤面：3回ずつ計測

序盤0果物・中盤15果物・密集35果物。各条件の探索seedは8191。3回は同じ入力で再現性と計測ばらつきを調べるための反復であり、独立したゲームの強さのサンプルではない。探索回数の実行順を順転/逆転/巡回で変えた。

計測は固定盤面ロードと外側の基準root構築を除き、各判断の探索・各経路の状態構築/再生/解放要求を含む。Unityの破棄完了やGCの全コストを各探索に完全帰属できる計測ではない。

|盤面|探索回数|平均±標本SD ms|最小〜最大 ms|予測側実物理tick|選択x|異なる全行動系列|異なる2手系列|深さ4到達|探索内GO|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|early_fixture|32|186.15 ± 19.13|172.07〜207.93|7282|0.0|32|18|32|0|
|early_fixture|64|352.04 ± 28.07|328.99〜383.30|14030|0.25|61|21|64|0|
|early_fixture|128|670.83 ± 12.71|658.89〜684.19|27434|0.25|116|25|128|0|
|early_fixture|256|1381.69 ± 2.99|1378.23〜1383.53|55483|0.75|206|25|256|0|
|mid_fixture|32|566.80 ± 36.32|543.96〜608.68|6867|0.0|31|17|32|0|
|mid_fixture|64|1093.41 ± 15.13|1083.86〜1110.85|13633|0.25|60|22|64|0|
|mid_fixture|128|2146.60 ± 14.46|2131.68〜2160.55|26729|0.25|118|25|128|0|
|mid_fixture|256|4435.83 ± 169.35|4300.36〜4625.69|53700|0.25|217|25|256|0|
|dense_safe_fixture|32|828.14 ± 18.32|807.76〜843.26|5818|1.0|30|18|22|16|
|dense_safe_fixture|64|1638.37 ± 19.72|1617.65〜1656.91|11461|0.5|58|21|46|26|
|dense_safe_fixture|128|3215.70 ± 17.92|3204.52〜3236.37|22216|0.5|103|25|90|56|
|dense_safe_fixture|256|6618.15 ± 143.59|6532.66〜6783.93|45375|0.5|170|25|193|112|

全行動系列にはGOで途中終了した短い系列も含む。探索内GOはサンプルの終端件数であり、実ゲームのGO確率ではない。root訪問は以下のとおり。候補順0/.25/.5/.75/1。

|盤面|回数|root訪問数|
|---|---:|---|
|early_fixture|32|[7, 6, 6, 6, 7]|
|early_fixture|64|[13, 13, 12, 13, 13]|
|early_fixture|128|[25, 26, 25, 26, 26]|
|early_fixture|256|[51, 51, 51, 52, 51]|
|mid_fixture|32|[7, 7, 6, 6, 6]|
|mid_fixture|64|[13, 13, 12, 13, 13]|
|mid_fixture|128|[25, 28, 26, 25, 24]|
|mid_fixture|256|[52, 54, 51, 50, 49]|
|dense_safe_fixture|32|[5, 5, 7, 6, 9]|
|dense_safe_fixture|64|[11, 7, 18, 13, 15]|
|dense_safe_fixture|128|[19, 13, 35, 31, 30]|
|dense_safe_fixture|256|[28, 17, 82, 74, 55]|

密集盤面の時間倍率（32回比）は64回1.98倍、128回3.88倍、256回7.99倍。探索回数と物理計算はほぼ比例。選択位置や系列被覆は変わるが、これだけで高得点化とは判断しない。

プロセス全体のsampled RSSピークは608.97/612.60/610.23MiB。診断レポート保持・破棄待ちオブジェクトを含み、各条件単独の常駐メモリではない。各条件のUnity allocated sampled peak範囲とGC0回数は `Python/outputs/step8s_fixed_04/summary.json` に保存。各条件3回の経路・chance・得点・GO・tick・ノード統計が完全一致。32回は以前の8-R original-RNG controlと9件（3盤面×3反復）一致。Unity側ソースhash検査も合格。

## 短時間UDP試験

同ゲームseed758300・探索seed8191、1 Playerずつ4条件各8手。すべて手数上限終了であり、自然GO比較の有効件数は0。途中得点を最終得点として集計しない。

|探索回数|成功落下|8手時点得点|合体数|平均判断ms|判断p95 ms|判断時間合計 秒|ゲーム実時間 秒|予測側実tick合計|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|32|8|6|1|283.71|329.92|2.270|11.656|58665|
|64|8|26|5|519.09|638.15|4.153|10.125|113538|
|128|8|26|5|1071.55|1274.34|8.572|16.781|227555|
|256|8|26|5|2388.72|2856.39|19.110|25.047|464904|

全32操作で指定探索数・深さ・root訪問保存・実物理tick保存・trace再計算・選択/適用座標・得点/報酬・合体数の監査合格。各条件の公開果物列10個は `[2,0,1,0,2,2,3,3,0,0]` で一致。全条件で予測GO/実GOは各8件false。GO正例がなく見逃し率や過剰予測率の性能は未評価。

この8手の得点差は強さの証拠ではない。判断総時間はUnityの各判断elapsedの和（Stopwatch実時間）であり、OSのCPU使用時間ではない。ゲーム実時間は移動・物理・通信・待機等も含む。探索時間が増えてもゲーム実時間が単純に同じ倍率になるとは限らない。

## 果物列と乱数・比較の限界

`SuikaWorkerOptions` がゲームseedでUnityEngine.Random.InitStateし、`PlayerController.SpawnNextFruit` はUnityEngine.Random.Rangeで次の果物を選ぶ。MCTSは別のSystem.Random(mcts_seed)を使用し、従来のsource_unchanged監査はUnityEngine.Random.stateも検査する。探索回数の増加によって実ゲームの乱数を消費する設計にはしない。

各ゲームは新しい独立Playerで一度seed初期化し、途中で自動Resetを繰り返さない。条件間は公開果物列の共通prefixを照合し、不一致ペアを除外する。短時間試験と固定盤面で乱数保存を確認したが、今後の全自然GOゲームもログ監査して確認する。

同seedでも、落下位置・移動時間・同期探索による実時間停止・通信間の追加物理tick・GO終了時刻は異なる。果物列のprefixを合わせることは、盤面や経過tickまで同じにすることではない。今回はゲームの時間進行を固定する変更をしないため、実測の得点差にはこれら実行上の影響も含まれる。

## 実験ツールと保存

`compare_mcts_budget.py` は任意の2〜4条件を受け取り、同seedで条件を1ゲームずつ順に実行する。seedごとに開始条件を巡回させ、常に大きい設定が最後になる偏りを緩和する。

- `experiment_plan.json`：条件、全ゲームseed、探索seed、全ジョブ、固定設定、Player exe/Assembly-CSharp hash、手数上限、step timeout。
- `seed_<seed>/iterations_<n>/attempt_<nnn>/`：既存JSONL、run.json、metadata、Playerログ。過去attemptは保持。
- 各ジョブの `result.json`：監査済み結果と元ログhash。保存は同一フォルダ内の一時ファイルからrenameで公開し、保存中断で不完全な完了マーカーを残さない。既存結果への上書きは拒否。
- `reports/0000/` 等：ゲーム終了ごと・再集計ごとに新しい番号のスナップショット。最大番号が最新。
- `comparison.json`：全ゲーム、欠損/中断、条件別集計、全ペア比較、除外理由、勝敗、得点差、95%CI、判断/総計算時間倍率。
- `games.csv`：回数、深さ、両seed、得点、自然GO、終了理由、落下数、最大果物、合体、GO不一致、平均/p95判断、総判断時間、ゲーム実時間、予測物理tick。
- `summary.csv`：条件別有効件数・平均・中央値・最高最低。
- `pairs.csv`：seed別対応得点差・除外理由・時間倍率。
- `comparisons.csv`：条件ペアごとの勝敗・平均得点差・CI・時間倍率。

条件別平均はその条件単独で正常な自然GOゲーム、ペア差は両条件正常・環境/バイナリ/果物prefix一致のペアだけで計算する。平均値の母数を区別する。手数上限・停止・エラーは自然GOに数えない。3seedの予備比較や全6ペアの多重比較は探索的で、95%CIはゲームseedを単位とした10,000回paired bootstrap、手や状態を独立標本にしない。n<2はCIなし。3〜10ゲームのCIは精度が低い。

### 中断と再開

Ctrl+Cでは既存workerが実行中の操作を終了/タイムアウトまで待ってログをflushするため、即終了でない場合がある。既定の実験用step timeoutは120秒。タイムアウトを成功扱いせず、その試行のログを残して停止する。従来の一般run_parallelはstep_timeout未指定なら従来の待機動作を維持。

再開は**ゲーム単位**。完了マーカーとログhashを検証し完了ゲームをskip。不完全・停止ゲームは同じseedで新しいattemptへ最初から実行する。ゲーム途中の物理状態からの再開ではない。手数上限で正常に閉じたゲームは完了済みの除外データとして保持し、同じ実験で勝手に再実行しない。

設定・Player exe/Assemblyが変わった実験は再開を拒否。同じフォルダへの二重起動はOSファイルロックで拒否。ログ改変や完了ゲームの監査エラーは正常扱いしない。途中停止によるpendingは未開始/中断試行を区別して記録する。

## 実行コマンド

### A：最初に実行する予備比較（4条件×3seed＝12ゲーム）

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\budget_pilot_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_mcts_budget.py --budgets 32 64 128 256 --games 3 --seed 759300 --search-seed 8191 --max-steps 3000 --output $out
```

各条件を同じ759300〜759302で実行する。256回は密集1判断約6.6秒のため長時間になる。3000手は安全上限であり、到達したら自然GOとせず除外。結果を確認してから本比較を決める。

### B：任意2条件の10組比較（20ゲーム）

以下では32対64。`$first` と `$second` を64/128や128/256等へ変更する。

```powershell
Set-Location C:\SuikaGameAI\Python
$first = 32
$second = 64
$out = "outputs\budget_compare_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_mcts_budget.py --budgets $first $second --games 10 --seed 759400 --search-seed 8191 --max-steps 3000 --output $out
```

追加実験は新しい保存先で `--seed 759500` 等へ変え、以前とseedを重複させない。同じseedを再収集して独立ゲーム数を水増ししない。

### C：中断した実験の再開

A/Bと同じPowerShellなら `$out` がそのまま使える。

```powershell
Set-Location C:\SuikaGameAI\Python
.\.venv\Scripts\python.exe .\compare_mcts_budget.py --resume --output $out
```

別のPowerShellなら次を貼り付け、表示された入力欄に実験フォルダのフルパスを貼る。

```powershell
Set-Location C:\SuikaGameAI\Python
$out = Read-Host "再開する実験フォルダのフルパス"
.\.venv\Scripts\python.exe .\compare_mcts_budget.py --resume --output $out
```

集計だけやり直す場合（新しいreports番号へ保存）：

```powershell
.\.venv\Scripts\python.exe .\compare_mcts_budget.py --analyze-only --output $out
```

## テスト・変更箇所

- Python233件合格。今回の新規14テストで条件差が探索回数のみ、重複seed拒否、自然GOとtruncated、果物/環境不一致、ペア単位CI、改変検出、二重起動、中断後fresh attempt、完了skip、保存失敗時の完了マーカー非公開等を検証。
- Unity MCTS861、rules84、path26、frames58、計1029チェック合格。256回は固定9検索・UDP8手でも実数/訪問保存を検証。
- 実ログの再開テストは完了4ゲームを全てskipし、Player再起動0、新規reports/0005だけ作成。中断ジョブの再実行と保存中断は短時間自動テストで確認し、ゲーム途中を保存復元する機能は実装していない。
- 既存のSelected drop X検査を再利用し、予測/実落下がない場合のゼロ座標誤検出対策を維持。
- 初期の計測ランチャーは診断起動引数不足、続いて上限128で失敗。修正後の成功ログだけを上記測定に使用。集計のメモリfield名誤りは完了済み36検索を再実行せず修正・再集計した。失敗ログstep8s_fixed_01〜03も削除していない。
- 成功測定：Python/outputs/step8s_fixed_04、通信：step8s_smoke_01、ビルド：step8s_build_01、Unity回帰：step8s_native_01。

|ファイル|関数/行|変更|
|---|---|---|
|Unity/Assets/Scenes/Script/StepPlanner.cs|PlanningSettings.Validate / 62|回数上限128→256だけ|
|Python/src/suika_ai/unity_env.py|validate_planning_settings / 447|同じ上限の整合|
|Python/compare_mcts_ai.py|episode / 78〜79|32固定監査をexpected_settingsの回数で監査。既存32の監査内容は維持|
|Python/src/suika_ai/parallel_play.py|collect_worker 75/108、run_parallel 188/199/222/229|任意step_timeoutを追加。未指定の既存呼出しは従来動作|
|Python/compare_mcts_budget.py|settings 11、save 16、experiment_lock 32、audit_game 43、completed 67、pair_result 76、summarize 90、run 137、make_plan 157、main 170|4条件逐次比較・厳密監査・集計・保存再開|
|Python/measure_mcts_budget.py|rss 7、main 170|標準Windows APIによるRSS、固定盤面反復・再現性・旧32互換検証・保存ログだけの再集計|
|Python/tests/test_mcts_budget.py|BudgetComparisonTests|14テスト追加|
|Python/tests/test_mcts.py|test_bad_budget_or_depth / 11|無効上限129→257に更新|

上の行番号は本報告時点のもの。DEVELOPMENT_LOG/PLANも簡潔に追記。Viewerや学習済みモデル・既存データを変更しない。

## 次の判断

最初にコマンドAを実行し、最新reportsのcomparison.json/CSVを確認する。現時点では自然GO得点の測定は未実施なので、探索回数増加が本当に強さにつながるかは未判断。予備3seedで有望な2条件を選び、新seed10組比較へ進む。差とCIだけでなく、1判断時間とゲーム全体の所要時間、途中終了/GO見逃しも併せて判断する。標準32回・深さ4は維持する。
