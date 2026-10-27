# STEP 8-AE：同期MCTSの無人収集（2026-10-27）

## 実装と境界

就寝中の収集はまだ開始していない。短時間テストのみ実施。従来のMCTS、importance/adaptive/time、ABのScene同期解放と要求ID／再送抑制を維持した。

新Player：Unity/Builds/Step8AE/SuikaGameAI.exe（Unity2022.3.21f1）。旧Step8AB_02ほかのPlayer、Scene、MctsPlanner、SuikaPhysicsSimulator、PredictionLifecycleの保護対象24ファイルはSHA256不変。GO0.83、rules_version=step8e-all-fruit-go-v2、固定5候補、25tick、chance/index/legacy expansion/random rollout。学習済みモデルもTestデータも変更していない。develop、commit/pushなし。

既存run_parallelの拡張モード複数ゲーム制限を外すのではなく、2つの独立枠それぞれで games=1/episodes=1 を使用する。終了した枠だけ次ゲームを開始し、設定・seedはゲーム開始時に固定。Unityをゲームごとに再起動するため、ゲームをまたぐSceneや乱数の残留も避ける。frame分割や新しい探索法は追加しない。

mcts_collection_budget=trueを明示した場合だけ、拡張探索の上限240秒を許す。通常の拡張モードは従来の120秒のまま。収集専用設定はfixed・深さ2〜16・自動深さOFF・widening OFFに限定。最大32,768回、安定判定による早期終了なし。指定反復完了または時間上限で終了する。

停止は反復境界。最後の1反復と集計により超過し得る。時間を厳密に240.000秒で打ち切るものではない。time_overrun_ms、stop_reason、actual_iterations、time_limit_reachedを保存。深い1反復が長い場合、超過も長くなり得る。

## タイムアウト

通信720秒は collect_worker -> env.plan_step(settings,timeout=720) -> UnityEnv.step の1手の待機deadline。先頭状態の受信、同期探索、横移動、落下、25tickの結果応答を含む。探索そのものの時間制御はUnity側240秒。time modeではなくfixed modeなので240秒を使い切る目的ではない。

起動待ちは30秒、resetは5秒、metadata get_environmentは5秒、最終状態受信は3秒の既存設定を維持。720秒をこれらへ一律に適用していない。ABのmetadata要求ID照合・排他・長い探索の再送backoffを維持し、探索完了応答の後に必要なmetadataを取得する。新Playerのcollection_budget_supported/time_limit能力を初期状態で検証してから実行する。

## プロファイル

Python/configs/overnight_mcts_profiles.json を --profiles で指定・編集できる。開始時にcollection.jsonへ内容を固定し、再開時は保存済み内容を使う。

|深さ|探索回数|ゲーム投入割合|
|---|---|---|
|4|1,024 / 8,192|各10%|
|6|2,048 / 16,384|各10%|
|8|4,096 / 32,768|各10%|
|10|8,192 / 16,384|各7.5%|
|12|8,192 / 32,768|各7.5%|
|14|16,384|5%|
|16|32,768|5%|

グループ60/30/10%の確率抽出であり、完了ゲーム数やCPU時間をこの割合にそろえるものではない。深いゲームが長いため、8時間後の完了データでは深い条件が少なくなる可能性がある。重みを最適と主張していない。

ゲームseed=base+job index、探索seedはschedule seedとjob indexから別のRandomで生成。プロファイル抽出の乱数も実ゲームの乱数へ渡さない。job.json、collection.json、各run.jsonに保存する。同じseed・条件の再指定は可能だが、通信間の物理tick揺れまで含めた実軌跡のビット一致は保証しない。別収集で同seedを再利用した場合も、学習時に同じseedグループへまとめる必要がある。

## 運転時間・中断・復旧

標準 --hours 8 --shutdown boundary：8時間で新規投入を停止。実行中の手は結果が返るまで待ち、保存してから次の操作を開始せず終了する。途中ゲームはreason=stopped、truncated=true、final_score=null、valid_for_return_learning=false。自然GO教師として使わない。8時間ぴったりの強制終了ではなく、通常は残りの手の探索時間、最悪では720秒の待機deadline＋後処理分だけ延びる。

--shutdown drain：8時間で新規投入だけ停止し、現在のゲームは自然GO／手数上限／エラーまで続ける。8時間は終了時刻ではなくなる。深い設定では大幅に延び得る。自然GO教師を優先するなら選択肢だが、標準ではboundary。

Ctrl+Cも新規操作を止め、未完了の1手を待って保存する。--resumeは保存済み条件と残り運転予算を使用する。停止中の時間は運転時間に加えない。CLIの追加条件で保存済み設定を上書きしない。8時間を消化済みなら再開しても新規ゲームは開始しない。追加8時間は新規出力で開始する。

完了済みattemptは再実行せず、エラー／正常な途中終了も保存して次jobへ進む。ゲーム終了記録があるのに結果JSONだけない場合は原ログから復旧する。完全に途中のattemptは新しいattemptへ保存して同じjob設定でやり直す。物理状態から途中再開する機能ではない。旧attemptの原ログは残す。最終集計はjob単位で最新の確定結果だけを数える。

出力フォルダは新規作成専用、collector.lockで同一フォルダの二重運転を拒否。再開時にはexeだけでなくAssembly-CSharp.dll、Scene／asset／UnityPlayer.dll等のSHA256を照合。連続3エラーで新規投入を止める。通常のエラーでは所有Playerを終了する。Pythonを強制killした場合にUnityが残ることはあり、その場合は同じポートを使用できず安全にエラー停止する。無関係なPlayerを自動killしない。

## 保存データと学習用途

- collection.json：全プロファイル、割合、seed方針、時間、Playerのファイルhash、環境版。
- runtime.json：累積運転秒、現在job、期限消化。collector_events.jsonl：開始・終了・中断・回路遮断の履歴。
- resources.jsonl：約5秒間隔のPID別Windows Private Bytes／Working Set。取得不能はnull。
- jobs/job_XXXXXX/job.json：ゲーム・探索seed、固定した探索設定。
- attempt_XXX/run.json / metadata/game_00.json / game_00.jsonl / game_00_player.log：既存の実通信保存を再利用。各JSONL行flush+fsync。
- observed_before：通信時の操作前状態。decision_source＋info.planning.source_fruits：探索受付時点の盤面・公開保持果物／NEXT。移動前の意思決定状態であり、移動後の落下直前スナップショットとは区別する。
- transition.state：実際の選択操作後25tickの状態。reward、between_steps_reward、score_before、score_at_drop等も元ログに保持。未選択候補は教師化しない。
- decisions.jsonl：選択X／実適用X、候補訪問数・平均点・ばらつき・GOサンプル、深さ、指定／実反復、時間／超過、終了理由、深さ別統計、物理tick、Scene／メモリ。MCTSのcompact reportを再利用し、大量の全反復traceを強制保存しない。
- actual_events.jsonl：source=actual_gameのイベントをevent IDで重複除去し、episode・drop_countから原ログの前後状態へたどれるよう保存。
- attempt_XXX_result.json：自然GO、return教師として有効か、最終得点、落下数、環境ID、Player hash、設定、探索seed、実時間、エラー。
- collection_summary.json / games.csv：完了件数、自然GO、有効件数、最終得点、平均／最高、操作回数、設定／判断時間／イベント、seed重複。未確定attempt一覧も別記する。

自然GOで得点保存則・受理・metadata・座標・イベント監査を通過したものだけをvalid_for_return_learning=trueにする。低得点ゲームも捨てない。探索の指定値ではなく実際の反復／時間／深さ／終了理由と方策設定を保持し、後の選別・重み付けを可能にする。収集時には学習・追加報酬・価値モデル更新を行わない。

## 特殊イベント

既存のScoreManager/FruitEvolution観測呼出に生成位置を追加。カウンタ・種類・時刻・得点・drop_countは既存v1互換。location.version=step8ae-location-v1、position_known/collider_knownで欠損を表す。Collider既知時の位置は生成直後のCollider.bounds.center、半幅／半高も保存。Collider不明時は生成座標のみで距離やcornerを推測補完しない。

壁／床は保存metadataのboundary AABBから読み、スイカAABBとの符号付き隙間を別途計算。実Collider曲面の最短距離や接触判定ではない。cornerの初期分析ラベルは「左右いずれかの隙間≤半幅、かつ床隙間≤半高」。閾値と生値を保存し、後で定義を変えられる。これはゲームの合体・GO・得点にもMCTSの評価にも使わない。

スイカ生成、first/second、2個共存、pair消滅、doubleイベントは引き続き実ゲームだけから記録する。MCTS内部Simulationは呼出対象外。イベントON/OFFの物理・得点一致を実際のFruitEvolution callbackで検証した。自然プレイでのスイカ／角／ダブル到達テストは今回実施していない。

## 短時間検証

- Python295テスト成功。上限のopt-in、weightedスケジュール、seed再現、2枠補充、期限停止、drain、エラー保存、完了記録から復旧、重複再実行防止、720秒deadline等。
- Unity既存1,029チェック（MCTS861/rules84/path26/frames58）成功。
- イベントON/OFF：物理状態・得点110点・7イベント一致、2個生成→共存→double消滅を確認。
- 旧Step8AB_02との32回／深さ4の固定盤面3回：選択X・全node・物理更新数一致、元盤面不変。

|実通信テスト|並列|保存手数|結果|
|---|---:|---:|---|
|深さ4/6、2秒上限|2|計6|全手成功、各判断2.005〜2.018秒、全体約12.47秒|
|深さ16、32回、上限設定240秒|2|計6|全手32回完了、各判断1.323〜1.517秒、全体約8.45秒|
|10.8秒運転期限、2秒上限|2|計8|両ゲームstopped、最終得点null、エラー0、保存・終了は約14.36秒|

全20手でprediction_scenes=0、prediction_pending_unloads=0。期限消化済みフォルダの実再開では新規Player／ゲーム投入0、二重計上0。

固定中盤の深さ16／32回を3回反復し、判断2.291/2.261/2.247秒。Unity確保量は約42.35/42.40/42.49MiB、Private約182.52/182.54/182.54MiB。診断が保持するroot1Scene以外の滞留なし、root解放後0、pending0。短時間の横ばいであり、32,768回・一晩の上限メモリを保証しない。

32,768回設定はUnityで受理。固定中盤で2秒上限により125/126回で停止、時間2.019/2.014秒（超過約19/14ms）。240,000ms上限値もUnity reportで確認したが、実時間240秒の探索は実行していない。

720秒は模擬時計で600秒後応答の受理、720秒無応答時のtimeout／pending維持と再送抑制を確認。実通信で720秒待つ試験はしていない。

## 推奨と収集効率

並列はまず2。深さ16の短い実通信では各Player Private約168〜184MiB、合計約350MiBだった。最大反復のピークや終盤では増える可能性があり、resources.jsonlを参照する。4並列へは拡張していない。

短い32回／深さ16なら2枠合計約0.71手/秒だったが、これは序盤・少数反復の値。実際の1,024〜32,768回設定のゲーム完了数へ外挿しない。仮に200手すべてが240秒なら判断時間だけで約13.3時間／ゲーム。8時間boundaryでは深いゲームが未完了となる可能性が高い。完了教師を増やすには浅い設定の割合を増やすかdrainを検討するが、今回の比率を最適と断定しない。成功例／失敗例の蓄積と、完了した自然GOデータ量を実運転後に確認して次を決める。

## 変更箇所

- Python/collect_overnight_mcts.py：CLI。
- Python/src/suika_ai/overnight_collection.py：settings(21)、choose_job(25)、audit_attempt(67)、run_job(114)、summarize(122)、collect(135)。
- Python/configs/overnight_mcts_profiles.json：12設定。
- Python/src/suika_ai/parallel_play.py：新Player能力確認(96)、external_stop連携(190/239)。既存引数は後方互換。
- Python/src/suika_ai/unity_env.py：collection opt-in検証(455〜477)。step自体の通信処理は不変。
- Unity/Assets/Scenes/Script/StepPlanner.cs：収集フラグ(34)。
- MctsAdaptiveControl.cs：収集専用240秒／深さ上限検証(15/23)。
- SuikaEpisodeEvents.cs：観測Location(11/15)。ScoreManager.cs:15/16、FruitEvolution.cs:82/128、PlayerController.cs:169：観測値の受け渡しだけ。
- UDPTrainingMetadata.cs:61：新Player対応能力。SuikaWorkerBuild.cs:26：別フォルダビルド。
- Python/tests/test_overnight_collection.py：10テスト。物理・UCT・rollout・報酬・重要性制御・Scene解放の実装は不変。

## 就寝前コマンド

PCの自動スリープで実行が止まらないよう、運転中はスリープしない設定にしておく。ツールはWindowsの電源設定を変更しない。

```powershell
Set-Location C:\SuikaGameAI\Python
$tag = (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
$out = "outputs\overnight_" + $tag
$gameSeed = Get-Random -Minimum 10000000 -Maximum 2000000000
Write-Host "保存先: $out / ゲームseed開始: $gameSeed"
.\.venv\Scripts\python.exe .\collect_overnight_mcts.py `
    --exe ..\Unity\Builds\Step8AE\SuikaGameAI.exe `
    --output $out `
    --workers 2 `
    --hours 8 `
    --shutdown boundary `
    --think-seconds 240 `
    --communication-timeout 720 `
    --profiles .\configs\overnight_mcts_profiles.json `
    --game-seed $gameSeed `
    --schedule-seed 20261027 `
    --max-jobs 1000 `
    --max-steps 100000 `
    --base-port 40700
```

同じPowerShellで再開：
```powershell
.\.venv\Scripts\python.exe .\collect_overnight_mcts.py --output $out --resume
```
別PowerShellなら$outに元の保存先を指定する。最新nightフォルダを選ぶ場合は次の通りだが、表示パスが対象か確認する：
```powershell
Set-Location C:\SuikaGameAI\Python
$out = (Get-ChildItem .\outputs -Directory -Filter "overnight_*" | Sort-Object CreationTime -Descending | Select-Object -First 1).FullName
Write-Host $out
.\.venv\Scripts\python.exe .\collect_overnight_mcts.py --output $out --resume
```

完了・途中結果の集計（Playerは起動しない）：
```powershell
.\.venv\Scripts\python.exe .\collect_overnight_mcts.py --output $out --summary
Import-Csv (Join-Path $out "games.csv") | Format-Table job,game_seed,depth,requested_iterations,final_score,natural_go,valid_for_return_learning,steps
```

ビルドが更新したTMP fallback fontの動的glyph/atlasキャッシュは、他フィールドに差がないことを機械的に確認したうえでそのキャッシュ差分のみ除去。ゲームasset設定は変更していない。
