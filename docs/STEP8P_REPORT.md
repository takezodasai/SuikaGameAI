# STEP8-P：root限定Coarse-to-Fineの試作

2026-10-24 / C:\SuikaGameAI / develop / commit・pushなし。

## 結論

coarse-rootを比較用に実装し、root7候補・将来decision/rollout5候補で検証した。標準のgrid5 MCTSは維持する。追加のx=.125が中盤で選択される例は得られたが、一貫した高得点化や固定9候補に対する計算効率の優位は未確認。rootだけの改善なので、.125→.125の2手系列は探索できない。密集盤面ではroot .125自体も提案されなかった。

## 1. 既存方式

grid5/grid9は各decision・rolloutでi/(count-1)を生成し、各手の保持果物のColliderと壁から得る合法なワールドXへ変換する。候補自体は盤面位置を見ない。board-fiveは各decisionとrolloutで独立したその時点の盤面幾何を使い、左右/中央anchorを維持して同種果物や上部の隙間へ2候補を置換する。既存方式を残し、今回はgrid5/grid9と新方式だけ比較した。

## 2. 具体的な設計・選別式

1. 同じ初期盤面から既存PhysicsScene2DのPathSessionをForkし、粗5位置0/.25/.5/.75/1をそれぞれ1手予測する（移動時間/cooldown/post25含む）。実ゲーム、スコア、Unity乱数を変更しない。
2. 親候補は、落下成功かつ予測GOでないものを先にし、既存式 S=reward/score_scale-weight_roughness*R（初期値reward/55-.2R）の降順。同点は既存RolloutScoresの幾何値、さらにindexで決める。MCTSの報酬・UCTにはこのSを混ぜない。
3. 親候補の左右の隣接粗区間の中点（.125/.375/.625/.875）を提案。各親から未採用の中点を1つ選び、幾何値が高い方を優先する。同点は左。既出の区間しかない親は飛ばし、異なる2親から計2個を得る。
4. 元の5候補を全て残して2個追加し、rootの7候補をソートする。後続decision/rolloutは固定5のまま。探索回数32/深さ4/random/chance/legacy expansion/index orderを維持。

式は既存の評価を流用した初期案で、最適性を主張しない。親の1手得点が悪くても元の粗い候補は削除しないことで、2手以降に価値が出る粗い位置を保持する。ただし細かい有望位置を全て保持する保証はなく、実際に既知15点経路をカバーできなかった。

合法範囲への正規化は既存処理を利用する。中点は隣接する合法中心位置の中間なので0〜1内。各手の移動・落下時には既存のCollider安全検査を再利用し、新しい壁や形状を導入しない。幾何評価も実Collider包絡を使用するが、合体の確実性を保証する評価ではない。

公開情報は現在のAとNEXT Bまで。粗1手予測の仮想Cは代表slot0を用いるが、Cはこの1手の物理・score/R・元盤面の幾何評価に使わない。実ゲームの非公開乱数は読まない。

## 3. 実際に選ばれた追加位置

|盤面|粗い位置の順位|採用した親|追加位置|最終root候補|
|---|---|---|---|---|
|序盤0果物|[0.0, 0.25, 0.5, 0.75, 1.0]|[0.0, 0.25]|[0.125, 0.375]|[0.0, 0.125, 0.25, 0.375, 0.5, 0.75, 1.0]|
|中盤15果物|[0.25, 0.0, 1.0, 0.75, 0.5]|[0.25, 1.0]|[0.125, 0.875]|[0.0, 0.125, 0.25, 0.5, 0.75, 0.875, 1.0]|
|密集35果物|[0.5, 0.75, 0.25, 0.0, 1.0]|[0.5, 0.75]|[0.625, 0.875]|[0.0, 0.25, 0.5, 0.625, 0.75, 0.875, 1.0]|

各盤面で候補生成は探索seedに依存せず3seedとも同じ。粗5位置の今回のrewardは全て0。序盤ではR/幾何も全て同点のためindex fallbackで左側へ細分化した。中盤ではR差が約0.00035以下と小さく、予測の接触誤差や数値差に敏感になり得る。ここが今回の選別信号の弱点で、候補生成に根拠が強いとは扱わない。

各粗候補の全結果（reward、R、GO、合体、移動/待機/post加点、tick）はraw fixed.jsonlのreport.refinement.coarse、順位/親/追加位置はrefinement、総時間と総tickはanalysis.jsonに保存。中点の幾何値そのものは今回ログに含めていないため、細分化方向の細かな同点診断には追加の計測が必要。

## 4. 固定盤面・3方式・3seed

探索seed8191/8192/8193。各条件32回・深さ4・post25・sync/random/chance/legacy/index。A/B/Cで同じiteration×depthの未知果物サンプル表を使用。action数やrollout開始、GO終了が違うため同じseedでも全経路の乱数消費が同じとは扱わない。

|盤面|方式|選択x（seed順）|平均探索報酬|平均合体/反復|探索内GO/96|候補生成ms|MCTS ms|総ms|総物理tick|
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
|序盤0果物|grid5|[0.25, 0.25, 0.25]|0.177|0.094|0|0.00|162.95|166.55|6967.3|
|序盤0果物|grid9|[0.875, 0.375, 0.0]|0.083|0.042|0|0.00|157.31|158.12|6692.0|
|序盤0果物|coarse7-root|[0.0, 0.25, 0.125]|0.125|0.083|0|4.93|154.63|159.97|7045.3|
|中盤15果物|grid5|[0.5, 0.5, 0.25]|1.062|0.198|0|0.00|518.60|520.14|6786.7|
|中盤15果物|grid9|[0.125, 0.625, 0.0]|1.542|0.177|0|0.00|508.25|509.82|6622.0|
|中盤15果物|coarse7-root|[1.0, 0.125, 0.25]|1.573|0.188|0|22.73|527.58|553.03|7009.7|
|密集35果物|grid5|[0.5, 0.75, 0.5]|27.042|2.323|40|0.00|806.23|811.15|5787.7|
|密集35果物|grid9|[0.625, 0.625, 0.75]|24.083|2.188|52|0.00|729.21|735.05|5098.7|
|密集35果物|coarse7-root|[1.0, 0.5, 0.5]|27.802|2.333|46|41.19|784.95|833.33|5787.3|

総msはprobe外側のwall計測で、候補生成+MCTS以外に少量の設定/結果処理等を含む。生成timeは追加root構築/粗5Fork/各1手予測/評価/破棄スケジュールまで含む。総tickは粗5予測分も必ず加算。MCTS自体は32反復のままで、追加の粗5回は別予算として明示する。

密集CはAより平均約2.7%遅く、Bより約13.4%遅かった。探索内報酬はA27.042/B24.083/C27.802だが、CがAを上回ったのは3seed中2つで僅差。選択rootは3seedとも元の粗候補で、追加fineが密集で直接選ばれた例はない。Bの短い時間にはGO早期終了等による少ないtickも影響しており、純粋なアルゴリズム速度差としない。

中盤seed8192ではCが追加.125を選択。C探索内でこのrootの訪問5回/平均7.2点、元の粗root最大平均3.0点だった。固定5にはない位置を有望と評価した例だが、少数の異なる未来サンプルでの平均であり、実ゲームの改善を証明しない。

### 候補ごとの訪問回数

|盤面|seed|A grid5|B grid9|C root7（上記候補順）|
|---|---:|---|---|---|
|序盤0果物|8191|[6, 7, 6, 7, 6]|[4, 4, 4, 3, 3, 3, 3, 4, 4]|[5, 5, 5, 5, 4, 4, 4]|
|序盤0果物|8192|[6, 7, 6, 6, 7]|[4, 4, 4, 4, 3, 3, 3, 4, 3]|[5, 4, 5, 4, 5, 5, 4]|
|序盤0果物|8193|[6, 7, 6, 6, 7]|[4, 4, 4, 4, 4, 3, 3, 3, 3]|[5, 5, 5, 4, 5, 4, 4]|
|中盤15果物|8191|[6, 7, 7, 6, 6]|[4, 4, 4, 3, 4, 3, 3, 4, 3]|[5, 5, 5, 4, 4, 4, 5]|
|中盤15果物|8192|[7, 6, 7, 6, 6]|[4, 4, 4, 3, 3, 4, 3, 4, 3]|[5, 5, 5, 5, 4, 4, 4]|
|中盤15果物|8193|[7, 7, 6, 6, 6]|[4, 4, 4, 3, 3, 3, 4, 4, 3]|[5, 5, 5, 4, 4, 5, 4]|
|密集35果物|8191|[7, 4, 10, 5, 6]|[2, 5, 3, 3, 5, 7, 4, 1, 2]|[5, 3, 6, 5, 6, 1, 6]|
|密集35果物|8192|[5, 5, 6, 10, 6]|[3, 4, 3, 3, 3, 6, 5, 1, 4]|[5, 3, 6, 6, 6, 1, 5]|
|密集35果物|8193|[4, 4, 10, 7, 7]|[3, 4, 3, 3, 3, 5, 7, 1, 3]|[3, 5, 7, 5, 7, 1, 4]|

rootの平均訪問機会は32/5≈6.4、32/9≈3.6、32/7≈4.6。Cの将来nodeは5候補で、固定9より分岐は少ない。全方式の物理到達深さは最大4（GOで短縮あり）。木への登録は最大2手目、非root同一edge再訪は今回全条件0回。探索木の分散問題をこの候補生成だけで解決したとは言えない。

同程度の物理予算による事後prefix比較もanalysis.jsonに保存した。候補生成tickを先に課金し、完了反復だけ採用したもの。密集の3seedではA26/29/29反復、B32/32/32、C26/29/28となり、Cの平均探索報酬は27.885/27.931/22.786、A27.231/30.310/20.793。優位は一貫せず、別の時間制限実行ではない。

## 5. 既知15点・18点経路

現在のPlayerでも2手診断を再実行し、.125→.125=15点/1合体/84tick、.5→0=18点/2合体/86tick、両GO falseを再現。根拠となる盤面/物理は同じ。

- A grid5は.125を持たない。
- B grid9は全階層に.125を持ち、今回の密集32反復でその2手prefixをseed順2/1/0回通った。
- Cは密集rootに.125を提案せず、さらに将来decisionも固定5なので15点prefixを表現できない。他の盤面でroot .125があっても2手目 .125は使えない。
- .5→0は全方式で可能。密集の通過数はA5/2/5、B2/0/0、C2/2/3。

これらは先頭2座標の通過数であり、その反復の4手報酬が必ず15/18という意味ではない。短い2手の最高得点を選ぶように調整していない。Cの候補集合が有望なfine系列を失う問題は残った。

## 6. rootのみ/将来decisionも細分化する場合のコスト

今回はrootだけ粗5回の追加予測。全nodeで同方式を行うと、node初訪問のたびに5予測・複製/評価が追加される。仮に32nodeに適用すれば最大160回程度の追加1手予測になり、現在のrollout込み約128回相当と比較して大きい。物理tickは移動距離/GOで変わるため、単純な倍数の実時間予測はしない。将来階層への細分化は今回は未実装・未測定。

## 7. 実通信・GO・回帰

ゲームseed756300、各8手、探索seed8191、順次1Player。Cは追加.125/.875も実際に選択・落下した。両8落下成功・9点/2合体、選択座標/得点保存則/公開果物系列/実行環境整合性成功、新しいworker例外なし。平均判断A295.73/C284.01ms。盤面・移動経路が分岐する短い試験で、速度や強さの優位の証拠ではない。両とも手数上限で終了し、自然GO比較から除外（有効ペア0）。

GO見逃し/過剰予測は両0だがGO正例0で精度は未評価。密集固定盤面のGO40/52/46は探索内の頻度であり、予測精度や実ゲーム死亡率ではない。GO .83/接触済み条件/判定時刻/既知の物理予測誤差は変更していない。

Python204テスト成功（新規6）。Unity MCTS861/rules84/path26/frames58=1029チェック成功。追加native候補試験は親順位・異なる親・中点重複なし・元anchor保持・unsafe親の優先除外を確認。Value parity24ケース成功、Playerビルド最終STEP6 BUILD OK。新規スクリプト初回import中にCS0246が記録されたが、import/再コンパイル後は成功し、実行済みPlayerで全診断が通った。

既存grid5は3盤面×3seedと元の非common乱数3盤面=12条件で旧版と完全一致（選択・action/chance列・木/訪問・score/merge/GO/tick）。Cの別Player再実行は3盤面とも同seedで同じ候補/経路/木統計/結果になった。物理/ゲーム6ソースSHA256は作業開始時と一致。

## 8. 変更ファイル・関数・行番号

|ファイル|位置/関数|変更|
|---|---|---|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/CoarseToFineCandidates.cs:7|Report/Refine/Build|新規。粗予測・順位・2親の中点追加・計測|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/CoarseToFineCandidates.cs.meta|Unity生成|新スクリプトGUID|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/MctsPlanner.cs:46|Report|候補選別結果と探索時間|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/MctsPlanner.cs:91|SearchNode|Cのみ非rootを5候補で作成|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/MctsPlanner.cs:163|PlanFrames|root選別、203/237でroot7/将来5の座標、node別metric長|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/StepPlanner.cs:48|Validate|coarse-root opt-in・対応設定の制約|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaCandidateProbe.cs:20|GeometryTests|新候補のnative検証|
|C:/SuikaGameAI/Python/src/suika_ai/unity_env.py:433|validate_planning_settings|新policy/7候補の検証|
|C:/SuikaGameAI/Python/src/suika_ai/parallel_play.py:197|run_parallel|試作は1ゲーム限定|
|C:/SuikaGameAI/Python/play_parallel_ai.py:21|main|coarse-root指定とroot候補7の既定化（新policy時のみ）|
|C:/SuikaGameAI/Python/analyze_two_step_probe.py:6|trace_search|root7/将来5を再構築し、実x・UCT・visit・報酬を監査|
|C:/SuikaGameAI/Python/analyze_coarse_probe.py:6|validate_decision/analyze|粗式・親/中点・anchor・全tick/時間・共通chance監査|
|C:/SuikaGameAI/Python/compare_coarse_ai.py:9|settings/validate_geometry/summarize/main|同seed比較、報酬/座標/環境監査、ゲーム単位CI|
|C:/SuikaGameAI/Python/tests/test_coarse_candidates.py:8|CoarseTests|新規6回帰テスト|
|C:/SuikaGameAI/docs/STEP8P_REPORT.md|本書|結果・制限・実行方法|
|C:/SuikaGameAI/docs/DEVELOPMENT_LOG.md、DEVELOPMENT_PLAN.md|末尾追記|簡潔な記録|

## 9. 実験用PowerShell

標準採用は推奨しない。固定盤面だけでは高得点化は未証明。追加位置を選べることと実ゲームの短時間互換性は確認したため、自然GOで効果の有無を調べる比較コマンドは用意した。ただし今すぐ10組実行を強く推奨する結果ではない。実行する場合は新しい出力先を作り、20ゲームを1Playerずつ順次実行する。

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\coarse_compare_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_coarse_ai.py --pairs 10 --seed 756300 --base-port 38900 --max-steps 3000 --output $out
```

coarse_comparison.jsonとcoarse_pairs.csvに平均/中央値/最大/最低、勝敗、seedごとの差、最大果物、GO confusion、判断時間、ゲーム単位bootstrap95%CIを保存。自然GO完了ペアだけ採用し、手数上限/異常終了/不整合は除外する。果物系列は共通prefixで監査するが、操作・移動・終了が変わるため同seedだけで完全な同一未来とは主張しない。

短時間の各8手だけ確認する場合:

```powershell
$out = "outputs\coarse_smoke_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_coarse_ai.py --smoke --pairs 1 --max-steps 8 --seed 756300 --base-port 38900 --output $out
```

固定盤面の保存済みログの再集計:

```powershell
$report = "outputs\coarse_fixed_audit_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".json"
.\.venv\Scripts\python.exe .\analyze_coarse_probe.py .\outputs\step8p_01\fixed.jsonl --output $report
```

通常CLIでも--candidate-policy coarse-root --candidates 7 --ai-mode mcts --games 1 --mcts-max-depth 4で指定可能。新方式は明示opt-inで、grid/5の既定は変えていない。旧比較方式の組合せ利用は保護のため新policy時に拒否するが、旧モードはそのまま利用できる。

## 10. 次の優先事項

一貫した高得点化は未確認なので標準化しない。次は、細分化候補を決める評価の情報量を検証することを優先する。今回は粗1手scoreが全て0で、微小なR差や同点indexに順位が依存した。まず、公開NEXTまで使う少数の2手probeで候補選別が安定するかを、追加物理コスト込みで比較する案が有力。ただし全81経路の前処理は目的に合わず、少数の診断に限定した設計が必要。

将来decisionまでの細分化を追加すれば既知15点経路を表現できるが、候補選別の信号が弱いまま全階層に展開するとコストと選別誤りを増やす可能性がある。今回それは実装していない。root評価の層化やMCTS構造の改良も同時には行わない。

結果: C:/SuikaGameAI/Python/outputs/step8p_01 と C:/SuikaGameAI/Python/outputs/step8p_smoke_01。長時間収集/自然GO大量実験/再学習/リアルタイム化/Viewer変更/4ゲーム新方式導入は未実施。
