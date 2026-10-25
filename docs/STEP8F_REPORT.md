# STEP 8-F：ゲーム進行とMCTS探索の分離（2026-10-23）

## 結論・到達点

1ゲーム限定の**フレーム分割＋将来tick予約**の試作を追加した。探索中にもライブ物理・描画・UDP・Viewerが進む。同期MCTSは既定のまま維持する。
ただし、**接触の多い盤面では予測した操作開始状態と実盤面が一致せず、MCTSを採用できない**。終盤でもMCTSを安定採用できる製品版としての完成扱いにはしない。許容差を根拠なく広げず、失効とheuristicフォールバックを記録する。
環境はdevelop、Unity 2022.3.21f1、rules_version=step8e-all-fruit-go-v2、GO比率0.83、dt=0.02、post_drop_steps=25。ゲーム本体のルール・Collider・物理設定を変更していない。commit/push/追加バックアップ/本格収集/学習なし。

## 方式の比較と既存構造

- 従来：UDPのplan_step受信 → 同じメインスレッドでUCT・独立PhysicsScene2D・PathSessionの全経路を同期計算 → 実ゲームのFixedUpdateで移動・落下。計算中は通常のFixedUpdate/描画/映像配信も進まない。Pythonは命令と結果保存、Viewerは最新フレームを表示する役割。
- 別Unity探索プロセス：通常描画と探索のメインスレッドを完全に分離できる利点がある。一方、ランタイムCollider/剛体/境界/接触フラグの転送・検証、追加プロセスのCPU/RSS、時刻同期が必要。**今回は別プロセスの速度・メモリは実測していない**。接触キャッシュを転送できない問題と古い判断の問題は別プロセス化だけでは解決しない。
- 採用した試作：既存のネイティブコピーを使い、経路の各Advance/待機後に制御を返す。Unity APIはすべてメインスレッド。Task.Runで物理APIを呼ばない。別のUnityプロセスを追加せず、単一プロセスで既存アルゴリズムを共有できるため、最小試作として採用した。

参考：[Unityのスレッド制約](https://docs.unity3d.com/2022.3/Documentation/Manual/overview-of-dot-net-in-unity.html)、[PhysicsScene2D.Simulate](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/PhysicsScene2D.Simulate.html)。

## 盤面の古さ・操作時刻の扱い

1. 要求を受け付け、stream/episode/action IDを検査。保持入力だけロックし、物理や時間は止めない。
2. T0の盤面を独立Sceneへコピー。保持・公開NEXTもコピーし、以降の未公開果物は従来どおり公開分布のサンプリングのみ使用する。
3. 操作予定tick T=T0+leadへ**何も落とさず**予測を進める。投影も4tick単位で分割する。初期値lead=150（3ゲーム秒）は実行予約の余裕であり、誤差許容値でも新しいゲームルールでもない。
4. Tのルートを凍結し、各MCTS経路はそこから独立コピーする。T0の古い盤面を探索したまま適用することはしない。score、負の生成IDの次番号、接触済み、sleep、速度、回転、剛体情報を引き継ぐ。solverキャッシュはコピーできない。
5. T+1のFixedUpdate開始時（実物理がpost-Tの状態）に照合し、一致した場合だけ同じFixedUpdateから既存の横移動を開始する。保持ID/NEXT ID、設定、果物の種類・生成合体系譜、位置・速度・角度・角速度・sleep/接触済み・接触の有無・質量・重心・慣性・得点・GOを照合する。合体IDはm(parentA,parentB)の系譜で対応付ける。
6. **許容差は現在ゼロ**。T0から動いていてもTの予測と一致すれば採用する。tickが進んだだけでは失効しない。これは公開状態の一致であり、不可視の接触cacheの同一性を証明するものではない。
7. 期限切れ、状態相違、設定/保持変更、例外では失効。初回を含め最大2回、予約leadは直前に経過したtick数の2倍も考慮して最大500tick。壁時間24秒、Unity割当量1,500MiBの上限。深さ・回数の自動縮小はしない。
8. 上限後は現在の実盤面から既存heuristicを明示実行し、final_policy=heuristicと理由を記録。fallbackも同期処理のため数十msの停止はあり得る。Reset/GO/終了で途中のiteratorとrootをDisposeする。GO条件自体は変えない。

記録はplanning.frame_search：request_id/game_id/episode_id/action_id、開始・予定・実行tick、開始/受信/実行時刻、各試行の初期/投影盤面、差、採用・再探索・fallback、処理区間の時間、進んだ描画フレーム数・映像数。キャンセルはObservation.frame_searchと診断ログにも残す。
移動は従来の速度、壁安全範囲、DropFruitを使用する。0.4秒cooldownは変更せず、落下後25更新も実際の落下から数える。待機中の加点はbetween_steps、実操作開始以降の加点はstepへ分ける。

## 最終Playerによる短時間計測

元ログ：Python/outputs/step8f_01/release_video_comparison。集計：同/release_measurements.json（step8f_01直下）。同じworker seed=749100、5候補、32回、深さ3/4、25更新。各条件で空盤面1手＋35果物の保存盤面1手。復元fixtureにsolver cacheや睡眠経過時間は含まれず、実通信での受付時刻まで完全一致した強さ比較ではない。

|条件|同期・35果物の探索|分割・35果物の処理区間合計 / 予約待ちを含む経過|全区間の最大Update間隔：同期→分割|Viewer実表示fps：同期→分割|
|---|---:|---:|---:|---:|
|32回・深さ3|668.4 ms|1476.7 ms / 9.12秒|677.8 → 81.6 ms|11.27 → 14.17|
|32回・深さ4|795.9 ms|1529.0 ms / 9.13秒|806.8 → 82.5 ms|10.00 → 14.09|

- 分割の35果物は**2回のMCTS＋投影＋heuristic fallback**の合計で、同期の1回と同じ仕事量ではない。work_msは各処理区間の壁時間合計（管理・投影を含む）で、OSのCPU時間そのものではない。速くなったとは主張しない。
- 空盤面の区間合計は深さ3=162.7ms、深さ4=208.3ms。予約を待つため操作開始まで約3.03秒。同期は146.7/236.3ms。各1回なので速度差の一般化は不可。
- 探索期間の最大Update間隔は、序盤32.8/21.4ms、35果物63.7/67.7ms（深さ3/4）。FixedUpdate間隔の中央値は約20.8ms、35果物での最大約67.4/68.6ms。6ms設定は**ソフト予算**で、1回のネイティブAdvanceの途中は中断しない。厳密な6ms上限ではない。
- 探索中に序盤は43枚、35果物は128/129枚の新しい映像を配信し、約14fpsを維持した。Viewerの数値はTkへの表示投入までであり、ディスプレイの発光時刻ではない。
- プロセス平均CPUは同期0.56/0.79コア相当、分割0.63/0.72コア相当。12論理CPU全体に対して約4.7～6.5%。実験時間と待ち時間が違うため効率比較には使えない。
- Unity Playerの標本ピークRSSは同期約196～197MiB、分割約182～184MiB。長期メモリ増加や4ゲーム時のCPU競合は未測定。
- 初期試作の1条件で、探索完了後の待機中に約1.55秒の停止を記録した。最終版の同条件では再現せず、最大Update間隔は約82ms。**その単発停止の原因は未特定**であり、あらゆる停止を解消したとは扱わない。

## 採用率・予測の整合性

- 固定盤面4要求：空盤面は2/2採用、35果物は0/2採用。全体2/4=50%。再探索2回、heuristic fallback2回。少数の意図的な固定条件であり、実戦の母集団採用率ではない。
- 35果物の初回照合：ID/種類/数・得点・接触の有無は一致したが、最大位置差0.053599637、速度差0.020247469、角度差21.1446228度、角速度差3.9991429度/秒。sleepフラグも不一致。重心・慣性・質量の差はゼロ。
- 再探索後：最大位置差0.010975521、角度差1.2136841度。他の速度等はゼロになったが、差を無条件許容せず破棄した。
- 原因について確認できたこと：初期の剛体コピーは既存のチェックを通り、採用済みの慣性コピーも残る。無入力の時間発展で接触盤面がずれる。**接触cache/睡眠経過の非復元が有力**だが、これだけを唯一の原因と実証したわけではない。render-frame単位のDestroy/GOとlocal tick単位の退役/GOの違いも残る。
- 連続実通信4手（release_continuity、seed749300、深さ4、headless）は4/4採用、各1試行、再探索/fallbackゼロ、全て合法な1回落下。4手上限で終了し、自然GO完了ではない。4手目までに自然加点6点が発生し、step報酬合計0＋between_steps6＝得点6で保存則が一致した。
- 採用した空盤面2件は開始状態の公開物理値がゼロ誤差。実落下X差ゼロ、総物理更新65対65、得点・GOも一致。**既存MCTS Candidateには落下後の全果物配列が保存されず、JsonUtilityの空value_stateは欠損**。このログから落下後の全位置/速度誤差を算出したとは主張しない（post_drop_comparison.json参照）。
- 新しいforkの公開NEXT全5種類について、既存PathSessionと同座標・同入力で2回落下し、質量は全て一致。1slotだけ自動計算後の慣性差7.45058e-9、重心距離差1.86265e-9が残った。他4slotはゼロ。この差を黙って完全一致扱いしない。旧ボード剛体のCOM/inertiaを明示コピーするSTEP8-Cの対処は維持した。

## テスト

- Python全139テスト成功。新しい設定範囲、既定sync、MCTS以外へのframes拒否、4ゲームframesを起動/出力作成前に拒否することを追加確認。合成データを一時フォルダに作る既存学習単体テストを除き、再学習はしていない。
- release_regression：新規frameテスト44、既存MCTS861、ルール84、Path26の計1,015アサーション成功。深さ3/4/5/6・32回で同期と分割の選択/UCT統計が一致し、途中の実fixed clockが進行。新しい2果物の接触を含む盤面で検査した。
- 重複要求、Reset/GOによるキャンセル、保持入力の解放、古い果物の未落下、途中破棄したSceneの解放を確認。GOキャンセルは**強制GOのライフサイクル試験**であり、新方式で自然GOまでの1ゲームを完了した実験ではない。
- 最終ビルドrelease_build.logで成功。既存Valueの24盤面パリティも実行。推論JSONのSHA256は7e95aee3f462afb9faa02843b9612bb018f0051b0c68349d1a89d508d2631d2cのまま。
- Computer Useで1画面Viewerの実描画と果物・得点の更新を短時間確認。終盤の滑らかさは上記のフレーム計測で確認。長時間録画、自然GOの見逃し率、mcts_value新方式、4ゲームframes、64回以上の新方式実測は未実施。
- ビルドに伴う既存のdirtyなTMPフォント生成物の差分は保持。今回のソース差分の空白検査は別途行い、元のdirty差分を巻き戻していない。

## 起動・停止・再集計

これは試験用。終盤でheuristicへ切り替わる制約を承知で、まず10手だけ表示する。Unity Playerは再ビルド済み。

```powershell
cd C:\SuikaGameAI\Python
$run = "outputs\step8f_view_{0}_{1}" -f (Get-Date -Format "yyyyMMdd_HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0,8))
.\.venv\Scripts\python.exe .\play_parallel_ai.py `
  --games 1 --view-games 1 --episodes 1 --max-steps 10 `
  --ai-mode mcts --planning-execution frames `
  --mcts-iterations 32 --mcts-max-depth 4 --candidates 5 --post-drop-steps 25 `
  --frame-budget-ms 6 --frame-lead-ticks 150 --frame-max-attempts 2 `
  --seed 749900 --base-port 35400 --require-metadata --expected-go-ratio 0.83 `
  --output $run
```

停止はPowerShellでCtrl+C。Viewerを閉じてもゲームと記録は継続する従来仕様。自然GOまで試す場合はユーザー側でmax-stepsを1000などへ変更（上限終了は自然GOではない）。同期比較はplanning-executionだけsyncへ変え、必ず新しい保存先にする。深さ5/6、64回も設定でき、設定を勝手に縮小しない。リソース/締切超過は明示失効・fallbackとなる。

固定盤面の短時間再検証と読み取り専用集計：

```powershell
$diag = "outputs\step8f_diag_{0}_{1}" -f (Get-Date -Format "yyyyMMdd_HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0,8))
.\.venv\Scripts\python.exe .\diagnose_frame_search.py --output $diag `
  --fixture outputs\step8c_01\dense_safe_fixture.json --execution sync frames --depth 3 4 --video
.\.venv\Scripts\python.exe .\analyze_frame_search.py --input $diag --output "${diag}_analysis.json"
```

双方とも既存出力の上書きを拒否する。診断の深さは3～6に制限し、長い自動収集はしない。CSVではなく既存JSON/JSONLを使用する。

## 変更ファイル・主な関数

|ファイル|関数等|変更|
|---|---|---|
|[MctsPlanner.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/MctsPlanner.cs:80)|Plan / PlanFrames|同一UCTループをiterator化。同期は最後までdrainし、新方式はAdvanceごとにyield。|
|[SuikaPredictionPath.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPredictionPath.cs:56)|Fork / PathSession(source) / CaptureFrame|凍結ルートのネイティブ複製、負ID採番・時計・得点の引継ぎ。|
|[UDPFrameSearch.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/UDPFrameSearch.cs:91)|BeginFrameSearch / FrameProjectionAndSearch / FrameFixedUpdate / RejectFrame / CancelFrameSearch|予約・照合・再探索・fallback・キャンセル・監査記録。|
|[SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:76)|Copy|非アクティブ/非シミュレーションNEXTの無効なゼロ質量getterで設定を上書きしない。プレビューの自動COM/inertiaを維持。|
|[PredictionDiagnostics.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/PredictionDiagnostics.cs:100)|BeginAliases / Begin / AfterPhysics|合体系譜だけの軽量追跡。毎tickの全盤面キャプチャは既定で増やさない。|
|[StepPlanner.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/StepPlanner.cs:7)|PlanningSettings / Decision|実行オプションと任意のframe_search記録。|
|[UDPStepProtocol.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/UDPStepProtocol.cs:58)|HandleStep / FixedUpdate / ClearStepForReset|重複制御を維持した受入・予約実行接続。|
|[UDPCommunicatorUnity.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/UDPCommunicatorUnity.cs:48)|Update / StopCommunication|フレーム仕事の更新・通信終了時キャンセル。|
|[UDPStateProtocol.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/UDPStateProtocol.cs:75)|SendPacket / SendSnapshot|game_tickと任意の監査JSON。|
|[GameManager.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/GameManager.cs:92)|ResetGame|物理オブジェクトを処理する前に探索を中止。GO条件は不変。|
|[SuikaFrameSearchSelfTest.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaFrameSearchSelfTest.cs:27)|Start|Native回帰44項目。微小な質量特性差も記録。|
|[unity_env.py](C:/SuikaGameAI/Python/src/suika_ai/unity_env.py:413)|PLANNING_DEFAULTS / validate_planning_settings|追加設定の後方互換な検証。|
|[parallel_play.py](C:/SuikaGameAI/Python/src/suika_ai/parallel_play.py:188)|run_parallel|試作を1ゲームに限定。|
|[play_parallel_ai.py](C:/SuikaGameAI/Python/play_parallel_ai.py:12)|main|planning-execution/frame-*オプション。|
|[diagnose_frame_search.py](C:/SuikaGameAI/Python/diagnose_frame_search.py:9)|run / main|所有する1ゲームだけの短時間計測。|
|[analyze_frame_search.py](C:/SuikaGameAI/Python/analyze_frame_search.py:9)|analyze / main|保存済み計測の読み取り専用集計。|
|[test_frame_execution.py](C:/SuikaGameAI/Python/tests/test_frame_execution.py:3)|FrameExecutionTests|設定・1ゲーム制限の回帰。|

## 次の優先事項・4ゲームへの拡張

1. 接触状態の失効を最優先で改善する。より短い予約leadを実測で決め、接触誤差と選択順位/GO安全性の関係を測定する。今回の最大位置差などを、そのまま根拠のある許容差と見なさない。
2. 新方式で選択候補の落下後の全盤面を任意保存する診断を追加し、接触・合体・GO直前のtick差を再検証する。完全なnative solver stateの複製は今回実現していない。
3. 単発の待機中停止を、GC/Scene解放/OSスケジューリングも含めて追加計測。ネイティブAdvance内の細分化で最悪フレーム時間を制限できるか検討する。
4. 採用率が低いまま長期のMCTS強さ比較に進まない。fallbackを含む結果を「MCTSの得点」として混ぜない。現在の同期32回/深さ3/4と新方式ではゲーム内の待ち時間も異なる。
5. 4ゲームへの全面導入はしない。現在はCLI/APIで新方式のgames>1を拒否し、旧syncの4ゲームは維持。拡張時はCPU負荷と期限切れ率を測定し、共有・上限制御した探索worker方式も比較する。4+4プロセスを自動起動する設計にはしていない。
