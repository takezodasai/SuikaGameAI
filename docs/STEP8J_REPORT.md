# STEP 8-J 固定9候補の検証（2026-10-23）

## 結論
固定9候補は既存の `candidate_policy=grid, candidate_count=9` で利用できた。新しいMCTSアルゴリズムは追加せず、全探索階層への適用を検証し、比較・監査ツールを整備した。既定の5候補・board-five・同期/分割方式は維持。**9候補の標準採用は見送る。実ゲームの高得点化は未証明。**

## 実装と変更行
- `Unity/Assets/Scenes/Script/SuikaCandidateProbe.cs:8` Search/Config/Searches：固定盤面診断に候補数・反復数を指定可能にした。旧policies形式も維持。46行のループ/50行の設定で5/32・9/32・9/64を同じ凍結rootから実行する。
- `Python/compare_mcts_ai.py:73` episode：5個固定の監査から、expected_settingsのcandidate_countとの一致へ変更。既存呼出しは従来5個のまま。座標照合の既存許容誤差・落下前GOの区別は変更していない。
- `Python/compare_grid_ai.py:9` settings：grid5/grid9の比較設定（sync32/depth4/post25）。13行validate_geometryで**全ノード**の座標列とroot32訪問を検査。24行summarizeで同一seed、公開果物系列の共通prefix、環境・実行バイナリ・候補数以外の設定、得点/報酬、実操作座標を監査する。自然GOペアだけ集計。71行mainで1 Playerずつ交互順実行、既存出力を上書きしない。
- `Python/tests/test_fixed_grid.py:7` 新規5テスト：9設定/既定5保持、ペア集計と上書き拒否、未来ノード不正座標拒否、途中終了の除外、本当の落下座標不一致の除外。
- 本報告、DEVELOPMENT_LOG/PLANへ追記。

MCTS本体の変更なし。`MctsPlanner.cs:107` root、208行childはともに同じcandidate_countで生成。144行のrolloutも同じ個数から選び、154行の `action/(candidate_count-1)` を全深さで使用。従来と同じAdvanceSearch/DropRangeの変換・壁/果物Colliderによる合法範囲を利用する。9位置は0, .125, .25, .375, .5, .625, .75, .875, 1。
`MctsPlanner.cs`・`SuikaPhysicsSimulator.cs`・`SuikaPredictionPath.cs` は作業前後SHA256一致（outputs/step8j_01/source_integrity.json）。UCT/rollout/得点/GO/未知NEXT/物理設定には手を入れていない。

## 固定盤面の条件
STEP8-Iの序盤0個/中盤15個、STEP8-C由来の密集35個/GO付近38個を再使用。公開A/Bと同一root、MCTS seed8191、最大深さ4、post25。各条件1回の診断測定であり、時間の平均/信頼区間ではない。GC・温まり・シミュレーション経路の長さが異なるため、9候補の方が速いと一般化しない。
結果：`Python/outputs/step8j_01/fixed.jsonl`、`fixed_analysis.json`、入力`fixed_config.json`。
全12探索で全ノードのgrid配置・root非汚染・prefix一致を確認。5候補は前回4盤面と選択/全ノード統計/物理tick一致。root未訪問候補は全条件0個。ただし未来の候補には多数未訪問がある。

|盤面|候補/反復|選択x|root訪問数（左→右）|ノード|物理tick|全計算ms|
|---|---|---:|---|---:|---:|---:|
|序盤|5/32|0|7,6,6,6,7|33|7282|193.66|
|序盤|9/32|0|4,4,4,4,4,3,3,3,3|33|6789|155.95|
|序盤|9/64|.25|7,7,8,7,7,7,7,7,7|65|13822|314.29|
|中盤|5/32|0|7,7,6,6,6|33|6867|524.28|
|中盤|9/32|.125|4,4,3,4,4,3,3,4,3|33|6714|501.74|
|中盤|9/64|.125|7,8,7,7,7,7,7,7,7|65|13795|1037.29|
|密集35|5/32|1|5,5,7,6,9|33|5818|804.11|
|密集35|9/32|1|4,3,3,3,4,3,5,1,6|32|5506|753.74|
|密集35|9/64|1|8,4,4,9,8,8,10,1,12|64|11406|1596.53|
|GO付近|5/32|.5|1,1,28,1,1|6|1498|328.22|
|GO付近|9/32|.375|1,1,1,13,12,1,1,1,1|10|1607|345.61|
|GO付近|9/64|.375|1,1,1,29,28,1,1,1,1|11|3329|741.55|

rootの平均return（点、深さ4までのサンプル、直後25tickの得点とは別）：
- 序盤5/32：[.143,0,0,0,.143]。9/32：全0。9/64：[0,0,.125,0,0,.143,0,0,0]。
- 中盤5/32：[2.143,2.143,0,2,2.5]。9/32：[3.75,5.25,0,2,3.75,0,0,1.5,0]。9/64：[2.143,2.625,0,1.143,2.143,.857,0,3,2.571]。
- 密集5/32：[15,11.6,28.714,27,37.667]。9/32：[27.25,2,5,13.333,25,15,24.6,0,41]。9/64：[26.375,1.5,3.75,29.333,27.5,28.25,32,0,34.083]。
- GO付近は全0。root直後GOの除外を維持し、9候補では.375と.5へ探索が集中した。全深さ終端GOは全サンプルで発生し、長期生存の証拠ではない。

各試行の最大サンプル得点/最大合体数（各列の最大であり同一経路の保証なし）は、序盤5/32=1/1、9/32=0/0、9/64=1/1；中盤は全15/1；密集は51/4、55/5、71/7。密集の終端GOサンプル数は16/32、15/32、30/64。**サンプル最大値を選択手の保証得点や実ゲームの強さと解釈しない。** 選択1.0の直後予測は全条件+0/0合体/GOなし、その後の探索経路で得点とGOが発生する。

## 既知の .125→.125
独立した連続PathSessionで再現：最初785→785、2手目785→800、計15点/1合体、GOなし。計84tick（55+29）、実落下world Xは-2.1430146694/-1.9148561954。果物のサイズが異なるため、同じ正規化Xでも実world Xは異なる。得点15は2手目post-drop、移動加点0。比較対象は固定5位置の**同じXを2回**の系列最大3点であり、5×5の全組合せ最適値ではない。

区別すべき点：
1. **利用可能**：9候補の全未来ノードに.125あり、2手目に.125を使った他prefixも32/64とも実際に存在。
2. **最初の.125を探索**：密集で32回時3訪問、64回時4訪問。
3. **.125→.125のprefixを探索**：32回も64回も0件。32回の.125始まりのaction index列は `[1,5,6,3]`, `[1,3,6,5]`, `[1,7]`、64回ではさらに`[1,4,3,7]`が追加。index/8で位置に変換。
4. **最終選択**：32/64とも1.0。既知15点経路を否定したのではなく、まだ試していない。最初の.125の平均returnは2→1.5点で、1.0は41→34.083点。最終選択は従来どおり即時GO除外後の最多訪問・同数時平均return等で決まり、平均値の最大だけではない。

32/9はrootあたり平均3.56訪問（5候補なら6.4）。さらに公開分布の未知C等のchance nodeへ分岐するため、同じ第2意思決定ノードへ再訪する回数は少ない。64へ増やしても.125の4訪問は異なるCスロットへ1回ずつで、既知組合せの発見には届かなかった。これは探索不足の具体例。ただし、64にすれば必ず強くなるという結果ではない。

## 計算コスト
軽量gridの候補生成計測は0ms/0calls（board専用計測器を呼ばず算術式を利用、厳密な演算時間0の意味ではない）。追加の物理スキャンを行って候補を作ってはいない。9/32は5/32比、序盤-19.5%、中盤-4.3%、密集-6.3%、GO付近+5.3%。短い1測定・経路差あり、改善率とは呼ばない。9/64は9/32比2.02〜2.15倍。探索の省略/近似なし、skipped_physics_ticks=0。診断スキャン時間はMCTS wall_msに含めない。

## 実通信スモーク
`Python/outputs/step8j_smoke_01`。同一seed751300、同一Player/hash/environment、1台ずつ各8手。公開系列10個一致。
- 5候補：15点/1合体、8/8落下成功、平均判断268.12ms、実行7.687秒。
- 9候補：15点/1合体、8/8落下成功、平均判断274.84ms、実行7.578秒。
- 実操作座標と選択候補の最大差0 / 2.384e-7 world unit。得点/報酬保存・全ノード候補数一致、worker errorなし、観測GOなし。
- 両方step_limit終了。自然GOペア0なので強さの統計には**不使用**（smoke_completed_not_strength）。手動/ViewerのGUI確認は今回未実施。自然GO/終盤誤差改善の証明ではない。

## テスト
Python全155テスト成功。Unity Player内 MCTS861、rules84、path26、frames58＝1029チェック成功。固定盤面probe/幾何テスト成功、Unity2022.3.21f1ビルド成功。既存Value parityのビルド前検証も実施。テスト中の新しいゲーム例外なし。既知の接触キャッシュとrender-frame GOタイミングの予測制約は未解決、validated_for_search=falseのまま。今回GO条件を変更したり誤差を許容して隠していない。

## ユーザー実行（PowerShell、既存フォルダを上書きしない）
単一ゲームの9候補：
```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\grid9_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\play_parallel_ai.py --games 1 --view-games 1 --episodes 1 --max-steps 3000 --ai-mode mcts --candidate-policy grid --candidates 9 --mcts-iterations 32 --mcts-max-depth 4 --post-drop-steps 25 --planning-execution sync --seed 751400 --base-port 38300 --output $out
```
5候補は `--candidates 5`。board-fiveは `--candidate-policy board-five --candidates 5`。今回Viewer自体の変更/GUI検証はなし。

10組・合計20ゲームの自然GO比較（1Playerずつ、ユーザー担当）：
```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\grid5_vs_grid9_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_grid_ai.py --pairs 10 --seed 751500 --base-port 38100 --max-steps 3000 --output $out
```
sync32/depth4/post25、候補だけ5/9へ変更。`grid_comparison.json`/`grid_pairs.csv`へ勝敗・平均/中央値/範囲・得点差・ペア単位95%bootstrap区間・GO不一致・時間を記録。途中終了/通信異常/報酬不整合/座標不一致等は除外理由を保存。既存の修正済み座標許容誤差を使用。3000手上限へ到達してもGO扱いしない。新seedを使っても短い10ペアの区間は不安定なため、効果量と各ペアも見る。
保存済み結果から再集計する場合は新しいreport-dirを指定：
```powershell
.\.venv\Scripts\python.exe .\compare_grid_ai.py --output $out --analyze-only --report-dir ($out + "_audit_" + [guid]::NewGuid().ToString("N").Substring(0,8))
```

## 次の判断
現時点では既定grid5を維持し、grid9を比較条件として残す。密集で必要な位置が利用可能になっても、chance分岐と9行動への分散で有望な2手prefixを見つけていない。まず上記自然GOペア比較で実得点と計算時間を測定する。
その結果で分散の問題が続けば、次の1案は**粗い位置から有望区間の中点を段階追加する方式**。固定予算で深い再訪を確保し、.125等も追加できる可能性がある。ただし既存Nodeの固定配列とindex/(count-1)は途中の候補数変更にそのまま使えない。座標をedgeに固定し、訪問済みの意味を変えずに追加する設計・乱数/枝独立性回帰が先に必要。狭い合体位置を初期粗探索で見逃すリスクもある。今回はProgressive Widening/rollout変更/探索深さ変更を実装していない。

コミット・push・データ削除・追加バックアップなし。develop維持。
