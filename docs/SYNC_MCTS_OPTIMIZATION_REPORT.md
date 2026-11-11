# 同期MCTSの計算内容を維持する内部最適化（2026-10-27）

## pushと作業範囲

ユーザーの「現状をpushし、得点の性能を変えずに時短」の依頼で、最適化前の全ソース・設定・報告書を9ad99f1としてcommit、origin/developへpushした。Player・モデル・ログは従来のignoreを維持し、Gitへ追加していない。基準commitを残した後に以下の最適化を実施。最適化分はレビュー可能な未commit差分として残す。developを維持。

最終Player：Unity/Builds/SyncOptimized_03/SuikaGameAI.exe。試作01/02と旧Step8AE/Step8AB_02等も上書きせず保持。実行中のovernight収集は旧Playerのまま続け、停止・再開・設定変更はしていない。Scene、MctsPlanner本体、PredictionLifecycle、旧Playerファイル、旧ValueNetの不変を確認。

変更は予測専用クローンの参照取得・列挙バッファ・重複同期に限定。UCT、chance乱数、rollout、報酬、探索回数、深さ、落下候補、合体、GO条件・ライン0.83、物理設定・Colliderは変更していない。環境ルールID step8e-all-fruit-go-v2を維持。

## 変更内容と安全条件

1. GO候補のTransform参照を登録時に保持。位置・HasCollided・IsPreview・IsMerging・activeは毎回その時点の値を読む。位置やGO結果をキャッシュしない。候補削除後の他要素の順序も維持。
2. 1回のAdvanceで保持中の同じオブジェクトのTransform/有効Collider参照を再利用。予測クローンの対応scriptでは保持中にColliderを追加・削除・有効切替しないことを確認。落下時のisTrigger変更と、次のAdvanceで保持果物が変わる処理はそのまま。
3. Copy内のMonoBehaviour/Renderer/Joint列挙を再利用Listへ格納。列挙順・unsupported script/Joint検証・clone有効化・Rigidbody設定の検査は維持。物理オブジェクトや中間worldをpoolしない。Disposeでバッファ参照をClearし、破棄済みコンポーネントを保持しない。
4. ReadBoardは同時点のRigidbody.position/velocityを各1回取得してx/yを取り出す。間にSimulateや書込みはない。
5. まだ落下していない移動／cooldown待機tickは、Transformを書いた直後に既にSyncTransformsしている。その後はBounds/Distance等の読取とmanagedカウンタのみで、Simulate/yield/追加Transform書込みがない。この場合だけ、同じtickのSimulate直前の2回目のSyncTransformsを省く。落下tick・落下後tickは従来どおり同期する。PhysicsScene2D.Simulate自体・dt・順序・回数は省略しない。

MctsPerformance.ExactOptimizationsは内部A/Bスイッチ（既定true）。通常のAI設定を追加するものではない。旧Playerを使えば旧実装で実行できる。新しい物理近似、solver cache共有、非同期化、GPU化、追加ペナルティは導入していない。

## 最終版の一致検証

序盤0果物、中盤14果物、密集35果物、GO近傍38果物の保存盤面を利用。固定seed8191、32回/深さ4・128回/深さ4・32回/深さ16。各設定warmup1組＋本測定1組、計24組。4つの盤面を繰り返した検証であり、24個の独立ゲームではない。

各A/Bは同じ生のfrozen native rootから開始し、順序を反転。選択位置、全候補の評価/訪問数、全node/行動系列、反復ごとの状態ハッシュ、得点、合体、GO、物理更新数がすべて一致。合計1,536反復分/variantを比較。実ゲームrootが変わっていないことと、診断が保持するroot以外の予測Sceneが残らないことも確認。

試作02でも4盤面×3設定×3組＝36組を同様に比較し全一致。最終03は列挙バッファのDispose時参照Clearを追加したもの。既存Playerとの別計測では、旧Step8AEと試作02の4設定×warmup/3測定＝16対応で全node・行動・得点一致を確認。過去のSTEP8-D baseline経路は区別して残す。

## 時間計測

最終03の密集35盤面。同じPlayer内で最適化OFF/ONを交互順序で実行し、warmupを除く各5回の中央値。状態ハッシュと詳細profilerはOFF。選択/探索木等の一致チェック自体は探索時間の外で行う。

|設定|OFF ms|ON ms|時間短縮率|
|---|---:|---:|---:|
|32回 / 深さ4|945.45|901.77|4.62%|
|128回 / 深さ4|3690.87|3541.26|4.05%|
|32回 / 深さ16|1422.14|1356.50|4.62%|

各5標本の短時間値であり、全盤面・全ゲームの保証値ではない。32/d4の範囲はOFF925.04〜956.90ms、ON889.90〜906.89ms。128/d4はOFF3673.95〜3776.63ms、ON3502.38〜3593.68ms。32/d16はOFF1400.29〜1529.62ms、ON1322.75〜1414.43ms。小標本のため安定したp95や有意差は主張しない。測定中、既存の収集Playerがバックグラウンドで1枠動いており、絶対時間にはCPU競合の影響もある。

旧Playerとの独立した非profile測定（試作02、各3回）でも、密集16/d3:408.62→393.54ms、32/d3:866.08→818.97ms、32/d4:1029.97→985.20ms、64/d4:1998.59→1960.83ms。別プロセスの順次測定なので、最終03の同一root交互A/Bを主表とする。

詳細profileは速度本測定と分離。中盤32/d16ではnative_physicsが約76〜79%を占め、残る主要コスト。Simulate28,439回、GO確認28,439回、object_copy1,304回はいずれも同数。SyncTransformsだけ45,614→30,487回。profileには計測自体の追加コストがあり、そのelapsedを上表へ混ぜない。

## 実通信と得点性能について

旧Step8AE、試作02、最終03で同じgame seed790100・MCTS seed8191・固定128回/深さ4・候補5・post25を各8手。全て正常終了し、選択位置は[0.5,0.75,0.25,0.75,0.25,1,0.25,0.5]、得点推移は[0,0,0,0,15,21,22,22]で一致。座標適用・得点保存・metadata/GOルール版・予測Scene/解放待ち0を確認。手数制限終了であり、自然GOとは扱わない。

ただし、旧版と試作02の6手目から操作間の時間進行に1tick差があり、果物の位置/速度まで実ゲーム全編でビット一致ではない。同じ旧Playerを再実行しても6手目から同様に盤面差が生じ、選択・得点は8手とも一致した。これは既存の通信/Update/FixedUpdateタイミング揺れとも整合し、最適化だけによる新しい物理誤差と断定しない。今回ゲーム側の時間進行を固定化する変更はしていない。

探索のroot入力と反復回数が同じなら今回の一致検証では判断結果が維持された。自然GOまでの平均得点・ダブルスイカ到達率を比較していないため、全ゲームでの得点性能を統計的に保証したとは言わない。

旧版と試作02の8手全体wallは18.16秒→18.83秒で、この短い実通信では起動/移動/通信を含む総時間の改善は見られなかった。純探索の短縮とゲーム全体の短縮を混同しない。

## 時間上限との関係・推奨用途

120/240秒などで打ち切る手は、速くなった分だけ反復数が増え、選択が変わる可能性がある。一定回数が完了する手では同じ探索を短くできるが、時間上限に張り付く手が必ず短くなるわけではない。adaptive/importance/wideningの時間予算に依存する停止・追加判断にも同じ注意が必要。

今回の旧ゲーム0は267手中11手で240秒上限に到達。探索時間44,294秒の全てへ一律4〜5%を掛けて最終所要時間とすることはしない。高得点化を維持する次の検証は、まず同じ固定反復数で上限に当たらない条件から比較する。自然GOの大量比較はユーザーが行う。現在の収集は旧Playerのまま完了させる。

## テスト・ファイル

Python299テスト成功。新規4テストは比較結果不一致・元盤面変更・Scene残留を高速化成功と誤認しないことを確認。Unity最終03の既存1029チェック（MCTS861/rules84/path26/frame58）とイベントON/OFFの物理・得点・カウンタ一致試験が成功。

- Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs：RegisterFruit周辺46〜55、Copy88〜105、FlushRemoval/IsGameOver208〜227、ReadBoard249〜254、RunTicks396/429/472〜476、Dispose569。
- Unity/Assets/Scenes/Script/MctsPerformance.cs:13：内部A/Bスイッチ。
- Unity/Assets/Scenes/Script/SuikaExactOptimizationProbe.cs：新規。固定root・全探索/物理状態比較。
- Unity/Assets/Editor/SuikaWorkerBuild.cs:30：旧ビルドを上書きしない最終Player出力。
- Python/benchmark_sync_optimization.py：新規。短時間A/B実行、root不変/Scene/数値一致監査、中央値等の保存。
- Python/tests/test_sync_optimization.py：新規4テスト。

詳細出力：Python/outputs/sync_opt_01/final_audit.json、exact_release/、timing_release/、各native selftest結果、release_smoke/。原ログ・旧モデル・旧Playerを削除/上書きしない。

## 使用方法

既存のプレイ/収集コマンドのexeだけを次へ変更する。探索条件は従来と同じものを使う。
```powershell
--exe ..\Unity\Builds\SyncOptimized_03\SuikaGameAI.exe
```
既存のovernightフォルダを新Playerへ差し替えてresumeしない。保存済みPlayer hashの照合で拒否する設計であり、新しい出力フォルダを用いる。8時間後の方針はユーザー指定の --shutdown drain を維持。

固定盤面で再検証する場合：
```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\sync_opt_check_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\benchmark_sync_optimization.py `
    --exe ..\Unity\Builds\SyncOptimized_03\SuikaGameAI.exe `
    --output $out `
    --fixtures .\outputs\step8c_01\dense_safe_fixture.json `
    --specs 32:4 128:4 32:16 `
    --repeats 2
```

結論：同じ探索計算を維持した数％の時短を確認。実ゲームの平均得点向上も低下も今回の短時間試験だけでは断定しない。既存の物理予測誤差・GO見逃し・自動配分の得点性能は今回改善した扱いにしない。
