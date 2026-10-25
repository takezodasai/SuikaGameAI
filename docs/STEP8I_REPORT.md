# STEP 8-I：盤面依存5候補の試作と比較（2026-10-23）

**結論：候補生成・比較基盤は実装したが、高得点化は確認できていない。従来gridを既定で保持し、新方式board-fiveは実験指定のみ。** 固定候補外の有利な予測例は見つかったが、今回の幾何方式はその位置を拾えなかった。

## 1. 基準方式と不変性

MCTS / sync / 32反復 / 深さ4 / 5候補 / post25 / seed付き実行 / 環境step8e-all-fruit-go-v2 / GO0.83。

従来候補は `(float)index/(count-1)`、5個なら0,.25,.5,.75,1。ワールド座標は `Lerp(range.min_x,range.max_x,x)`。

安全範囲は既存PlayerDropPlacementの壁内側、保持果物のCollider.bounds（offset・scale・rotation・Circle/Capsule等を含む）、既存contact clearance、必要ならPlayer自身のColliderから求める。従って果物サイズで実座標範囲は変わる。しかし盤面上の果物・同種果物・隙間は固定候補の配置に使わない。

MCTS本体変更前に `baseline.jsonl` を保存。変更後gridの4固定盤面で、選択Xと全20候補の検索評価、即時得点、合体、GO、物理tick、移動tick、落下位置が一致した（4/4）。初回probeはDecisionのNonSerializedなMCTS内部レポートを保存していなかったため、変更前後の全内部木のbit一致まで確認したとは主張しない。以降はReportを独立フィールドで保存するよう補った。既存native回帰では同期/分割の木の一致等も継続確認した。

既存sync/frames/frames_adaptive、STEP8-Hのtick分割、他AIモード、Viewerは削除していない。ゲームルール・Collider・物理設定・GO・果物確率・モデルは変更していない。develop維持、commit/pushなし。

## 2. 新しい5候補

設定 `candidate_policy="board-five"`。今回はsyncの通常MCTS・5候補・1ゲームに限定。gridは従来の候補数/実行方式を維持する。

1. 左端0、中央.5、右端1は必ず保持する。
2. 左半分と右半分にそれぞれ1候補を用意する。
3. 保持果物と同種で、上から落とす経路の水平footprintを他の高い果物のboundsが遮らない対象を探す。上側の対象を優先し、同じ高さなら元の.25/.75に近い方、同点なら小さいxを選ぶ。
4. 対象のCollider中心に、保持Colliderの中心offsetを補正して合わせる。合法範囲へ正規化する。
5. 適当な同種対象がなければ、上部bandのCollider区間から保持幅を引いた隙間の中心を候補にする。上部bandは最高点から保持幅分の範囲。
6. 候補がなければ従来の.25/.75を残す。

結果は `[0, left, .5, right, 1]`。アンカーから正規化.025以上を離し、重複や片側への集中を避ける。.025は元の.25間隔の10%という候補多様性の試作値で、衝突許容誤差ではない。

果物の種類はFruitEvolution.fruitType、形状情報は現在の実Collider.boundsを使う。物理Colliderを円等へ置換しない。Circleの半径やCapsuleの向き/寸法はboundsへ反映される。ただしboundsによる遮蔽は保守的な幾何近似で、斜めの滑り込みや遅延連鎖を保証しない。

保持/NEXTは盤面形状リストから除外する。生成に使うのは現在の保持果物と盤面だけ。GOライン近接ペナルティは追加せず、候補のGO除外は既存物理予測に任せる。

計算量は概ねO(n²+n log n)。候補生成のための追加物理予測はゼロ。診断用の座標scanは試験時だけ。

## 3. MCTSへの接続

盤面依存候補は根だけでなく各予測状態で生成する。探索ノード初回到達時に配列を保持し、同じノード再訪時にindexの意味を変えない。prefix signature不一致は従来どおりエラーにする。rolloutではその時点の盤面から配列を作り、従来と同じ一様ランダムindexを選ぶ。

UCT、展開、逆伝播、得点、leaf cache、深さ、反復数、dt、post25は維持。幾何方式が変えるのは各indexが表す落下位置だけ。grid分岐は従来の除算をそのまま使い、幾何情報の取得もしない。

ログにはpolicy、候補の由来、各ノードの実際の正規化X、各反復のaction_x、生成時間/回数を追加した。既存のaction indexだけをXへ再変換してはいけない。未知NEXTは従来どおり公開prefab-slot分布から仮想サンプリングし、Unityの未公開乱数を読まない。同じ探索seedでもGOで経路が短くなれば以降の乱数消費位置は変わるため、両方式の全反復が同じchance列とは扱わない。

## 4. 固定盤面比較

保存先 `C:\SuikaGameAI\Python\outputs\step8i_01`。

- 序盤：empty boardと公開保持/NEXTを明示した診断fixture。
- 中盤相当：保存済み密集fixtureの低い15果物を抽出。自然な中盤の代表性は保証しない。
- 密集：保存済みdense_safe_fixture、35果物。
- GO付近：保存済みnear_go_fixture、38果物。

各ケースは同じ凍結native rootから両方式を実行。Player seed749100、MCTS seed8191、32/4/5/post25。ライブをA/B間で進めない。fixtureのcontact/solver内部cacheを完全復元する試験ではない。

| 盤面 | grid候補→選択 | board-five候補→選択 |
|---|---|---|
| 序盤 | 0,.25,.5,.75,1 → 0 | 同じ → 0 |
| 中盤15個 | 0,.25,.5,.75,1 → 0 | 同じ → 0 |
| 密集35個 | 0,.25,.5,.75,1 → 1 | 0,**.349260**, .5,.75,1 → **.349260** |
| GO付近38個 | 0,.25,.5,.75,1 → .5 | 同じ → .5 |

根で同じ候補になっても、2手目以降の配列が変わる場合がある。

| 盤面・方式 | 根の訪問回数（左から） | ノード数 | native tick | 計画全体ms | 候補生成合計ms / 回数 |
|---|---|---:|---:|---:|---:|
| 序盤 grid | 7,6,6,6,7 | 33 | 7282 | 192.30 | 0 / 0 |
| 序盤 board | 7,6,6,6,7 | 33 | 7180 | 150.69 | 2.24 / 94 |
| 中盤 grid | 7,7,6,6,6 | 33 | 6867 | 522.68 | 0 / 0 |
| 中盤 board | 7,7,6,6,6 | 33 | 6816 | 509.06 | 3.90 / 92 |
| 密集 grid | 5,5,7,6,9 | 33 | 5818 | 852.02 | 0 / 0 |
| 密集 board | 4,9,7,4,8 | 33 | 5138 | 719.29 | 4.66 / 72 |
| GO付近 grid | 1,1,28,1,1 | 6 | 1498 | 316.92 | 0 / 0 |
| GO付近 board | 1,1,28,1,1 | 6 | 1498 | 328.72 | 0.63 / 11 |

根の訪問数は全て32。各候補の平均評価はfixed_analysis.jsonのroot_meansに保存。密集gridは15.0,11.6,28.714,27.0,37.667点、boardは6.25,31.667,23.714,3.0,30.125点。選択候補の平均値は37.667→31.667で、改善とは言えない。一方、探索した単一経路の最大はgrid51点/4合体、board65点/6合体。単一最大値は期待得点でも実ゲーム成績でもない。

全ケースで選択候補の即時post25得点/合体は0/0、即時GOはfalse。GO付近の即時GO配列は両方式true,true,false,true,trueで、既存の除外が維持された。GO付近では深い探索の全32反復が終端GOになり、即時安全だけで長期安全とは言えない。

全体時間は初回コスト・経路長・GO停止時刻も異なる単発測定。719msと852msだけで「候補生成による高速化」と結論づけない。生成合計0.63〜4.66msと経路変更による物理計算量の差を区別する。

## 5. 固定5候補外の事例

診断では0,.125,.25,.375,.5,.625,.75,.875,1と少数の同種果物中心を試した。これは実行時の候補生成には含まれない。2手の試験では公開Aと表示NEXTのBだけを落とす。仮想C=slot0は2手終了時の保持であり落とさない。実際の未公開Cを読んでいない。

密集35果物で、同じ正規化位置にA/Bを2手落とす比較：

| x | 最初の実world X | 合計得点増分 | 合体 | 合計tick | 2手後GO |
|---|---:|---:|---:|---:|---|
| 0 | -2.8624 | 0 | 0 | 90 | false |
| **.125** | **-2.1430** | **15** | **1** | **84** | **false** |
| .25 | -1.4236 | 0 | 0 | 73 | false |
| .5 | .0152 | 3 | 1 | 52 | false |
| .75 | 1.4540 | 3 | 1 | 72 | false |
| 1 | 2.8927 | 0 | 0 | 64 | true |

.125は固定5候補になく、この限定した2手系列では固定候補の最大3点を上回った。15点は2手目の落下後に発生し、移動中の加点ではない。ただし移動時間・経過tickも異なり、遅延した自然合体の影響を完全には分離していない。また固定5×5の全2手系列を上回ったという試験でもない。

GO付近のfixtureでは.25は即時GO、.375や.4369/.3991は即時非GOだった。ただし固定候補の.5も非GOであり、off-gridが唯一の回避手という意味ではない。2手後はそれらもGOとなった。

**今回の幾何方式は.125を根候補へ入れられず、.349260を選んだ。** 隠れた同種果物、衝突後の滑り込み、遅延連鎖、動く果物の将来位置は軽いbounds計算だけでは捉えにくい。特定のfixtureに合わせて.125を後付けしない。

## 6. 短時間の実ゲーム

同一Player build、seed750300、各方式を1プロセスずつ各8手。headless/sync、32/4/5/post25。4ゲーム展開はしない。

| 指標 | grid | board-five |
|---|---:|---:|
| 成功した操作 | 8 | 8 |
| 8手後の得点（最終得点ではない） | 26 | 26 |
| 実合体数 | 3 | 3 |
| GO | なし | なし |
| 計画時間 平均/中央値/最大ms | 249.88 / 263.74 / 281.94 | 255.36 / 266.39 / 296.13 |
| 候補生成合計/1手 平均ms | 0 | 2.11 |
| 候補生成合計/1手 最大ms | 0 | 3.87 |
| drop間隔 実秒 平均/中央値/最大 | 1.219 / .993 / 2.040 | 1.151 / 1.060 / 1.880 |
| drop間隔 tick 平均/中央値/最大 | 59.14 / 61 / 102 | 57.57 / 54 / 94 |
| 根の配列が固定5個と異なる手 | 0 | 7 |

drop間隔標本数は各7。新方式の実計画平均は約2.2%増だが、盤面や移動が異なるため候補生成だけの純粋コスト差ではない。極端な増加はこの短時間試験では見られなかった。

選択候補のapplied_xと実drop Xの差は最大2.384e-7 world units。既存のSelected drop X検査を通過し、許容誤差は変更していない。全得点26=step報酬26+step間0、conserved=true。公開果物系列10個は両方式 `[3,0,4,3,3,0,1,1,0,2]` で一致。環境メタデータのGO比0.83、ルールv2、binary/environment hashの対応も監査した。

両ゲームはstep_limitによる打切り。**自然GOゲームは0件、有効な強さ比較ペアも0件。** 26点を最終得点として集計しない。最新監査のstatusはsmoke_completed_not_strength。旧の中間集計ではincomplete_or_invalidだったが、打切りを強さデータから除外した結果であり、実行失敗ではない。元ファイルを上書きせずlive_smoke_audit_finalへ再集計した。

例外・操作不一致・報酬二重計上は見つからなかった。ただしGOの正例がなく、GO見逃し/過剰予測が増えないと結論づける材料には不足する。長期得点性能も未検証。

## 7. 比較実験スクリプト

`Python/compare_candidate_ai.py`。

- grid/board-fiveだけを変え、両方MCTS32・深さ4・5個・post25・sync。
- 常に1ゲームずつ実行し、seedごとに実行順を交互にする。
- 同じseedの公開果物系列の共通prefix、環境/binary、policy以外の全設定を検査。
- 既存episode監査・Selected drop X検査・報酬保存則を再利用。
- 自然GOのみ有効ペア。途中終了・不足ログ・seed/設定/座標不一致は理由付きで除外。
- 平均/中央値/最大/最小、操作/合体/計画時間、GO混同行列、ペア得点差/勝敗とpaired-seed bootstrap 95%区間を保存。1ペアではCIを作らない。操作・状態を独立標本として増やさない。
- JSON/CSVは新規作成のみ。再集計は新しいreport-dirを指定する。

「同じseed」は全プレイの物理状態の一致を意味しない。行動が変われば盤面が変わる。果物系列も長期に一致し続けるかはログから監査し、異なるペアを正常扱いしない。

## 8. テストと互換性

- Python150検査成功。新policyの型/組合せ、4ゲーム拒否、ノードX対応、旧Player拒否、ペア単位CI、打切り除外、実座標不一致、上書き拒否を含む。
- native MCTS861 / Rules84 / Path26 / Frame58、計1029検査成功。従来sync/粗分割/細分割とGO・物理・Resetの回帰を維持。
- 幾何テスト：アンカー維持、同種中心の選択、順序入替の不変性、合法範囲と並び、空盤面のgrid、遮られた同種候補の抑制を成功確認。
- Unityバッチbuild成功、Value parity24ケース成功。既存モデルSHA256 `7e95aee3f462afb9faa02843b9612bb018f0051b0c68349d1a89d508d2631d2c` を確認。
- 正常な既存ログ・モデルは変更/削除しない。追加フィールドは後方互換。リアルタイム方式やViewerの新機能・録画再生は実装しない。

主な結果ファイル：baseline.jsonl、final_comparison.jsonl、fixed_analysis.json、native/、live_smoke/、live_smoke_audit_final/、smoke_analysis.json。comparison.jsonlはReport保存を補う前の中間結果なので、最終の解析はfinal_comparisonを用いる。

## 9. 変更ファイル・関数・行番号

全て `C:\SuikaGameAI` 内。

| ファイル | 主な箇所 | 内容 |
|---|---|---|
| Unity/Assets/Scenes/Script/DropCandidateGenerator.cs (+.meta) | 6/9 Generate | 幾何候補5個、同種/隙間/アンカー |
| Unity/Assets/Scenes/Script/SuikaPredictionPath.cs | 161 DropCandidates | 現在のlocal Colliderから型/形状を取得 |
| Unity/Assets/Scenes/Script/MctsPlanner.cs | 22 Node.positions、41 Report、134生成、154 actionX、258 metrics | ノードに配列を固定し、各予測とログへ実Xを渡す |
| Unity/Assets/Scenes/Script/StepPlanner.cs | 27/35 Validate | grid既定・実験組合せの検査 |
| Unity/Assets/Scenes/Script/SuikaCandidateProbe.cs (+.meta) | 15 GeometryTests、Start | 同一root A/Bと限定的な座標診断 |
| Python/src/suika_ai/unity_env.py | 413/423 defaults/validate | 候補方式の指定と入力検査 |
| Python/src/suika_ai/parallel_play.py | 197 run_parallel | board-fiveは1ゲーム限定 |
| Python/play_parallel_ai.py | 21/55 main | --candidate-policy |
| Python/compare_candidate_ai.py | settings/validate_geometry/summarize/main | 1ゲームずつのpaired比較と監査・統計 |
| Python/compare_mcts_ai.py | 35 episode、63/78 | expected_settingsを省略可能引数に追加。既存呼出しは従来設定のまま |
| Python/tests/test_candidate_policy.py | 全体 | 新policyと集計の回帰 |
| docs/STEP8I_REPORT.md、DEVELOPMENT_LOG.md、DEVELOPMENT_PLAN.md | 今回追記 | 実測と判断 |

変更の核：`actionX = positions == null ? (float)action/(count-1) : positions.x[action]`。gridは同じ除算、boardはそのノードで固定した配列。Select等の数式を変えない。

## 10. ユーザー用PowerShell

新方式を1画面で短く試す（8手、強さ評価ではない）：

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\board_five_demo_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + ([guid]::NewGuid().ToString('N').Substring(0,6))
.\.venv\Scripts\python.exe .\play_parallel_ai.py --games 1 --view-games 1 --episodes 1 --max-steps 8 --ai-mode mcts --candidate-policy board-five --planning-execution sync --mcts-iterations 32 --mcts-max-depth 4 --candidates 5 --post-drop-steps 25 --seed 750301 --base-port 37900 --output $out
```

従来方式は`--candidate-policy grid`。省略時もgrid。同期のため探索中のカクつきは残り、今回その改善は対象外。

10組・20ゲームを自然GOまで比較する場合（長時間実験、Codexでは未実行）：

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\candidate_compare_10_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + ([guid]::NewGuid().ToString('N').Substring(0,6))
.\.venv\Scripts\python.exe .\compare_candidate_ai.py --pairs 10 --seed 750400 --base-port 37800 --max-steps 3000 --output $out
```

自然GO前に3000手へ達したゲームも除外する。異常や打切りで除外がある場合は正常完了扱いしない。JSON/CSVのeligible/exclusion_reasonsを確認する。全体停止はCtrl+C、完了済みログは残る。

既存結果だけを新しい場所へ再集計するには：

```powershell
.\.venv\Scripts\python.exe .\compare_candidate_ai.py --analyze-only --output "outputs\実際の比較フォルダ" --report-dir "outputs\未使用の集計フォルダ"
```

保存されるcandidate_comparison.jsonに有効ペア数・除外理由・勝敗・平均差CI、candidate_pairs.csvにseedごとの得点差がある。既存の実行がポートを使っている場合は空いているbase-portを選ぶ。

## 11. 標準採用と次の改善

**標準採用しない。** 追加生成は軽いが、固定4盤面のうち根が変わったのは密集1件で、その選択平均評価は改善していない。候補外の有利な.125を拾えていない。実通信8手は同点で、自然GOまでの差は未測定。低コストと動作成立だけで強くなったとは言えない。

次はまず今回の2方式を自然GOまで同一seedで比較し、平均得点だけでなくペア差CI、GO誤り、操作コストを見る。候補生成の採用は実ゲーム結果を見て決める。

その後の対象の比較（今回未実装）：

- **探索回数/深さの費用対効果を優先して小比較**。根の訪問は約4〜9回で、最大65点の経路があっても平均判断は低い。grid32/深さ4を基準に、まず64/深さ4等の1軸を比較して判断の安定性と実得点を調べる。計算量増を明記し、回数を増やせば必ず強くなると仮定しない。
- heuristic rollout：無作為な先の手を減らせる可能性はあるが、全5候補を物理評価するならrolloutコストが増え、手作り評価への偏りも入る。反復数だけでなく同じ実計算時間で比較が必要。
- 木の効率化：同じ計算を安くできれば反復へ回せるが、それだけで評価の質は変わらない。既存高速化との重複、solver/cacheを壊す再利用を避ける。
- 7/9候補や局所補間：.125の例には有望だが、32回固定では1候補の訪問がさらに少なくなる。今回のfixtureに合わせて候補を追加せず、候補数/反復数/実コストを別条件で検証する。

現段階で「5候補が高得点化を妨げる場面はあり得る」という具体例は得た。しかし「今回の盤面依存5候補がその制約を解決した」という実測根拠は得られていない。
