# 高得点・ダブルスイカAIの調査と開発戦略

調査日：2026-10-28。現在の実装、過去の検証資料、完了済み収集ログ、一次研究資料を照合した。**推薦は仮説であり、強化成功の報告ではない。** 収集設定の実測と実行案は [DATA_COLLECTION_STRATEGY_20261028.md](DATA_COLLECTION_STRATEGY_20261028.md) に分けた。

## 1. 何を作るべきか

最有力案は **短期のUnity物理探索＋観測タイミングを合わせた長期価値学習＋少数の連続座標候補**。最初は1手＋価値、必要なら2〜3手の確率的な探索へ進む。現在のMCTSは基準として残し、同じ実時間予算で比較する。優れた価値推定が得られるまでMCTSへ無理に接続しない。

最初に実装すべきものは新しい大型モデルではなく、**同一の意思決定状態から複数行動を評価する、時刻・復元誤差の監査付きデータ生成／順位評価基盤**。現時点の最大の不足は「あるゲームの最終得点を予測できるか」以上に、「同じ状態で行動を変えたとき、本当に良い行動を識別できるか」を測る教師・試験である。既存の2手全探索、PathSession、実通信診断を再利用する。

物理再現の誤差が大きければ、その盤面からの復元を実ゲームの反実仮想の正解とは扱わない。シミュレーター内部の比較として別管理し、実ゲームでの順位一致を確認する。この入口を通過できない場合は、まず新規の実ゲーム中に判断境界を正確に記録して検証する。過去ログが不完全だから学習全体を停止する必要はなく、既存の実測return学習は並行して行える。

## 2. 調査範囲と確度

- コード：MctsPlanner、MctsAdaptiveControl、MctsDepthControl、StepPlanner、DropCandidateGenerator、SuikaPredictionPath、SuikaPhysicsSimulator、FruitEvolution、PlayerController、GameManager、収集スクリプト、方策モデル／学習処理。
- 資料：STEP7-C比較、8-C/K/R/S/AB/AC/AE、方策学習・成功抽出比較レポート等。過去の実測と今回の新規集計を明示的に区別した。
- 新規集計：2026-10-28 19:16:31 JST時点の完了記録80件のうち自然GO・学習利用可・errorsなし78件。中断2件を除外。進行中のゲームは読み込まない。17,531判断の軽量decisionsログを集計、約3.05秒。全原ログの物理軌跡を今回再監査したものではない。
- 新しいUnity実行・学習・Playerビルドはゼロ。既存収集へのCPU競合を避け、保存済み診断結果を再利用した。
- 文献は著者論文、大学・学会・公式実装を優先。論文全文を確認できた資料と、公開要旨・書誌・コードまで確認した資料を混同しない。Suikaの一部学位論文は要旨取得後のPDF再取得に失敗した。論文の優劣を再現したわけではない。

## 3. 現在のMCTSの正確な意味

### 3.1 選択・展開・逆伝播

`MctsPlanner.Select` は、即GO／落下失敗と判明した枝を安全な枝がある場合に除外する。未訪問は標準ではindex順。既訪問は

`mean_points / 55 + C * sqrt(log(max(1,node.visits))/edge.visits)`

で選ぶ。最終root行動は原則最大訪問数、同数なら平均点。全GO時は既存fallbackであり、任意の追加高さ罰則はない。

行動を実行したあとchanceを抽選し、対応するdecision子を作る。標準では**新しいactionまたは新しいchance子に入ると残りはrollout**。rolloutは候補indexの一様乱数であり、全候補の物理検査をしてから最善を選ぶ方式ではない。選んだrollout行動を実際に物理計算してGOになったら終了する。

各反復の物理状態はrootから独立したnative worldへ短いprefixを再生する。木の訪問edgeにだけ、1回ずつ `finalScore - edge開始時score + leaf` を戻す。標準reward-onlyはleaf=0。2手目で初めて得た点も反映される。GO後の追加行動や価値加算はしない。深さ制限内の得点最大化と、自然GOまでの総得点最大化は同じ目的関数ではない。

### 3.2 既知果物とchance

PlayerControllerはAの落下直後にSpawnFruitを呼び、元NEXTのBを保持果物にし、その先のCを新NEXTとして表示する。従って、Aの判断時はA/Bが既知、Bの判断時にはB/Cが既知。MCTSはライブの隠れた生成乱数を読まず、公開prefabスロットの分布からCをサンプルし、その観測で子を分ける。

現在の生成は `Random.Range(0, fruits.Length)` なのでスロット一様。ただし型が重複したprefab構成では型一様とは限らない。分布は環境カタログから取るべきで、常に各型1/5とハードコードしない。reward-onlyで最終評価に影響しない未落下NEXTは既存の縮約を行う。

正しい期待値は概念的に `E_C[max_b Q(次の観測B,C,b)]`。CがBの判断時に公開されるのに `max_b E_C[...]` に固定すると適応能力を失う。一方、Aの行動を未来の確定Cに合わせるのは情報漏洩。さらに先の果物系列も、各行動時点で公開された範囲だけを使う。

### 3.3 最大深さ≠探索木の深さ

今回の完了ゲーム内の全判断・全到達actionを集計した。下表はその深さで**木に登録された行動の割合**であり、選択行動の正解率でも実ゲームの成功率でもない。rolloutを含めて到達した物理経路と区別する。

|指定深さ／回数|ゲーム数|深さ2の木action|深さ3|深さ4|深さ6以降|
|---|---:|---:|---:|---:|---|
|4／128|32|81.40%|4.48%|0.01%|対象外|
|4／256|19|90.67%|15.88%|0.22%|対象外|
|4／512|10|95.31%|34.19%|1.87%|対象外|
|6／256|13|90.62%|15.80%|0.06%|深さ5・6は0%|
|6／2048|2|98.82%|75.06%|8.49%|深さ6は0%|
|12／8192指定|1|99.58%|90.90%|33.86%|深さ6は約0.01%、7〜12は0%|

深さ6／256の非root再訪は深さ3で2,170回、深さ4以降ゼロ。深さ12／8192も深さ6以降のaction再訪はゼロ。従って、現在の深さを16へ増やすと「16手先で適切な行動比較が成立する」という説明は誤り。深いランダム方策のreturnサンプルは得られるが、長期戦略の解決とは別である。

chance×行動によって序盤のdecision枝数が概ね乗算的に増える。ただしGO、偏った選択、最終chance縮約があるため、単純な25の累乗を実際の木ノード数と同一視しない。

### 3.4 安定性と過去の改良

STEP8-Rの同一密集盤面・32回では探索seed8191/8192/8193の選択が0.5/0.75/0.5。固定seedでの再現性と、別探索seedでの判断安定性は別物。今回は新規の再実行をしていない。

STEP8-Kで `.125→.125` が15点、`.5→0` が18点と実通信で再現した。しかし後者は既存MCTSも試しており、4手評価では別の行動を選ぶ。短期で点が出る経路だけを正解としない。

Open-loop、追加decision展開、shuffle、幾何rollout等は既に診断されている。単なるノード数・被覆数の増加を成功と扱わない。ここから同じ局所的な設定変更を繰り返すより、評価対象と教師の改善を優先する。

## 4. 物理と時刻：学習より前に揃える条件

25tickは落下後の観測窓。移動・cooldownを含む総操作時間ではない。既存cooldown0.4秒、AI移動速度3.75、dt約0.02秒。移動距離により階層ごとの総tickが変わる。

STEP8-Rでは密集盤面の初手.5/.75で、追加落下なしでもそれぞれ30/44tick後に+3点が生じた。同じ総経過tickで比較すれば、初手.5で100tick後の「次を0へ」と「待機」の差は+36点。ただし旧18点経路の+3点をすべて第2落下の効果とは言えない。

同検証では得点・合体・GO・lineage集合が一致した条件でも、最大位置差0.03305、速度差0.20918、角度差7.24955度が残る。元native worldのsolver接触キャッシュや睡眠内部タイマーはJSONから完全復元できない。枝の継続は同じPathSession内なら接触履歴を維持するが、cold rootから実ゲーム履歴が戻ったことにはならない。

実GOはGameManager.Update、予測はtickごと。Destroy遅延・接触直後・合体直後の順序差も残る。現在のFruitEvolutionではpreview／mergingを除外し、HasCollidedと中心yの厳密なライン超過で判定する。合体親がライン上にいてもmerging中は除外し、生成果物にHasCollidedを継承する。GameManagerのクラス初期値0.9は実環境の設定値ではないため、実PlayerのmetadataとScene値0.83で確認する。今回は変更しない。

同期MCTSはUnityメインループを占有する。探索に10秒かかっても、その間に実ゲームが500tick進むわけではない。ただし要求間や応答前後の数tick、FixedUpdate catch-upは残る。探索のwall秒、物理tick、実際の落下tickを独立して保存する。

**重要度：最上位**はGO近傍・時刻差で行動順位が逆転する系統誤差。探索を32768回へ増やしても解消しない。スナップショットに位置・速度・角速度・Collider等があっても、完全な物理チェックポイントと呼ばない。

## 5. 機械学習が改善しなかった原因候補

最新の固定構造比較はTrain116ゲーム66群、Val26ゲーム15群、独立Test11ゲーム11群。成功Train19ゲーム17群、Val6群、Test2群。通常／成功2倍／4倍のTest選択一致は25.79/26.33/25.17%。2倍の差のseed bootstrap区間は0を含み、Top2と訪問KLは通常より悪い。成功ゲームの全行動を多く抽出するだけでは、成功への寄与を教えたことにならない。

|原因候補|確認できたこと|未確定部分と識別実験|
|---|---|---|
|量・独立性|判断数より独立seed群が少ない。高探索>=1024はTrain2群、Val/Test0群|学習曲線をseed群単位で作る。Testを再調整に使わず新holdoutを固定|
|教師の弱さ／曖昧さ|128回のroot訪問分布は平均正規化entropy0.926、最大訪問占有率30.8%|entropyは教師の誤りの証拠ではない。同じ盤面を別探索seedで再評価し、教師自身の一致率とモデル一致率を比較|
|学習目標の不一致|選択模倣は現在MCTSを再現する目標。ゲーム得点改善を直接最適化しない|return学習・行動対の順位学習を同じ盤面で比較|
|behavior混合|ゲーム終端returnは収集方策の性能を含む。上限・深さ・行動集合が混在|方策群ごとの校正、同じ条件のサブセット、behavior条件付き診断。倍率sqrt(iterations)は品質の保証ではない|
|入力とモデル|各果物を共有MLP→mean/max、候補xはpool後に追加。候補と個々の果物・果物同士の関係は直接計算しない|現構造に局所距離等を追加した安価な対照、候補条件付きpool、少量Attention/GNNの順で比較。Deep Sets全般の不可能性と断定しない|
|予測状態との分布差|現実ログの完全特徴と予測後の欠損／cold接触は違う|同一状態のfeature parity、欠損flag、予測状態での校正を分離|
|反実仮想の不足|未選択候補の実returnは存在しない|選択された後の最終得点を他候補にコピーしない。複数行動の独立継続で順位教師を作る|

旧STEP8-ACのMAEは新265.45、旧構造再学習276.30、score+count ridge272.84点。順位評価のTestは条件が揃った4seedで、Valに一貫した優位がない。平均MAEを少し下げても、同じ状態の僅かな行動差を識別できる保証はない。GO直前の過大評価を得点帯・残り手数・行動後状態で分ける必要がある。今回旧Testを再評価してモデルを再選択してはいない。

## 6. 関連研究から使えること／使えないこと

以下の適性・必要量はこのPCと現在データに対する設計判断。論文がSuikaの強化を保証したという意味ではない。データの絶対必要数はモデル・環境次第なので「何件で必ず成功」とは示せない。

### 6.1 探索

|方法・一次資料|仕組み／実績|本件への適性、コスト、実装と検証|
|---|---|---|
|UCT [R1]|平均returnに探索bonusを加える木探索|現状を再利用。確率分岐と短い予算で深い比較が不足。理論上の漸近性を有限回の品質保証にしない|
|PUCT／AlphaZero [R3]|学習方策を探索priorに、価値を葉に利用。囲碁・将棋等|方策が弱いままpriorを強くすると偏りを増幅。良いprior・価値を得てから。現在のUnityに接続可能だが、学習と探索の双方を検証する負荷は高い|
|Expectimax／確率的浅探索 [R2]|行動で最大、観測結果で確率平均|公開NEXTと少数スロットに合う。2〜3手＋価値なら有力。ただし全展開は行動×chanceで増大し、2048ほど安価な遷移ではない|
|Progressive Widening [R4]|ノード訪問に応じ有限サンプルの行動／確率結果を増やす|連続xに合うが、追加候補の比較不足・早期終了との干渉がある。既存は9上限で等間隔になりやすい。候補増加率を得点改善と同一視しない|
|Gumbel／Sequential Halving [R5]|少ないroot評価で行動を比較する配分法|rootの判断を目的とする代替案。優れたpolicy/value前提の原論文の改善を、無学習UCTへそのまま移せない。単純な対応乱数付きroot逐次比較を先に対照とする|
|MPC＋CEM [R6]|複数の行動列を評価して分布を更新、毎手計画し直す。連続制御で使用|1次元xに利用可能。非NNの候補生成にもなる。接触の不連続、多峰性、未来公開情報に応じた適応を固定列が表しにくい。モデル学習型PETSの性能を本Unityへ外挿しない|
|Beam Search|各層の上位K状態を保持|実装容易、2〜3手診断には良い。即時得点0の有望枝を切る危険とchanceの偏った選別がある。chanceは高得点結果だけを残さず確率質量を扱う|

### 6.2 価値と強化学習

2048は合体後のafterstateを価値学習し浅い探索を足す成功例がある [R2,R7]。ただし離散格子・安い正確な遷移で、動く剛体、接触履歴、移動時間のある本件とは異なる。n-tuple表をそのまま使うより、**行動で生じた結果を価値評価する分離**を参考にする。特定の角配置は移植しない。

|学習法・資料|教師／特徴|本件の判断と検証|
|---|---|---|
|Monte Carlo return [R8]|自然GOの実追加得点|今あるログで最も低リスク。分散と収集方策依存がある。得点帯MAEに加え同状態行動順位を試す|
|TD(0), n-step, TD(lambda) [R8]|実報酬＋次状態推定のbootstrap|大量の終端待ちを減らせるが、誤推定伝播・off-policyが課題。まずMCとの同一split比較。中断をGO=0にしない。操作間加点も区間に含める|
|Afterstate V / action-conditioned Q|物理操作後の盤面、または(s,x)を評価|本命。前者は物理による局所幾何を利用、後者は安いが中間xの外挿が危険。現在スコアを再加算せず追加得点の単位を統一|
|Distributional value [R9]|期待値だけでなくreturnの分布|低得点側と高得点尾部の情報に利点。ただし確率的returnの幅とモデルの知識不足は別。データが少ない段階で分布を信頼区間と呼ばない|
|DQN / Double DQN [R10]|有限行動のQ学習、過大評価を抑える改良|5/9候補では候補だが任意xを自然に扱えない。GO誤差はDouble化だけで直らない。新たな対話データが必要|
|Actor-Critic / PPO [R11]|価値推定で方策勾配を支援、PPOは更新を抑制|Unity ML-Agentsの再利用性はある。ただしon-policy相互作用が高コスト。既存ログを最大活用したい現段階の第一選択ではない|
|SAC [R12]|連続行動・off-policy・entropy正則化|任意xへ進める代替本命。ただし固定5点ログだけでは未観測xのQが不安定。広い行動coverageとオンライン検証が前提|
|CQL / IQL [R13,R14]|観測外行動への過大評価を抑えるoffline学習|混在ログを使える。しかし存在しないダブル成功や中間xの正しい価値を作り出せない。保守性で強い改善を避ける可能性もある|
|ExIt [R15]|探索で改善→学習→学習を探索へ戻す|長期の推奨ループ。単発の模倣と違い、探索側が改善した教師を作ることを検証。最初からAlphaZero全体を実装しない|
|MuZero / Sampled MuZero [R16,R17]|潜在遷移＋policy/value、連続行動はサンプル集合で探索|将来の時短候補。今は正確なUnityがあり、稀な接触GO・合体の学習モデル誤差と必要データが大きい。全面置換を急がない|

単独プレイヤーでは通常の対人self-playに相手は存在しない。ここで有効なのは更新した自分の方策によるデータ再収集・policy iteration。学習用イベントを増やすだけで方策模倣が強化学習になるわけではない。

### 6.3 盤面表現と非NN対照

|表現|推論規模の目安|利点|問題／採否試験|
|---|---|---|---|
|既存Deep Sets [R18]|果物数Nに概ね比例|小型・可変個数・既存コードを再利用|低幅のpoolで局所関係が圧縮される。候補xと果物の相対距離を与える対照を先に試す|
|CNN|格子面積に比例|局所関係と空間共有|画像化で速度・接触・小さな隙間を落とす可能性。数値情報が既にあるので画素から再認識する必要は薄い|
|GNN / Interaction Network [R19]|近傍edge数E、全対ならN^2|同種ペア・接触・距離を直接表現|関係の定義と過学習に注意。少量のデータで自動的にDeep Setsより強いわけではない|
|Set Transformer / Attention [R20]|通常N^2、一部近似は線形化|果物間・候補との関係を学習|少数seedで大規模化は危険。幅・総学習予算を合わせた比較が必要|
|ridge、木系回帰、n-tuple的幾何特徴|少量データでも開始しやすい|非NNの強い対照、入力問題を診断|連続座標と非局所接触を手製離散化する損失。特徴は入力に使い、位置攻略の報酬として固定しない|

GPUはNNの学習・多数盤面のbatch推論には有用だが、現在のPhysicsScene2DをそのままGPUで大量評価する機能ではない。GTX1070の既存環境で対応するライブラリを別途確認してから導入する。物理エンジンをGPU版へ置換した性能を現行と同一視しない。

### 6.4 Suika固有の資料

Julian Poelsma (2025) の修士論文 [R21] は自作SuikaでMonte Carlo系が他手法・人間比較より良かったと要旨で報告。検索で取得できた本文5.3.4〜5.3.5には、1手50simulation、2手50simulation、計算量を近づけた2手25simulationの比較がある。ランダムな候補提案、等間隔、型合わせの比較もあり、短いMonte Carlo探索を真剣な対照にする理由になる。ただし同じ予算なら2手が常に勝つという表ではない。一方 Nik Glavic (2025) の学士論文 [R22] はUnity/ML-Agentsの学習agentが人間に匹敵／上回ると要旨で述べる。両者の結果から本環境のMCTS/PPOの優劣は決まらない。比較相手・ルール・物理・得点基準が揃わず、今回詳細の再現検証もしていない。これは「SuikaではMCTSだけが正解」の根拠にならない。

公開コード [R23,R24] も存在するが、独自シミュレーター・円形当たり判定等を使う例で、現UnityのCollider、cooldown、GO判定と互換ではない。掲載スコアを本プロジェクトのベンチマークへ混ぜない。Threesについては今回、同等条件で優劣を判断できる一次実験を確認できていない。

## 7. 5択を超える方法

現固定候補は正規化xの等間隔で、実座標は保持果物のCollider・壁から求めた合法範囲へのLerp。5点でも型ごとの合法範囲は変わる。grid9は全階層で9点。board-fiveは端／中央等のcoverageを残して同種や上部の隙間を幾何学的に利用する。

既存wideningは単なる訪問閾値だけでなく、区間幅と端点の平均returnを使うpromising追加、および幅を優先するcoverage追加を交互に行う。budgetedはnode訪問・残り反復・残り時間・最低訪問も監査する。ただし最大9・最小間隔1/8では最終的に固定9と同じ位置へ行きやすく、.37付近を自由に細分化する方式とは異なる。

|方式|コストと利点|主要リスク|推薦|
|---|---|---|---|
|固定9/17/31|実装簡単、coverage明確|同じ反復で1候補の訪問減少。chance枝と掛け算|9を対照、17以上を無条件標準化しない|
|Coarse-to-Fine|同じ物理予算を局所比較へ配分|初期順位誤り、1手0点による絞り込み誤り|複数の山＋探索用の広域候補を維持。短期評価だけで切らない|
|Q(s,x)で任意点評価|多数xのbatch推論が安い|訓練が5点なら中間xは未検証|中間座標を実際に試す追加データを先に作る|
|座標を生成するpolicy|少数の良い候補を提案できる|平均回帰では左右の良い位置の中間という悪手を出す|混合分布／複数候補。uniform成分を残す|
|SAC等で直接x|本来の連続行動を扱う|相互作用コストと未観測行動のQ誤差|中期の代替案、現ログだけで完成とはしない|
|学習提案＋Unity検証|安価な提案と真の短期遷移を分担|モデルと物理の誤差双方が残る|本推薦。まずrootで少数、非rootへは後から|

候補生成案：5anchorを維持し、上位複数候補の隣接区間から局所候補と広域候補を予算内で混合する。最初から一番の周りだけに限定しない。間隔は合法範囲とCollider寸法をメタデータとして記録するが、スコアの滑らかさやLipschitz性を仮定しない。物理接触で評価が急変するため、補間は提案であって値の正解ではない。必要量はまず3種類の盤面で、既存5点＋4中間／jitter点、共通の仮想futureサンプル複数を試す診断から設計する。

## 8. 推奨するafterstate／価値の厳密な定義

初手Aを実行し、移動・cooldown・post25を終えた時点をhとする。`r=Score(h)-Score(root)`、その時点の追加得点価値をVとし、`Q=r+E_C[V(s_h with held=B, NEXT=C)]`。Vはhより後の点だけを予測し、遅延合体がh後ならV側へ含める。終端GOではV=0。rや合体点を別途再加算しない。

ここでCはAの判断時に未知。候補は、(1)公開分布のC別Vを平均する、(2)NEXT未知flagを明示したmarginal Vを、同じ入力条件で学習する、の2つ。既存の「NEXT既知」モデルへ未知C=0を入れて同等と主張しない。Cはpreviewで物理盤面へ触れないため、同じAの物理結果に対しCだけ替えてNN評価できる範囲がある。ただしこれは特徴と時刻の同値性を確認してからの最適化案。

2〜3手探索ではBの行動はサンプルとして公開されたCに条件付けてよい。その先のDをまだ知らない段階でDごとに都合のよいBを選ぶのは不可。共通乱数を使う場合も、評価側にある系列をactorへ渡さない。

初期学習は実測MC return＋将来スイカ生成を別headで校正する。これらは収集方策の結果で、最適価値ではない。次に同状態の複数行動継続による順位教師を追加する。TD/n-stepはその後。予測不確実性が大きい／入力が訓練外なら既存探索へ戻すか多めに物理評価する。任意の不確実性罰則を標準得点へ混ぜず、独立した比較条件にする。

## 9. 構成の比較と採否

|構成|強化の可能性（未証明）|計算／データ|実装・再利用|主リスク|
|---|---|---|---|---|
|現MCTSを大予算化|短期評価の分散低下|物理費用大、NN不要|最も容易|深い部分のrandom支配、予測誤差は残る|
|1手＋非NN回帰価値|早い判断、安価な対照|既存returnで開始可|容易、既存features再利用|表現不足、action順位が悪い|
|1手＋afterstate NN価値|長期情報と物理を分担|中、既存MC＋候補比較|高い再利用性|訓練／予測状態差、過大評価|
|2〜3手＋価値／sampled Expectimax|公開NEXTを活用|中〜高、分岐管理必要|PathSession再利用|chance爆発、価値誤差の最大化|
|MCTS＋価値|現行との連続性|NN推論＋物理、教師中〜多|中程度|葉価値の偏り、探索分配が依然問題|
|Policy＋Value＋PUCT/ExIt|反復的に教師を強くできる|大、学習／収集ループ|実装高|弱いpriorの自己強化、評価汚染|
|SAC／IQL等＋物理検証|任意x、専門家を超える余地|オンラインcoverage必要|中〜高|Qの未観測点誤差、収集コスト|
|MuZero型潜在探索|Unity呼出し削減の可能性|最も多い学習データ・開発量|低〜中|稀な合体／GOのモデル誤差|

推薦は1手＋価値から2〜3手へ進む案。MCTSを捨てるのではなく、**学習した長期価値が安い探索にも役立つかを先に確認できる**ため。価値が効かなければ物理探索側のroot比較・候補生成へ戻り、巨大なpolicy/value/MuZeroを一括実装しない。

## 10. ダブルスイカをどう学ぶか

コード上、type10同士は消滅し**その接触で追加ゲーム得点は加算しない**。空き空間が生まれたあとの得点効果はあり得るが、ダブル回数と最終得点は別指標。スイカ生成も、大きい果物の生成過程の得点とイベントを二重にゲーム得点へ加えない。

今回集計78ゲームではdoubleイベント0。報酬を巨大にしても成功軌跡は増えない。Go-Explore [R25] の状態へ戻って探索する発想や、2048の段階的な練習 [R7] を参考に、スイカ生成後の実在盤面から複数方策・未来系列で継続する。復元誤差を監査し、人工／復元開始／自然開始を別集計。最終的な達成率は自然開始の未使用seedで測る。

中間イベントはスイカ、スイカ＋メロン1/2、2スイカ、doubleを初回callbackで記録し、unknown maskを維持。現在収集Playerの旧イベントにはメロン共存の一瞬を完全観測できない部分があり、新しい記録Playerへの変更は次の収集からのみ。特定の位置へ報酬は与えない。

Multi-taskでscore、各到達確率、生存等を別出力にし、追加報酬は別台帳に保持。最初は補助教師として使い、ゲーム制御へ無条件に足さない。double重視と点数重視のPareto比較を行い、通常得点を落として中間目標だけを稼ぐ挙動を検査する。HER [R26] は達成した別目標を再利用できるが、未達doubleを達成ラベルへ変える方法ではない。

## 11. 開発順と進行・撤退条件

|段階|実装・学習|検証して次へ進む条件|失敗した場合|
|---|---|---|---|
|0：行動比較基盤|decision tick／移動／cooldown／公開観測を固定、同rootの5+中間候補、未来系列を評価側で管理|まず序中終3盤面の繰返し。点・合体・GO・最初の分岐tickを追跡。予測と実行で順位を比較|cold復元を実測と区別。GO不一致が多い部分は先に修正／診断|
|1：価値の基準比較|既存Deep Sets／ridge・木回帰でMC追加点＋WM補助教師、配置報酬なし|seed群holdout、通常／成功、GO直前校正、行動順位が単純対照を安定して上回る|大型モデルへ飛ばず教師・時刻・behavior混合を切分け|
|2：浅い探索へ接続|1手＋V、未知Cの周辺化、既存MCTS維持|同wall時間で選択品質・GO不一致・短時間実通信を確認|価値なし物理探索へfallback、NNの有効範囲を狭める|
|3：限定的な連続x|上位複数＋広域候補、少数点追加、実測branch data蓄積|中間xのrank精度と予算を合わせた実ゲーム得点改善|5/9を維持。学習外xの予測最大値だけで選ばない|
|4：反復policy improvement|新方策の盤面を収集、重要状態を再探索、TDを対照追加|同累積CPU-hourの改善、未知seedの自然GO成績|古いデータへ閉じた模倣を反復せずcoverageを再設計|
|5：稀な目標の練習|WM後のcontinuation、目標別価値、必要なら小型Attention/GNN|自然開始でWM2/double率と得点を両方改善|中間目標のproxy報酬を弱める／無効化|

固定盤面は開発用、モデル選択はVal、最終判断は未使用seedの自然GO。平均／中央値／高得点率／スイカ1個・2個／double率／GO誤差／wall秒を報告。ゲームseedを独立標本とし、同seed方式を対応比較、信頼区間を付ける。途中終了は右打切りとして分離。比較時は同じ実時間予算と別に同じ物理tick予算も示し、単純な予測return上昇を成功と呼ばない。

## 12. 参考文献（実在・一次資料を確認）

各行の本件適用は上の提案。著者の成果がこのUnityで再現されたという意味ではない。

- **R1** Levente Kocsis, Csaba Szepesvari (2006), *Bandit based Monte-Carlo Planning*, ECML. [著者PDF](https://sites.ualberta.ca/~szepesva/papers/ecml06.pdf), DOI 10.1007/11871842_29.
- **R2** Marcin Szubert, Wojciech Jaskowski (2014), *Temporal Difference Learning of N-Tuple Networks for the Game 2048*. [著者PDF](https://www.cs.put.poznan.pl/wjaskowski/pub/papers/Szubert2014_2048.pdf), DOI 10.1109/CIG.2014.6932907. 検索側の本文を確認、再openは取得失敗。
- **R3** David Silver et al. (2017), *Mastering Chess and Shogi by Self-Play with a General Reinforcement Learning Algorithm*. [論文](https://arxiv.org/abs/1712.01815).
- **R4** Adrien Couetoux, Jean-Baptiste Hoock, Nataliya Sokolovska, Olivier Teytaud, Nicolas Bonnard (2011), *Continuous Upper Confidence Trees*. [著者アーカイブ](https://hal.science/hal-00542673). 書誌・検索本文確認、PDF入口はアクセス制限。
- **R5** Ivo Danihelka, Arthur Guez, Julian Schrittwieser, David Silver (2022), *Policy improvement by planning with Gumbel*, ICLR. [論文PDF](https://openreview.net/pdf?id=bERaNdoegnO). forum HTMLは認証画面、検索でPDF要旨を確認。
- **R6** Kurtland Chua, Roberto Calandra, Rowan McAllister, Sergey Levine (2018), *Deep Reinforcement Learning in a Handful of Trials using Probabilistic Dynamics Models*. [論文](https://arxiv.org/abs/1805.12114).
- **R7** Wojciech Jaskowski (2016 preprint), *Mastering 2048 with Delayed Temporal Coherence Learning, Multi-Stage Weight Promotion, Redundant Encoding and Carousel Shaping*. [論文](https://arxiv.org/abs/1604.05085).
- **R8** Richard S. Sutton, Andrew G. Barto (2018), *Reinforcement Learning: An Introduction*, 2nd ed. [出版社](https://mitpress.mit.edu/9780262039246/reinforcement-learning/), [著者稿](https://www.incompleteideas.net/book/bookdraft2018mar21.pdf).
- **R9** Marc G. Bellemare, Will Dabney, Remi Munos (2017), *A Distributional Perspective on Reinforcement Learning*. [論文](https://arxiv.org/abs/1707.06887).
- **R10** Hado van Hasselt, Arthur Guez, David Silver (2015 preprint / AAAI2016), *Deep Reinforcement Learning with Double Q-learning*. [論文](https://arxiv.org/abs/1509.06461).
- **R11** John Schulman, Filip Wolski, Prafulla Dhariwal, Alec Radford, Oleg Klimov (2017), *Proximal Policy Optimization Algorithms*. [論文](https://arxiv.org/abs/1707.06347).
- **R12** Tuomas Haarnoja, Aurick Zhou, Pieter Abbeel, Sergey Levine (2018), *Soft Actor-Critic: Off-Policy Maximum Entropy Deep Reinforcement Learning with a Stochastic Actor*. [論文](https://arxiv.org/abs/1801.01290).
- **R13** Aviral Kumar, Aurick Zhou, George Tucker, Sergey Levine (2020), *Conservative Q-Learning for Offline Reinforcement Learning*. [論文](https://arxiv.org/abs/2006.04779).
- **R14** Ilya Kostrikov, Ashvin Nair, Sergey Levine (2021 preprint / ICLR2022), *Offline Reinforcement Learning with Implicit Q-Learning*. [論文](https://arxiv.org/abs/2110.06169).
- **R15** Thomas Anthony, Zheng Tian, David Barber (2017), *Thinking Fast and Slow with Deep Learning and Tree Search*. [論文](https://arxiv.org/abs/1705.08439).
- **R16** Julian Schrittwieser et al. (2019 preprint / Nature2020), *Mastering Atari, Go, Chess and Shogi by Planning with a Learned Model*. [論文](https://arxiv.org/abs/1911.08265).
- **R17** Thomas Hubert et al. (2021), *Learning and Planning in Complex Action Spaces*. [論文](https://arxiv.org/abs/2104.06303).
- **R18** Manzil Zaheer, Satwik Kottur, Siamak Ravanbakhsh, Barnabas Poczos, Ruslan Salakhutdinov, Alexander Smola (2017), *Deep Sets*. [論文](https://arxiv.org/abs/1703.06114).
- **R19** Peter W. Battaglia, Razvan Pascanu, Matthew Lai, Danilo Rezende, Koray Kavukcuoglu (2016), *Interaction Networks for Learning about Objects, Relations and Physics*. [論文](https://arxiv.org/abs/1612.00222).
- **R20** Juho Lee, Yoonho Lee, Jungtaek Kim, Adam Kosiorek, Seungjin Choi, Yee Whye Teh (2019), *Set Transformer: A Framework for Attention-based Permutation-Invariant Neural Networks*. [ICML](https://proceedings.mlr.press/v97/lee19d.html).
- **R21** Julian Poelsma (2025), *Creating an AI that plays Suika game*, Leiden University, master's thesis. [大学公開論文](https://theses.liacs.nl/pdf/2024-2025-PoelsmaJJulian.pdf). 表紙・要旨と検索側で本文5.3.4〜5.3.6／表3〜5の一部を確認。全文の再取得は不安定で、物理・全実験条件の詳細は未検証。
- **R22** Nik Glavic (2025), *Development and training of reinforcement learning agents for the Suika computer Game*, University of Maribor, bachelor's thesis. [大学書誌・要旨](https://dk.um.si/IzpisGradiva.php?id=94996). 本文の具体的スコアは未検証。
- **R23** Gnaij12, *SuikaBot*, 公開実装、公開年未確認（参照2026-10-28）。[GitHub](https://github.com/Gnaij12/SuikaBot).
- **R24** MattJacobs30, *SuikaReinforcement*, 公開実装、公開年未確認（参照2026-10-28）。[GitHub](https://github.com/MattJacobs30/SuikaReinforcement).
- **R25** Adrien Ecoffet, Joost Huizinga, Joel Lehman, Kenneth O. Stanley, Jeff Clune (2020 preprint / Nature2021), *First return, then explore*. [論文](https://arxiv.org/abs/2004.12919).
- **R26** Marcin Andrychowicz et al. (2017), *Hindsight Experience Replay*. [論文](https://arxiv.org/abs/1707.01495).
- **R27** Tom Schaul, John Quan, Ioannis Antonoglou, David Silver (2015 preprint / ICLR2016), *Prioritized Experience Replay*. [論文](https://arxiv.org/abs/1511.05952).

## 13. 今回の成果物・未実施事項

新規：この資料、収集戦略資料、`Python/analyze_collection_research.py`、専用6テスト、`outputs/strategy_research_20261028_01` と `_02` の分析資料。01は初回集計、02がentropy追加後の正本。既存MCTS・モデル・学習処理・Unityソースは今回変更しない。commit/pushなし。

専用6テストは成功。自然GOと中断の区別、進行中ファイルの除外、worker-hour分母、入力ファイル不変、壊れた完了記録の除外を確認。既存Unity/Python全回帰は今回走らせておらず、以前の346件成功と今回の検証を混同しない。新方式の強さ、復元精度改善、4/8並列性能、GPU実装は未検証。
