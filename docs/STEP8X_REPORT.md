# STEP 8-X：探索予算と候補追加の連動（2026-10-25）

## 結論

新方式は比較用の widening_policy="budgeted"。既定legacy・32回MCTS・旧wideningを維持。GO .83、環境step8e-all-fruit-go-v2、物理/得点/出現確率/UCT/random rolloutは変更していない。新PlayerはUnity/Builds/Step8X/SuikaGameAI.exe。develop、commit/pushなし。
高得点化は未確認。自然GO実験は実施していない。まず3seed×4条件の予備比較をユーザーが実施する。

## 変更前の8-Wの確認

旧Playerで3固定盤面を測定。adaptive32..512は序盤512回/2494ms/x0、 中盤128回/2095ms/x.25/stable、密集512回/13211ms/x.5。固定512まで継続しても各盤面の選択位置は同じ。特に中盤の早期終了は同seedの512回の選択と一致した。ただし3盤面・1seedであり安定判定の妥当性を一般化しない。
旧widening+adaptiveも動作し、各盤面512回・最終9候補、2494〜13211msのadaptiveのみとは別の経路になった。旧combined時間2513/8433/13098ms、選択.25/.125/.5。中盤のstableは512回上限と同時で、早期節約ではない。
旧wideningは1候補ずつ追加。既定ではノード訪問10/40/90/160以上、追加済みの安全候補が各1訪問以上なら次を追加、上限9（設定上限31）。adaptiveと併用できるが、追加前にstable終了でき、未訪問候補をstable評価から外していた。
32..32768・120秒設定の境界はPython回帰で再確認。32768回/120秒を実行したわけではない。拡張時間上限は反復境界のsoft limit、32反復未達はno dropエラー。木・統計は同一判断内で継続、手間では共有しない。

## 新方式：いつ追加するか

- 初期5位置0/.25/.5/.75/1を保持する。
- ノード訪問32以上で5→7、128以上で7→9。一般式32×(1+追加済み数/2)^2。
- 現在の候補はすべて予測済みで、安全候補は各adaptive_min_action_visits（既定4）以上。全候補GO/落下不可なら追加しない。
- 新規2候補×4訪問の機会を見積もる。ノード到達率=node.visits/完了反復数、必要な残り反復=8/到達率。残回数と、これまでの最大1反復時間×必要反復分の残時間を両方要求する。
- 到達率は過去からの推定であり、将来の訪問を保証しない。非rootも同じ条件。追加した安全候補の4訪問未達、または前checkpoint以降の候補追加があればstable終了を抑止する。ただし時間/反復上限を優先し、未評価不足のまま上限終了する場合はログで識別できる。
- B/C共通で拡張adaptiveの未訪問・不足候補をstable扱いしない補強を追加。従来非extendedの判定は変更しない。
- 同一木へedgeをappendし既存visits/sumを保持。新edgeは0開始。物理状態/未知果物の処理は変更しない。
- 上限widening_max_candidatesは5..31の奇数で指定可能。今回9、17以上は設定受理のみで実運用未検証。閾値は初期診断値で最適化済みではない。

## どこへ追加するか／追加相談への回答

既存TryWidenの配置ロジックを再利用。区間幅w、両端のMCTS平均将来得点qを使い、1個目は

merit = w × (1 + clamp(max(q_left,q_right)/55, 0, 1))

が最大の区間の中点。2個目は評価を使わず最も広い区間の中点。同点はseed/node ID/追加数で再現可能に選ぶ。追加の物理probeや乱数消費はない。スコアは選択確率や真の価値ではなく探索標本の平均。
「訪問数で追加可否を決める」と「高評価位置の近くへ追加する」は別問題である。現方式は両方を一部組み合わせるが、評価による倍率は1〜2に制限され、幅が優先されやすい。上位2位置に集中する方式ではない。初期5→9まででは4つの中点が埋まり最終的に固定9と同じ配置になる。したがって今回の主な差は段階追加と探索配分であり、精密な局所最適化が完成したとはいえない。
上位複数位置の近傍へ.0625なども追加しつつ元5点を残す別方式は次の比較候補。ただし現在の平均値はランダムrolloutやGOで変動するため、最高平均1点だけに絞らず、訪問数・不確実性・位置の分散も条件とするのが妥当。今回は同時変更すると効果の帰属が不明になるため実装していない。最終的には自然GO得点と時間で採否を判断する。

## 固定盤面の結果

A=fixed128、B=adaptive5、C=adaptive9、D=fixed256。全て深さ4、sync/random、B/C上限512、全条件20秒、auto-depth OFF。
以下は1判断ごとに別Playerで測定した値。各1測定であり速度差を統計的優位と扱わない。

|盤面|方式|反復|候補|選択x|ms|物理tick|Unity確保peak MiB|
|---|---|---:|---:|---:|---:|---:|---:|
|early_fixture|adaptive5|512|5|0.0|2402|112054|181|
|early_fixture|adaptive9|512|9|0.0|2310|108016|181|
|early_fixture|fixed128|128|5|0.25|603|27434|76|
|early_fixture|fixed256|256|5|0.75|1191|55483|111|
|mid_fixture|adaptive5|128|5|0.25|1930|26729|86|
|mid_fixture|adaptive9|512|9|0.375|8176|107740|221|
|mid_fixture|fixed128|128|5|0.25|1960|26729|86|
|mid_fixture|fixed256|256|5|0.25|3917|53700|131|
|dense_safe_fixture|adaptive5|512|5|0.5|11898|92374|291|
|dense_safe_fixture|adaptive9|512|9|0.625|11912|90594|289|
|dense_safe_fixture|fixed128|128|5|0.5|2782|22216|103|
|dense_safe_fixture|fixed256|256|5|0.5|5754|45375|165|

3盤面のC再実行で全反復物理・全ノード統計が完全一致。従来32も旧8-Wと3盤面で一致。追加探索はfixed512の同じ物理計算を途中から継続する構造で、既存の追加探索基盤を維持。
512以内ではCの非root候補追加は0。追加されたroot4候補は実際に選択/再訪。密集x.875は即時GOのため1訪問で除外され、これを4回試すよう強制しない。
同じ512反復での非root既訪問edge再訪数は、序盤B362/C242、密集B379/C288。候補追加が深い統計の分散を改善した証拠はなく、むしろ減っている。中盤Bは128回で終了、C512回なので直接同予算比較ではない。
序盤2048回の追加診断は約10.48秒、非root66候補追加・その再訪336回。深さ1での追加を実確認した。512比較の優位性を示すデータとしては扱わない。
探索内GOサンプルは密集B181/512、C207/512。実ゲームのGO率ではなく、探索した異なる経路の結果。選択候補の即時GO除外は維持。
0.5秒上限診断は91反復・約502msでtime_limit。候補7で終了。最短時間の保証ではなく、反復境界の超過を記録する。
一括21判断プローブはフレームを戻さずScene解放を溜め、確保メモリ約2.8GB・終了遅延が発生した。結果出力完了後に自分のプローブのみ終了し、上表の独立Player12判断で再計測した（全12件exit0）。一括プローブの累積メモリを各方式固有の使用量として比較しない。実ゲームの継続的メモリ増加は長時間未検証。

## 実通信とテスト

各方式4手、計16落下成功。座標・報酬保存・設定・root訪問・イベント・公開果物系列一致の監査合格。全てstep_limitで自然GOサンプル0。4手終了時は全方式0点/合体0。実ゲームでの合体/GO頻度改善を検証したとは扱わない（物理/合体/GOの回帰はnative tests）。
A反復128×4、B512/512/512/128、C512/512/512/128、D256×4。C候補9/9/9/7。平均判断msは893/3204/3269/1867。短い序盤の値。
Python265テスト成功。Unity既存1029チェック（MCTS861/rules84/path26/frames58）、追加native selftests（残回数・時間不足・5→7→9・非root・全GO・早期停止抑止・統計保持）成功。全経路監査21件で公開NEXT/未知chance/物理tickの保存を確認。要約ログ12独立診断と16実通信を監査。
旧Step6/8T/8U/8W Player608ファイルのhash不変。Scene/Prefab/物理設定変更なし。ビルド生成フォント差分だけは開始時の内容に復元した。

## 比較ツールと保存

Python/compare_allocation_mcts.py。条件をseedごとに循環し、4seedブロックごとに逆順、1Playerずつ実行。ゲームseedと探索seedを分離し、両方記録。完全に同じ物理履歴になる保証はない。判断時間・通信間のゲーム進行が違い得る。
最大30seed×4方式。Player/Python hashと実験設定を固定、変更時は再開拒否。既存フォルダへ新規実験を上書きしない。完了ゲームはresult.jsonとhashを保存。途中停止のattemptは保存したまま新attemptでゲームの最初から再実行。完了したstep_limitは再実行せず、自然GO得点比較から除外する。
Ctrl+Cは既存run_parallelの停止フラグで処理中の手を待ち保存するため即時ではない。今回実際のCtrl+Cを送る試験は未実施。完了4件への--resumeで新Player/追加attemptなしを確認。ハッシュ破損検出はPythonテスト。
reports/連番/にcomparison.json、games.csv、pairs.csv、comparisons.csv、summary.csv、actual_events.json/csv、achievement_rates.json、allocation.json/csv。探索終了/継続理由、checkpoint選択変化、候補追加・最終訪問/再訪、depth_metricsはallocation JSONに保持。実ゲームイベントsource=actual_gameのみ。未知イベントを未達成に補完しない。比較は対応seed単位bootstrap95%CI、複数比較は探索的と明記。

## ユーザー用コマンド

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\allocation_compare_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_allocation_mcts.py --games 3 --seed 763100 --search-seed 8191 --time-limit 20 --max-steps 3000 --output $out
```
3seed/12ゲーム。最大30seedは--games 30。最初は3を推奨。手数3000に届いたら自然GO扱いしない。
再開：同じPowerShellなら `--output $out --resume`。別ウィンドウなら実際の保存先を指定。設定変更や--smokeを追加しない。
```powershell
.\.venv\Scripts\python.exe .\compare_allocation_mcts.py --output $out --resume
.\.venv\Scripts\python.exe .\compare_allocation_mcts.py --output $out --analyze-only
```
--analyze-onlyは新しい集計フォルダのみ作成しゲームを起動しない。既存8-S〜8-W実験は今回再開しない。

## 変更箇所

- MctsAdaptiveControl.cs: Validate(14), TryBudgeted(51), GuardAdditions(66), Assess(77)。追加記録に最終訪問を追加。
- MctsPlanner.cs: PlanFramesの追加(222)、checkpoint保護(367)、追加候補の最終統計保存。UCT/rollout/報酬不変。
- StepPlanner.cs: PlanningSettings.widening_policy(41)、既定legacy。
- unity_env.py: PLANNING_DEFAULTS(417)、validate_planning_settings(423)。
- SuikaAdaptiveProbe.cs: SelfTestsに新方式の境界検証。
- SuikaWorkerBuild.cs: BuildAllocation(21)、8-Wビルド上書き保護。
- compare_allocation_mcts.py: settings(12)、audit_decision(22)、audit_game(62)、summary(81)、run(109)、make_plan(132)、main(148)。
- tests/test_allocation_mcts.py: 条件差/境界/実行順/完了hash/不正早期停止の5テスト。
- この報告書、DEVELOPMENT_LOG.md、DEVELOPMENT_PLAN.md。

## 次の判断

標準採用しない。高得点化の証拠なし。候補追加のタイミングは制御できたが、非rootの深い探索統計の薄さは残る。まず4条件3seedの予備比較で最終点・スイカ率・時間・GO見逃しを確認し、十分なら追加seedへ進む。局所細分化は別の比較軸にする。候補生成の改良だけでダブル達成を期待しすぎず、将来は物理探索+新環境の方策/長期価値を実ゲームで検証する。ただし今回はモデル学習も新しい局所配置方式も実装しない。
