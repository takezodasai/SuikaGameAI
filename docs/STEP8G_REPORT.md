# STEP 8-G 計測と動的予約の試作（2026-10-23）

**結論：待ち時間短縮の効果は確認したが、MCTS採用率と密集盤面の停止時間は改善できていない。新方式は実験用に限定し、標準にはしない。従来の同期MCTSは維持する。**

## 1. 比較条件とデータ

Unity 2022.3.21f1 / develop / ルール step8e-all-fruit-go-v2 / GO0.83 / 32反復・深さ4・5候補・post25 / seed749100 / 1Player＋Viewer。並行して複数の計測Playerを動かしていない。既存モデル・ゲームルール・Collider・物理設定・MCTSのUCT/展開/rollout/逆伝播・報酬・未知NEXT分布は変更していない。

保存先は `C:\SuikaGameAI\Python\outputs\step8g_01`。

- `fixed/sync_d4`, `fixed/frames_d4`：序盤2要求＋35果物の密集fixture2要求。
- `fixed_adaptive_final/frames_adaptive_d4`：最終試作で同条件。密集fixtureは `outputs/step8c_01/dense_safe_fixture.json`。
- `continuous/{sync,frames,frames_adaptive}_d4`：それぞれ連続4手。自然GOまでの長期プレイではない。
- `fixed/frames_adaptive_d4` は初期試作の失敗記録。序盤の短い計測値を密集盤面に転用して予約期限に間に合わなかった。最終値へ混ぜない。
- `analysis.json`：上記ログの集計。`decisions.jsonl`に各要求の前後状態と完全な探索記録、`runtime.jsonl`に更新間隔/GC/I/O、`resources.json`にPlayer資源、`viewer.json`に表示統計。

連続試験で見えている保持/NEXTは3方式とも `(1,3),(3,0),(0,4),(4,2)` で一致。操作時刻が異なるため盤面は同一とは扱わない。全要求で報酬保存則conserved=true。連続4手終了時の得点は全方式0、GO正例は0件であり、強さやGO見逃し率を推定する材料には不足する。

## 2. 操作が遅かった直接原因

`frame-lead-ticks=150` は最大待機時間ではなく、**探索の基準にする未来tickの予約量**。固定dt約0.02なので150tickは3ゲーム秒。探索が終わっても予約tickの照合までは操作しない。実時間3秒を厳密保証するタイマーではない。

旧framesの連続1手目は、探索完了まで0.223実秒・9tick、その後の検証まで142tick＝2.84ゲーム秒待った。密集fixtureでは1探索が0.82〜1.07実秒で終わっても、結果完成後2.48ゲーム秒待機。失効した再探索は予約が302tickへ増え、完成後さらに5.44〜5.50ゲーム秒待った。密集1要求全体は9.74〜9.86実秒、累積探索workは1.57〜1.72秒。最大の無駄は計算そのものだけでなく予約待機と失効後の再予約である。

時間は重なって進むので、cooldown・探索・移動を無条件に足し合わせない。

- cooldown：設定0.4ゲーム秒。今回の実測の最初のCanDrop成立は前回dropから21tick＝約0.42秒（浮動小数と離散判定の結果）。仕様は変更しない。
- APIのpost25：落下後約0.5ゲーム秒を観測するため、次の要求を送る時点では通常cooldownを既に超える。
- 横移動：`movement_start_tick`から`drop_tick`を測定。ゲームの既存AI速度に依存し、予約待機と区別する。
- 完了→次要求：Python処理、fresh観測待ち、UDP待ち等を含む。今回の連続試験では8〜10tick相当の区間があるが、これは純粋なネットワーク遅延ではない。送信時刻を両端で同期計測しておらず、UDP単独遅延は未分離。
- fallback：一致しない結果を採用せず、既存heuristicで現在盤面を判断する。高速に見えてもMCTSの強さの維持とは別問題。

`frame_search.history`は試行ごとに開始/結果完成/検証tick・wall、lead、完了反復数、探索ゲーム時間、完成後待機、差分を記録する。`info`には要求・前回drop・次合法tick・移動開始・drop・完了時刻を追加。最終ビルドで、準備済み結果のdecision_finishをcommit時刻と混同しないよう修正した。主要比較ログはこの最後の計測フィールド修正前のため、非同期の判断時間は必ず `planning.frame_search.history` を使う（既存記録は書き換えていない）。

## 3. 採用した試作はAだけ

新しい明示指定 `execution_mode=frames_adaptive`。sync/framesの既定値を変えない。

- 完全な探索が終わった物理tick数とUpdate間の最大tick差を直近8件記録。
- 予約量＝ceil(最大探索tick×1.25)＋2×最大Update差、最小10・最大500tick。
- 未接触盤面と接触済み盤面を分けて校正。未知の区分では従来150tickから開始する。
- 期限超過は予約下限を2倍へ引き上げ、8回の完全探索後に下限を解除。設定が変われば校正を消す。
- 状態不一致だけを理由に待機を自動倍増しない。
- 25%は試作のスケジューリング余裕であり、安全性保証や物理許容誤差ではない。
- 位置/速度/回転/GO/接触資格/sleep/果物ID等の照合は厳密なまま。未完了探索は採用しない。

これは粗い分類であり、果物数・速度・盤面密度を連続的にモデル化していない。初期状態の最大速度は記録するが、予測器への係数としてはまだ使用していない。新しい密集盤面で期限を守れる保証はない。

Anytime、落下中の先回り探索、現在盤面での候補再評価、木の再利用は今回実装していない。

## 4. 連続4手の結果

| 指標 | sync | 従来frames | 試作adaptive |
|---|---:|---:|---:|
| MCTS採用 | 4/4 | 3/4 | 2/4 |
| heuristic fallback | 0 | 1 | 2 |
| 再探索 | 0 | 1 | 2 |
| drop間隔・ゲーム秒 平均/中央値/最大 | 0.933 / 1.020 / 1.040 | 6.093 / 4.060 / 10.500 | 2.273 / 1.400 / 4.060 |
| drop間隔・実秒 平均/中央値/最大 | 1.194 / 1.284 / 1.312 | 6.141 / 4.082 / 10.597 | 2.340 / 1.529 / 4.111 |
| 最大Unity Update間隔ms | 307.75 | 80.18 | 79.88 |
| Viewer表示fps | 12.25 | 14.39 | 14.30 |
| キャプチャ→Tk提出p95 ms | 70.12 | 71.86 | 77.08 |
| 表示中のフレーム最大古さms | 346.37 | 90.14 | 125.48 |
| PlayerピークRSS MiB | 187.32 | 176.61 | 176.71 |
| 平均CPU使用コア相当 | 0.53 | 0.56 | 0.70 |

各間隔の標本数は3。CPU値はPlayerの累積CPU秒÷測定実秒、PC全体使用率でも探索瞬間ピークでもない。Viewer/PythonのCPU/RSSとGPU負荷はこの表に含まない。Tk提出までの時間は実モニターへの表示遅延ではない。

drop tick（sync / frames / adaptive）：

- sync：63,115,152,203。実秒4.4477,5.7317,6.7178,8.0303。
- frames：213,416,602,1127。実秒7.3445,11.4267,15.1702,25.7676。
- adaptive：213,281,484,554。実秒7.3403,8.7211,12.8325,14.3612。

adaptiveの2手目予約は15tick、要求→検証0.342実秒。待ち時間削減は確認できた。一方3/4手目は状態不一致でfallbackし、採用率は悪化した。短期4手の割合に統計的な一般性はないが、標準化の根拠にはできない。

## 5. 固定fixtureと判断一致

固定試験の序盤2ケースでは、sync/frames/adaptiveとも選択位置0.0/0.5で一致。密集2ケースではsyncは0.25、両framesはfallback後0.75。これを「MCTS判断一致」とは数えない。framesは未来盤面を根としており、同じfixtureだけでも評価時刻が異なる。

同一の凍結ルートを使うnativeテストでは深さ3/4/5/6の4ケースで、同期/分割の選択・UCT木・全32反復が一致（4/4）。これはアルゴリズム整合性の小規模回帰であり、任意の接触盤面や実ゲームの強さの100%一致を保証しない。

| 密集2要求 | 従来frames | 最終adaptive |
|---|---:|---:|
| MCTS採用 | 0/2 | 0/2 |
| 要求全体 実秒 | 9.738 / 9.862 | 4.442 / 2.950 |
| 累積work ms | 1572 / 1717 | 1612 / 1731 |
| 試行ごと完了反復 | 全て32 | 全て32 |
| 最終理由 | projected_state_mismatch | projected_state_mismatch |
| 最大作業区間ms | 49.84 / 48.06 | 153.05 / 140.73 |

adaptiveでは期限超過を避けたが、接触後の投影誤差は解決していない。最大位置差0.02834/0.03124 world units、最大角度差5.636/21.084度。旧方式も最大位置0.05360・角度21.145度。二回目の照合で約0.011位置差が残る。連続試験では微小位置差1.91e-5やsleep等flags差でも失効した。誤差が小さいことだけでGO・合体が同じと断定できないため、閾値は緩めていない。

選ばれた候補の現在盤面での再評価を今回はしておらず、これらの誤差が選択・GOリスクをどの程度変えるかは未確定。候補に付随する空のvalue_state既定値を完全な予測盤面として扱って比較してはいけない。GO正例の検証不足も残る。

## 6. カクつきの切り分け

密集込みの固定試験で最大Update間隔はsync773.68ms、旧frames77.89ms、最終adaptive166.46ms。したがって**約82ms以内を維持できたとは言えない**。adaptiveには153msの長い作業区間がある。比較Playerの稼働時刻を確認し、計測の同時実行による競合ではない。

`frame-budget-ms=6`はチェック可能な区切りで止めるソフト予算。予測のAdvance、物理Sceneの構築/コピー/解放、衝突callback等の途中を中断できない。単に予算を1msへ下げても、それらの区間を短くできない。今回の計測では153ms区間の内部処理別内訳は取れていないため、GCだけ、またはSimulateだけが原因とは断定しない。

以前の1.55秒停止は再現しなかった。固定adaptiveで観測された最大値は診断JSON化1.665ms、ログWrite/Flush0.985ms、UDP観測作成35.818ms。UDPスコープ中のGC回数差は最大8、低速windowでGC累積カウントは増えているが、各GCの停止時間や153msとの因果は未分離。ログFlushが1.55秒の直接原因だったという証拠は得られていない。これらは実行全体の最大値であり、同じフレームに重なったと解釈しない。

Viewerは最新フレームのみを扱い、今回約13.5〜14.4fps。固定adaptiveでフレーム古さ最大203ms。同期の古さ848msに対して短くなったが、現在の配信設定自体15fpsなので30/60fpsの滑らかさには到達しない。物理/画面が更新されること、頻繁に果物を落とせること、MCTSで判断することは別指標。

## 7. 追加でカクつきを改善する案（今回未実装）

優先順：

1. **予測Advanceの物理tick単位で中断できる構造にする。** 同じdtとtick順、衝突/合体/削除/GO処理の順を保ち、凍結した予測世界だけを進める。重い1区間を短くする最優先候補。32反復を減らす対策ではない。同期との木/状態一致を回帰し、コピーや解放部分の別スパイクも計測する。単一のnative Simulate自体は途中で止められない。
2. **使い捨て配列/List/DTO/JSONと全Scene走査を減らす。** 果物レジストリ、バッファ再利用、完成後の待機UpdateでStopwatch/スライス記録を増やさない等。Incremental GCは既にONなので、ONにするだけの改善はない。Unity公式も割当削減と配列再利用を推奨する：[GC best practices](https://docs.unity3d.com/2022.3/Documentation/Manual/performance-garbage-collection-best-practices.html)。物理Scene/Rigidbodyのプールは接触履歴・挿入順・sleepを変え得るため、単純な使い回しはしない。
3. **録画は1ゲームのUnity Playerウィンドウを直接取得する方式も比較する。** Viewerの15fps制限・共有メモリ/Python/Tkの経路を省ける。MCTSがUnityメインスレッドを止める問題そのものは残る。直接表示で滑らかなら、その後にViewerの表示経路を最適化する。
4. **探索停止を減らした後にViewerを30fpsへ。** 640×360の映像転送・画像変換・合成を計測してから上げる。fpsだけ上げると負荷が増えて逆効果になり得る。最新フレーム優先とゲーム非待機は維持する。
5. **描画のフレーム間隔を揃える。** 現状の実行時VSync/targetFrameRateを記録し、描画頻度だけを制御する小比較を行う。DesktopではVSyncとの関係を確認する必要がある：[Unity targetFrameRate](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Application-targetFrameRate.html)。物理dtやtimeScaleを変更して滑らかに見せない。Rigidbody補間もGO判定がtransform.positionを参照する現構成では無検証で導入しない。
6. **それでも1Player内で両立できなければ探索用worker分離の最小設計。** 描画プロセスから重い計算を離す利点はあるが、状態転送・接触キャッシュ・時刻整合・結果失効が課題。Unity APIを単にTask.Runへ移せない。今回大規模移行はしない。

## 8. B/Cと計算時間の現実的制約

B Anytime：暫定手の採用には、その時刻の合法性とGO再評価が必要。既存native小ケースでは深さ3で16/32反復の選択index2に対して64反復は0となる例があり、少ない探索が同品質とは言えない。これは独立したbudget試験であり、実際の8/16/24時点の採用率・最終32との差は未計測。標準採用しない。

C 先回り：既存APIの落下後25tick＝約0.5ゲーム秒に次操作の計算を重ねる候補がある。保持中の移動時間も利用候補。ただし公開された次果物のみ、予定時刻の予測ルートと検証が必要。異なる接触状態へ木の訪問数や価値をそのまま移すのは不正確。今回の密集1探索は約0.82〜0.98実秒で、0.4秒ごとに完全32反復を毎回終える保証はなく、再探索が加わるとさらに遅い。分割は計算自体を速くしない。現在のAPIはそもそもpost25の観測を待つため、最短cooldownで次入力する機能とも分けて考える。

次の実装はまず1の細かい中断＋処理内訳計測を推奨。その後、現在盤面での同一候補/GO再評価の設計と小検証を行い、失効結果を安全に再利用できるか判断する。GO正例・合体直前・密集の回帰が必要。Anytimeと先回りを一度に導入しない。

## 9. 変更ファイル・関数・行番号

いずれも `C:\SuikaGameAI` 基準。既存未コミット変更を保持しており、Git差分全体が今回の変更ではない。

| ファイル | 主な箇所 | 今回の内容 |
|---|---|---|
| Unity/Assets/Scenes/Script/FrameLeadEstimator.cs (+.meta) | 6 SetConfiguration/Observe/ObserveMiss/Suggest/RetryLead | 予約時間推定の純粋クラス |
| Unity/Assets/Scenes/Script/UDPFrameSearch.cs | 14 Attempt、100 BeginFrameSearch、114 StartFrameAttempt、143 UpdateFrameSearch、183 FrameFixedUpdate、216 RejectFrame | 校正の区分・適応予約・探索/照合時計・失敗理由 |
| Unity/Assets/Scenes/Script/UDPStepProtocol.cs | 23 StepResult、38 ClearStepForReset、61 HandleStep、183 FixedUpdate、240 CompleteStep | 前回drop/合法/実drop/完了時計、最終計測修正 |
| Unity/Assets/Scenes/Script/SuikaRuntimeProbe.cs | 23 Write、33 UdpSpan、59 WindowRow | JSON・Flush・UDP作成の時間とGC差 |
| Unity/Assets/Scenes/Script/UDPStateProtocol.cs | 147 SendSnapshot/149 SendSnapshotCore | 診断ON時のみUDP作成計測 |
| Unity/Assets/Scenes/Script/StepPlanner.cs | 31 Validate | 明示指定のadaptiveのみ許可 |
| Unity/Assets/Scenes/Script/SuikaFrameSearchSelfTest.cs | Run | 推定器6検査追加、既存の深さ3〜6等は維持 |
| Python/src/suika_ai/unity_env.py | 432 validate_planning_settings | adaptiveの入力検査 |
| Python/src/suika_ai/parallel_play.py | 196 run_parallel | 実験は1ゲーム限定 |
| Python/play_parallel_ai.py | 44 main | 選択肢追加、既定syncを維持 |
| Python/diagnose_frame_search.py | 55 main | 新モード比較・play stageで連続手計測 |
| Python/tests/test_frame_execution.py | 27 | opt-in/旧既定/設定維持の回帰 |
| docs/STEP8G_REPORT.md、DEVELOPMENT_LOG.md、DEVELOPMENT_PLAN.md | 今回追記 | 結果・制約・次の方針 |

MctsPlanner.cs、SuikaPhysicsSimulatorの物理挙動、モデルは今回変更していない。診断OFF時はI/O計測の出力を行わない。追加スキーマは後方互換。frames_adaptiveは1ゲームのみで、既存syncの4ゲーム/Viewerは維持。

## 10. 検証

- Python unittest：140検査成功。
- Player native：Frame50、MCTS861、Rules84、Path26、計1021検査成功。キャンセル/Reset/GO/重複要求/予測Scene解放を含む。
- Value parity24ケース、最終EditorバッチのTestAndBuild成功。既存警告（FruitCollisionHandler未使用フィールド）は残る。
- StreamingAssets/suika_value_epoch3.json SHA256：7e95aee3f462afb9faa02843b9612bb018f0051b0c68349d1a89d508d2631d2c。既存モデル未変更。
- 最終の時計だけの修正後はclock_smokeで1要求の実通信を確認。主要比較は修正前historyから集計し、性能の再測定はしていない。
- 新たな長期得点比較、自然GO精度評価、4ゲームadaptive、GPU計測、Computer Useでの目視判定は未実施。Viewer実プロセスの表示提出と実通信/物理更新のログを測定した。

## 11. 実行方法

現時点では得点性能の基準としてsyncを推奨。1ゲーム/Viewer付き、自然GOまたは最大1000手で終了：

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\step8g_sync_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + ([guid]::NewGuid().ToString('N').Substring(0,6))
.\.venv\Scripts\python.exe .\play_parallel_ai.py --games 1 --view-games 1 --episodes 1 --max-steps 1000 --ai-mode mcts --planning-execution sync --mcts-iterations 32 --mcts-max-depth 4 --candidates 5 --post-drop-steps 25 --seed 749201 --base-port 36400 --output $out
```

実験adaptiveを短く試す場合だけ、同コマンドの `--planning-execution sync` を `--planning-execution frames_adaptive --frame-budget-ms 6 --frame-lead-ticks 150 --frame-max-attempts 2` に、`--max-steps 1000`を`--max-steps 10`にする。保存先も新しくする。これは採用率/強さの改善版として推奨するものではない。旧分割比較には`--planning-execution frames`。深さ5/6や64/128反復は設定可能だが、重くなり校正も取り直す。

Ctrl+Cで停止できる。最大手数や中断は自然GOではない。既存の別実行がポートを使っている場合は重複させず空いているbase-portに変更する。

## 12. 判断

Aは余分な待機を減らしたが、密集採用0/2・連続採用2/4・最大Update166msなので今回の成功条件には未到達。標準化しない。次は予測の中断粒度と失効の原因/候補再評価を優先し、従来syncの強さを維持できる証拠を積む。commit/pushなし。
