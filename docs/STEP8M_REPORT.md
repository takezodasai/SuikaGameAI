# STEP 8-M：chance分岐と公開情報条件付きOpen-loop診断（2026-10-24）

## 結論
**標準採用しない。** 公開保持果物/NEXTを区別したOpen-loop試作Bは、序盤/中盤/密集の32回・深さ4では統計共有が発生せず、従来chance方式A_commonと全探索経路・得点・GO・物理tickが一致した。計算時間は約5.4〜6.8%増。再訪効率も高得点化も改善したとは言えない。
純粋なaction履歴だけのOpen-loopを既定へ入れたのではない。未来の公開情報への適応を残すため、今回のBは **action履歴＋その時点の保持type＋公開NEXT type** をノードキーにした比較用方式。行動履歴だけの方式は探索内のC別方策を平均化するため、要件に合わないリスクがある。実ゲームで毎手再計画することと、探索中にCに適応することは別である。

## 実行済みrollout10組の結果
実際の保存先：`Python/outputs/rollout_compare_20261024_013111_a55ec512`。今回20ゲームを再実行せず、`outputs/step8m_01/rollout_audit`へ再監査した。自然GO10組/20ゲーム、除外0。seed/公開系列共通prefix/環境/同バイナリ/共通chance表/得点報酬保存/実操作座標を再確認。
|指標|random common|guided90 common|
|---|---:|---:|
|平均得点|2163.5|1875.5|
|中央値|2125|1826|
|最小〜最大|1667〜2831|1563〜2692|
|勝利数|7|3|
|平均操作数|228|203.5|
|ゲーム単位の平均判断msの平均|574.04|588.80|
|GO見逃し|2|2|
|GO過剰予測|0|1|

ペア差guided−random：平均−288点、95%ペアbootstrap区間[−554.1, −8.2]。seed752500〜752509の10組を標本単位とし、手を独立標本にしていない。今回の10組ではguidedに不利な結果である。小標本bootstrap区間であり、すべてのseedで劣る普遍的証明とはしない。これは共通chance条件の比較で、旧legacy乱数順序との比較ではない。既定randomを維持する判断を裏付ける。

## 1. 公開タイミングと従来木
PlayerController.cs:131 DropFruit はAを落とした直後、172行でSpawnFruitを呼ぶ。SpawnFruit（207行）は元NEXT Bを新しい保持果物へ昇格し、241行のChooseNextFruitでCを新しいNEXT表示にする。従って：
- Aの判断：保持AとNEXT Bが公開。Cの**真の確定値**は使えない。
- Bの判断：保持BとNEXT Cが公開。Cのtypeを条件にできる。
- Cの判断：保持CとNEXT Dが公開。
ChooseNextFruit（179行）はRandom.Range(0,fruits.Length)。MCTSも同じ公開prefabスロットの一様分布を使用する。実際の隠し乱数を読まず、C/Dを仮説サンプルとして進める。

従来MCTSはaction edgeごとに `chance[slot] -> child` を保持する。未知Cが異なればB判断のchildが異なり、それぞれ別に訪問と点単位returnを蓄積する。SelectはUCT、未訪問edgeをExpansion、`rollout=expanded||newChance` で残りを一様randomにする。新しいchance子が作られても、その子のdecision edgeが当該反復で選ばれるとは限らない。
STEP8-Kの9候補.125の3/4訪問が別Cへ分かれ、各子arrivals=1/visits=0のままになったのはこの構造による。確率を最大化したり、隠しCを知って選んだバグではない。1サンプルのrewardは各訪問nodeへfuture score差として1回ずつ逆伝播される。

## 2. Bの実装
設定 `tree_policy=public_open_loop`。既定は `chance`。Bは同期・grid・mcts・random rollout・1ゲームに限定。既存frame/board-five/value/guidedの通常方式は維持する。
ノードキーは `OpenNodeKey(actionHistory, publicFruitKey)`、publicFruitKeyは保持type:NEXT type。**過去のchance値すべてでは条件付けしない**ため、以前に落ちた果物が異なっても、同じaction履歴と現在公開の果物の組へ戻れば統計を共有できる。
深さ4のreward-only最終手では、さらに後に落とさないNEXTは従来のirrelevant-chance collapseに従ってサンプルせず、不使用の−1とする。実ゲームでそのNEXTが表示されないという意味ではなく、評価時間外なので利用しないという意味である。rootの公開NEXTは深さ1設定でも保持する。

### 物理状態とGOの隔離
- 各反復は従来通りfresh root/Forkから全prefixをnative scene内で再生。中間の異なる盤面や接触キャッシュを使い回さない。
- nodeの訪問/returnだけ共有。GO・drop_success・即時候補は**完全なStateSignatureごとの別配列**に保存し、Select直前に現在状態へBindOpenStateする。
- 同じStateSignatureから同じactionを再生した結果は、状態別のtransition signatureと厳密照合。物理誤差を許容して一致扱いしない。
- 異状態へleaf cacheを流用できないためBではleaf再利用を無効にした。今回A/Bともcache hit0、物理省略0だった。
- 同一action履歴でも公開果物が違えば別nodeであり、Cに応じた違うaction統計を持てる。ただし同じ公開果物で盤面形状が違う場合のfuture returnを平均化する制約は残る。盤面に完全に適応する最適方策を保証しない。

## 3. 情報テスト
追加native InformationTestsとPython監査を実施。
- 保持typeだけ違う場合、NEXTだけ違う場合、同じhistoryでもキーが分離すること。
- 異なる公開contextの統計へ異なる良いactionを与え、Selectが0/4を別々に選べること（構造的単体試験。実ゲームで最適な適応を学べた証明ではない）。
- 同じ統計nodeにboard-AのGO情報をBindすると除外、board-Bへ切り替えると誤って除外せず、board-Aへ戻すと再び除外すること。
- C=slot0/4を明示サンプルし、`.5,0,.5`を独立native worldで再生。保持/NEXT列は例として空盤面で `0:1 → 1:0 → 0:1` と `0:1 → 1:4 → 4:1`。中盤/密集は `1:4 → 4:0/4 → 0/4:1`。
- 3落下後は両方D=type1となり、共有キー `/2/0/2|1:-1` が同じ。しかしfinal StateSignatureは3盤面とも異なっており、異なる物理盤面を保持していることを確認。
- 密集のこの2ケースは得点0+18+21でともにGOなし。**chanceにより実際のGOが逆転するnative正例は今回確認できなかった**。GO情報隔離は単体試験、通常MCTSの13終端GOは固定試験で確認したが、GO見逃しの解消や全状態でのGO一致は未証明。

Bの全反復で、保持typeがA/B/前々回chance、NEXTがB/直前chanceに対応すること、node keyが実際の公開情報と一致すること、rollout開始境界、ノード/edge訪問数、異なる状態数を別Python実装で検証。futureの真のCをroot keyに入れていない。サンプルCはAのaction選択後に生成され、B以降で公開された仮説として使う。

## 4. 固定盤面比較
同root、MCTS seed8191、grid5、32回、深さ4、post25、random rollout。A_common/Bは同一iteration×depthのchance表。旧乱数順序を保つlegacyも独立対照として保持。
|盤面|方式|選択X|root訪問数|root平均return（点）|物理tick|全計算ms|
|---|---|---:|---|---|---:|---:|
|early_fixture|A_chance|0.25|6,7,6,7,6|0.000,0.143,0.000,0.143,0.000|6860|177.48|
|early_fixture|B_public_open_loop|0.25|6,7,6,7,6|0.000,0.143,0.000,0.143,0.000|6860|187.15|
|mid_fixture|A_chance|0.5|6,7,7,6,6|0.000,0.857,3.429,0.000,1.000|6729|565.33|
|mid_fixture|B_public_open_loop|0.5|6,7,7,6,6|0.000,0.857,3.429,0.000,1.000|6729|601.76|
|dense_safe_fixture|A_chance|0.5|7,4,10,5,6|27.000,18.250,39.700,17.600,27.000|5987|884.35|
|dense_safe_fixture|B_public_open_loop|0.5|7,4,10,5,6|27.000,18.250,39.700,17.600,27.000|5987|944.44|

各盤面ともA/Bは**全32反復のaction列/chance列/得点/合体/GO/tick/rollout位置が一致**。ノード33個、異なる物理状態を同時に蓄積したnodeは0。最大深さ4のこの予算で有用な共有が起きたことにはならない。
|盤面|A/Bの2action-prefix再訪数|訪問済み非root node|rollout回数（第1〜4手）|Advance回数|GOサンプル|最大sample得点/合体|
|---|---:|---:|---|---:|---:|---|
|序盤|11/11|8/8|0,20,32,32|128/128|0/0|1/1|
|中盤|11/11|9/9|0,20,32,32|128/128|0/0|15/1|
|密集|14/14|9/9|0,20,29,26|119/119|13/13|62/5|
再訪数は同じ2action prefixの出現数−1の合計であり、同じ観測nodeへ戻った回数とは違う。密集の32非root node中23個はarrivalsがあってもdecision edgeの訪問0。action-onlyの表面上の再訪数だけで改善としない。

密集の18点prefix `.5→0` はA/Bとも5回。15点prefix `.125→.125` は今回の固定5候補には存在しないため、発見率の評価対象外。9候補の実装/STEP8-Kの81診断は維持しているが、今回追加の9候補探索は行わなかった。将来return平均28.406点/最大62点、終端GO13/32もA/B一致。これは4手のサンプル値であり、2手18点の保証でも最終実得点でもない。

### なぜ共有が起きないか
Bを判断する時のCは公開情報なので残す必要がある。次のC判断では保持CとNEXT Dも残る。従って最初の2〜3階層は従来chance履歴に近い分割が必要になる。以前の果物を忘れて共有できる深いnodeへ、32反復では十分に再訪していなかった。情報を失わずにshare keyを変えるだけでは、この設定の分散は解消しなかった。

## 5. コスト・近い予算での比較
B/A時間比は序盤+5.45%、中盤+6.44%、密集+6.80%。各1回・逐次測定でGC/温まり等の影響があり、統計的な速度差の推定ではない。別の初回試験でも同じ経路/再訪で追加コストが観測された。
A/Bの総tickが全3盤面で完全に同じなので、同じ反復数かつ同じ物理更新予算で比較できている。それでも共有効果は0でBが遅い。余分な時間は状態別signature/GOキャッシュと公開情報/診断記録等による。今回は時間を合わせるための反復増減を行っていない。
Unity割当サンプル増分（MiB）は序盤8.82/8.61、中盤11.19/10.69、密集15.33/14.22。前の試行の遅延解放/GC/開始量が異なるので、Bの省メモリ化とは解釈しない。managed開始/終了、Unity開始/最大は元reportへ保存。OS working-setの瞬間ピークや長時間のメモリ増加は未測定。Bの状態別cacheは予算/盤面次第で追加メモリが必要。

## 6. 実通信・回帰
seed753300、1PlayerずつA/B各4手。両方0点/0合体、全落下成功、GOなし。平均判断224.68/241.42ms。score/reward保存、選択候補と実座標、公開系列、共通chance表、tree/情報監査を通過。両方step_limit終了なので自然GOペア0、強さ集計から除外。探索木異常/新しい例外なし。自然GO直前やGO見逃し・過剰予測の正例、長時間メモリは未確認。Viewer/GUIのプレイテストは今回行っていない。
Python179テスト成功。最終PlayerでMCTS861/rules84/path26/frames58＝1029チェック成功。追加native情報/幾何テスト成功、Value parity24/Playerビルド成功。追加テスト単独起動で読み込みパス不足が一度発生したため、test_open_treeにテスト対象のパスを明示し全テストを再実行して成功した。
legacyの3固定盤面は以前と選択/全ノードの従来統計/総tick一致（追加した公開context等の診断フィールドは比較から除外）。PhysicsSimulator/PlayerController/TwoStepPlanner/FruitEvolution/GameManagerの作業前後SHA256一致。ゲームのCollider/物理/GO.83/出現確率/環境ルール版は変更していない。

## 7. 変更ファイル・関数
- Unity/Assets/Scenes/Script/MctsPlanner.cs:79 BindOpenState（現在盤面のGO/候補へ切替）、89 OpenNodeKey、113 PlanFrames（opt-in木管理、261付近でaction history＋公開果物から共有node取得）。SelectのUCT式/最終選択/点単位Backpropagationは維持。Bはstate-local transition照合、leaf cache無効。
- Unity/Assets/Scenes/Script/SuikaPredictionPath.cs:172 PublicFruitKey：予測world内の現在公開果物だけ取得。既存Advance/Runの物理処理は変更なし。
- Unity/Assets/Scenes/Script/StepPlanner.cs:28 tree_policy既定chance、38-39でBの設定制限。
- Unity/Assets/Scenes/Script/SuikaCandidateProbe.cs:8 Search/9 Config、107 InformationTests、163付近の明示情報テスト。既存81経路診断/rollout比較を維持。
- Python/src/suika_ai/unity_env.py:416既定/423-424検証、parallel_play.py:197の新方式1ゲーム制約、play_parallel_ai.py:60の設定導線（--tree-policy）。
- Python/analyze_tree_probe.py:6 validate_open_report、37付近analyze：公開情報・展開境界・訪問数/状態数監査と固定盤面集計。
- Python/compare_tree_ai.py:9 settings、13 validate_geometry、34 summarize：同seed自然GOペア比較と除外監査。
- Python/tests/test_open_tree.py：既定保持/不正設定/1ゲーム制約/公開タイミング/隠し情報/訪問保存/不正leaf cache/状態数の検証。
- 本報告とDEVELOPMENT_LOG/PLANへ追記。

## 8. 実行コマンド
比較ツールは用意したが、今回の同予算診断では効果0のため**このまま長時間比較を優先することは推奨しない**。任意で自然GOまで10組比較する場合：
```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\tree_compare_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_tree_ai.py --pairs 10 --seed 753500 --base-port 38600 --max-steps 3000 --output $out
```
A/Bともgrid5/sync32/depth4/post25/random、共通chanceあり。tree_comparison.json / tree_pairs.csvに平均・中央値・得点範囲・勝敗・seed差・ゲーム単位95%bootstrap区間・GO不一致・最大果物type・時間を保存。途中終了/通信異常/公開情報不一致/異なるchance表/報酬異常/実座標不一致は除外。比較用同バイナリ/同環境/公開系列共通prefixも確認。n<2は区間なし。

短い操作だけ見る場合：
```powershell
$out = "outputs\tree_smoke_" + [guid]::NewGuid().ToString("N")
.\.venv\Scripts\python.exe .\compare_tree_ai.py --smoke --pairs 1 --max-steps 4 --seed 753300 --output $out
```
単一ゲームでBを明示指定するにはplay_parallel_ai.pyの従来コマンドへ `--tree-policy public_open_loop --mcts-common-chance --ai-mode mcts --planning-execution sync` を追加（rollout=random、grid）。既定tree-policy=chance、common-chanceなしが旧legacy。Bを4ゲームで実行する変更はしていない。

保存先：outputs/step8m_01（verified_fixed.jsonl、verified_analysis.json、information_only.jsonl、各テスト、rollout_audit）、outputs/step8m_smoke_01。既存データは上書きしていない。

## 9. 次に試すべき1方式
**chance子ノードの生成とdecision actionのExpansionを分離する方式**を推奨。現在の `rollout=expanded||newChance` は、新Cの子を作っただけでもrandom rolloutへ移行する。これが23個のdecision訪問0ノードを残した直接の設計要因である。
次の別実験では「新chanceそのものをdecision Expansion枠として消費せず、未訪問actionを1個展開する」案を検証する価値がある。C別nodeは維持するため公開情報を失わず、出現確率・実得点・物理ルールを変える必要もない。新しい予測を追加するのではなく、既に進める経路のどのdecision edgeに統計を蓄積するかを変える案。ただしaction分布やrollout開始位置が変わるので、判断品質は固定盤面/近いtick予算/自然GO得点で改めて比較する必要がある。今回この変更は行っていない。

|代案|今回の結果からの評価|
|---|---|
|chance生成/decision Expansionの分離（推奨）|公開情報と確率を保ち、実際に訪問0が残る箇所へ直接対応。比較的小規模に検証可能|
|情報状態を維持した共有prior|C別の本統計を残し、短期得点等だけ優先順位へ共有する余地。仮想訪問/得点の二重計上と重みバイアスへの検証が必要|
|chance Progressive Widening|再訪集中は可能だが、既知5種の分布と期待値を歪めない扱いが必要|
|UCT探索回数配分の変更|cold Cへ再訪を促せるが、未展開actionの情報自体が乏しい。先にExpansion切替を切り分ける|
|位置周辺の段階探索|候補不足には対応するが、今回のchance分散/訪問0の原因への直接策ではない|

純粋Open-loopの共有を増やすために公開NEXTを捨てる変更、根拠のないGOペナルティ、rolloutの同時変更は行わない。新方式の標準化・大規模比較・深さ増加は今回の結果から正当化できない。

最終：develop維持、commit/pushなし、既存ログ/モデル/AI/Viewer/4ゲーム/フレーム方式/2手診断を保持。新しい学習・長時間ゲーム収集は実行していない。
