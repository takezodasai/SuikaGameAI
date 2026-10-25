# STEP8-N：chance後decision展開の診断結果

2026-10-24 / develop。commit・pushなし。

## 結論

比較用の `expansion_policy=chance_decision` を実装した。標準は `legacy` のまま。2・3手目の木への登録は増えたが、root以外の同じaction edgeの再訪は今回すべて0回で、chance分散の解消・高得点化は確認できなかった。自然GO比較を行う前に標準化しない。

## 従来処理と変更

MctsPlanner.PlanFramesの各反復は、独立PathSessionを初期盤面から再構築する。Selectは合法性とUCTを使い、未訪問edgeを配列順に先に返す。各drop後、GO/最大深さで終了し、それ以外は既存のWaitTicksを進める。その後edge.chance[slot]にdecision状態ノードを生成/再利用する。従来は「edge初訪問またはchance子初生成」でrolloutへ移り、以降の位置はrandom。chanceは常に既存の出現分布でサンプルし、UCTでchance結果を選ばない。

Bでは各反復の最初の新chance子に限り、次のdecision actionを1つ木で選び、その後rolloutへ移る。親edgeも初訪問なら1反復で最大2個のaction edgeを初展開する。追加展開を再帰的に連鎖させない。GO/待機中GO/深さ到達なら追加しない。物理計算の最大深さは4のままで、rolloutから木に登録する区間を変えたもの。

visitsリストには木のnode/edgeとその時点のscoreを一度だけ保存し、終了時に node.visits++ と edge.Add(finalScore-visit.score+leaf,terminal) を一度だけ行う。chance子のarrivalsは到着時に加算、visitsは実際にそのノードのactionを選んだ反復だけ加算する。rolloutだけの子に訪問実績を捏造しない。既存leaf cacheを含む物理経路と報酬算出は変更していない。

```csharp
public static bool AfterChanceRollout(bool expanded,bool newChance,bool extend,bool extraUsed,out bool pending) {
    pending=extend&&newChance&&!extraUsed;
    return !pending&&(expanded||newChance);
}
```

## 情報・乱数・比較条件

固定5/32回/深さ4/random/sync/post25。A_commonとBで同じ iteration×depth のchance表を使う（mcts_common_chance=true）。既存標準の乱数順序はmcts_common_chance=false、expansion_policy=legacyでそのまま残す。両設定のAを前回8Mと比較し、3盤面×2条件で選択・全action/chance列・得点・合体・GO・tick・ノード/訪問統計が一致した。

共通表は未知果物のサンプル条件を揃えるためのもの。展開とrolloutの回数が変わるためrandom rolloutの乱数消費は同一ではなく、同じseedで全未来が一致する比較ではない。rootの判断は公開A/Bだけに条件付けられ、A落下後に公開される仮想Cはその後の判断から利用。未公開の実ゲームの乱数列を参照しない。末尾の物理報酬に影響しないNEXTは既存どおりunknown/代表chanceへ縮約。ログのpublic_observations、node id、chance表を監査した。

## 固定盤面（各条件1回、時間はばらつき未評価）

|盤面|方式|選択x|decision状態node|初展開action edge|新chance子|追加decision|実物理tick|全体ms|
|---|---|---:|---:|---:|---:|---:|---:|---:|
|序盤0果物|A_legacy|0.25|33|17|32|0|6860|162.20|
|序盤0果物|B_chance_decision|0.0|65|51|64|32|7130|170.86|
|中盤15果物|A_legacy|0.5|33|17|32|0|6729|507.55|
|中盤15果物|B_chance_decision|0.75|65|51|64|32|7102|582.60|
|密集35果物|A_legacy|0.5|33|17|32|0|5987|836.71|
|密集35果物|B_chance_decision|0.5|65|51|64|32|6461|910.80|

nodeはdecision状態、chance展開はedge内のoutcome→child対応。独立したchance-objectは作らない。初展開action edgeとは初めてvisits>0になったedge数。単なるnode作成数と混同しない。

|盤面|方式|登録edge数(1/2/3/4手)|木で行動した回数(同)|2座標prefix再訪|同じ非root edge再訪|rollout開始手:回数|探索内GO反復|平均4手報酬|
|---|---|---|---|---:|---:|---|---:|---:|
|序盤0果物|A_legacy|[5, 12, 0, 0]|[32, 12, 0, 0]|11|0|{'2': 20, '3': 12}|0|0.062|
|序盤0果物|B_chance_decision|[5, 32, 14, 0]|[32, 32, 14, 0]|16|0|{'3': 18, '4': 14}|0|0.000|
|中盤15果物|A_legacy|[5, 12, 0, 0]|[32, 12, 0, 0]|11|0|{'2': 20, '3': 12}|0|1.125|
|中盤15果物|B_chance_decision|[5, 32, 14, 0]|[32, 32, 14, 0]|18|0|{'3': 18, '4': 14}|0|0.469|
|密集35果物|A_legacy|[5, 12, 0, 0]|[32, 12, 0, 0]|14|0|{'2': 20, '3': 12}|13|28.406|
|密集35果物|B_chance_decision|[5, 32, 14, 0]|[32, 32, 14, 0]|18|0|{'3': 18, '4': 14}|14|33.969|

座標prefix再訪はchanceや物理状態を区別しない診断指標。Bで11→16、11→18、14→18と増えたが、同じ非root edgeへの再訪は0。状態node自体の再訪はあるが、その際も未訪問actionが残り、次のactionを1回ずつ試す段階にとどまった。従って行動別期待値の蓄積が改善したとは言えない。全方式とも物理的には深さ4へ到達する反復があり、「木の深さ」と「rolloutを含む到達深さ」を区別する。

Bの2手目の木行動は、5候補の密集盤面でindex0/1/2/3/4が18/9/4/1/0回。未訪問候補を左から試す既存規則によって、新chance子で左側が優先される。UCTを変更しない今回の制約に従ってこの順序は維持したが、random rolloutを置き換える際の強い偏りである。

各候補の訪問数/平均得点、全反復の行動・chance・phase・到達深さは verified_analysis.json の root_actions / iterations / trace に保存。

A_legacy root (x,visits,mean_points): [(0.0, 7, 27.0), (0.25, 4, 18.25), (0.5, 10, 39.7), (0.75, 5, 17.6), (1.0, 6, 27.0)]

B_chance_decision root (x,visits,mean_points): [(0.0, 4, 20.5), (0.25, 4, 17.75), (0.5, 9, 39.0), (0.75, 8, 41.25), (1.0, 7, 36.143)]

## 既知の15点・18点経路と64回診断

同じ35果物盤面の81経路を再実行。0.125→0.125は15点/1合体/84tick/GO false、0.5→0は18点/2合体/86tick/GO falseを再現。drop/cooldown/公開A・B/形状/GOは既存PathSessionに従い、未知Cはこの2手の物理報酬に不要。root/live/Unity乱数不変を確認。

5候補には0.125がない。18点座標prefixは密集Aが5回、Bが4回。これは「先頭2座標を通った回数」であり、4手結果のrewardが必ず18点になるという意味ではない。

|密集9候補/64回|選択x|登録edge(各手)|15点prefix回数|18点prefix回数|GO反復|平均探索報酬|実tick|ms|
|---|---:|---|---:|---:|---:|---:|---:|---:|
|A_legacy|0.625|[9, 34, 0, 0]|3|5|31|24.484|10611|1577.20|
|B_chance_decision|0.625|[9, 63, 32, 0]|3|4|20|36.062|11961|1861.76|

15点prefixは両3回、18点は5→4回、選択は両0.625。Bの平均探索報酬は高いが、展開順・サンプル・GO終了の構成が違い、実ゲーム得点の改善証明ではない。9/64は5/32より大きな予算の別診断。

## 計算予算・メモリ

同じ32回でBの時間は序盤+5.34%、中盤+14.79%、密集+8.85%。物理tickは+3.94%、+5.54%、+7.92%。物理幅やhorizonは変えず、選ぶ座標と移動時間・GOで作業量が変わる。密集9/64は+18.04%、tick+12.72%。

最小総tickを上限として、完了反復だけのprefixでも比較した（独立した再実行ではなく事後解析、全体固定費を含まない）。密集A32回5987tick/28.406点に対しB29回5858tick/34.793点、選択は両0.5。9候補ではA64回10611tick/24.484点、B56回10441tick/36.411点、選択両0.625。近い予算でも探索内平均は上がったが、自然GO得点の評価ではない。

密集5/32の探索中Unity割当メモリ増分A15.36MiB/B14.30MiB、managed終了−開始A0.85MiB/B3.43MiB、GC0 A15/B15。9/64ではUnity増分30.68/31.13MiB、managed増分4.78/5.96MiB、GC0 41/26。これらは同一Player内で順番に測ったサンプル値で、プロセス全体の真のピーク/リーク判定ではない。Bの追加nodeと診断配列分の保持コストがある。

## 実通信・GO・回帰

seed754300、各8手、各1Playerの順次起動。両8落下成功、25点/2合体、選択座標一致、報酬保存則/公開果物系列/環境メタデータ一致、worker例外なし。平均判断A275.64ms/B281.08ms。自然GO0で手数上限終了、比較有効ペア0として正常に除外。GO対照は各8 true negative、見逃し/過剰予測0件だが正例0でGO精度は測定不能。密集固定盤面のGO回数は探索内サンプル数であり、実ゲームの見逃し率ではない。GO/接触予測の既知誤差は今回修正していない。

Python189テスト成功。Unity native MCTS861/rules84/path26/frames58=1029チェック成功、展開境界のnative4条件も成功。Unityコンパイル/Playerビルド成功。旧Aは前回と6条件で木/経路/tick一致。ゲーム/物理/GO関連6ファイルのSHA256は作業前後一致。

既知経路の再確認用Playerを最初に起動した際、私の引数にRuntimeProbeがなく診断ハーネスでNullReference→タイムアウトした。該当テスト用Playerを終了し、必要引数を追加した別出力への再実行はexit0。失敗ログknown_test.log/空のknown_paths.jsonlも削除せず保存。実通信ログには新しい例外なし。headlessのNull GPU用shader unsupportedログは既存の描画非対応警告で、スクリプト例外と区別した。

## 変更ファイル・関数・行番号

- Unity/Assets/Scenes/Script/MctsPlanner.cs:38 IterationMetric、45 Report、80 AfterChanceRollout、PlanFrames 151/156/286/297。展開境界と1反復上限、診断カウンタ/公開情報を追加。UCT/Backpropagation/Advanceは維持。
- Unity/Assets/Scenes/Script/StepPlanner.cs:31/39 PlanningSettings/Validate。legacy既定、sync/chance/grid/random限定のopt-in。
- Unity/Assets/Scenes/Script/SuikaCandidateProbe.cs:8 Search、48 GeometryTests、160 Start。固定盤面設定とnative境界テスト。
- Python/src/suika_ai/unity_env.py:416/423 validate_planning_settings。設定追加・互換性検証。
- Python/src/suika_ai/parallel_play.py:197 run_parallel。試作は1ゲーム限定。
- Python/play_parallel_ai.py:44 引数--expansion-policy、61 main。既存CLIから明示指定可能。
- Python/analyze_two_step_probe.py:6 trace_search。旧ログを受け入れつつ追加展開/訪問/UCT/rolloutを再構築して監査。
- Python/analyze_expansion_probe.py:6 summarize_rows、50 main。物理tick/公開情報/再訪/予算比較を追加する新規診断。
- Python/compare_expansion_ai.py:9 settings、13 validate_geometry、43 summarize、92 main。順次1Playerで同seedペア比較、自然GOのみ有効、得点保存/座標/seed/系列/実行環境/木監査、ゲーム単位bootstrap95%CI。
- Python/tests/test_expansion_policy.py:新規10テスト。GO終端、重複逆伝播、不正quota、既存ログ、設定制約、1ゲーム制約。
- docs/STEP8N_REPORT.md（本書）、DEVELOPMENT_LOG.md/DEVELOPMENT_PLAN.md追記。既存dirty変更は維持。

## ユーザー用10組比較（任意、標準採用のための証拠はまだ不足）

新しいPlayerはビルド済み。Unity EditorのPlayや同ポートのPlayerを停止し、次をPowerShellから実行。4ゲームへの展開はせず、20ゲームを1Playerずつ順次実行する。最大3000手で止まったゲームは自然GOとせず除外する。

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\expansion_compare_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_expansion_ai.py --pairs 10 --seed 754300 --base-port 38700 --max-steps 3000 --output $out
```

出力はexpansion_comparison.json（eligible/exclusion、得点分布・勝敗・ペア差・95%CI・計算時間・GO confusion）とexpansion_pairs.csv、全run/JSONL。既存出力先がある場合は拒否する。途中停止時も正常なJSONLは保持し、後から別report-dirを指定して再集計可能。

```powershell
.\.venv\Scripts\python.exe .\compare_expansion_ai.py --output $out --analyze-only --report-dir ($out + "_audit_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
```

固定診断再集計（保存済み入力は変更しない）:

```powershell
$report = "outputs\step8n_analysis_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".json"
.\.venv\Scripts\python.exe .\analyze_expansion_probe.py .\outputs\step8n_01\fixed.jsonl --output $report
```

## 次の推奨

標準採用しない。今回のBでノードは増えたが、非rootの同じactionへ2回以上訪問する前に予算を使い切り、左からの初展開偏りも残った。次に1軸だけ試すなら「chance分岐を保った、未訪問actionへの初展開予算配分」を推奨する。例えば情報状態を混ぜず、兄弟chanceに対し初展開候補を再現可能な順序で分散する。UCT適用後の選択/報酬/確率/物理を維持し、左右の偏りと同一edge再訪/期待値分散を測る。今回これは未実装。

Progressive Wideningは少ない予算を既存actionに集められるが、既知5候補をさらに遅らせる危険がある。chanceを恣意的に制限すると確率の歪み/公開NEXT適応の損失を招く。Coarse-to-Fineは位置解像度問題向けで、今回のchance分散と初展開順の直接対策ではない。情報共有も異なる保持/NEXT/物理状態を平均しない条件が必要で、8Mの結果から無条件共有は推奨しない。

結果: Python/outputs/step8n_01 / step8n_smoke_01 / step8n_smoke_01_audit。長時間ゲーム実験・再学習・4ゲーム試作導入は未実施。
