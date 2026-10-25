# STEP 8-K：探索漏れと2手全探索の診断（2026-10-24）

## 結論
- 既知の `.125→.125` は予測15点/1合体、実通信でも15点/1合体を再現した。
- 81経路の最善は `.5→0` 等の18点/2合体。**この最善経路は固定5候補にも存在する。** 前回の「固定5位置で同じXを2回なら最大3点」は25通りの全組合せ比較ではなかった。今回の結果から「候補不足が唯一の原因」とは言えない。
- `.125` の訪問3回/4回は、毎回異なるchance分岐へ入り、2手目以降がすべてランダムrolloutとなった。2手目の`.125`は物理計算で一度も試されず、対応する子ノードの行動訪問も0のままだった。
- MCTSは全探索の最善prefix `.5→0` 自体は試していた。それでも4手先の平均returnと訪問数では1.0を選ぶ。探索漏れと、異なる予測時間の評価差を分けて考える必要がある。
- 診断Dは1.177秒、153回の落下予測・7086tick。実ゲームの標準モードには組み込まず、固定盤面の診断専用とした。高得点化の自然GO実験は未実施。既定の固定5/sync32/depth4/post25維持。

## 実装と再現条件
変更は明示コマンド起動時だけ動くSuikaCandidateProbeとPython診断/解析/テスト/開発記録。通常UDPのAI設定・MCTS・two_step等に変更なし。

`SuikaCandidateProbe.cs:58 EnumeratePairs` で9×9のループを実行。**毎経路ごとに凍結rootから新しいPhysicsScene2Dを構築し、1手目を再実行、その同じnative worldで2手目を継続**する。1手目終了盤面をJSON化して復元したり、その途中のnative sceneをForkして接触キャッシュが引き継げたことにする実装ではない。兄弟間で果物/接触キャッシュを共有しない。全81回で同じfirst-indexの終了StateSignature一致を検証。

```csharp
var path=root.Fork(manager);       // 毎経路、新しいcold root
var first=path.Advance(row.first_x,25,0);
if(!path.GameOver)
    second=path.Advance(row.second_x,25,-1);
```

第1手は元の保持果物type1、第2手は元の公開NEXT type4。0は第1手のあとに表示される仮のCスロットであり、Cを落とさない2手の物理得点評価では不要な将来情報の代表値。ライブの非公開乱数/NEXTは取得しない。Cの型で戦略を条件付けすることもない。保持・NEXTは既存のpreview処理で物理盤面から分離される。第2手後は将来NEXT未知(-1)、3手目は実行しない。

`SuikaPhysicsSimulator.cs:392-422` の既存RunTicksがAI速度×dtで移動し、目標到着かつnextAllowed以後だけ落下する。移動中も既存Simulate(dt)を継続。初期クールダウンもrootから引き継ぎ、毎落下後0.4秒制限を維持。移動後さらに25tickを実行する。25tickは盤面静止まで待つ意味ではない。独自待機や瞬間移動は追加していない。

dt=.02、GO高さ約3.3、GO比率.83、環境step8e-all-fruit-go-v2。元スコア785、保持位置X=.05097544。root構築9.938ms。初期rootのcold solver cache、実ゲームのrender-frame GO/Destroy順序等の既存誤差は解消していない。予測はexperimentalのまま。

## 直接原因：ログから再構成した探索
`MctsPlanner.cs:144` はrollout中に `rng.Next(candidate_count)` を使用する。146行でedge初訪問をExpansionとし、207-212行でchance子ノードが新しい場合もrolloutへ切り替える。
```csharp
bool newChance=!edge.chance.TryGetValue(chance,out child);
// 子ノードは作るが、この反復の残りはrollout
rollout=expanded||newChance;
```

以下は0始まりのiteration番号。すべて9候補、深さ4。
|反復|第1手.125の処理|Cスロット|第2手|以降のX列|全経路得点|終端GO|
|---|---|---:|---:|---|---:|---|
|1|Expansion、新chance|1|.625|.75,.375|0|false|
|14|Selection/replay、新chance|2|.375|.75,.625|6|false|
|29|Selection/replay、新chance|4|.875|GOで終了|0|true|
|47（64回時のみ）|Selection/replay、新chance|0|.5|.375,.875|0|true|

第2手はいずれもrollout。32回の3訪問は3つの異なるC子ノード、64回の4訪問は4つの異なるC子ノードへ1回ずつ。これらの子はarrivals=1だがvisits=0、全行動訪問0。ノード作成とそのノードでの行動展開は別である。**同じ第2意思決定ノードを再訪して未訪問候補を順番に試す段階に達していなかった**。

UCT (`MctsPlanner.cs:50 Select`) は
`mean_points/55 + sqrt(2)*sqrt(log(node.visits)/edge.visits)`。
反復14の.125は2.297415（平均0点・訪問1の時）、反復29は1.889565（平均3点・訪問2）、反復47は1.638476（平均2点・訪問3）で、その時点では再訪された。しかし訪問の蓄積先が異なるchance子に分かれた。最終的な.125の平均returnは32回=2点、64回=1.5点、1.0は41点/34.083点。root UCT・生成ノード・arrivals・全edge訪問数・root平均returnを全反復再構成し、保存ログと一致を検証した。単なる回数不足という推測ではない。

報酬 (`MctsPlanner.cs:220`) は `finalScore-visit.score+leaf`。reward-onlyではleaf=0。2手目で初めて得た得点もrootへそのまま反映されるため、即時得点しか評価していないバグではない。既知prefixが試されていないため、その15点が当該rootのサンプルに入っていない。rollout中の経路は物理計算されるが、そこに新しい行動edgeを毎手作り逆伝播する方式ではない。

深さ到達数：
|条件|1手止まり|2手止まり|3手止まり|4手到達|
|---|---:|---:|---:|---:|
|5/32|0|4|6|22|
|9/32|1|5|3|23|
|9/64|1|7|11|45|
早期終了はGO等。全サンプルが4手まで計算されたわけではない。

## 81経路の結果
81組のうち第1手GO9組（同じ第1位置.875の重複9組）なので第2手を実行しない。他の72組の第2手を計算した。最終GOは25組、GOなし56組。GOは終端扱いで、それ以降の果物を落とさない。得点=first_reward+second_reward、tick=first_ticks+second_ticksを81組全件で検証。

診断上の選択は「両落下成功かつGOなしを優先、その中の2手総得点最大、同点はXの辞書順」。全経路GOならライン超過が小さく、終端が遅い経路を選ぶ診断用規則。ゲーム本体/MCTSの選択規則は変更しない。高さ・危険度は記録のみで新ペナルティに使っていない。

|経路|得点内訳|合体|tick|GO|D（分析用）|
|---|---|---:|---:|---|---:|
|.125→.125|0+15|1|55+29=84|false|.204287|
|.5→0（選択）|0+18|2|26+60=86|false|.210870|
|.5→.125|0+18|2|77|false|.209638|
|.625→0/.125|0+18|2|104/96|false|.220408/.218654|
|.75→0/.125|0+18|2|123/114|false|.232090/.230630|

Dは既存HeuristicEvaluatorの、GOライン下方15%帯における果物中心の近さ（未接触は既存重み.5）から求める最大値で、GO確率ではない。Collider上端を使う高さHとは別の指標。重み変更・GOルール変更はしていない。
既知2手は実world X -2.143014669/-1.914856195、最善は .015165448/-2.556531429。果物ごとの安全範囲が異なるので同じ正規化Xでもworld Xは異なる。

## MCTSとの判断・コスト比較
単一固定盤面各1測定。計算時間の統計的優劣ではない。
|方式|最初の選択X|root平均return（最大4手）|落下予測回数|物理tick|全計算ms|サンプルUnity割当増分MiB|
|---|---:|---:|---:|---:|---:|---:|
|A 固定5/32/深さ4|1|37.667|114|5818|884.50|15.20|
|B 固定9/32/深さ4|1|41.000|112|5506|796.54|15.32|
|C 固定9/64/深さ4|1|34.083|228|11406|1811.35|30.61|
|D 固定9/2手全探索|.5、次0|18（選択した2手の確定予測値）|153|7086|1177.01|34.95|

A/B/Cは最初の手だけを決定し、2手目を一意に予約しない。表の37〜41点は4手のサンプル平均であり、Dの18点と同じ予測時間ではない。A/B/Cの選択X=1の直後25tickは0点/0合体/GOなし。その第2手として実際に探索されたprefixをD表で再評価すると、1→0は15点/1合体/GOなし/D=.9496。9候補の1→.125も15点/D=.9488。これらは**第2手の最終決定ではなく、診断上のprefix比較**。

さらにDの最善`.5→0`は、Aで反復8/16（全4手return39点・3合体・GOなし）、Bで反復4（55点・5合体・GO）と19（39点・3合体・GOなし）、Cではさらに35/57でも試されている。MCTSは「すべての良い2手を見逃した」のではない。別のrollout結果を含む平均値・訪問数でX=1を選んでいた。深いGOのサンプルでも、その時点までの得点は消さずに逆伝播する現行仕様も維持（新しいGO罰則なし）。

Dの計測内訳：初期root構築9.94ms（D総時間の外）、81回のroot再構築148.19ms、1手目計507.59ms、2手目計444.45ms、評価計20.95ms、解放予約9.16ms、残り約46.66msは署名照合・記録等。最初の1手も毎兄弟再生しているので、9回だけの1手予測ではない。153はSimulate呼出回数ではなくAdvance回数で、Simulateは7086tick分。

Dのmanaged heap開始8,486,912→終了12,087,296 bytes、Unity割当開始108,965,447→サンプル最大145,609,807 bytes、GC0は9回。これらは逐次測定の開始/終了/経路ごとのサンプルであり、OSのworking setや厳密な瞬間ピークではない。前条件の遅延解放も含み得る。Dispose時間はUnloadScene等の**解放予約**までで、非同期解放の完了時間は未測定。結果オブジェクト生成も含めた未最適化の診断コストである。

## 実ゲームの短時間テスト
同じ固定fixtureを再ロードし、1Playerで各2手のみ実行。`live_smoke.json`に前状態/各step/reward/メタデータを保存。
- 公開保持type1、NEXT4、スコア785を確認。
- .125→.125：785→785→800、1合体、両落下成功、GOなし。
- .5→0：785→785→803、2合体、両落下成功、GOなし。
- 座標は最大2.384e-7 world unit差、移動tick30/4と1/35、落下後各25物理更新を確認。
- 最善経路の第2手は移動中+3、落下後+15。全18点を加算し二重計上していない。
- 実stepのinfo.physics_stepsは落下後tickの25、診断Dのphysics_steps/総ticksは移動込み。実drop_tickはPlayerの累積tickであり、予測の経路内tickと直接引き算しない。
- 実測所要時間は既知経路1.187+.578秒、最善経路.610+1.281秒。UDP/描画フレーム/命令間隔も含むため予測CPU時間とは別。
- 復元後の命令到着まで物理は動く。ライブの接触キャッシュ/タイミングまで厳密に一致させた試験ではない。今回確認したのは得点・合体数・落下・GOの短時間一致で、全物理状態の完全一致ではない。
- 環境metadataはrules_version=step8e-all-fruit-go-v2、GO比率float値.8299999833（.83）。自然GOまでのゲームや強さ比較は未実施。Viewer/手動GUI試験は今回未実施。

## 次に試す1方式
推奨は**一様ランダムrolloutに軽量heuristicを混ぜる方式**。今回は実装していない。

|方式|今回の原因への適合|主なリスク/費用|
|---|---|---|
|Beam Search（2手上位→深い探索）|有望prefixは見つかる|短期18点で長期有利を剪定し得る。81探索1.18秒を丸ごと追加すると同時間の改善でない|
|Progressive Widening|9行動への分散緩和は可能|今回未訪問は候補欠落ではなくchance分岐後のrandom rollout。狭い位置の追加遅れ、index安定性が必要|
|2手表による優先順位付け|有望prefixの再訪を促せる|81計算の初期費用。Cごとの価値を統合してよいわけではなく、短期バイアスに注意|
|軽量heuristic混合rollout（推奨）|実際に未探索だった第2手以降のrandom選択へ直接対応|heuristicの偏りで長期手を失うリスク。ランダム成分を残し、物理/報酬/UCTは維持して単独比較|

既存DropCandidateGenerator等の公開盤面幾何から合法候補を軽く順位付けし、一定割合は従来一様サンプリングを残す案。既知経路が必ず見つかる保証はない。今回の81表はrollout改善の固定盤面診断oracleとして利用し、採用候補の得点/GO、32回のprefix発見率、全体msを比較する。計算時間を合わせたseedペア自然GO実験が標準化の条件。81表の得点を全chanceノードにそのまま「事前訪問」として入れたり、公開Cごとの合法な次行動の違いを潰す方式は避ける。

## 変更ファイル・検証
- Unity/Assets/Scenes/Script/SuikaCandidateProbe.cs:9 Config.exhaustive、14 Row、36 PairOutcome、42 PairReport、51 BetterPair、58 EnumeratePairs、118 Startの診断分岐。旧scan/searches形式と通常起動を保持。
- Python/analyze_two_step_probe.py:5 trace_search、42付近analyze、末尾main：UCT/展開/rollout/ノード訪問の再構成、81経路保存則、最善選択の別実装監査、JSON/CSV出力。
- Python/diagnose_two_step.py:6 main：1固定盤面のA/B/C/Dを90秒上限で実行。自分で起動したPlayerだけ終了、新規出力フォルダ必須。
- Python/tests/test_two_step_diagnostic.py:5 TwoStepDiagnosticTests：9テスト（展開後/新chance後rollout、UCT不一致、偽の子訪問、81網羅、2手目加点、二重計上/GO後落下拒否、GO高得点の除外、誤った最善経路拒否）。
- docs/STEP8K_REPORT.md、DEVELOPMENT_LOG.md、DEVELOPMENT_PLAN.md。

Python全164テスト成功。Unity Player内MCTS861/rules84/path26/frames58＝1029チェック成功、Value parityとEditorビルド成功、新しいゲーム例外なし。MCTS3条件すべてSTEP8-Jとroot選択・全ノード統計・総物理tick一致。MctsPlanner/PhysicsSimulator/PredictionPath/TwoStepPlanner/PlayerController/StepPlannerの作業前後SHA256一致。未コミット変更保持、develop、commit/pushなし。

## 固定盤面の検証コマンド（PowerShell）
新しい診断を含むPlayerをビルド済み。既定fixtureは今回の密集35個。
```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\step8k_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\diagnose_two_step.py --output $out
```
このコマンドはA/B/C/Dを固定盤面で比較するだけで、自動プレイの標準を切り替えない。`analysis.json`にUCT履歴、`pairs.csv`に全81経路、`fixed.jsonl`に元のUnity結果を保存。別の保存済み盤面は `--fixture <JSONパス>`。古いPlayerに戻した場合はUnityのTools/Suika/Test Value Parity And Buildでビルドする必要がある。
今回の出力は `Python/outputs/step8k_01`。verified_analysis.json/csvに追加監査済み結果、live_smoke.jsonに実通信を保存。既存の結果は上書きしない。
