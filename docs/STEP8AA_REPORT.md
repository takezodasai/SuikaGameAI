# STEP 8-AA：局面に応じたMCTS予算配分（2026-10-26）

## 実装と使用範囲

比較用 `mcts_budget_mode="importance"` を追加した。既定fixed・従来32回・adaptive・time・旧widening/budgetedの処理は残す。新Playerは `Unity/Builds/Step8AA_02/SuikaGameAI.exe`。最初の試作Step8AAも残した。Step8X以前を上書きしない。GO比率0.83、ルールID step8e-all-fruit-go-v2、Collider、物理、得点、果物出現確率、UCT、rollout、報酬は維持。commit/pushなし。

## 判定式（研究用の初期値）

既存のroot選択（即時GO除外、最大訪問数、同数なら平均得点）を基準とする。各安全候補について、平均m、訪問数n、標本分散vを用いる。

- 不確実性幅 U = 2 × max(i,j) sqrt(v_i/n_i + v_j/n_j)。2標準誤差を診断余裕として使う。相関したMCTS統計について95%信頼区間・最善手保証とは主張しない。
- 明確な優位：選択候補の平均 − 他候補の最大平均 > max(許容差δ, U)。安全候補が1つなら優位判定可。
- 実用上同等の推定：(最大平均 − 最小平均) + U <= δ。
- δ は既存設定 adaptive_value_tolerance、既定3点。最適値や実ゲーム損失の上限ではない。
- 即時GO/落下不可を除くroot候補は全て既存 adaptive_min_action_visits（既定4）以上が必要。未知候補は除外して安定扱いしない。
- 通常は32/64/128の3checkpoint、重要局面は32/64/128/256の4checkpoint以上が必要。
- 直近2区間で、root候補集合が変わらず、平均の変化<=δ、同じ勝者が続くことを要求。ただし、連続して候補群が実用上同等と推定された場合、勝者の微小な入れ替わりは許容し、equivalent_winner_changeとbest_changesへ記録する。
- 安定要件と「明確な優位」または「実用上同等」を満たした場合に確信ベースで終了。全候補即時GOの場合も複数段階後に既存フォールバックへ渡せる。GO条件やフォールバックの選択式は変更しない。

重要性は、接触済み果物の中心がGOラインから約1直径以内、即時GO候補の存在、選択候補の探索内GO率、候補間のGO率差、即時得点機会の幅で判定する。後3項の閾値には既存 adaptive_max_terminal_rate（0.1）とmcts_point_scale（55点）を使用する。幾何は注意指標であってGO確率ではない。重要でも安定すれば256等で終了でき、必ず120秒使う規則ではない。評価値への高さ/GO近接ペナルティは追加しない。

次の倍増段階の推定費用 = 必要反復数 × 直近段階の平均反復時間 × 1.5 + 過去最大1反復時間。残り時間が不足する場合は insufficient_budget_for_next_stage として終了する。これは確信による終了ではなく、不確実なまま予算配分を打ち切る判断。実測を使う予測なので、同seedでもCPU負荷や時間境界次第で終了段階が変わり得る。

元の反復境界での時間チェック・探索上限は維持する。120秒はsoft limitで1反復分等の超過を time_overrun_ms に記録する。32回に到達する前に上限を超えた場合、従来どおりno dropのエラーとなる。探索木・統計は判断内で保持し、深さは探索中に変更しない。

## 候補追加・深い探索

既存TryBudgetedの局所訪問閾値32/128、追加候補を評価できる残予算、安全候補の最低訪問等を再利用する。その上で次を条件にする。

- 直前checkpointが、候補群の同等性で決着しておらず、順位/評価/GO差に未解決の問題を示す。
- 当該decision node自身にも評価のばらつき、またはδを超える平均差がある。
- 元の5位置を残し、5→7→9。追加座標は既存の有望区間/広い区間の交互選択。Coarse-to-Fineを新実装したわけではない。
- 新しいroot候補を未評価のまま確信終了しない。即時GO候補は再度4訪問を強制しない。
- 非rootの追加候補が未評価であることだけでは、全体の安定終了を禁止しない。rootに集約された不確実性は引き続き判定する。

rollout依存や深い枝の再訪不足は記録するが、それだけで際限なく探索を続けない。短い固定盤面テストでは非root追加は0件で、root追加・再訪を実測。非root対応は追加selftestと共通のnode処理で検証したが、自然GOでの有効性は未検証。

## 自動深さ

OFFでも新方式を利用できる。ONの範囲は既存2〜8、手動指定2〜256。16以上は実験的。新方式ではbudget_checkpointsに安定性を保存するため、既存MctsDepthControlの増深に必要な情報が得られる。各手開始前だけ変更し、途中の報酬統計を混在させない。

既存の条件は、前回128反復以上かつ最深部tree比率<5%・再訪<8なら深さを1減らし、安定かつtree比率>=25%・再訪>=8なら1増やす。今回のGUIは4→3→3。増深分岐は既存selftestで確認したが、実プレイでの増深や得点への有効性は未確認。timeモード自体の既存制約は変更していない。

## 測定結果

3固定盤面、探索seed8191、各2回、深さ4、自動深さOFF、上限1024回/10秒、Budgeted Widening ON。各判断を独立Playerで実行。復元盤面は配置/運動状態の再構築で、元ゲームの接触solver cacheを復元するものではない。

|盤面|反復|判断時間（2回）|候補|選択x|物理tick|終了理由|
|---|---:|---|---:|---:|---:|---|
|空盤面|128|788.5 / 692.4 ms|5|0.25|27434|stable_practical_tie|
|中盤|256|4304.6 / 4208.1 ms|9|0.125|54409|insufficient_budget_for_next_stage|
|35果物|256|6093.4 / 6122.7 ms|9|0.625|43299|insufficient_budget_for_next_stage|

3件とも同seed再実行の選択・ノード統計・物理更新が一致。中盤・密集の結果を「確信が得られた」とは扱わない。密集盤面はGO付近の接触済み果物1個を検知。中盤で追加4候補の訪問26/31/27/30、密集で1/18/51/23。1訪問の候補は即時GOとして除外された。非root追加は0。

初期試作では空盤面の微小な勝者変化を理由に512回まで継続したため、上記の同等候補群の安定判定へ修正した。初期試作のPlayer/ログも削除していない。

## テストと保護

- Python 272テスト成功。time/importanceの120秒待ち、最初の0/1/2通の損失、低速フレームでのメタデータ取得を仮想時計で検証。前回の長時間通信修正を維持。
- Unity既存1029チェック成功：MCTS861、rules84、path26、frames58。
- 新native selftests：複数checkpoint、明確な優位/同等候補/不確実な候補、微小勝者変更の記録、GO重要性、全GOフォールバック、予算不足、root未評価候補、非root追加による終了の過剰抑止を防ぐ条件、旧統計保持、深さ設定等。
- cap32で32反復、極小時間で32未達/no dropを確認。32768回完走や120秒連続の新方式テストは今回実施しない。
- 旧Step8Xと新最終Playerを3盤面×4設定で比較。従来32回・adaptive・time・budgetedの選択、全ノード、全反復内容、物理tickが12件一致。
- 旧Step6/8T/8U/8W/8Xの760ファイルのSHA256不変。Scene/Prefab/物理設定差分なし。

GUI3手：上限512回/8秒、自動深さON、seed765100、Unity画面と1画面Viewerを起動。512/128/128反復、深さ4/3/3、候補9/5/5、判断3006.8/565.0/703.9ms、落下位置.125/.5/.25。3手成功、座標・報酬保存・実落下数0/1/2・metadata・video_frames増加・video_error空を監査。全3手0点、step_limit終了。自然GOや高得点化の検証ではない。画面キャプチャによる目視QAは行っていない。

## ログと変更ファイル

既存game_00.jsonlの各transition.info.planning.mctsに importance_context と importance_checkpoints を追加。score、実落下数、board_fruits、GO近傍指標、gap/U/平均幅/GO率差、候補数、勝者変更、継続/終了理由、残り時間/次段階推定時間、root/nonroot pending、tree/rollout action数、非root再訪を保存。既存candidate_additionsに追加位置/反復/深さ/選択理由/最終訪問/再訪、depth_metricsに深さ別統計を残す。時間上限、超過、選択座標、思考時間も既存フィールドに保存する。GUI用--episode-eventsを追加（既定OFF）。実ゲームと予測のイベントは混ぜない。

- MctsImportanceControl.cs: Capture / Assess / AllowRefinement / SelfTests（新規）。
- MctsPlanner.cs: Report / PlanFrames（新モードのみのcheckpoint・候補追加gate・ログ）。
- MctsAdaptiveControl.cs: Validate（importanceの受理のみ）。旧Assess/GuardAdditions/TryBudgetedの計算を変更しない。
- SuikaAdaptiveProbe.cs: SelfTests（追加判定のnative検証）。
- SuikaWorkerBuild.cs: BuildImportance / IsProtectedDestination / CheckProtectedBuildGuard（新規別出力先、Step8X保護）。
- unity_env.py: validate_planning_settings（新モード検証）。通信修正を保持。
- play_parallel_ai.py: main（--episode-eventsの明示設定）。
- Python/tests/test_importance_mcts.py（新規）、test_long_planning_communication.py（importanceも再送回帰検証）。

全監査データはPython/outputs/step8aa_01/。final_audit.json、gui_audit.json、python_tests_final.log、final_compatibility.jsonl等。

## 次の判断

標準採用・高得点化・ダブルスイカ改善は未確認。物理予測のGO見逃し、推定分散が捉えない系統誤差、稀な連鎖の未観測、時間依存の終了段階、深い枝の少ない再訪は残る。まず自動深さOFFで固定予算MCTSと同seed自然GO比較し、得点と時間・早期終了後に得点機会を見落としていないかを見るのが望ましい。自動深さの効果は別条件で検証する。
