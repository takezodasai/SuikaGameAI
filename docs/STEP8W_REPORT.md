# STEP 8-W：拡張探索予算と探索開始前の深さ選択（2026-10-25）

## 結論

既定の従来MCTSは変更しない。新方式はmcts_extended_budget=trueで明示指定する。legacyの制限/標準profile32回・深さ4、従来のUCT/chance/random rollout/報酬/物理/GO/候補方式を維持。新PlayerはUnity/Builds/Step8W/SuikaGameAI.exe。Step6/8T/8U Player456ファイルhash不変。
変更前の8-U開発内容を60656eeとしてdevelopへcommit/pushし再現点を作成した。既存比較ログ・モデルはGit除外のまま保存。旧比較ツールはPython hash差で再開を拒否するため、旧8-U比較を再開する際は60656eeのPythonを分離して使用する必要がある。今回旧実験は再開していない。

## 設定

|項目|新方式|
|---|---|
|ON/OFF|mcts_extended_budget。既定false|
|探索回数|32〜32768。fixedはmcts_iterations、time/adaptiveはmcts_max_iterationsが上限|
|段階追加|adaptiveで32→64→128→256→…、同じroot/統計/RNGのまま継続|
|時間上限|mcts_time_limit_seconds、0より大きく最大120秒。新方式ではfixedにも適用|
|早期終了|adaptiveのみ。既存の候補訪問・選択安定・平均値変化・終端率・経験的標準誤差の判定を再利用|
|深さ|2〜256。新CLIの既定4。16以上はexperimental_depth=true|
|自動深さ|mcts_auto_depth。既定OFF。ONではauto_depth_min/maxの2〜8に限定|
|全経路出力|新方式の通常は要約。mcts_full_trace=trueは短時間診断向け|
|候補|固定5/9または既存widening。今回候補追加規則自体は変更していない|

時間上限または回数上限、adaptive安定判定で停止。時間は反復境界で確認し、反復途中の物理を切断しない。min32に届かなければ成功した判断にせず、minimum32 not reached; no dropの明示エラー。時間を超えて32回を無理に完了させる方式ではない。
時間上限はsoft。準備・反復・結果集計の経過を測定しtime_overrun_msへ記録。JSON生成・UDP転送・実移動/落下時間は別で、1手のAPI往復全体が120秒以内という保証ではない。Pythonの既定通信待ちには新探索時間の予算を加算する。呼出側が短いtimeoutを明示した場合はその指定を尊重する。最悪時の反復超過、120秒の連続負荷は未検証。
同一判断内の木は保持するが、異なる実ゲームの手/深さの木を使い回さない。深さ変更時は新しい木で開始し、異なるhorizonのreturnを混在させない。

## 自動深さの初版

UDPの各手開始前に、前の正常完了した判断の深さ別診断から次の深さを選ぶ。エピソードResetで履歴破棄。候補方式/探索seed等のキーが異なる履歴は使わない。各手の実行中は深さ固定。
初回は指定深さを2〜8の自動範囲へclamp。前回最深部が128反復以上でtree action率5%未満・revisit8未満なら次の手の深さを1下げる。前回rootが安定し、最深部tree action率25%以上・revisit8以上なら1上げる。それ以外は保持。回数と深さの比例式にはしていない。
5%/25%/8回は初期診断用の未最適化閾値。前の手の統計は現在盤面の難しさを保証せず、浅くすることが長期価値を改善するとも保証しない。したがって既定OFF・実験扱い。深さを上げる分岐はsynthetic native testで確認したが、実ゲームで上げるケースの有効性は未確認。

## ログ・計算の維持

depth_metricsに各深さのnode数/action訪問/revisit/tree action/rollout action、depth_selectionに指定/採用/前回深さ/根拠を保存。既存checkpointに選択x・平均・訪問数・安定理由が残る。total_physics_ticksは大予算に備え64bitへ拡張。
新方式の要約出力はroot全候補/訪問/平均値/候補追加イベント/深さ別集計/GOサンプル数/最大到達深さを保持し、全経路iterationsと非root個別nodeの送信を省く。計算中の探索木は削除しない。従来方式の出力は従来どおり。要約ログへ従来のfull-trace専用監査スクリプトをそのまま適用しない。
要約はUDP 4096fragment上限や全経路の巨大化を避けるため。内部で必要な物理・乱数・UCT・報酬を省略した高速化ではない。深さ256/32768回の内部メモリ量は未検証で、入力上限対応を実用性の保証と解釈しない。

## 短時間テスト

|盤面|条件|実反復|深さ|終了|判断ms|超過ms|
|---|---|---:|---:|---|---:|---:|
|early_fixture|legacy32|32|4|iteration_limit|225.96|0.00|
|early_fixture|extended32|32|4|iteration_limit|167.58|0.00|
|early_fixture|fixed128|128|4|iteration_limit|641.78|0.00|
|early_fixture|adaptive128|128|4|iteration_limit|625.66|0.00|
|early_fixture|ceiling32768|372|4|time_limit|2001.59|1.59|
|early_fixture|depth2|32|2|iteration_limit|72.35|0.00|
|early_fixture|depth8|32|8|iteration_limit|498.38|0.00|
|mid_fixture|legacy32|32|4|iteration_limit|516.22|0.00|
|mid_fixture|extended32|32|4|iteration_limit|511.30|0.00|
|mid_fixture|fixed128|128|4|iteration_limit|2027.16|0.00|
|mid_fixture|adaptive128|128|4|adaptive_stable|2079.06|0.00|
|mid_fixture|ceiling32768|122|4|time_limit|2001.05|1.05|
|mid_fixture|depth2|32|2|iteration_limit|320.81|0.00|
|mid_fixture|depth8|32|8|iteration_limit|1036.07|0.00|
|dense_safe_fixture|legacy32|32|4|iteration_limit|794.31|0.00|
|dense_safe_fixture|extended32|32|4|iteration_limit|813.77|0.00|
|dense_safe_fixture|fixed128|128|4|iteration_limit|3013.86|0.00|
|dense_safe_fixture|adaptive128|128|4|iteration_limit|3045.17|0.00|
|dense_safe_fixture|ceiling32768|83|4|time_limit|2009.60|9.60|
|dense_safe_fixture|depth2|32|2|iteration_limit|498.22|0.00|
|dense_safe_fixture|depth8|32|8|iteration_limit|1043.04|0.00|
|early_fixture|depth16|32|16|iteration_limit|1084.32|0.00|

3盤面のlegacy32/extended32は旧8-Uの選択位置・全反復物理・state digest・全node統計と一致。adaptive128はfixed128の同じprefixと一致し、再開始/二重計算していない。1µsの予算は全3盤面で32未達/no dropを確認。
最大32768設定/2秒の実反復は372/122/83、超過1.59/1.05/9.60ms。別の中盤5秒上限/32768で128反復・約2026ms・adaptive_stableを確認。cap128と同時のstableを早期節約と誤記していない。
実通信は固定128/auto ON4手とadaptive/32768上限/2秒4手の合計8手。正常落下、報酬保存、root訪問保存、深さと実設定一致、要約送受信を確認。自動深さ4→3→3→3、探索中変更なし。adaptive実反復128/305/128/239、安定/時間/安定/時間で終了。全てstep_limitで自然GO比較から除外。
Python260テスト、既存Unity1029チェック、新境界/深さ選択selftest成功。手動深さ2/8は各3固定盤面、16は序盤1盤面32反復だけ実行。256は設定受理/境界検証のみ。32768全反復、120秒の連続探索、自然GOでの強さ、ダブル到達、GUI/Viewerの滑らかさは未検証。同期処理なので長い探索中の画面停止は残る。

## 実行例（短時間・ユーザー用）

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\budget_smoke_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\play_budget_mcts.py --mode adaptive --max-iterations 512 --time-limit 5 --depth 4 --max-steps 8 --output $out
```

自動深さを試すときだけ --auto-depth を追加。9候補は --candidates 9、wideningは --widening（初期5）。両方を同時指定しない。
上限を指定する例は --max-iterations 32768 --time-limit 120。これは最大まで実行する指定ではないが、1手が長時間になる可能性がある。今回はCodexで120秒探索/自然GOを実行していない。固定の回数を試すなら --mode fixed --iterations 256 とし時間上限にも従う。深さ16以上/長時間は実験的で、比較前にメモリ・誤差・時間を測る。
run.json/game_00.jsonl/metadata/summary.jsonへ保存。各transition.info.planning.mctsを確認。出力フォルダは新規のみ。このCLIに中断ゲーム途中からの再開機能は追加していない。旧比較CLIと旧Playerは残す。

## ダブルスイカへ向けた率直な提案

深さ256は長期戦略の実現そのものではない。8-Vでは4手目のほぼ全てがランダムrolloutで、さらに深くしてもランダムな未来の得点ノイズや物理誤差を増やす可能性がある。未公開果物の分岐も急増する。
優先候補は、新環境のMCTS実ゲーム履歴から方策（有望位置）と価値（将来追加得点）を学ぶ反復改善。旧ValueNetの単純再投入は勧めず、候補順位と自然GOの得点で検証する。次点はGO誤差の切り分けと、同seed128/256の計算予算実験。今回新NNや新rolloutは実装していない。
現ルールのスイカ同士の消滅は無加点で、空間を空ける長期利益が短い得点探索へ見えにくい。ルールへbonusを追加せず、将来得点の価値評価で利益を学べるか検証する。double成功0の既存データだけで成功分類モデルを学習すると全失敗モデルになり得るため、成功例と生存/将来点のデータが必要。最終採否は平均最終点とスイカ/ダブル率で判断する。

## 変更ファイル

MctsDepthControl.cs（新規）、StepPlanner.cs、MctsAdaptiveControl.cs、MctsPlanner.cs、UDPStepProtocol.cs、SuikaAdaptiveProbe.cs、SuikaWorkerBuild.cs、Python/src/suika_ai/unity_env.py、parallel_play.py、play_budget_mcts.py（新規）、tests/test_extended_budget.py（新規）、この報告書とDEVELOPMENT_LOG.md。ゲームのPrefab/Scene/物理/GO/得点/出現確率、既存モデルは変更していない。
