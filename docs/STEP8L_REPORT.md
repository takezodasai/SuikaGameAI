# STEP 8-L rollout改善の試作と比較（2026-10-24）

## 結論
従来randomを既定のまま、幾何guided rolloutを明示opt-inで追加した。標準採用しない。
密集盤面の同一chance表・5候補32回では、guided90は探索内GOを13→5、平均サンプルreturnを28.41→32.28点にした。ただし既知18点prefixの訪問は5→2回で、発見率向上の証拠ではない。9候補64回の15点prefixはrandom3回、guided90/mixed50とも0回。短期スモーク4手はrandom10点/1合体、guided90は0点/0合体。自然GO得点の改善は未検証で、一貫した品質改善と判断できない。

## 現在のrollout・確率モデル
MctsPlanner.PlanFramesは、非rollout時にUCT Select、未訪問edgeを展開する。展開edgeまたは初めてのchance子に入ると、その反復の残りをrolloutにする。従来は `rng.Next(candidate_count)` で一様に行動を選ぶ。1反復のExpansion後にも物理を深さ上限まで進めるが、rolloutの全手にtree edgeを作るわけではない。同じ行動と同じchance子の履歴を再訪したとき、そのノード内の訪問が蓄積する。
合法Xは常に既存候補とGetDropRange由来。tree側は既知の即時GO/落下失敗候補を、他の候補がある場合は除外。従来rolloutは実行前にGOを知るための追加予測をせず、GOになったら実際の予測遷移で終端にする。guidedも法的条件・GO条件は変えず、幾何値だけで順位付けする。

PlayerController.ChooseNextFruitのRandom.Range(0,fruits.Length)とMCTSのNext(slots)は、同じ公開prefabスロットの一様分布。chanceはUCTで最大化せず無条件サンプリングされる。現在保持Aと公開NEXT Bを使い、A落下後に表示される未知Cを仮説としてサンプルし、次の意思決定では表示済みになったCを参照できる構造。liveの非公開乱数/NEXTは読まない。reward-only最終未落下果物に関する既存chance collapseも維持。
今回確認した範囲に確率モデルの不具合は見つからなかった。5種のCへ再訪が分散することは現方式の探索効率上の問題であり、確率のバグとは区別する。接触キャッシュ・実ゲームのrender GO順序の既存誤差は別問題として未解決。

報酬は最終スコア−各訪問時点スコアを点単位で逆伝播。reward-only leaf=0、valueモードは従来通り。移動中・待機中・落下後の加点も既存PathSession経由で含む。深いGOでも既得点を消さない。UCT、Expansion条件、逆伝播、得点、終端ルールは変更していない。

## 新しい式
追加Simulateは0回。PathSession.RolloutScoresは実Collider boundsと盤面果物だけを読む。保持/NEXTのpreviewは盤面集合から除外し、隠れたNEXTも公開NEXTのtypeもrollout順位付けには使わない。
各候補iの保持Collider幅と重なる盤面果物のうち、最上部の上端tを求める（何もなければ床）。最上部が同種なら
`G_i = clamp01(1 - abs(dropColliderCenterX-fruitColliderCenterX)/(heldHalfWidth+fruitHalfWidth))`
とし、異種なら0。同じ高さの同種候補はG最大を使う。
`D_i = clamp01((t + heldHalfHeight - colliderOffsetY - (GO_y - band))/band)`
`band = .15 * (GO_y-floor_y)`
`S_i = G_i - D_i`

G/Dの両方を0〜1にして同じ尺度で初期重み1ずつ。横の近さはCollider半幅で正規化、Dの.15は既存のdanger_band_fraction初期値に合わせた試作値。**最適な重みとする根拠はなく、今回の盤面へ合わせて調整していない。** GO近傍以外の高さ減点は追加していない。Dは幾何的近さであり実際のGO確率ではなく、GO判定や候補除外には使わない。

これは垂直な影の包絡の近似であり、滑り込み・側面接触・遅い合体・連鎖・移動時間中の盤面変化を評価しない。最高点のAABBによる遮蔽近似も、Circle/Capsuleの正確な接触予測ではない。実際の状態遷移はこれまでのPhysicsScene2Dで計算するため、Collider/物理設定を変更した近似物理ではない。

A：random（一様）。B：90%はS最大、10%一様。C：50%はS最大、50%一様。S同点時は一様に選ぶ。幾何scoreの係数を実ゲームの報酬に足したり、UCTのpriorに流用していない。

## 乱数の比較条件
既定はmcts_common_chance=falseで、従来通りactionとchanceが同じSystem.Randomを消費する。randomでは新しいNextDoubleを呼ばず、以前の乱数順序を保つ。
比較用opt-inは別Random(seed XOR 0x356A9)から全iteration×depthのchance表を事前生成し、その位置から読む。実行されなかった深さも表にはあるが、これは実ゲームの未来ではなく公開分布からの仮説であり、行動を選ぶ関数からはアクセスしない。guidedの追加乱数消費がchance標本をずらさない。
A/B/Cは同じ表、同じMCTS seed8191、同じ凍結root。使ったchanceが表と一致すること、同じ比較内の表が一致することを監査。GOによる深さ差や行動による到達盤面の差があるため、同じ物理的未来を完全に共有する比較ではない。
**A_commonと従来legacyも同一ではない**。共通表を使うだけで密集の選択1→.5へ変化した。効果をguidedだけに帰属しないため、全3盤面でlegacy対照も測定し、以前と全tree統計/選択/tick一致を確認。

## 固定5・32回・深さ4・post25（各1測定）
深さ別rollout列は第1/2/3/4手の使用回数。rootからrolloutにはならないので第1手は0。
|盤面|方式|選択X|root訪問数|root平均return（点）|深さ別rollout回数|tick|計算ms|探索内GO|
|---|---|---:|---|---|---|---:|---:|---:|
|early_fixture|legacy|0.0|7,6,6,6,7|0.14,0.00,0.00,0.00,0.14|0,19,32,32|7282|194.86|0|
|early_fixture|A_random|0.25|6,7,6,7,6|0.00,0.14,0.00,0.14,0.00|0,20,32,32|6860|155.87|0|
|early_fixture|B_guided90|0.5|6,6,7,7,6|0.17,0.33,1.00,0.86,0.00|0,17,32,32|7335|175.10|0|
|early_fixture|C_mixed50|0.25|7,7,6,6,6|0.00,0.14,0.00,0.00,0.00|0,18,32,32|6710|158.42|0|
|mid_fixture|legacy|0.0|7,7,6,6,6|2.14,2.14,0.00,2.00,2.50|0,16,32,32|6867|521.03|0|
|mid_fixture|A_random|0.5|6,7,7,6,6|0.00,0.86,3.43,0.00,1.00|0,20,32,32|6729|511.64|0|
|mid_fixture|B_guided90|0.25|6,7,6,7,6|0.00,4.71,0.00,0.86,1.00|0,18,32,32|7123|541.47|0|
|mid_fixture|C_mixed50|0.25|6,7,7,6,6|0.00,1.43,0.86,0.00,1.00|0,19,32,32|6707|522.76|0|
|dense_safe_fixture|legacy|1.0|5,5,7,6,9|15.00,11.60,28.71,27.00,37.67|0,22,28,22|5818|780.23|16|
|dense_safe_fixture|A_random|0.5|7,4,10,5,6|27.00,18.25,39.70,17.60,27.00|0,20,29,26|5987|824.90|13|
|dense_safe_fixture|B_guided90|0.5|6,4,8,8,6|29.00,11.25,39.12,36.88,34.33|0,17,32,32|6257|850.35|5|
|dense_safe_fixture|C_mixed50|1.0|5,3,8,7,9|22.60,5.33,35.25,31.00,38.22|0,20,30,27|6076|824.44|12|

legacy/A/B/Cの落下予測Advance回数：序盤・中盤は全128。密集は114/119/128/121。rollout方策は追加の物理予測を行っていないが、GOが減ると深い手まで計算するため総tickが増える。
A/B/Cの最大サンプル得点（序盤）は1/3/1、中盤15/15/9、密集62/62/70。最大合体数（密集）は5/5/6。最大値は採用手の保証得点でも長期実得点でもない。
密集で.5→0のprefix発見回数はA5/B2/C2。固定5には.125がないので15点prefixの発見可否をこの条件で評価しない。序盤/中盤の同じ座標列が、密集の15/18点を意味するわけでもない。

### 近い物理予算での補助比較
保存済み全反復から、3方式の最小総tick以下に収まる**完了反復prefix**だけを取り出した。独立に時間制限をかけた試験ではない。時間はiteration elapsedの合計であり、初期準備/最終report/一部解放の外側コストを含まない。
密集共通予算5987tick：
|方式|使用反復|tick|prefix時間ms|prefix選択|平均return|GOサンプル|
|---|---:|---:|---:|---:|---:|---:|
|A|32|5987|819.38|.5|28.41|13|
|B|30|5940|800.41|.75|32.53|5|
|C|31|5872|791.05|1|30.19|11|
全32回と違いBの選択が.75になる。近いコストでも平均returnはBが高いが、異なるrollout方策のreturnは同一の真の最適価値ではなく、これだけで判断品質や高得点化を証明しない。序盤/中盤のprefix結果もanalysis.jsonに保存。

### 9候補・64回・密集だけの追加診断
|方式|選択X|tick|Advance|全体ms|15点prefix|18点prefix|GOサンプル|
|---|---:|---:|---:|---:|---:|---:|---:|
|A|.625|10611|230|1509.99|3|5|31|
|B|.5|11900|247|1756.19|0|4|14|
|C|1|11655|238|1734.53|0|5|24|
従来legacy9/64では15点prefix0だったが、共通chanceでrandomの乱数順序も変わった今回は3回。guidedの改善とは言えない。B/Cは依然0であり、15点prefixへ特別誘導する実装/調整はしていない。
近いtickのprefixはA64回10611tick、B57回10551tick、C58回10506tick。平均サンプルreturn24.48/34.84/29.09、GO31/12/22、選択.625/.625/1。4手到達は47/59/51回（全64）。

## 計算コスト
5/32のBはA比、序盤+12.34%、中盤+5.83%、密集+3.09%。Cは+1.64%、+2.17%、密集ほぼ同じ。単発測定で順序/GC/経路差があり、速度差の統計的推定ではない。
密集のrollout選択そのものはA合計.051ms、B4.451ms、C1.912ms。全rollout選択1回平均は.00067/.05496/.02483ms。9/64では.00054/.06867/.03039ms。追加幾何が全体を支配しているわけではなく、GO回避により4手まで計算する頻度が増えたことも総時間に影響する。メモリ増分は元reportに保存している（Unity経路ごとのサンプル、OSピークではない）。

## 短時間の実通信
outputs/step8l_smoke_01、同seed752300、各4手、1Playerずつ、A_common対B。Aは10点1合体、Bは0点0合体、全8落下成功、両方GOなし、平均判断268.25/252.99ms。得点/報酬保存、候補と実座標照合、環境/実行バイナリ/公開果物系列/共通chance表の監査が通った。step_limit終了なので自然GOペア数0、統計から除外。4手の得点で強弱を結論づけない。Cの実ゲーム試験と自然GO試験は未実施。新しいゲーム例外なし。GUI/Viewer操作は今回は行っていない。

## テスト・変更ファイル
Python全170テスト成功。Unity Player MCTS861/rules84/path26/frames58＝1029チェック成功。追加の幾何テスト（同種整列、異種による遮蔽、GO近傍、列挙順不変）成功。Value parity24件・Playerビルド成功。保護対象PhysicsSimulator.cs/PlayerController.cs/TwoStepPlanner.cs/gameDisplay.unityのSHA256一致。
- Unity/Assets/Scenes/Script/StepPlanner.cs:28-30 設定追加、Validate:38-39で範囲/同期MCTS制限。既定random/旧乱数維持。
- Unity/Assets/Scenes/Script/MctsPlanner.cs:35/41 計測、118-122共通chance表、151-162rollout選択、171chance取得。Select/Expansion条件/Backpropagationは維持。
- Unity/Assets/Scenes/Script/SuikaPredictionPath.cs:172 RolloutScores、211 RolloutGeometryScores。読み取り専用のCollider幾何評価を追加。既存Advance/Wait/Runの物理処理は変更なし。
- Unity/Assets/Scenes/Script/SuikaCandidateProbe.cs:8 Searchにrollout設定、GeometryTestsの追加検証、PlanFramesに設定を渡す。既存81全探索も維持。
- Python/src/suika_ai/unity_env.py:416既定/423-426検証、parallel_play.pyのrun_parallelに1ゲーム制約、Python/play_parallel_ai.py:45付近CLI/59設定。
- Python/analyze_rollout_probe.py:6 summarize_rows：制御フロー/rollout実施フラグ/chance/回数と同tick prefix監査。
- Python/compare_rollout_ai.py:9 settings、13 validate_geometry、31 summarize、80 main：自然GOペア比較・新規出力・集計。
- Python/tests/test_rollout.py：既定保持、不正設定、4ゲーム拒否、自然GOと最大果物集計、途中終了除外、chance/実行設定の不一致除外。
- 本報告とDEVELOPMENT_LOG/PLANへ追記。

## ユーザー用PowerShell
自然GOまでrandom対guided90を10組（20ゲーム）比較する場合。**両方共通chance使用の比較条件**であり、legacyの標準自動プレイを切り替えるものではない。
```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\rollout_compare_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_rollout_ai.py --pairs 10 --seed 752500 --base-port 38500 --max-steps 3000 --output $out
```
rollout_comparison.json / rollout_pairs.csvへ平均/中央値/得点範囲、勝敗、seedペア差、ゲーム単位のpaired-bootstrap95%区間、GO見逃し/過剰予測、最大果物type、判断時間を保存。step_limit/異常終了/系列不一致/座標異常/報酬異常は除外して理由を保存。n<2は区間なし。手単位を独立標本にしない。

1ゲームの任意試作設定：
```powershell
$out = "outputs\guided_test_" + [guid]::NewGuid().ToString("N")
.\.venv\Scripts\python.exe .\play_parallel_ai.py --games 1 --episodes 1 --max-steps 3000 --ai-mode mcts --candidates 5 --mcts-iterations 32 --mcts-max-depth 4 --post-drop-steps 25 --planning-execution sync --rollout-policy guided --rollout-random-probability 0.1 --mcts-common-chance --seed 752600 --output $out
```
Cはprobabilityを0.5へ。従来標準はrollout-policy=random（既定）でcommon-chanceを付けない。今回新方式の4ゲーム展開は拒否する。既存randomの4ゲーム/Viewer/frame方式は維持。

## 次の改善の判断
Bの探索内GO減少は有望な診断だが、既知経路発見や実得点の改善は未確認なので標準化/探索深さ増加へ進めない。式の重みを今回の1盤面に合わせて増やすこともしない。
次に1方式だけ試すなら、**比較用Open-loop MCTSの小規模診断**を推奨する。action履歴で統計を共有し、各反復の未知果物は公開分布から再サンプルすれば、Cの値ごとに訪問が分散する現象を直接減らせる可能性がある。ただし今のnode.signature一致やleaf cacheはそのまま流用できない。実物理worldを共有/コピーすることとは別で、各反復は従来通り独立native worldで再生する必要がある。

|次案|利点|リスク/費用|
|---|---|---|
|chance訪問の層化|出現分布を均等に監査しやすい|C=5への分散自体は残り、訪問3〜4回では再訪できない|
|chance Progressive Widening|少数outcomeへ再訪を集中できる|既知5種の確率を歪めない重み/追加条件が必要、希少局面を捨てる危険|
|Open-loop（推奨は診断のみ）|同じaction prefixへ訪問を集める|本来表示Cに適応できる将来方策を平均化して弱くする可能性。prefix照合/cache設計変更の負担は中〜大|
|探索結果再利用|再計算を減らし得る|接触予測誤差とリアルタイム失効が既知、今回の同期課題の先にある|

Open-loopが必ず強いという主張ではない。legacy syncを基準に、同root/同chance/近いtick予算で訪問集中・GO・時間を診断し、その後seedペア自然GO得点で判断する。今回これらは実装していない。

既存データ/モデル削除なし、GO.83/環境ID/物理/出現率/UCT/得点維持、develop、commit/pushなし。
