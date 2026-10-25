# STEP 8-D MCTS性能分析・最適化（2026-10-22）

develop。commit/pushなし。通常のゲームルール・GO比率0.83・Collider/物理設定・出現分布・学習済みモデル・既存AIモードを維持。長時間の得点比較は実施していない。

## 結論

35果物・32回・深さ4の詳細計測なし本測定では、1ゲームの中央値933.02→839.49ms（時間10.0%減、1.111倍）、4ゲームでは1手あたり1240.89→1092.41ms（12.0%減、1.136倍）。探索回数・深さ・候補数5・post_drop_steps25を削減していない。約1秒の計算が数十msになったわけではない。同期探索中の実ゲーム停止は残る。

フル状態を含む同一root A/BはMCTS240組＋mcts_value8組すべて一致（warmup含む）。MCTS本測定は各条件1ゲーム2回、4ゲーム各worker2回＝8回であり、同じrootと同じseedを繰り返した性能検査。240個の独立盤面・独立ゲームを検証したという意味ではない。高得点化の証明ではない。

## 計測方法と対象

- rootは序盤0果物、中盤14果物（既存自然プレイturn16）、密集35果物、GO近傍38果物。後3者は保存ログ由来。復元できるのは公開された配置/速度/角度/接触済み等で、元のsolver接触cache・sleep経過時間は復元できない。元エピソードとのビット一致は主張しない。
- 各A/Bは同じUpdate内・同じ生の実ゲームrootを使用。実ゲームの物理を途中で進めない。実際の通常同期Planと同様にメインスレッドを占有する診断で、timeScaleや物理設定の変更・物理tick省略は行わない。
- MCTS seed8191、worker745000、各設定1組warmupを別記、その後2組。実行順を交互に反転して、2番目のvariantに不利なqueued Scene/GCの影響を均衡化。解放を待って次の組へ進む。
- inclusive時間は子処理を含むため加算禁止。exclusiveは計測した子スコープを控除。native_physicsはSimulate内の衝突callback/合体生成を含む。Scene生成とrootコピーを分離。
- 生成/コピーは既存Instantiate＋Collider/Rigidbodyの設定・検証をまとめて測定。ネイティブ内部のColliderとRigidbody別コストやGC停止時間そのものをUnity Profilerで分離したわけではない。GCはCollectionCount差のみ。
- 詳細タイマー/全反復の状態ハッシュには追加負荷がある。そこで35果物だけは両方を無効にした追加A/Bも実行。通常利用には詳細計測/ハッシュ記録を有効にしない。
- mean/median/p95/maxは各summary.jsonに保存。n=2/8のp95は最大値相当で、母集団の安定したp95推定や有意差を示さない。4worker間のCPU競合もあるため独立標本としてCIを付けていない。

## 改善前のボトルネック（密集35、32/d4、1ゲーム、本測定平均）

|処理|改善前 ms|改善後 ms|備考|
|---|---:|---:|---|
|全体|979.568|836.432|inclusive|
|物理Simulate（callback含む）|578.049|572.777|inclusive|
|衝突callback（上行の内数）|10.595|10.254|inclusive|
|GO判定|136.013|44.771|inclusive|
|Scene生成|1.160|1.137|inclusive|
|root初期化（コピー含む）|81.370|82.322|inclusive|
|オブジェクト生成/コピー（初期化/合体の内数）|55.733|55.137|inclusive|
|盤面読み出し|37.917|14.061|inclusive|
|形状/接触の評価特徴|24.736|3.552|inclusive|
|明示的Transform同期|24.209|26.742|inclusive|
|prefix状態/署名|27.230|24.714|inclusive|
|遷移署名|8.151|8.509|inclusive|
|UCT selection|0.042|0.046|inclusive|
|逆伝播|0.019|0.023|inclusive|
|Scene解放予約|3.159|3.281|inclusive|
|既訪問prefixのAdvance（上記処理を含む）|204.631|174.539|inclusive|
|rolloutのAdvance（上記処理を含む）|492.214|400.693|inclusive|

物理が約59%、GO判定約14%。Scene生成は約0.12%で主因ではなかった。rootを32回コピーするコストはあるが、コピーを含む初期化も約8%。選択・逆伝播自体は0.1ms未満。prefix再計算は全体の約21%だが、その時間は物理/GO等の内数。状態が近いという理由で省略していない。

物理更新は前後とも平均5818回、オブジェクトCopyはともに平均1432回。ReadBoardは302→117回、評価特徴作成は114→15回。物理仕事を減らさず未使用出力を削減した。

## 実装内容・安全性・行番号

|ファイル/関数|変更|
|---|---|
|Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:47 RegisterFruit、:202 IsGameOver|private cloneの不変のFruitタグを登録時に判定。合体消滅時はGO対象リストから除去。HasCollided・preview・merge・高さ・activeという同じ論理積を、軽い条件から評価する。HasCollidedは毎tick現在値を読む。りんごの小文字タグも現状どおり除外。|
|同:220 ReadBoard|metadataを付ける際、ID→果物の二重走査をやめ、同じ果物を読み出した場でMeasureFruit。id順sortと値の意味を維持。|
|同:356 Run|captureState/captureEvaluation/captureInitialの内部出力フラグを追加。Simulate、移動、合体、スコア、GO、果物生成順は同じ。|
|Unity/Assets/Scenes/Script/SuikaPredictionPath.cs:78 Advance/:80 AdvanceSearch|既存public Advanceは常に全出力。MCTSだけ未使用データを省く内部経路を利用。状態署名/Value入力は引き続き完全なSnapshot。|
|Unity/Assets/Scenes/Script/MctsPlanner.cs:79 Plan/:92 PlanCore、:143 AdvanceSearch呼出し|既訪問edgeは既存評価を再利用。rolloutは未参照の盤面配列・手作り評価を出力しない。初期盤面配列は最初のroot結果だけ作成。乱数呼出し/UCT/バックアップ/最終選択を変更していない。|
|同:73 Digest/:186 IterationMetric|診断時だけ全反復の公開状態をSHA256化してA/B照合。既存leaf cacheと不要final chanceの統合を維持。新たな近似状態cacheは追加していない。|
|Unity/Assets/Scenes/Script/MctsPerformance.cs:7|opt-inの階層inclusive/exclusive計測。通常時はcontextなし、タイマー/Frameリスト/ログ生成なし。|
|Unity/Assets/Scenes/Script/FruitEvolution.cs:52 OnCollisionEnter2D/:56 CollisionCore|同じ衝突処理を計測scopeで包むだけ。合体ルール・得点・生成位置は変更なし。|
|Unity/Assets/Scenes/Script/SuikaRuntimeProbe.cs:75 ActionEvent/:82 LoadFixture|診断時だけ4phaseのwall/Time.time/fixedTime/cooldownを記録。既存fixture loaderに計測用path指定を追加。baseline切替も診断フラグがある時のみ。|
|Unity/Assets/Scenes/Script/UDPStepProtocol.cs:78/:150/:197/:218|判断開始・移動開始・実落下・完了の診断呼出しのみ追加。action_id/通信/移動/cooldown/物理更新数は不変。|
|Unity/Assets/Scenes/Script/SuikaMctsBenchmark.cs:9/:32|回数上限付きの固定root A/B、木統計・全反復状態・得点/合体/GOの比較、非同期Scene解放確認。通常はcomponentを作らない。|
|Python/benchmark_mcts.py:6 run|所有Player1/4だけを起動・終了。短い固定盤面反復、CPU/RSS、nvidia-smiのシステムGPU指標を記録。|
|Python/analyze_mcts_benchmark.py:10 summarize|不一致/元盤面変更/未解放をエラーにし、分布と前後比を出す。出力は新規作成のみ。|
|Python/analyze_action_timing.py:7 analyze|同じepisode内の連続落下だけ集計。fixture Resetを落下間隔へ混ぜない。|
|Python/diagnose_runtime.py:39 run_condition|診断用--baseline追加。既存通常コマンドの意味を維持。|
|Python/tests/test_mcts_benchmark.py|正常集計と、不一致・元状態変更・未解放を拒否する4テスト。|

新規C#に対応する.metaも追加。ゲームScene/Prefab/ProjectSettingsは今回編集していない。ビルドで既存のTMP生成アセットに差分が残る可能性があるため、元からあった変更も含めてrevertしていない。保持果物のCOM/慣性placeholderを強制コピーしないSTEP8-C修正を維持。

## 全固定盤面の本測定（詳細計測＋状態照合あり、中央値ms）

|盤面|回数/深さ|1ゲーム 旧→新|4ゲーム 旧→新（1手）|
|---|---|---:|---:|
|early|16/d3|56.04 → 56.22|79.09 → 98.66|
|early|32/d3|123.32 → 107.53|205.47 → 200.31|
|early|32/d4|174.10 → 167.88|303.02 → 290.84|
|early|64/d4|368.46 → 333.79|680.79 → 664.71|
|mid|16/d3|219.81 → 193.03|325.62 → 303.45|
|mid|32/d3|439.71 → 396.09|693.19 → 611.30|
|mid|32/d4|628.51 → 554.17|978.25 → 900.27|
|mid|64/d4|1299.73 → 1102.92|1960.59 → 1826.16|
|dense_safe_fixture|16/d3|397.80 → 334.78|515.95 → 450.16|
|dense_safe_fixture|32/d3|845.92 → 708.82|1129.74 → 988.04|
|dense_safe_fixture|32/d4|979.61 → 836.46|1306.72 → 1157.14|
|dense_safe_fixture|64/d4|2037.86 → 1774.67|2756.03 → 2425.91|
|near_go_fixture|16/d3|204.08 → 180.62|234.69 → 212.07|
|near_go_fixture|32/d3|426.09 → 368.30|519.51 → 458.94|
|near_go_fixture|32/d4|432.98 → 389.85|505.16 → 467.03|
|near_go_fixture|64/d4|924.96 → 841.09|1128.41 → 1019.42|

密集32/d4の詳細計測あり1ゲーム：旧median979.61、p95/max1008.79、新median836.46、p95/max855.59ms。序盤16/d3では1ゲーム56.04→56.22ms、4ゲーム79.09→98.66msと改善が見られない。小標本のCPU競合/順序差の影響があり、全条件で必ず速くなるとは主張しない。

## 35果物の追加本測定（詳細計測・状態hashなし、中央値ms）

|回数/深さ|1ゲーム 旧→新|4ゲーム 旧→新（1手）|
|---|---:|---:|
|16/d3|371.50 → 320.39|482.72 → 436.18|
|32/d3|826.68 → 681.02|1028.82 → 927.48|
|32/d4|933.02 → 839.49|1240.89 → 1092.41|
|64/d4|1981.25 → 1674.64|2552.36 → 2286.21|

4/medianを計算した純探索の参考処理率は32/d4で約3.22→3.66判断/秒。ただし各workerの探索が揃っていると仮定する換算値であり、実ゲームの落下/秒や学習データ生成量ではない。実際のstepは以下のとおり。

## CPU・GPU・メモリ・GC

詳細固定盤面ベンチ全期間（起動/warmup/解放含む）の所有プロセス平均は、1ゲーム2.01論理core相当（12論理core換算16.8%）、4ゲーム6.36相当（53.0%）。sampled peak RSSは194.9/776.9MiB。システム全体GPUはどちらもmedian6%、p95 10%。GPU値にはデスクトップや他アプリが含まれ、MCTSのGPU利用率と解釈できない。

Value併用の密集32/d4本測定：全体997.42→887.67ms、leaf_evaluationから子Snapshotを除いた時間26.50→24.44ms。後者は推論以外の軽い条件分岐も含む上限で約2.8%。仮にこれをGPUでゼロ時間にしても全体の約3%しか削減できず、転送/dispatch/バッチ化の追加コストがある。GPU導入は今回は見送った。

- CPU逐次最適化：今回実装し、同じ探索木を保った時間短縮を確認。残る主因はネイティブ物理。
- multicore：現在の4独立ゲームが既にCPUを使う。Task.RunでUnityオブジェクト/物理Sceneを触らない。root並列探索は別Unity workerが安全な候補だが、16×4本の独立UCTは1本64反復と同じ探索ではない。訪問数/returnの統合、乱数・chance・GO方針とCPU競合を別実験で検証する必要がある。未実装。
- GPU：GTX1070はCUDA CC6.1だが、既存環境はCPU推論。GPU対応runtimeの互換性/転送/小バッチ費用を確認せず依存関係を入れ替えていない。今は優先しない。
- GPU物理：Unity組込み2DはBox2D。PhysicsScene2DにGPUへ切り替える設定はなく、3D PhysX GPU機能と混同しない。独自GPU物理への置換は接触/合体/GOの一致リスクが大きく今回対象外。
- native world/prefix再利用：solver cacheを含む中間Sceneを分岐cloneできない。使い終わったworldを再配置して同じだと仮定するpoolや近似盤面transpositionは実装していない。既存の厳密な最終edge cacheのみ維持。

cleanup_scheduleは約3msだが、実破棄は非同期。A/B後のScene数0を確認。cleanup_window_msは実完了までのフレーム待ち込みの壁時計で、純粋な破棄CPU時間ではない。全Scene解放を2フレーム固定で判定した最初の試験は待ち不足になり除外（bench_single）。正規のsingle_02/fourは上限付きで実完了まで待ち、全件0を確認した。

Viewer実通信の4画面では16手のPlan中GC0カウント合計328→263、headlessでは373→311。MonoのGC1/GC2も同じカウントになり得るため3種類の停止を足し算しない。停止時間そのものは未測定。詳細profilerにもallocationがあるのでこれを通常時のGC回数と同一視しない。長時間メモリ安定性は未検証。

## Viewer・操作間隔：実測と限界

32/d4、同seed群・同fixture・各worker序盤2手＋密集2手（密集は毎回restore）。両variantで計72手。固定A/Bとは異なり、UDP受信まで実盤面が動くので初期状態/tick/選択位置は完全同一とは限らない。

|条件|序盤plan median 旧→新 ms|密集plan median 旧→新 ms|Viewer active fps 旧→新|
|---|---:|---:|---|
|m1v|225.30 → 245.63|874.37 → 1023.46|8.38–8.38 → 8.53–8.53|
|m4v|324.88 → 323.39|1072.72 → 1015.29|7.45–9.00 → 8.05–9.89|
|m4h|381.67 → 374.78|1261.93 → 1112.70|なし → なし|

1画面の新処理には1295.99msの遅いPlanがあり、同じ5514物理tickでもnative物理/コピー等の複数区分が遅くなっていた。OS負荷・CPUクロック・GC待ち等のどれかは特定できず、単に最適化により常時遅くなった/常時改善したとは判断しない。固定root反復では前後一致と平均的な短縮を確認。

4画面のUnity最大Update間隔は1231→1110ms、headless1295→1134ms。1画面は893→1308ms（外れ値）。全Plan中、通常Update/FixedUpdate/フレーム/UDP送信/video更新の増分は0のまま。Viewerだけの問題ではなく、そのPlayerの実ゲーム更新も止まる。4Playerは別々に停止しViewer全体は独立して更新する。

公開済み映像→Tk投入p95は4画面で旧59.6–72.8、新57.8–67.8ms。Tk投入fpsはモニター実表示/録画fpsと同じではない。capture/共有メモリ/表示/古い映像保持時間の分布はruntime_*_summary.jsonに保存。Viewer自体のコードは8-Dでは変更していない。

起動と1.2秒flush待ちを含む短時間harness全体の実成功step数/資源サンプル期間では、4画面16手/10.39秒=1.54→16手/10.83秒=1.48手/秒、headless16手/7.33秒=2.18→16手/7.31秒=2.19手/秒。これは定常状態の性能ではないが、今回の短時間試験で実ゲーム全体の手数/秒の向上が実証されたとはいえない。1ゲームは4手/9.95→4手/10.97秒。CPU/RSSは4画面25.4→24.5% / 785→792MiB、headless43.4→44.3% / 561.6→561.5MiB。

同じepisodeの序盤連続落下だけ（4workerで各1間隔）の4画面中央値は、実時間969→926ms、ゲーム内時間610→560ms。headlessは実時間1039→981ms。1画面は774→811msと短縮なし。密集試験は各手前にResetするので密集の連続落下間隔は測定していない。

4画面・新処理の序盤は、前落下→次判断約526ms（うちstep完了→次要求約27ms）、判断約342ms、その後横移動/合法落下待ち。密集時の判断中央値は約1017ms。これらの中央値を単純に足して1回の落下間隔にしない。各行動の原データで別計測している。

落下後観測は全件約500ゲームms（25tick）で、cooldown .4秒より長い。今回、移動開始時のcooldown残りは全件0で、追加cooldown待ちが主因ではなかった。横移動とcooldownは本来重なって進む。AI/手動の有効速度は既存設定7.5×0.5=3.75 world単位/ゲーム秒で維持。

思考中のゲーム時計増分は0。ただし終わった次フレームにUnityが遅れたFixedUpdateをまとめて実行する。maximumDeltaTime=.333秒の上限もあり、実時間とゲーム内時間は一致しない。特に密集試験では落下直後の25tickの一部が同一フレームで消化され、500ゲームmsの観測が約160実msになるケースもあった。思考時間を短縮すると横移動/観測の壁時計の見え方も変わる。25tickを.4秒や.25秒へ短縮する変更はしていない。

## 正確性・互換性テスト

- フル状態A/B：mcts240組（1＋4worker、4盤面4設定、warmup＋2本測定）、mcts_value8組。選択位置・全node visits/Q/chance統計・全反復action/chance・報酬・合体・GO・tick数・公開Snapshotハッシュが一致。時刻/果物系列/同じrootを保ち、元盤面/スコア/Unity RNG不変とprefix再現guardも通過。
- 詳細計測なし追加A/Bは1＋4worker×4設定×3組=60組。全木統計/行動/得点/合体/GOが一致。この追加試験では全反復Snapshotのハッシュは作っていない。
- 既存Unity native MCTS selftest 861項目、Path selftest26項目成功。これは861ゲームではない。public Advance/既存two_step/GO fallback/未知NEXT/重複実行防止等の既存回帰を含む。
- Editor TestAndBuild成功。Value入力24ケースの特徴誤差0、Python/C#点数最大誤差0.00006103515625点。モデルSHA256 7e95aee3f462afb9faa02843b9612bb018f0051b0c68349d1a89d508d2631d2cで維持。
- Python125テスト成功。新規集計のファイル解放を直した後、関連4テストを再実行して成功。全体テストに含まれる合成データの一時学習以外、既存モデル再学習なし。
- 実通信72手：drop_success、score_before＋reward＝返却scoreを確認。新規C#例外なし。headlessのunsupported shaderログはnographics由来。短時間のみで、GO見逃し率や高得点能力を再推定する長時間ゲームはしていない。
- 接触cache、per-tick予測GOとUpdate実ゲームGO、Destroyのtick/frame差という8-Cの限界は解決していない。最適化前後が一致したことは実ゲームと常に一致する証明ではない。

## りんごのタグ問題

Unity/Assets/Scenes/Prefab/apple.prefab:19 は m_TagString: fruit。GameManager.cs:49–50 と予測IsGameOverは大文字Fruitを要求する。そのためtype5りんご自身はHasCollidedがtrueでラインより上でもGO要因にならない。果物の物理/合体/得点処理が消えるわけではなく、他の正常タグ果物は引き続きGO対象。今回のタグcacheも同じ条件を保持し、修正していない。タグ修正はゲーム環境と学習ラベル/過去得点比較の条件を変えるため、別承認→環境IDを変えてデータ/モデル互換性を評価する必要がある。

## 次の優先順位

1. 実ゲームの小規模な得点比較と固定root品質回帰を先に用意する。高速化の前後一致は示せたが、MCTSがheuristic/valueより強い、64が16より強いという証明はない。長期比較はユーザー実行。
2. 操作タイミングの明確化。既存STEP8C_TIMING_DESIGN.mdに従い、観測窓と合法最短落下を分離する設計を確認してから(x,τ)へ進む。今回未実装。
3. Viewer滑らかさを優先するなら非同期/別予測workerの設計。root取得tick・入力予約・結果失効・実適用時の状態差を定義してから小さく試す。Task.Run移設は不可。CPUを追加消費するので速度向上は保証しない。
4. MCTSアルゴリズム/rollout品質の改善。今回物理の約半分がrolloutに使われたが、単純に回数/深さを減らさない。固定盤面の候補順位と少数seed得点で検証。
5. さらなるCPU逐次高速化。native物理、不要な観測の残り、署名allocation等を再計測。Scene使い回しはsolver cache/衝突順を変えない保証が必要で大規模には実施しない。
6. CPU root並列は1ゲームでの効果だけでなく4ゲーム総throughput/CPU/RSSを測り、UCT統合後の品質変化も別評価。既に6.36論理core相当使うため安易に増やさない。
7. GPUは現状最後。Value全除去でも約3%の上限で、GPU物理への作り直しはリスクが大きい。

この順序は「MCTSが高得点かを確認する」「合法な時刻と停止を正しく扱う」を速度の数値だけより優先する提案。待機行動/非同期/並列探索/GPUを今回実装したという意味ではない。

## 再現コマンド（新しいoutput名を使う）

PowerShellで、他の収集Playerがポート31000〜31007/28000台を使用していない時に実行。通常プレイのコマンドは変わらず、新ビルドのUnity/Builds/Step6/SuikaGameAI.exeを使う。追加の長時間収集は不要。

```powershell
cd C:\SuikaGameAI\Python
.\.venv\Scripts\python.exe benchmark_mcts.py --output outputs/step8d_user_01 --games 4 --fixtures outputs/step8c_01/dense_safe_fixture.json --repeats 2 --timing-only
.\.venv\Scripts\python.exe analyze_mcts_benchmark.py --input outputs/step8d_user_01 --output outputs/step8d_user_01_summary.json
```

全状態の照合と処理内訳を取る時は--timing-onlyを外す。--mode mcts_valueでValue併用を測れる。--games 1で単体。出力が既にある場合は上書きせず失敗する。

## 保存先・資料

すべてC:/SuikaGameAI/Python/outputs/step8d_01/配下。正式固定計測bench_single_02/bench_four、通常に近いtiming_single/timing_four、Value測定value_profile、Viewer実通信runtime_baseline/runtime_optimized、native_regression、各*_summary.json、action_*.json。profile_beforeは最適化前の初期切り分け。bench_singleは待ち不足で中断した未採用の予備試験。ビルド失敗の旧logも削除せず保持し、final_build.logの最終成功を採用した。

Unity公式: [2DはBox2D](https://docs.unity3d.com/2022.3/Documentation/Manual/PhysicsSection.html)、[Unity APIのthread制約](https://docs.unity3d.com/2022.3/Documentation/Manual/overview-of-dot-net-in-unity.html)、[PhysicsScene2D.Simulate](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/PhysicsScene2D.Simulate.html)。NVIDIA公式: [GTX1070 CC6.1](https://developer.nvidia.com/cuda/gpus/legacy)。
