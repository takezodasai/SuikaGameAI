# 代替候補B：独立盤面検証・実験用AI（途中停止時点）

2026-11-02。ユーザーの「区切りで終了」に従い、進行中の対応ペアまでで停止。予定32分岐試行のうち18試行を実施、自然GO17・既存Playerの技術失敗1。残り14は未実行。新モデル学習、commit/pushなし。全32試行が完了した報告ではない。

出力: `Python/outputs/alternative_candidate_01`。集計: `analysis_pause/analysis.json`。生ログ: `branch_unseen_08/tasks`。

## Bの事前固定規則と実装

既存 `staged_action_experiment.choose_alternative` を基準とする。

1. Aは従来MCTSの最終推奨。通常は即時非GOの有効候補から訪問数最大、同数なら平均が0.001超高い候補。全GO時の従来fallbackは維持。
2. BはAと異なるindex、訪問数>0、drop_success=true、immediate_go=falseの候補に限定。
3. 平均報酬最大を選ぶ。同値なら訪問数最大、さらに同値なら最小index。Bのmean比較に新しいepsilonや重みを導入しない。
4. Bがない、またはBがAと同じ座標なら、実験用AIはAへfallback。全GOで新方式が無条件に危険なBを選ぶ処理ではない。
5. 初手比較で有効な別座標がない盤面はquarantineし、好都合な別盤面へ差し替えない。今回の8盤面にはすべて有効Bが存在した。

Bは「A以外の平均最大」であり、常に全体平均順位2位とは限らない。通常ゲームBでは110有効選択中109が平均順位2位、1が1位だった。最後の1判断は全候補即時GOで従来fallbackに戻った。

新規Player: `Unity/Builds/AlternativeCandidate_01/SuikaGameAI.exe`。新規opt-in controller `SuikaAlternativeActionLab` は旧Labの進行処理を継承する独立実装。既存MCTS/旧Lab/物理/ゲームルールは変更していない。各判断で元のMCTSをそのまま実行し、その後の実行座標だけを `legacy` / `alternative` で切り替える。

両モードとも同期128反復、深さ4、固定5候補、random rollout、既存UCT/chance/報酬、post-drop25tick。新規選択処理は乱数を消費せず、探索木・統計・元の推奨を変更しない。

ログの `planning.selected_x` は元MCTSのA、`final_selection` にA/B/実際の選択/fallback理由、`command.x` に実行指示を保存。release/actionで実際の落下を追跡する。将来の学習でAを実行行動と誤認しない。

## 新規8元ゲームの選定・独立性

元収集は `overnight_diverse_20261029_012253_922ae62c`。元seed昇順、生成前/後を交互に割り当てる既存規則。元ゲームの最終得点や今回の分岐結果の大小で選ばない。

dry-runで新規8群・予定32試行を確認。元seed、元初期8果物、スナップショットが過去分岐群と重複しないことを `independence_certificate.json` に保存。予約Test19のseed/初期系列も除外。これは分岐実験で未使用の群という意味であり、将来モデル学習時には元ゲームの既存学習利用履歴も合わせて分割監査する。

|root|元seed|初期スイカ|A座標/訪問/平均|B座標/訪問/平均|
|---|---:|---:|---|---|
|Job34 生成前|925294008|0|0 /32 /135.91|0.5 /32 /135.84|
|Job36 生成後|925294010|1|0 /73 /68.32|0.75 /18 /44.94|
|Job38 生成前|925294012|0|0.75 /33 /239.82|0 /28 /237.18|
|Job47 生成後|925294021|1|0.25 /28 /13.68|0 /27 /13.44|
|Job51 生成前|925294025|0|0.25 /78 /205.23|0 /17 /182.24|
|Job53 生成後|925294027|1|0.75 /29 /15.52|0.25 /26 /13.85|
|Job56 生成前|925294030|0|0.5 /37 /183.32|0.75 /35 /182.91|
|Job57 生成後|925294031|1|0.75 /30 /17.90|0.25 /26 /15.73|

近似cold再構成であり、元ゲームの内部接触状態を厳密復元した反実仮想ではない。8盤面の短い再実行で全記録初期状態/RNG/tick一致を確認し、未来seed変更が初回探索統計を変えないことも診断した。未来系列は行動選択AIへ渡していない。

## 初手だけ変更：自然GO追加得点

①=2026110401、②=2026110402。2手目以降はすべて旧Player `StagedAction_02` の従来MCTS128/4。A/B実行順は盤面/未来ごとに交互。

|root|① A|① B|① B-A|① 落下数差 B-A|② A|② B|② B-A|
|---|---:|---:|---:|---:|---:|---:|---:|
|Job34 前|869|716|-153|-12|958|787|-171|
|Job36 後|752|673|-79|-10|未実行|未実行|—|
|Job38 前|496|840|+344|+34|未実行|未実行|—|
|Job47 後|1083|748|-335|-18|未実行|未実行|—|
|Job51 前|1202|技術失敗|—|—|未実行|未実行|—|
|Job53 後|1066|733|-333|-24|未実行|未実行|—|
|Job56 前|734|786|+52|+8|未実行|未実行|—|
|Job57 後|494|793|+299|+41|未実行|未実行|—|

- 第1未来の有効7盤面ではA4勝/B3勝、平均A784.86/B755.57、差-29.29点。ただし8群中1群はBの技術失敗で欠損。この完了部分を全8群の期待効果とはしない。
- 2未来とも完了したのはJob34だけ。平均差-162、未来間の標本SD12.73点、平均落下数差-10.5。2未来での順位反転なし。他7盤面の未来による順位反転はまだ評価できない。
- 有効8対応ペアは独立8盤面ではなく、独立7盤面（Job34に2未来）。全8元群で試行したが、Job51の自然GO比較は未成立。
- 主集計を両未来完了rootに限定するとn=1なので、bootstrap CIを出す根拠が不足する。計算コードはroot単位bootstrapを実装しているが、今回はnullとする。状態/判断/未来を独立ゲームとして水増ししない。
- 各試行の時間・落下数・初期一致・共通果物列は `analysis_pause/branch_summary.json` のpairsと生resultに保存。初回ペア404.125秒、単純な全main見積6466秒。全体上限120分を固定したまま進め、今回は上限前にユーザー指定で停止した。

自然GO17試行で新規スイカ生成9件（全て初期0の生成前盤面で最初の1個）。生成後の自然GO8試行では新規生成0。新規2個目・2個共存・ダブル達成はいずれも0。初期から置かれた1個は新規成功に数えない。失敗試行の観測途中イベントは別扱い。

## 既存Playerの技術失敗

Job51・未来①・初手Bは96落下・観測追加1220点で、旧Playerの `SuikaPhysicsSimulator.Copy` が `Rigidbody clone state mismatch: cherry(Clone)` を検出して終了した。自然GOではなく、1220を最終returnやB勝ちに使わない。元エラーログ・attempt_000を保持し、再実行・別seedへの置換なし。

表示されたmass/inertia/position/velocity/rotation/angularは同じに見えるが、検査には未表示のgravity/drag/constraints等もあり、rotation表示も丸めを含む。原因を特定したとはしない。物理設定、コピー値、検査閾値を緩めて通す変更は行っていない。新しいBアダプターを使っていない旧baseline続行中のエラーであり、少なくとも新アダプターの実行による例外ではない。

収集側に明示的な `--quarantine-trial-errors` を追加。native endが保存された技術失敗を無効試行としてcommitできるが、自然GOとすることは禁止。既定は引き続きfail-fast。再開では失敗attemptを繰り返さず、完了済み試行も再利用した。失敗が行動経路に依存する可能性があり、完了部分の平均が無作為欠損下の推定だとも主張しない。

## 通常開始から毎手B：別実験

開発seed904732101、探索seed8191、新Playerで同じ設定。通常開始の比較は初手分岐に混ぜない。

|方式|終了|得点|落下数|実行時間|MCTS平均判断|MCTS p95判断|
|---|---|---:|---:|---:|---:|---:|
|毎手A|600秒上限・打切り|1946（観測値、最終値不明）|199|602.13秒|2.209秒|約2.86秒|
|毎手B|自然GO|767|111|360.05秒|2.494秒|約3.49秒|

開始公開状態と共通113果物の列は一致。MCTS乱数と実果物乱数は分離。異なる行動後の物理状態は当然異なる。Aの1946を自然GO最終得点にはせず、正式な自然GO得点差は未算出。

Bは110判断で有効代替を選び、1判断は全即時GOで元の生存fallback。座標0/0.25/0.5/0.75/1を11/28/22/35/15回使用し、端固定ではない。両方式とも新規スイカ/共存/ダブル0。記録時点のretained/pending Scene最大0。判断msは元MCTSの測定値であり、完全なゲームwallには選択アダプター、進行、起動終了も含む。異なる盤面を通るため、この平均差をアダプター自体の計算コスト差とはしない。

この1seedでは毎手Bの高得点化を支持しない。一方で1seedだけで全般的な優劣を確定しない。`Q^(legacy)(s,B)` を初手だけ比較した結果は、毎手Bを選ぶ別方針の強さを意味しない。

## テスト・保存・停止

- Unity新規選択テスト10、既存rules127/MCTS861/path26、合計1024チェック成功。乱数非消費、非破壊、GO/失敗/未訪問除外、同点処理、fallbackを確認。
- 旧Playerと新Playerのlegacyモードを同じseedで3落下比較し、公開状態、操作/tick、初回を含む探索統計・経路の観測prefixが一致。長大な軌跡の完全一致を保証した検証ではない。
- Python全472テスト成功。8盤面指定、期限短縮、エラー隔離・再実行防止、停止要求/明示的resumeを追加検証。
- 既存389保護ファイルを照合。既存ファイルへの変更は `Python/branch_teacher_batch.py` の機能追加のみ。Core MCTS/物理/ゲーム規則/旧Playerは不変。元8ログ/fixturesと予約manifestもSHA照合済み。
- 実通信はヘッドレス。GUIオプションは用意したが、今回GUIプレイを検証したとはしない。
- 分岐データは有効8ペア、16行動例、独立7rootへ出力。Train4群/Validation3群、独立Test0。Job51は原ログと無効試行として保持。新モデルは学習していない。

停止時、実行中collectorは協調停止機能追加前のコードだったため、未着手の次ペア入口を一時的な制御マーカーでブロックした。現ペアは自然GOまで終了、次ペアにはtask_startもnative起動もない。マーカーは停止後 `operator_controls` へ移動して履歴保存し、タスクパスを再開可能に戻した。raw runtimeのFileExists停止記録は削除せず `pause_confirmation.json` でユーザー停止と区別する。これはnative物理エラー1件とは別の操作記録。

今後は `branch_teacher_batch.py pause --output <batch>` が現ペア終了後の協調停止を要求する。明示的な後日の `run --resume` は古い停止要求を無視する。今回は自動再開せず、稼働Player0を確認した。

## 変更の入口

- `Unity/Assets/Scenes/Script/AlternativeCandidateSelection.cs:11` 固定B選択。
- `Unity/Assets/Scenes/Script/SuikaAlternativeActionLab.cs:10` 独立した実進行controller。
- `Unity/Assets/Editor/SuikaAlternativeCandidateBuild.cs:6` 別フォルダbuild、既存出力拒否。
- `Python/alternative_mcts_experiment.py:29` 通常ゲーム・各判断の参照規則照合。
- `Python/branch_teacher_batch.py` 最大8群、指定未来seed、外側期限、無効試行隔離、停止・再開。
- `Python/analyze_alternative_validation.py:27` 完全2未来群/各未来群/通常ゲームの分離集計。
- `Python/tests/test_alternative_mcts.py` / `SuikaAlternativeCandidateTest.cs`。

## 判断と次回

常にBを選ぶ標準採用はしない。未知の第1未来では7群の平均差-29.29点、通常Bも767点で、有利さは再確認できていない。ただし＋344、＋299、＋52のケースはあり、A/Bの優劣が局面・未来で変わることも確認した。

残り評価が未完了なので、小型モデルの有効性まで結論しない。再開時は残りの事前固定条件を優先し、現データに合わせたB規則・閾値調整はしない。その上で差分学習を試す場合も「常にA」「常にB」を基準にし、今回見たrootは開発扱い、最終評価は別の未使用元seed群を事前確保する。既存の予約Test19は今回使わない。

実験用AIの利用例（今回は追加実行しない）:

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\alternative_play_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\alternative_mcts_experiment.py `
  --selector alternative --seed 904732101 --seconds 600 --max-drops 1000 --output $out
```

`--selector legacy` でAへ切り替える。必要なら `--view` で画面表示を指定できるがGUIは未検証。600秒に達すれば自然GO前でも打ち切りとして保存する。現在のバッチは元の計算予算が約24分残るが、14未実行ゲームが全て収まる保証はない。ユーザーの次の指示まで再開しない。
