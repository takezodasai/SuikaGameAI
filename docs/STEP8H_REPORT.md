# STEP 8-H：物理tick単位の中断と検証（2026-10-23）

## 結論

**細粒度の中断・再開と固定盤面での計算一致は実装・検証できた。しかし、ゲーム全体の長時間停止の解消、落下間隔の改善、判断失効の解消には至っていない。既定はsyncのまま。**

今回、GO0.83、環境step8e-all-fruit-go-v2、Collider/物理設定/果物確率、UCT/rollout/報酬/深さ/反復数、モデルを変更していない。developを維持しcommit/pushなし。既存の未コミット変更は保持。4ゲームへの新方式展開、録画再生、GPU化、A〜Dの新実装は行っていない。

## 1. どこを中断可能にしたか

従来は `MctsPlanner.PlanFrames` の1回のAdvanceが、横移動・cooldown待ち・落下・post25物理更新をまとめて同期実行していた。6ms予算はAdvance終了まで確認できない。

`SuikaPhysicsSimulator.RunTicks` に既存の物理ループをそのまま移し、1tickで次の順序を完了してからyieldする。

1. 同じdtで保持果物を移動し、壁との安全確認。
2. 目標到達＋同じcooldown条件なら一度だけrelease、公開NEXTを保持へ更新。
3. SyncTransforms → PhysicsScene2D.Simulate(dt)。dtは従来約0.02秒。
4. collision callback内の既存合体/加点。
5. trace、FlushRemoval、GO確認、tick加算。
6. 継続が必要なら中断。最終tickでは結果DTOの作成まで行う。

iteratorが位置・対象・postカウンタ・得点区間・時刻を保持し、PathSessionが同じ独立PhysicsScene2Dを保持する。再開時に前tickを再実行しない。待機ループも `WaitTickFrames` で1tick単位にできる。元の同期Run/WaitTicksは同じiteratorをyieldで待たず最後までdrainする。

MCTSは実行粒度だけを切り替え、乱数を引く位置・UCT選択・展開・rollout・逆伝播・既存leaf cacheは同じ。新しい省略/近似/cacheは追加していない。Select/Backprop/単一Simulate/callback/1オブジェクトのコピー/Scene作成を内部で細断していない。

C#のusing/finallyで、中断中のReset/GO/キャンセルでも内側iteratorとPathSessionを解放する。Profilerの計測スコープもyieldを跨がず閉じる。

## 2. 切り替え方と互換性

新しいAIモードを作らず、既存の実行方式にbool `frame_tick_slicing` を追加した。既定false。

- `--planning-execution sync`：従来同期。既定。
- `--planning-execution frames`：従来の予約150tick＋粗い中断。
- 同じframesに `--frame-tick-slicing`：同じ予約、同じ探索のtick単位中断。
- frames_adaptiveも残すが、今回の主比較には混ぜない。

syncでも内部検証用にbool=trueをdrainできるが、画面を継続更新するにはframesとの組合せを使う。分割運用は従来どおり1ゲームに限定。既存のsyncでの4ゲーム/Viewer/他AIモードは残している。

## 3. 固定盤面の完全性比較

`C:\SuikaGameAI\Python\outputs\step8h_01\verified_parity.jsonl`。

序盤、密集fixtureの低い15果物を取り出した中盤相当、35果物の密集盤面 × 深さ4/5/6 = 9条件。中盤は合成fixtureであり自然な中盤の代表性は保証しない。公開情報を含む同一native rootを凍結し、全方式がそこからforkする。同一MCTS seed8191、Player seed749100、32反復/5候補/post25で比較。ライブrootを各方式の間に取り直していない。

同期との比較は**旧分割9/9、新分割9/9で完全一致**。選択位置、全ノードの訪問回数/評価値/子ノード、ノード数、各反復の行動列・仮想chance系列・tick・合体・得点・GO、各候補、最終状態digestを比較。実行時間だけを比較用コピーで除く。

密集の深さ4/5/6では終端GOの反復も14/18/21件あり、その結果も一致。ただし同じfixtureの探索内反復で、独立した自然GO正例53件という意味ではない。実ゲームのGO見逃し率を推定する試験ではない。

| 密集盤面 | 深さ4 | 深さ5 | 深さ6 |
|---|---:|---:|---:|
| 同期の能動計算ms | 814.27 | 915.31 | 913.94 |
| 旧分割の能動計算ms | 819.85 | 922.22 | 930.00 |
| 新分割の能動計算ms | 807.02 | 931.91 | 940.05 |
| 新/旧の変化 | -1.56% | +1.05% | +1.08% |
| 旧方式の最大再開区間ms | 13.39 | 12.85 | 12.56 |
| 新方式の最大再開区間ms | 3.49 | 4.05 | 4.22 |
| 新方式の開始〜終了実時間ms | 894.01 | 1038.85 | 1046.17 |
| native物理tick数 | 6113 | 7056 | 7051 |
| decision nodes | 33 | 33 | 32 |

単発かつsync→coarse→fineの順。初回JIT/キャッシュ/スケジューラ/Profiler負荷を含むので、わずかな負の値を高速化実績とは扱わない。目的は計算総量を削らず中断点を増やすことであり、計算時間の大幅削減ではない。9条件で新/旧の能動コストは約-1.56〜+8.63%、序盤の+8.63%を含む。

同じ密集盤面のnative Simulateは平均0.0934/0.0943/0.0954ms、最大0.703/1.175/0.772ms。中断できる最小単位はこの単一tick＋移動/合体/GO等であり、Simulateだけの時間ではない。観測最小native時間は0.005〜0.072msだが、フレーム時間保証に使わない。

新方式の1反復あたり能動計算平均は25.22/29.12/29.38ms（全work÷32の平均。最終集計等も含む）。各反復のwall最大40.13/48.49/48.58msで、これにはyield後の描画や待ちが含まれる。wall反復時間をCPU時間と呼ばない。

## 4. ライブの画面停止：改善は一様ではない

1ゲーム＋Viewer、seed749100、32/深さ4・5・6/5候補/post25、予約150、2試行上限。各深さで序盤1要求＋同じ35果物fixture1要求。実行中に別の計測Playerを同時起動していない。

| 深さ | 旧 最大Unity Update間隔ms | 新 最大Unity Update間隔ms | 旧Viewer fps | 新Viewer fps |
|---|---:|---:|---:|---:|
| 4 | 253.97 | 79.65 | 13.67 | 14.15 |
| 5 | 185.37 | 120.97 | 13.69 | 13.77 |
| 6 | 79.42 | 245.54 | 13.93 | 13.79 |

**深さ6は悪化しており、密集でも50ms以下という目標は未達。** 前回の153msや166msはハード上限ではない。今回も実行ごとのスパイクに変動がある。1回ずつの最大値の差だけで方式の優劣を確定しない。

新方式の密集MCTS内部のtick/chunkは小さくなった一方、探索以外の同期処理が残っている。最終の内訳計測 `final_atomic/frames_d6` で：

| 処理 | 観測した最大ms | 中断の扱い |
|---|---:|---|
| Selection | 0.148 | 小さい同期処理のまま |
| Expansion側の1chunk | 3.991 | 物理tick境界で中断 |
| 単一native Simulate | 2.408 | 内部は分割しない |
| 合体等も含む1physics_tick | 2.569 | 完了後に中断 |
| Path fork全体 | 2.781 | 1回のコピーは同期 |
| オブジェクトcopy | 3.161 | 同期、全処理の最大値で他の経路も含む |
| GO確認 | profile参照 | tick内の順序を維持 |
| Backpropagation | 0.399 | 同期のまま |
| Scene解放予約 | 0.748 | 実際のUnity解放完了時間ではない |
| 探索開始準備全体 | 69.956 | 依然同期 |
| そのうち設定照合 | 20.919 | 依然同期 |
| 初期native rootコピー | 26.771 | 依然同期 |
| alias初期化 / 初期capture | 7.596 / 7.323 | 依然同期 |
| **失効後のheuristic fallback全体** | **286.712** | **従来の5候補予測が同期のまま** |

この要求の最大作業区間286.75ms、最大Unity更新間隔335.65ms、Viewer13.71fps、表示中フレームの古さ最大371.65ms。**残留停止の一部は「MCTS反復が長い」のではなく、失効後に同期heuristicを実行するため**と確認できた。別の深さ4計測では準備83.90ms、fallback67.93ms。全過去スパイクを同じ原因と断定するものではない。

初回準備69.96msに対し再試行8.84msで、cold start依存は見られる。JITだけが原因と断定する計測はしていない。設定照合の全Scene走査/JSON化、初期コピー、記録が含まれる。開始準備をフレーム跨ぎで単純に分割すると、コピー中にライブ盤面が変わるため別の整合性設計が要る。

1回のSimulate自体が今回の主要な長時間停止源ではない。次は同期fallbackの同一盤面での5候補予測分割と、開始準備の負荷削減を別検証する必要がある。現在rootを凍結して5候補をforkするだけでも、余分なcopyの質量/慣性やcontact初期状態の一致を検証してから採用すべきであり、今回無断で切り替えていない。

## 5. 判断採用と操作間隔は別問題

連続4手（自然GOまでではない）。sync/coarse/fineの公開保持/NEXT列はいずれも `(1,3),(3,0),(0,4),(4,2)`。scoreは4手後全方式0、全要求のreward_accounting.conserved=true。強さ比較には不十分。

| 指標 | sync | 旧分割 | 新分割 |
|---|---:|---:|---:|
| MCTS判断採用 | 4/4 | 3/4 | 3/4 |
| 再探索 / heuristic fallback | 0 / 0 | 1 / 1 | 1 / 1 |
| 落下間隔 実秒 平均 | 0.923 | 6.039 | 6.111 |
| 実秒 中央値 / 最大 | 1.035 / 1.038 | 4.012 / 10.437 | 4.057 / 10.520 |
| ゲーム秒 平均 | 0.887 | 6.040 | 6.113 |
| ゲーム秒 中央値 / 最大 | 0.960 / 1.040 | 4.020 / 10.440 | 4.060 / 10.520 |
| 最大Unity更新間隔ms | 406.60 | 182.31 | 110.51 |
| Viewer fps | 10.87 | 13.81 | 13.56 |

間隔の標本数は各3。旧/新分割の選択xはいずれも0,.25,.25,.75で一致し、4手目は両方heuristic。syncは4手目0。進行時刻が違う盤面を比較するので、syncとの行動差をアルゴリズムの不一致と混同しない。

序盤＋密集の各深さの採用は旧/新とも1/2。密集は両方失効してfallback。15果物の中盤も両方0/1で失効。**今回の標本で採用率の悪化は見られなかったが、改善した証拠もない。** 全てprojected_state_mismatchで、同じ32反復を完了した結果でも位置/sleep/接触資格等の厳密照合を満たさない。許容誤差を広げていない。

150tickの予約と再試行時の302tick予約はそのままなので、細分化だけでは約3秒・約6秒の先読み待機を削減できない。ゲームの0.4秒cooldownとは異なる。実ゲームの物理/描画/通信は探索のフレーム間にも進行するが、操作頻度と採用率の改善は別課題。

## 6. 記録内容と計測の意味

`planning.frame_search.history`に各試行のstart/result/validationのtickとwall、initial/projected、今回追加の`live_at_result`（診断ON時）、差分、拒否理由、反復数を記録。infoのdrop_tick/drop_wall/drop_game_time、previous_drop_tick、next_legal_tick、movement_start_tickと合わせて読める。

FrameReportにtick_slicingと処理別profileを追加。scopeごとのmin/max/累積/callsから単一native tick、copy、GO、UCT、fallbackを区別する。Scopeは親子で包含するため、inclusive時間を全部足さない。`elapsed_ms`やResult.simulation_msは細分化時にはyield待ちも含むwall時間。能動コストはwork_msとprofileを用いる。

GCはCollectionCountの差であり、停止時間の計測ではない。最終の診断フィールドだけの修正で、fallbackが最大だった際にもlargest_slice_gc0を更新するようにした。主比較とfinal_atomicの旧値はこの修正前なので、そこでGC原因を断定する用途に使わない。既存ログは書き換えていない。

## 7. GC・メモリ・Viewer

固定密集32反復でGC0カウントは旧→新、深さ4：40→48、深さ5：44→49、深さ6：43→43。新方式はiterator/計測の追加コストがあり、メモリ回収が減ったとは言えない。計測用scope自体の割当も含む。GCの個々の停止時間やIncremental GCの処理時間は未分離。

固定新方式のmanaged heapは密集で約3.02/3.18/4.30MiB、Unity管理対象メモリ約42.85〜42.89MiB（RSSとは異なる）。Viewer付きの深さ別比較ではPlayerピークRSS約176.6〜178.9MiB。連続4手はsync185.6、旧172.4、新175.2MiB。

ライブの平均CPUは旧約0.82〜0.84コア相当、新約0.75〜0.88コア相当（Player CPU秒÷測定実秒）。CPU全体使用率や探索瞬間ピークではない。Viewer/Python自身とGPU負荷は未計測。

Viewerは既存15fps配信のままで約13.6〜14.2fps。最新フレームだけを表示する。平均fpsが維持されても一時的に古いフレームが残るため、Unity更新間隔と表示フレームの古さも見る。Tk提出までの計測は実ディスプレイ表示遅延ではない。今回、Computer Useでの目視判定は行わず、実Player/Viewerを起動し物理更新・表示提出・共有メモリ遅延を記録した。

## 8. A〜Dの具体的な設計比較（今回未実装）

| 案 | 現コードとの接続 | コスト/効果 | 条件・リスク |
|---|---|---|---|
| A：次操作を早期探索 | DropFruit→NEXTが保持に移り、新しい公開NEXTが確定した後に予測rootを確保。既存post25の観測中にframeWorkを進める | 中〜大。既存約0.5ゲーム秒の観測待ちと探索を重ねる余地。full32を削らない | 現在activeStepと次の探索を別管理し、現在stepの報酬/action_id/lockを変更しない。予定意思決定tickで検証する。未知のさらに先の果物は参照しない。接触誤差は残り、密集0.8〜1秒の計算全体を隠せる保証なし |
| B：Anytime | 各反復の逆伝播完了後に暫定root選択を取り出す。実行前に現盤面で合法性/GO確認 | 中。期限超過時の全破棄を減らせる可能性 | 8/16/24/32反復の一致・得点・GOを別測定。少ない訪問数の手をfull32と同品質と扱わない。今回の優先目標に対して品質リスクが大きい |
| C：部分再利用 | 同じheld/NEXT/環境/時刻条件の既存候補を「提案」として保持し、現盤面で再予測。訪問数や平均値は異なる盤面へ引き継がない | 中〜大。候補だけの再評価なら再探索より安い可能性 | 1手の合法性/GOが一致しても深さ4の順位を保証しない。完全MCTS再計算との一致とGO差をオフラインで検証。serialized状態一致でもsolver cache一致ではなく、木全体の無条件再利用は不可 |
| D：予定tickの選択 | 初期物理状態/速度/接触・果物数の区分と、実測探索時間の上位側を使ってTを決める。結果完了後に勝手にTを動かさない | 中。空盤面の過剰待機を減らせる。8Gの推定器を再利用可能 | 8Gで採用率低下があり、短い待機＝良い判断ではない。予定時刻の盤面不一致を解決する方式ではない。最短合法tickとAPI意思決定境界も区別する |

**次のリアルタイム方式はAの小試作を推奨。** full32・深さ4を維持したまま、既に存在する落下後の観測待ちに計算を重ねられるため。Bの探索打切りやCの異なる盤面への価値再利用を先に行うより判断品質の条件を明確にしやすい。ただし採用率改善を約束するものではなく、予定tickの厳密照合・不一致時の記録は必要。

Aの最小受入試験：1ゲーム/固定25tick、Drop/Spawn後の公開保持・NEXTを記録、探索開始だけを早める。現在stepが終了するまでは実行しない。同じ凍結rootのfull32一致、reward保存則、Reset/GOで現在/次両処理の破棄、予定tick一致、自然GOに近い盤面の失効率を検証。次action_idを勝手に受理せず、重複/手動入力の責任範囲も分離する。

その前提として、録画の滑らかさには同期fallbackとcold準備の対策も必要。新しい判断方式Aの効果と、fallbackを分割する技術改善は別の小試作・別測定にする。見かけの採用率を上げるためにGO照合を弱めない。

## 9. 変更ファイル・主な関数・行番号

`C:\SuikaGameAI` 基準。行番号は今回の最終ソース。

| ファイル | 箇所 | 変更 |
|---|---|---|
| Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs | 360 Run、368 RunTicks、401 physics_tick | 同じ物理ループを同期drainとtick中断で共有 |
| Unity/Assets/Scenes/Script/SuikaPredictionPath.cs | 55 fork constructor、125 AdvanceSearchTicks、144 WaitTicks、145 WaitTickFrames | 予測世界を保持して継続、wait tick単位化、fork計測 |
| Unity/Assets/Scenes/Script/MctsPlanner.cs | 147 advance分岐、185 wait分岐 | 実行粒度のみ切替、アルゴリズムの選択/乱数/報酬は維持 |
| Unity/Assets/Scenes/Script/StepPlanner.cs | 21 PlanningSettings | 既定falseのbool追加 |
| Unity/Assets/Scenes/Script/MctsPerformance.cs | 8 Metric、Scope.Dispose | 処理別min/max時間を追加 |
| Unity/Assets/Scenes/Script/UDPFrameSearch.cs | 13/22 report、116 StartFrameAttempt、141 FrameProjectionAndSearch、174 result capture、238 CommitFrameFallback | profile、開始/完了盤面、1tick投影、fallback等の内訳 |
| Unity/Assets/Scenes/Script/SuikaFineSearchSelfTest.cs (+.meta) | 全体 | 9固定条件・3方式の一致/コスト検証 |
| Unity/Assets/Scenes/Script/SuikaFrameSearchSelfTest.cs | lifecycle loop | fine中断中のReset/GO/重複検証を追加 |
| Python/src/suika_ai/unity_env.py | 416 defaults、439 validation | boolと型検査 |
| Python/play_parallel_ai.py | mainの--frame-tick-slicing、57 settings | 実行オプション |
| Python/diagnose_frame_search.py | run、36 plan_step、main | 旧/新の短時間比較 |
| Python/tests/test_frame_execution.py | 追加テスト | 明示指定と32反復/深さ維持 |
| docs/STEP8H_REPORT.md、DEVELOPMENT_LOG.md、DEVELOPMENT_PLAN.md | 今回追記 | 結果と次の設計 |

iteratorの核心：

```csharp
using (MctsPerformance.Measure("physics_tick")) {
    // 既存の移動・release・Simulate(dt)・合体・FlushRemoval・GO確認
}
if (result.game_over || (dropped && post >= postSteps)) break;
yield return null;
```

ゲームの時間を止める処理や、別スレッドでUnity APIを呼ぶ処理は追加していない。途中の予測Sceneは非表示の独立世界であり、ライブの標準PhysicsSceneはUnityが通常更新する。

## 10. テストと保存先

全て `Python/outputs/step8h_01` に新規保存。既存の結果は削除/上書きしていない。

- `verified_native`：Frame58 + MCTS861 + Rules84 + Path26 = **1029検査成功**。
- `verified_parity.jsonl`：27実行、旧/新それぞれ9条件で同期一致。`parity_analysis.json`に集計。
- `coarse_live` / `fine_live`：深さ4/5/6のViewer付き序盤・密集。
- `continuous_coarse` / `continuous_fine`：連続4手。`mid_coarse` / `mid_fine`：15果物1要求ずつ。
- `atomic_dense` / `final_atomic`：残留停止を追加計測。`live_analysis.json`は主比較の集計、final_atomicは追加計測なので別途参照。
- Python **141テスト成功**。テスト内の小さな合成学習のみで、実モデルの再学習ではない。
- 最終メタデータ修正後のEditorバッチBuild成功、Value parity24ケース成功。最大推論差0.00006104点。物理計算はverified時から変更していないため、全プレイ試験を反復していない。
- モデルsuika_value_epoch3.json SHA256 `7e95aee3f462afb9faa02843b9612bb018f0051b0c68349d1a89d508d2631d2c` を確認、未変更。
- 自己テスト起動引数に誤りがあった先行`native`/`final_parity`は採用しない。正しい引数で`verified_*`を実行した。元の診断記録も削除しない。

自然GOまでの得点比較、GO見逃し頻度、4ゲームfine、GPU負荷、長時間メモリ挙動は未検証。新方式を標準化する根拠はまだない。

## 11. ユーザー用PowerShell

短い1ゲームViewerテスト（10手で打切り、自然GOと区別する）：

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\step8h_fine_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + ([guid]::NewGuid().ToString('N').Substring(0,6))
.\.venv\Scripts\python.exe .\play_parallel_ai.py --games 1 --view-games 1 --episodes 1 --max-steps 10 --ai-mode mcts --planning-execution frames --frame-tick-slicing --frame-budget-ms 6 --frame-lead-ticks 150 --frame-max-attempts 2 --mcts-iterations 32 --mcts-max-depth 4 --candidates 5 --post-drop-steps 25 --seed 749201 --base-port 37400 --output $out
```

旧分割は`--frame-tick-slicing`だけを外す。同期基準は同flagを外して`--planning-execution sync`にする。保存先はそれぞれ新しくする。自然GOまで見る場合は`--max-steps 1000`等にするが、今回Codexはその長時間比較を実施していない。Ctrl+Cで停止可能。使用中のPlayer/Unity Editorは勝手に閉じず、ポートが競合する場合は空いているbase-portを使用する。

深さ別の診断をユーザーが追試する場合：

```powershell
$out = "outputs\step8h_diagnostic_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + ([guid]::NewGuid().ToString('N').Substring(0,6))
.\.venv\Scripts\python.exe .\diagnose_frame_search.py --output $out --fixture outputs\step8c_01\dense_safe_fixture.json --execution frames --depth 4 5 6 --video --stages early dense --frame-tick-slicing --base-port 37500
```

既存の本番起動コマンドがsyncなら挙動はそのまま。今回の結論は「探索の計算一致と細分化に成功、全体の滑らかさ・操作速度・判断失効は引き続き未解決」。
