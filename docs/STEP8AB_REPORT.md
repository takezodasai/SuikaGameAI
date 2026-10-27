# STEP 8-AB：予測Scene解放・長時間通信の修正（2026-10-26）

## 結論と検証範囲

再現した根本原因は、予測Sceneの非同期解放要求が生成速度に追い付かず滞留すること。回収不能な永久リークと断定するのは正確でない。予測を止め十分なフレームを与えると旧方式でも解放された。一方、探索を繰り返す運転ではScene/GameObject/Native側の使用量が増え、Scene生成と物理処理が遅くなる。

修正後は各反復の専用Sceneを返却前に同期解放する。毎回新しいPhysicsScene2Dを作る構造は維持し、pool化によるsolver内部状態の共有や、物理tickの省略は行わない。実ゲームの物理・GO・得点・果物出現・UCT・rollout・importance判定式を変更しない。

新Player：Unity/Builds/Step8AB_02/SuikaGameAI.exe。最初の計測試作Step8ABも残した。過去Player1214ファイルのSHA256不変。develop、commit/pushなし。旧Playerはソース修正だけでは直らないので新Playerを使う。

55手の自然進行、120秒探索2回、GUI3手まで合格した。最大予算importanceで自然GOまでの全編、数時間の連続運転、全盤面における安定性を保証したものではない。

## 根本原因の切り分け

旧DisposeはownedのSetActive(false)、PhysicsMaterial2DのDestroy、UnloadSceneAsyncのスケジュールだけで終了していた。GameObjectやPhysicsSceneの解放完了を確認しないまま次の反復を開始し、メインスレッドを同期探索が占有する。探索後の数フレームでも消化が間に合わず、次の判断へ残った。

同じ凍結中盤盤面・128回・深さ4・seed8191を10回、判断間に2フレームだけ挟んで計測。旧方式は診断フラグ -suikaLegacyPredictionCleanup で旧解放処理を再現し、探索コードと計測器を共通にした。このフラグは通常プレイに指定しない。

|方式/回数|保持予測Scene|GameObject|Unity確保量|Private Bytes|Working Set|判断ms|
|---|---:|---:|---:|---:|---:|---:|
|旧・1回目|129|約3170|約87MiB|221.8MiB|164.1MiB|2118|
|旧・10回目|962|約23300|約379MiB|559.9MiB|462.7MiB|2414|
|修正・1回目|1|75|約42.5MiB|184.3MiB|120.5MiB|2223|
|修正・10回目|1|70|約42.5MiB|186.9MiB|123.6MiB|2084|

修正後の1 Sceneは測定用に保持している固定root。rootを閉じると0。全1281 Sceneの生成/解放数が一致し、GameObjectは49へ戻った。旧方式ではroot閉鎖後8フレーム経っても894 Scene/21663 GameObjectが残り、明示GC後も変わらなかった。

別試験で旧方式に240フレームの待機を与えると、各32回探索後の解放待ち32が0へ減った。永久リークというより、運転中に増え続ける解放バックログであることを確認。

Scene生成時間（128回合計）は旧7.09→40.88ms、修正4.21→4.00ms。物理時間は旧1485→1686ms、修正1533→1472ms。1反復平均は旧16.5→18.9ms、修正17.4→16.3ms。冷却/OS負荷等の差もあるため、小さな速度差を一般的な高速化率とは扱わない。同じ盤面でも旧方式だけに蓄積と時間悪化が見られた点が切り分けの根拠。

## メモリ指標とGC

- managed_live：GC.GetTotalMemory(false)。GC前には回収可能なManagedオブジェクトも含む。
- managed_heap：Mono heap容量。
- unity_allocated：Unityが追跡する確保量。Nativeだけの値ではない。
- unity_reserved/unused_reserved：Unityの予約量/未使用予約量。確保量より大きくても即リークではない。
- working_set：Windowsで常駐しているページ。private_bytes：プロセスのPrivate Commit。GPUドライバ等を含むためUnity確保量と一致しない。

Unity内のSystem.Diagnostics.Processは今回0を返したため、WindowsのGetProcessMemoryInfoで実測する。取得不能時は-1を返し、0使用として扱わない。外部Python依存は増やしていない。

修正後の反復試験ではUnity確保約42～43MiB、予約約129MiBで横ばい。明示GCでManagedは約4.3→1.3MiBとなるが、Native Scene数は既に0。旧方式はManagedが約22→16MiBへ減っても約355MiBのUnity確保と894 Sceneが残った。

GC回数を記録し、明示GCの時間は旧18.4ms/修正1.0ms。自然GCそのものの停止時間は独立に分離できておらず、Scene解放を含むprofileとGC回数を併記する。製品側に毎反復のGC.Collectを追加していない。

## 修正と安全条件

- PredictionLifecycle.cs Register/Release/Read：専用Sceneハンドルの所有、生成/解放/保留数、メモリを管理。
- SuikaPhysicsSimulator.cs Dispose：専用Sceneを同期解放し、生成した予測専用materialだけ即時破棄。owned/sourceCopies/pendingRemoval/ids/goCandidates/materials/Traceの参照を解放する。
- SimulateNative：Simulate中フラグをtry/finallyで管理し、その最中のDisposeを禁止する。
- SuikaPredictionPath.cs：待機tickも同じガード付きSimulateを使う。tick幅と実行回数は変えない。

Unity 2022.3のSceneManager.UnloadSceneは非推奨で、trigger等から安全に呼べないAPIである。本対応は専用・停止済み物理Sceneの所有確認、Simulate/衝突callback外、メインスレッドでの解放に限定する。デフォルトSceneやassetを対象にせず、解放後Scene.IsValidがfalseであることを確認する。共有materialは破棄せず、newで作った予測専用materialだけを破棄する。Unity更新時は再検証が必要。

公式根拠：
- https://github.com/Unity-Technologies/UnityCsReference/blob/2022.3/Runtime/Export/SceneManager/SceneManager.cs#L172
- https://docs.unity3d.com/2022.3/Documentation/ScriptReference/SceneManagement.SceneManager.UnloadSceneAsync.html

## 通信との因果関係・修正

旧運転ではNative解放バックログにより、探索後のUpdate/通信処理も遅くなった。Unityは1フレーム1コマンドを処理するため、再送の残りやmetadata要求が後回しになり、5秒のmetadata期限を超えていた。元の失敗はmetadataエラー後にPythonのfinallyが所有Playerを終了させたもので、自然GOではなかった。

根本のScene滞留を取り除き、5秒を30秒へ延ばす対処はしていない。前回の長時間plan_stepの再送抑制も維持。

追加で、environment要求へrequest_idを付け、Unityはenvironment_request_idを返信。対応能力フラグを見てPythonが照合し、別要求の完全な古いmetadataを受理しない。同じ要求の再送は同一ID、0.5秒以上の間隔。get_environmentを他のUnity操作と排他にして、複数の未完了要求を作らない。旧Playerは能力フラグがない場合の従来検証を維持し、旧Pythonも新しいフィールドを無視して動作する。

任意の --keep-player-on-error はGUI限定。エラー時にAIを停止し、所有Playerのウィンドウを診断用に残す。検証を省略してAIを続行する機能ではない。既定はOFFで、正常GO/手数終了/Ctrl+Cの後始末は従来どおり。GUI保持分岐は自動テストで検証したが、実GUIへ故意の通信障害を注入する試験は行っていない。

## 自然進行55手

importance、上限128回/2秒、自動深さON、Budgeted Widening ON、seed765100、画面なしの1ゲーム。55手・347点・GOなしでstep_limit終了。自然GO完了データとしては扱わない。

|手|果物数|反復|深さ|判断ms|Unity確保MiB|Private MiB|Working Set MiB|予測Scene/解放待ち|
|---|---:|---:|---:|---:|---:|---:|---:|---|
|1|1|128|4|710|41.3|168.0|120.0|0/0|
|10|6|128|2|485|42.1|184.9|123.6|0/0|
|20|5|128|3|1077|42.1|185.2|123.8|0/0|
|30|9|128|3|1358|42.1|186.3|124.0|0/0|
|40|11|128|2|823|42.2|186.2|124.4|0/0|
|50|14|128|3|1538|42.2|186.2|125.0|0/0|
|55|16|64|3|862|42.3|186.2|125.0|0/0|

果物数と探索深さ・反復数が変わるため、この表だけで速度改善率を評価しない。全55手の得点保存、episode/action整合性、metadataのruntime profile、GO0.83とルールID、通信エラー0を監査。

## 120秒探索2回・GUI

上限まで探索する状況を作るためtimeモード、自動深さOFF・深さ4、最大32768回/120秒、Budgeted Widening ON、画面なしで2手だけ実施。

|手|反復|候補|判断秒|超過ms|Unity確保MiB|Private MiB|Working Set MiB|解放後予測Scene|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|1|23892|9|120.070|69.75|61.1|392.9|329.8|0|
|2|18508|9|120.070|70.05|61.8|409.8|352.1|0|

2回ともtime_limitで正常終了、落下・metadata・得点保存に成功。importanceの特定局面で実際に120秒使うケースそのものは未再現。共通の同期探索/Scene解放/再送/metadata経路を検証した。Private Bytesは大きな探索の後に増えており、2回だけで全ての予約メモリが完全に頭打ちになるとは保証しない。予測Sceneの累積は0。

GUIはimportance・自動深さON・上限128回/2秒で3手。Unity画面とViewerを起動し、610/524/780ms、深さ4/3/3、候補7/5/5。全3落下成功、metadata確認、映像フレーム取得、得点保存を確認。スクリーンショットによる目視QAはしていない。思考中の描画停止は同期MCTSの従来仕様として残る。

## 互換性とテスト

- Python 278テスト成功。ID誤応答排除、同一ID再送、操作排他、旧Player対応、長時間待機、GUI保持の分岐等。
- Unity既存1029チェック成功（MCTS861/rules84/path26/frames58）。
- 旧Playerと3盤面×4設定（従来32回/adaptive/time/budgeted）で選択・評価・全ノード・全反復内容・物理tickが12件一致。
- 追加で旧Step8AA_02と新Playerを3盤面×32反復で比較。4手予測終端の位置/速度/角度/接触/score/GO等を含む状態ハッシュが96経路一致。実ゲームとの物理予測誤差が解消したという意味ではない。
- Source/RNG/score不変を既存テストで確認。Scene/Prefab/ProjectSettings変更なし。
- 過去Player1214ファイルのハッシュ不変。既存実験の再開・上書き・削除なし。

## ファイルと行番号

- PredictionLifecycle.cs: Register(18), Release(20), Read(53)。新規、metaも生成。
- SuikaPhysicsSimulator.cs: SimulateNative(58), constructor登録(69), Dispose(528)。
- SuikaPredictionPath.cs: 待機物理更新のSimulateNative呼び出し(153)。
- SuikaLifetimeProbe.cs: Start(13)。診断時のみ生成される反復測定器。新規、metaも生成。
- MctsPlanner.cs: Report(43), PlanFrames開始/終了メモリ記録(160/432)。探索式は変えない。
- UDPTrainingMetadata.cs: ObservationのID/能力フラグ(61), FillTrainingSnapshot(179)。
- UDPStateProtocol.cs: HandleCommandのenvironment応答(30)。
- unity_env.py: get_environment(208), _get_environment(220)。
- parallel_play.py: run_parallel(189), エラー時の任意GUI保持(260)。
- play_parallel_ai.py: --keep-player-on-error(25)、run_parallelへの転送(77)。
- SuikaWorkerBuild.cs: BuildLifetime(25)。別フォルダ出力。
- tests/test_metadata_requests.py、tests/test_player_error_visibility.py：追加回帰。

測定ログ：Python/outputs/step8ab_01/。final_fixed/legacy.jsonl、legacy_drain.jsonl、compatibility.jsonl、physical_old/new.jsonl、progression_55/、stress_120x2/、gui_3/、final_audit.json、python_tests_final.log等。

## 残る課題

今回再現したScene解放バックログは修正・検証できた。数時間の最大予算importance自然GO全編や全ての盤面は未検証。実ゲームと予測の接触/GO誤差、importanceの得点性能、自動深さの有効性は別課題であり、今回改善したとは主張しない。エンジン非推奨APIを限定使用するため、Unity更新時は解放・数値一致テストを必須とする。メモリ/Scene計測を残しているので、次の長時間実行でも監視できる。
