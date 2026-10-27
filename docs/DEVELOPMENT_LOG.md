# 開発記録

本資料は現在の確認情報から新規作成したもので、過去資料の復元ではない。

## 2026-10-18 STEP 1：UDP停止処理

- 対象：SuikaGameUnity/Assets/Scenes/Script/UDPCommunicatorUnity.cs。
- 停止後のUpdateでudpListener.Availableを参照するnull例外を修正。
- 定期送信は送信ソケットがなくなった時点で終了。6種類の単発送信も停止後は何もしない。
- StopCommunicationの既存null判定を維持し、複数回の停止を許容。OnDestroyからも呼び、Scene破棄時にポートを解放。
- 合体通知のデバッグ用LogError("よばれたよ")を4か所削除。実際の参照未設定などのエラーは維持。
- ポート、JSON構造、行動番号、物理設定、Scene、Prefabは変更していない。既存差分を保持。
- ゲームオーバー通知→停止→Scene再読込→新インスタンスのStartという既存の再開経路を維持。
- Tools/Test-UdpLifecycle.ps1：実コードをUnityスタブとコンパイルし、ローカルUDP通信で停止・再生成を検証する。UnityのScene・スケジューラー・JSON変換は検証対象外。
- 回帰テストは成功：定期UDP送信、二重停止、停止後Updateと6種類の通知、停止後コルーチン終了、破棄・終了処理、同じポートの再利用、新インスタンスからの送信。サンドボックス内はUDP受信タイムアウトのため、許可されたサンドボックス外実行で確認。PowerShell 7で `& ./SuikaGameUnity/Tools/Test-UdpLifecycle.ps1` を実行する。
- Unityプレイテストは未実施。状態：修正済み・動作未検証（Unity上）。
- 追加の関連リスク：定期観測がStart直後にcurrentFruitを参照するため、初期化順序依存は残る。今回は修正範囲外。

### ユーザーによる確認手順

1. Assets/Scenes/gameDisplay.unityを開き、コンパイル完了後にConsoleをClearしてPlay。
2. 通常の移動・落下・合体・加点を確認し、果物を積んでゲームオーバーにする。
3. 一度はEnterを押さず2秒待ち自動再開を確認。別の終了時にはEnterで即時再開を確認。
4. 再開後にも移動・落下できること、既存Python連携を使う場合は観測受信と行動送信が再開することを確認。
5. ConsoleにNullReferenceException、ObjectDisposedException、ポート使用中のSocketException、不要な「よばれたよ」がないことを確認。最後にPlay停止。

## 2026-10-18 STEP 2：数値観測・reset

- STEP 1はユーザーがUnity動作確認済み。残りの不具合候補は保留。
- 既存UDP JSONに全果物のID/種類/位置/速度/角度/角速度、操作果物、NEXT、episode_id、stream_id、state_id、reset_request_idを追加。仕様はUDP_PROTOCOL.md。
- FruitEvolutionの型値を使用。RuntimeのIsPreviewで操作中/NEXTを区別し、IsMergingで消滅予定の果物を除外。名前やタグに依存しない。
- resetはScene再読込を使わず、旧果物を非アクティブ化・破棄し、既存PlayerControllerの生成処理とScoreManagerを初期化。物理設定/進化順/得点/キー操作は変更なし。受信ソケットは維持。
- 数値モードでは画像を省略し、ゲームオーバー後も受信・観測を継続してPython resetを待つ。旧DQNのみのモードでは画像送信と2秒自動再開を維持。
- 初回観測は全Start完了後に遅延し、果物未生成時のnull参照を避ける。停止ガード/OnDestroy解放は保持。
- Pythonに標準ライブラリのみのUnityEnvと確認用CLIを追加。古い/重複状態を除外、分割JSONを再構成し、同一request_idのreset再送と完了状態を照合。旧main.py/DQNは変更なし。
- テスト：C#停止回帰テスト成功。Python unittest 5件成功（JSON検証、順不同/重複/不正分割、古い観測除外、reset再送、実UDP往復）。ローカルUDPはサンドボックス外の許可実行で確認。
- Unity 2022.3.21f1の既存gameDisplayでPlay成功。実Python接続で3回連続reset、異なるepisode_id、空盤面/score=0/操作果物/NEXTを確認。
- 90秒以内の既存落下命令による実通信テストで落下・物理値更新・ID継続・合体/加点を確認。639点でgame_over=trueの盤面全体を受信し、Pythonからreset成功。最後にもresetし、その後Play停止。
- Play中と停止後のConsoleは新規例外0件。GUI承認による前面切替で最初の2回は通信待機がタイムアウトしたため、待機中にUnityへ前面を戻して成功。通信ポート/セキュリティ設定は変更していない。
- 未検証：全種類の合体組合せ、Unity実機での60KB超の分割、大量長時間運転、通信遅延/欠落の実環境負荷。数値モード導入後の旧DQNを使った学習も未実施。
- 保留事項：appleのタグがfruit（他はFruit）であることを確認。今回の観測/resetはコンポーネント検出のため影響しないが、既存GameManagerの終了判定への影響は次回以降。TimeControllerは対象Sceneで非アクティブのまま。Missing参照/gameOverText等は今回未修正。
- STEP 3の実装は開始していない。

## 2026-10-18 STEP 3：正規化X指定のstep

- PlayerDropPlacement.cs（PlayerControllerのpartial）に実Collider由来の安全範囲・瞬間移動・移動後の重なり検査を追加。既存DropFruitを再利用。既存キー移動の境界ルールは変更していない。
- 調査：左右Wallは高さが十分ある軸平行BoxCollider2D＋Kinematic Rigidbody2D。PlayerのBoxColliderはSceneで無効。保持果物はPolygonCollider2DのTriggerで、落下時に非Trigger化しRigidbody2Dを追加/重力1にする既存処理。
- 既存の接触フラグ＋速度減衰には境界への食い込み余地がある。AIには壁/果物のboundsとワープ境界の共通範囲を適用し、Collider2D.Distanceで最終検査する。キーボードへの共通クランプ導入は仕様判断が必要なため保留。
- 最初の端点テストではdefaultContactOffset 1個分の余白でも実Collider距離判定が左壁との重なりを検出して拒否。両Collider接触空間＋追加余白として3倍の既存ContactOffsetを確保し、拒否判定は維持。その後端点試行成功。Editor自動Refreshが反映しない場面は明示RefreshとDLL更新日時で反映を確認。
- UDPStepProtocol.csにepisode/stream/action_idの照合、実行前ID確保、重複排除、busy拒否、完了状態キャッシュを追加。0.5秒以上の物理tickまたは終了時に結果を返す。UDPStateProtocolへdrop_range/step_resultを追加。UDPCommunicator/PlayerControllerはstep中の入力混入だけを防止。
- UnityEnv.step(x)は(state,reward,done,info)を返す。範囲外はValueError。再送は同一ID。タイムアウト/不整合/拒否を成功扱いせず、結果不明後はreset必須。旧episodeの遅延結果も除外。main.py/DQNは変更なし。
- Python unittest計12件成功。C#実通信クラス＋Unityスタブの停止回帰/重複/処理中拒否/範囲外/終了状態/古いID/旧episode/落下途中例外後の再送テスト成功。
- Unity 2022.3.21f1の既存gameDisplayでPlay成功。実通信の端点9試行（0/0.5/1を各3回）で毎回空盤面に1個だけ落下。全命令を二重送信し、落下ID・実X・壁内側・物理tick25回を検証。
- 上記端点試行で出現対象5種類（0〜4）を確認。例：type1の安全区間[-2.70621,2.70261]、type4は[-2.45173,2.42635]。果物サイズにより範囲が変化する。
- 続けて28回step（中央16回＋固定seedランダム12回）成功、合体/115点の加点とreward整合を確認。最後にreset成功。STEP 3テストではゲームオーバー到達までは行っていない（終端命令拒否は自動テスト、終了後resetはSTEP 2実機確認済み）。
- step完了後に左/右キーとEnter落下をGUIで確認。テスト中とPlay停止後のConsoleに新しい例外0件。最後はPlay停止。
- 未確認：長時間運転、全種類の全端点組合せ、人間の境界長押しとの数値比較、遅延/欠落/同時入力の実環境負荷、STEP 3での実機終端step。必要時はcheck_unity_step.py等で追加確認する。
- Scene/Prefab/物理設定/進化順/出現確率/得点は変更なし。既存未コミット差分を保持。STEP 4以降は開始していない。

## 2026-10-18 STEP 3.5：滑らかなAI移動

- PlayerDropPlacement.csへInspector調整可能なaiMoveSpeedを追加（既定2.5 Unity単位/ゲーム秒）。既存キーボードspeed=5×入力0.5を基準にした初期値であり、公式速度の完全再現ではない。キーボード処理は変更なし。
- UDPStepProtocolをmoving→post_drop→completedに分離。FixedUpdateの各刻みで速度*fixedDeltaTimeだけ進め、到着後に既存DropFruitを1回呼ぶ。落下後0.5秒のtick計測は実際の落下時に開始する。移動中も盤面の物理・合体・得点は通常進行。
- STEP 3の範囲・ワープ境界・果物サイズ検査を維持し、各移動tickと落下時に重なり/有効なCollider距離を検査。端でより大きいNEXTが生成される場合だけ、新規果物の初期位置を描画前に安全区間へ補正し、次の移動の開始点が壁内部にならないようにした。キーボード生成は従来のまま。
- UDP観測に速度・fixedDeltaTime・timeScale・進行状況を追加。結果に予定/実測移動tick、移動時間、開始/目標位置を追加。action_id予約・再送排除・完了結果キャッシュは維持。内部の落下試行も予約し、途中例外後に次FixedUpdateが再落下しないようにした。
- 移動中resetはactiveStepを破棄。移動中game_overはdrop_success=falseの終端結果を返し、果物を落とさない。Pythonはこれを正当な終端として扱う。
- UnityEnv.stepの既定timeoutを距離/速度/timeScaleに基づく自動計算へ変更。明示timeout指定、結果不明後のreset必須動作は維持。
- 初回実機で、移動に伴うboundsの浮動小数点誤差（約2e-7）によりPythonの結果整合チェックが拒否。結果のmin/maxを最終DropFruit時の実計算値へ揃えて解消。安全チェックを緩めてはいない。
- Python自動テスト14件成功。C#回帰テスト成功：移動中重複/到着後1回落下/移動中reset・終了/途中例外/0.01・0.04秒刻みでゲーム内移動時間が一致/落下後0.5秒を移動と別計測。
- Unity 2022.3.21f1でInspectorのAI Move Speed=2.5表示を確認。実通信でx=0,1,0,0.01,0.02,0.8を連続実行し、左右両方向の中間座標・速度上限・壁内側・到着後落下・25post-drop tickを確認。盤面の同じ果物のYが移動中にも変わることを確認。
- 上記実機で命令を二重送信しても重複落下なし。移動途中のreset、旧命令の遅延再送拒否、reset後の次stepを確認。
- Play中のInspectorを0.75へ変更して同じ短時間テストも成功。端から端は359移動tick/約7.18ゲーム秒で、5秒超でも自動timeoutにより正常完了。画面で途中位置を確認。近距離は6tick/0.12秒や14tick/0.28秒で完了。
- テスト中と停止後のConsoleは新しい例外0件。最後にPlay停止しInspectorの既定2.5へ戻ったことを確認。Scene/Prefabへ速度変更を保存していない。
- 未検証：実機で移動中のゲームオーバー到達（自動テストで分岐検証済み）、全フレームレート/全速度/全果物の網羅、長時間運転。境界で新しい大きい果物の生成位置を補正する際、Playerも初期位置に合わせ直すため、落下後の手元位置には小さな変化があり得る。移動中の果物は連続移動。
- 進化順/得点/重力/摩擦/Collider設定は変更なし。既存差分を保持。STEP 4には着手していない。

## 2026-10-18 STEP 4：独立物理環境・予測比較（精度未達、未完了）

- SuikaPhysicsSimulator.csを追加。LocalPhysicsMode.Physics2Dの独立Sceneに実オブジェクトを非アクティブな親の下で複製。描画/既知の補助スクリプトを無効化し、Polygon/Box形状、マテリアル、Rigidbody設定を保持。未知のスクリプト/階層/Joint/進行中合体は拒否。終了時は全コピーを無効化しSceneをUnloadSceneAsync、専用マテリアルも破棄。
- FruitEvolutionの既存合体条件/進化Prefab/スコアルールを共用。予測Contextが生成/削除/加点を引き受け、実ScoreManager・音・UDP通知へ書き込まない。実ゲームの分岐は従来どおり。Danse.Startの摩擦0.5/反発0.01初期化を共用メソッド化（値は変更なし）。GameManagerへ終了高さの読取プロパティのみ追加。
- STEP 2 JSONだけでは不足する実Collider/Rigidbody/睡眠状態をUnity内で取得。複製の有効化で速度が失われることを実測し、有効化後に位置/速度/角速度を復元。動的bodyには質量/重心/慣性も復元し、その後に速度を再設定。Kinematicは慣性0を維持（setterでは0.0001へクランプされるため設定しない）。角度APIの微小な往復丸めは初期検査で1e-4度の範囲を許容。
- Predict(player, manager, x, postDropSteps=-1)が現在のidle盤面から1手予測。指定速度×fixedDeltaTimeのMoveTowards、移動中の盤面物理、到着後の落下、落下tick＋その後ceil(0.5/fixedDeltaTime)tickを再現。postDropStepsは1..5000、総tick上限10000。将来NEXT乱数は生成しない。現在見えているNEXTだけ保持する。
- 通常stepは変更せず、診断compare_stepだけが同じUpdate内で予測→実stepを開始。action_idの予約/重複排除/完了キャッシュを再利用。実total tickと予測結果を完了観測へ追加。予測API自体は実ゲームを進めず、比較命令は意図的に実stepも実行する。
- 予測前後に実果物の位置/回転/速度/角速度/睡眠/合体フラグ、Player位置、スコア/BEST、UnityEngine.Random.stateの不変を検査。最終10試行で全件不変。メインスレッド同期計算のため数msの描画待ちはあり、非同期・並列化は未実装。
- 最終実機比較：x=.65を8回＋左右端各1回。全10回で種類/個数・スコア・非終了状態・総物理tick一致。15点合体、2合体25点の試行を含む。空盤面/自由落下の最初3回は全誤差0。接触ありでは最大位置差0.0578314 Unity単位、速度差0.482445単位/秒、角度差9.58486度、角速度差119.227度/秒。落下X差最大2.38419e-7単位。総tick26〜129で比較。
- 1予測6.2596〜24.0614ms（Scene構築/コピー/計算/破棄予約を含み、非同期Unload完了待ちは含まない）。測定値はSuikaGameAi/SuikaAi/prediction_comparison.json。
- 比較スクリプトは位置1e-3/速度1e-2/角度0.5/角速度1.0の診断閾値で不一致を検知し失敗終了する。許容値を引き上げて合格扱いしていない。結果はstatus=experimental、validated_for_search=false。
- 残差要因：複製先に実世界の接触履歴/solver cacheを移植できないこと、内部body/接触作成順、削除とStart/終了判定の描画フレーム単位タイミング。初期接触0の自由落下は一致、接触ありで残差を観測。ただし個別要因の寄与は切り分け未完了。予測ではSimulate各tick後に合体元を無効化、終了判定も各tick。実ゲームではDestroyは描画フレーム末、終了判定はUpdateのため複数tick/フレームで差が出得る。
- Python unittest17件成功。C# UDP停止/重複/移動/例外/リセット回帰成功（スタブでありPhysics精度検査ではない）。初回sandbox内のUDPテストは通信制限でtimeoutし、ローカル通信を許可した実行では成功。
- Computer UseスキルでUnity 2022.3.21f1の既存Editorを操作、Play/実通信比較/終了後reset成功、Console例外0（既存CS0414警告のみ）。予測Sceneが残らないことをHierarchyで確認。最後にPlay停止。実機game_over到達、スイカ消滅、全種類/全接触/複数tickフレーム/長時間の網羅は未検証。
- Scene/Prefab/物理設定/得点/出現確率は変更なし。既存未コミット差分は保持。STEP 4は精度未達で未完了。次は接触履歴を保持するためのエピソード初期状態からの決定的リプレイ等を検討し、フレーム単位の合体削除/終了判定を記録して比較する。正確な任意盤面スナップショット復元を達成したとは主張しない。STEP 5は開始しない。
- 今回のソース変更一覧：追加 SuikaGameUnity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs と.meta、SuikaGameAi/SuikaAi/check_unity_prediction.py、tests/test_prediction_comparison.py、prediction_comparison.json。更新 Unity側 FruitEvolution.cs、Danse.cs、GameManager.cs、UDPStateProtocol.cs、UDPStepProtocol.cs、Tools/Test-UdpLifecycle.ps1。資料 DEVELOPMENT_PLAN.md、DEVELOPMENT_LOG.md、UDP_PROTOCOL.md。PlayerController.cs/ScoreManager.cs/UDPCommunicatorUnity.cs/Python unity_env.pyの既存差分には今回は変更を加えていない。Editorがcsproj/ログ/レイアウト等を通常更新する点は別。

## 2026-10-20 STEP 4：接触誤差の更新単位での調査

- C:\SuikaGameAIのdevelop、開始時clean。コミット/Pushなし。Scene/Prefab/物理設定/ゲームルールは変更なし。
- 任意指定のPredictionDiagnosticsを追加。Physics2DFixedUpdate直後に最大512tickを記録し、ID系譜・接触点/法線/normalImpulse・合体/生成/削除時点と数値差を比較。比較専用に最大150post-drop tickを指定可能、通常stepの25tickは維持。
- 初回10ケースで接触中の最初の有意差をtick1（0.02秒）に特定。初期数値は一致、実側の継続接触がコピー側では新規接触になる。合体/Destroy以前に差が出る。
- 自由落下→最初の床衝突でもtick74まで数値一致、tick75で分岐。接触点/法線19点は完全一致、normalImpulseの最大差12.15802。接触履歴欠落だけが原因と断定できず、solver拘束順/fixture作成順等は未確定。不確かな物理修正は行わない。
- 同一盤面A/B10ケース：診断なし/ありの予測結果は全件一致、実ゲームとの最終厳密比較は4/10合格。種類/個数・スコア・総tick・非終了状態は10/10一致。最大最終位置差0.0829872、速度差0.963758。盤面条件が前回と異なるため改善率にはしない。
- 合体用2ケース：2個目が両側tick59でtype2+2→3、6点加点・生成・削除要求が一致。次のtick採取前に実Destroy/予測無効化。終端/長時間/複数tickフレームの合体は未検証。
- 同一盤面の平均予測時間：診断なし13.08263ms、あり16.61295ms（追加3.53032ms）。Scene生成.06353、コピー1.18375、計算/採取15.29616、解放予約.05874ms。非同期解放完了時間は未測定。
- Python19テスト、C#回帰成功。Computer Useで新しいUnityプロジェクトのgameDisplayをPlay/比較/reset、Console例外0、最後に停止。詳細・各変更ファイルの関数/行番号/変更前後/抜粋はSTEP4_DIAGNOSTICS.md。結果はPython/prediction_trace_before.json、prediction_trace_paired.json、prediction_trace_merge.json。
- STEP 4未完了、STEP 5未着手。次は最初の床衝突fixtureでScene種別・body/fixture登録順等を1要因ずつ切り分ける。エピソード全再生は未実装で、今回の初回衝突の差を解決する保証もない。


## 2026-10-20 STEP 4-A：単体床衝突と方針判断

- develop、開始前の未コミット変更を保持。コミット/Pushなし。本番Simulator/ルール/物理設定の変更なし。
- Editor専用SingleCollisionProbeを追加。PredictionDiagnostics.Compareには明示actual Recorderのオーバーロードだけ追加。
- ブドウ1個＋元bottom、同じfactoryで自動defaultと手動localを120tick比較：同順は全tickの物理値差0。登録/有効化順序だけ逆にすると初回床接触tick62で差。位置差0.00594811、角度差1.6353455度。最大位置差0.03617935。点+法線一致15/19、インパルスも差。独立Scene/手動Simulateそれ自体が必ず誤差を生む仮説は支持されない。
- 本番の内部登録/拘束順や接触履歴が一意に特定されたわけではない。順序の推測修正はしない。新factory同士の最小実験であり、本番Copyの改善完了ではない。
- 120tick物理＋詳細記録ループ5.2837ms/5.1749ms、Scene作成解放は除外。本番13.08msと直接比較不可。
- Unityで短時間Play/実験/復帰/Stop、Consoleエラー0。Python19テスト成功0.319秒、UDPライフサイクル/step回帰成功。実験後は新しいPlayから通常操作を行う。
- docs/STEP4_CODE_GUIDE.mdに実コード抜粋と行番号、主要関数・通信順序・用語を詳記。docs/STEP4_DIRECTION.mdに測定結果、A/B/C精度とregret、層別STEP4-B案を記載。
- 推奨はB：完全一致の追求をいったん止め、STEP4-Bで合体/得点/終端と候補順位を評価。95%/80%等は仮目標。10試行で探索精度の達成判断はしない。STEP5未実装。


## 2026-10-20 STEP 4-B：予測精度の収集・集計基盤

- develop、既存未コミット変更を保持。コミット/Push、物理設定/ルール変更、STEP5実装なし。
- 新規Python CLIと集計module、13テストを追加。compare_stepを再利用し、試行数/episode長/入力/horizon指定、JSONL逐次保存、JSON/CSV集計、設定/資産ハッシュ、再開/オフライン再集計に対応。
- Unityは診断のfinal_actual/final_predictionと、Resultの可視NEXT型/終端高さの情報追加だけ。果物を親系譜aliasで対応し、不明な対応や更新/初期条件不一致を明示。終端の食い違いは除外に埋もれない別表へ残す。
- 実通信：100更新（約2秒以上）7試行/2episode、25更新3試行/1episode。すべて比較条件一致。本物の合体正例3（0→1、1→2、3→4）が予測と一致。非0得点1/3/10点も一致。連鎖・密集・終端近傍・実終端の正例は0で未評価。候補順位の正解は取得していない。
- 100更新の延べ16果物：位置平均.0137325/最大.113766、速度平均.0345394/最大.187123、角度最大16.9596度、角速度最大35.6236度/秒。診断なし平均10.8134ms、診断付き14.2156ms（非同期解放完了等は除外）。旧測定とは盤面/期間が違うため改善比較不可。
- UnityでPlay/実通信/Consoleエラー0/Stopを確認。Python32テスト成功0.463秒、既存UDP回帰成功。JSONL追記/新episodeで再開/オフライン再集計を確認。
- 少数・相関ありの測定なので95%目標達成とは判断しない。層別追加収集と公平な同盤面候補評価基盤が必要。docs/STEP4B_EVALUATION.mdに実コード/行番号/計算式/手順/判断条件を記載。


## 2026-10-20 合体後の持続的めり込み：対策と短時間検証

- develop上で作業。既存未コミット変更を保持。コミット/Pushなし。Scene/Prefab/物理設定・進化順・得点は変更なし。
- 確認：FruitEvolutionは接触中の2個の中点に大型果物を生成し、元の果物はDestroy待ちだった。重なり除去は通常の物理演算任せ。隔離Sceneでは、起きているRigidbodyでも深い重なりが300tick（6秒）継続する配置を再現。スリープだけが原因ではない。複雑なPolygon内部の拘束等のエンジン内部原因は未特定。
- FruitEvolution.RemoveFruitで消費済みColliderを直ちに無効化。新規MergeOverlapResolverを合体直後に実ゲーム/予測で共通実行。元のPolygon距離から深い重なり（defaultContactOffsetの3倍超）を検出し、短い位置補正を最大32周行う。補正経路の途中も既存の壁/他果物への新しい重なり・既存重なりの悪化を検査し、不適切なら元の位置へ戻す。許容深さはdefaultContactOffset。速度/形状/重力/摩擦の書換えなし。
- 限界：補正は位置の直接変更なので、合体時の軌道・接触・見え方は従来と変わり得る。密集して安全な逃げ先がなければ打切り、全ケースの解消保証はしない。ユーザー報告と同一の実盤面はまだ再現できていない。
- Editor専用MergeOverlapProbeを追加（Play中 Tools > Suika > Run Merge Overlap Probe / Ctrl+Shift+F9）。元Prefab/本番合体処理/独立PhysicsScene2Dで5種類×3配置×300tick。20261020_124357_875（変更前）と125806_604（変更後）：6秒後最大深さ0.215273→0.004245 world units、全300tick深い重なりが続くケース1→0/15。最初から親に重なるストレス配置を含み、合体前に隣接果物が両親から離れている5配置では変更前も持続バグは出ていない。15件の一般的なバグ再現率と解釈しない。
- 追加の直接補正試験：空き空間で深さ0.298425→0、壁で囲むと0.298425→0.150530（残存）。壁への深さは最大0.010000で許容値内。補正で必ず解消できるという主張はしない。隔離試験中、実スコア/乱数不変を確認。15配置+壁試験の合計680.65ms、予測1回の性能測定とは異なる。
- Unityコンパイル/Play/隔離試験/Stop、Console例外0。Python32テストと既存UDPライフサイクル回帰成功（これらは新しいネイティブ物理補正自体の試験ではない）。実通信check_unity_prediction --merge-case --post-drop-steps 100：2回落下、合体1、実/予測とも加点3、reset成功。予測所要8.31/7.22ms。合体後位置差0.002001、厳密閾値0.001を超えるため比較全合格にはならない（既存の予測誤差がなくなったとは判断しない）。
- 測定JSONはPython/merge_overlap_probe_*.json、実通信はPython/merge_fix_live_20261020.json。従来1,000試行の保存結果は未変更で旧挙動の評価。次は通常の密集盤面で問題が出ていた合体を確認し、必要ならその配置を追加回帰にする。STEP5未実装。


## 2026-10-20 合体後の押し出しを力方式へ変更（ユーザー指定の試作）

- ユーザーの「生成場所は変えずに、重なったら強く押し出す」「一度実装」に従い、前項の直接位置補正を撤去。生成位置は従来の中点、以後もtransform/body.positionを補正から書き換えない。消費済みColliderの即時無効化は維持。
- MergeOverlapResolver.Resolveは合体後の押し出し時間を登録。TickはPolygonの深い重なり（接触オフセット3倍超）を検査し、中心から外向きへ質量比例のImpulseを毎物理更新加える。深さに応じ加速、押す方向の速度成分を上限管理（落下速度・衝突による全速度の絶対上限ではない）。静的/kinematic障害物に向かうCollider.Castを避け、代替方向を試す。壁の衝突解決はUnity物理に任せるため、壁への食い込みゼロの保証はない。
- EvolutionManagerのEvolutionDatabase InspectorにMerge Push Acceleration=30（基準加速度 world units/s²）、Max Speed=5（押出方向 world units/s）、Duration=2（ゲーム秒）を追加。暫定値で公式挙動の再現値ではない。Duration=0で以後の合体の押し出し無効。重力・摩擦・質量・形状・進化順・得点は未変更。
- FruitEvolution.FixedUpdateで実ゲームを更新。SuikaPhysicsSimulator.TickMergePushは手動Simulate直前に同処理を実行し、Copyは進行中のOverlapPushTimeRemainingも引き継ぐ。reset/破棄後のオブジェクトに対する常駐管理リストは作らない。予測の計算中に実ゲーム側へ力は加わらない。
- MergeOverlapProbeを力方式へ更新：300tickの前にTickMergePushを明示実行。力を加えた瞬間に座標が直接変わらない、タイマーコピー、時間切れ、実スコア/RNG不変をネイティブUnityで確認。
- 130928_210.json（保持する実装）：15配置中14で6秒後深さ0。ただし14件は未補正でも自然解消する配置であり、修正の成功数と解釈しない。従来からの持続再現（桃2個＋近傍チェリー、offset=.35、合体前から重なるストレス配置）は0.215273→0.21067とほぼ変わらず、全300tick重なり継続。力だけではこの持続バグは未解消。
- 直接生成したパイナップル/チェリーの試験：開放空間では深さ0.298425→0、壁で囲むと→0.004718。ただし壁への一時的最大深さ0.042165で、試験の許容0.03を超えsafe=false。力/移動先検査だけでは物理的な壁接触中の最大食い込みを保証できない。15配置＋壁試験合計854.73ms。
- 0.25秒後に斜め45度へ押す追加案も1回比較（131313_756.json）。持続深さ0.21068、壁最大0.048411で改善なし。追加案は撤去し、130928時点と同じ実装を残した。原因をエンジン内部の拘束と断定はしていない。強さの追加調整だけで解決する保証はない。
- Unityコンパイル/Play/試験/Inspectorの3項目表示/Stop、例外0（既存CS0414警告あり）。Python32テスト0.442秒、UDP回帰成功。実通信merge_push_live_20261020.json：2落下、合体1、実/予測とも10点、reset成功、両試行で既存比較閾値内。位置最大差1.19e-7、予測8.37/7.51ms。ただし周囲の押し出しを伴う密集盤面の実/予測一致は未検証。
- 変更はMergeOverlapResolver.cs、FruitEvolution.cs、EvolutionDatabase.cs、SuikaPhysicsSimulator.cs、Editor/MergeOverlapProbe.cs、当ログ。developを維持しコミット/Pushなし、Scene/Prefab/ProjectSettingsの意図的変更なし。生成位置保持・力方式の試作完了だが、持続バグの完全修正として扱わない。


## 2026-10-20 押し出し試作の撤回・復旧チェックポイント

- ユーザーから実プレイで不自然な挙動の報告。直接位置補正/Impulse押出しの両方式を撤回し、合体前の通常の中点生成・Destroy処理へ復旧。Inspectorの押出し項目・FixedUpdateフック・予測の押出しタイマーも撤去。
- 復旧対象は今回の実験分のみ。既存STEP4-A/Bの未コミットの評価・診断コードとテスト/資料は保持。ユーザー指示により復旧したソース構成をdevelopへコミット/Pushする。評価結果の大量データはローカルに残し、Push対象に含めない。
- 別案は復旧チェックポイントの後に検証。強制的な押出しを再導入しない。


## 2026-10-20 押し出し撤回後：Colliderの内部境界を減らす対策

- 復旧チェックポイント32b94b912d500f6fa8c90acaeaee20b997f16715をorigin/developへPush済み。STEP4-A/Bの未コミットのソース/資料も含め、押し出し実験導入前のゲーム処理を保存。評価データはPushせず保持。新対策はこのコミットの後のローカル変更であり、未コミット/未Push。
- ブラウザ調査：Box2D開発者の公式記事 https://box2d.org/posts/2020/04/stuck-inside/ は、深い重なりと凸分割の内部接触が互いに対抗し拘束される現象を説明。UnityのPolygonCollider2D.useDelaunayMesh公式資料および2022.3.21f1同梱APIも確認。資料の説明は今回の内部ソルバー原因の直接証明ではない。
- 対照試験ではDelaunay全体有効化や一部種類のみ有効化、内部形状への重なり追加、元頂点の凸包化のみでは別ケースが悪化。実ゲームへは採用しない。作業中の試験専用MergeColliderGeometryは撤去し、未検証の実験コードを実ゲームへ残さない。
- ユーザーが「当たり判定の小さな形状差は許容する」と回答。画像/生成位置/Transformサイズを維持し、11種類のPrefabのPolygonCollider2D.m_Pointsだけを8支持線で作る凸8頂点へ変更。支持線は元の点群のx,y,x+y,x-y方向の極値から導出。元点をすべて包含し、ローカルの上下左右の極値は同じ。円Collider化や追加の力/座標補正はしない。重力/摩擦/質量設定/得点/出現確率/Scene/物理設定/.meta/進化順は未変更。
- 元点列に非隣接辺の交差を確認（チェリー125組、パイナップル5組、閾値付き線分交差）。細かい折返し等の不整合を含む。8頂点化後のネイティブshapeCount=1により分割境界がなくなる。これが改善要因であることを実験は支持するが、全てのめり込み原因の特定ではない。
- 当たり判定の面積増分（元の各pathの靴紐面積の和との比較、重複pathのunion面積ではない）：apple5.779%、cherry5.566%、grap9.414%、kaki3.676%、melon5.320%、nashi5.473%、orange5.946%、painaple4.878%、peach5.168%、storobary6.074%、watermelon5.214%。画像や軸方向サイズは同一でも角付近の接触、転がり、形状から計算される慣性等の挙動は変わり得る。
- 隔離Sceneの48配置×300tick（6ゲーム秒）比較：元形状では6件が全tickで深さ0.03超のまま継続、最終最大0.373326。合体後のみ8頂点化/全体8頂点化とも深さ0.03超の残存0、最終最大約0.005007。比較JSONはPython/merge_overlap_probe_20261020_144227_218.json。48配置中17が合体前に隣接果物と両親が離れた配置、31は元から重なるストレス配置。一般的な実プレイでの発生率や完全保証と解釈しない。
- 実Prefab適用後の回帰：Python/merge_overlap_probe_20261020_144639_898.json、48配置すべてで合体/shapeCount=1/最終深さ<=0.03を確認、最大0.00500677、637.25ms、実ゲームのスコア/RNG不変。EditorのTools > Suika > Run Merge Overlap Probeで再実行可能。テストは壁/床なし。実際の密集盤面や長期プレイ全体は未確認。
- Unityで新しいPlayから実通信10落下（中央8、左右端各1）、合体1、加点6、reset成功、Console例外0、Stop確認。Python/collider_fix_live_20261020.jsonでは得点/種類/ゲームオーバー真偽/tickが10/10一致。ゲームオーバー正例は0。厳密な全物理値の閾値内は6/10、最大位置差0.0264502、予測平均4.40827ms。別条件の旧平均11.43msと速度/精度を直接比較しない。予測誤差の問題は残る。
- Pythonの幾何回帰5件追加、合計37テスト成功0.994秒。復旧コミットの元Prefabと比較し、8頂点の凸性/元点包含/軸方向極値不変/面積増分10%以下/Polygon点以外の全設定不変を検査。既存UDP回帰も成功。
- 途中の試験エラー：Play中のスクリプト再コンパイル後、UDPCommunicatorUnity.CompleteStep(168行)でNullReferenceExceptionが反復。Stop→新Playで復旧し最終実通信では再発なし。再生中のコード再読込への耐性は別件として未修正。試験用凸包処理のone-path仮定でもInvalidOperationExceptionが発生し、kakiに2pathがあることを確認後、隔離試験を修正。いずれも記録し、最終テストの成功と混同しない。
- 最終変更：Unity/Assets/Scenes/Prefabの11果物、Editor/MergeOverlapProbe.cs、Python/tests/test_fruit_collider_geometry.py、当ログ。ゲーム本体C#には押し出し/補正を残さない。次はユーザーが以前問題の出た密集合体を確認し、必要ならその配置を回帰に追加。旧1,000試行の精度は新形状では再評価が必要。STEP5未実装。


## 2026-10-21 画面サイズによる配置ずれ・手動Collider変更への対応
- developで実施。ユーザーが11果物をCircle/Capsuleへ変更し、旧Polygonを無効化した状態を確認。今回Prefabは変更していない。
- 原因：背景は幅基準CanvasScaler、得点は固定ピクセルOverlay、主人公/NEXTはworld座標で基準が混在。
- 背景・得点CanvasをWorld Spaceへ変更。背景の既存800×436.9686をcameraの高さ10world unitsに合わせる。得点は既存テキスト枠が画面内に入る1000px基準で配置（見た目の基準位置は要ユーザー確認）。GameViewportで背景の縦横比を保つviewportに収める。余白ができる方式でcamera orthographicSize=5、物理座標、game-over高さ計算は維持。
- FruitColliderShape.Getで有効Colliderを参照。保持/落下/壁安全範囲/予測/合体/摩擦設定/診断をCircle/Capsuleに対応。合体時に旧Polygonを再有効化する処理を除去。前回のPolygon形状専用テストと隔離probeも現在のColliderに対応。
- Unity付属Roslyn＋Unityアセンブリ参照でruntime全C#のコンパイル成功（既存の未使用フィールド警告3件）。Pythonテスト成功。Scene配線・スケール・得点枠の画面内配置も自動検査。
- Computer Useで起動中ウィンドウを確認したがUnity Editorは未起動。Play/リサイズの見た目/合体/実通信/新形状での予測精度は未検証。修正済み・動作未検証。旧Polygonで得た精度・めり込み統計は新形状の保証にならない。
- コミット・Push未実施。STEP 5は未着手。

### 2026-10-21 Editorコンパイルエラー修正
- MergeOverlapProbe.csの75・76行：FruitEvolutionをGameObject引数へ渡していた2箇所をevolved.gameObjectへ修正。前回はruntimeのみコンパイルしEditor側の型エラーを見落としていた。
- Unity付属Roslynでruntime全C#とAssets/Editor内の全C#を別アセンブリとしてコンパイル成功。Play動作は未確認。コミット・Pushなし。

## 2026-10-21 右移動停止・ブドウのプレビュー落下・NEXT位置
- develop。PlayerControllerの保持/NEXT初期化で既存Rigidbody2Dの速度・角速度・重力を0へ。NEXTのみsimulated=false、保持側は壁トリガー用にsimulated=true。DropFruitで速度0、重力1、simulated=trueへ戻す。ブドウPrefabに元からあるDynamic/GravityScale=1がプレビュー中にも働いていた原因を確認。Prefab・形状・質量・全体重力は変更なし。
- FruitCollisionHandlerのEnter/Exit通知はplayerController.currentFruitと一致する果物だけ許可。落下済み果物が後から壁通知を出し、現在の右移動フラグを立てる経路を遮断。Spawn時に前の果物の左右フラグをクリア。
- NEXTは背景RectTransformの正規化座標(1625/1920,1-290/1080)へSpriteRendererの画像bounds中心を合わせる。背景の丸の中心を原画像で確認。SceneのPlayer Prefabインスタンスに背景参照のoverride追加。InspectorのNext Preview Anchorで微調整可能。
- SuikaPhysicsSimulatorも同じPreparePreviewBody/ReleaseFruitBodyを使用し、予測側だけ古い落下初速度になる不整合を防止。
- 新規Editor/PreviewControlProbe：Play中Tools/Suika/Run Preview Control Probe (Ctrl+Shift+F10)。元の果物配列を一時的にブドウ限定にして、0.4ゲーム秒の保持/NEXT安定、落下開始速度0・重力1、旧果物の右壁コールバック無視、新果物でMoveRight可能、NEXT画像中心と背景anchor一致を検証し、元配列に戻してreset。実UnityでPASS。
- Runtime/Editor全C#コンパイル成功、Python36テスト成功。Computer UseでPlay・回帰probe実行・NEXTが丸の中心にある見た目を確認。Consoleエラー0・警告0（Play検証時）。停止して終了。
- Scene Reload操作は最初に自動承認審査が未保存変更破棄の可能性で拒否。ユーザーが未保存変更なし・Reload許可と回答後に再読み込みした。
- キーボード長押しを含む長時間の実プレイ、今回の修正後の予測精度統計は未確認。コミット・Pushなし。

## 2026-10-21 STEP 4 現在のCircle/Capsule環境へ予測を適応
- ユーザーが実ゲームのバグ解消を確認。developで対応、コミット/Pushなし。手動変更済みPrefab・物理設定・Sceneは今回変更しない。Editor内の未保存Scene（Speed=10等）も保存/再読み込みせず保持。
- SuikaPhysicsSimulator.Copy：盤面のruntime Rigidbody状態コピーとfresh prefab生成を区別。修正前の短時間比較でイチゴ合体→ブドウ生成時にRigidbody clone state mismatch (grap inertia=0.0001/0)を実際に確認。Prefab資産の未初期化慣性0/重心をcloneへ上書きせず、実ゲーム同様に生成されたColliderからUnityが計算した値を使用。実盤面のbodyコピーは従来通り状態を復元・検査（simulatedも追加）。
- 予測内でNEXT表示を次の操作用へ切り替える際にPreparePreviewBody(false)を呼び、simulated=true/重力0/速度0へ。PlayerDropPlacement.GetDropRangeForFruitを実ゲーム・予測で共有し、次の大きな果物を同じ壁・形状・ワープ境界・clearanceで安全範囲にclamp。果物形状はInstantiateで現在のCircle/Capsuleと無効Polygonの設定をそのままコピー、旧Polygonを有効化しない。
- 予測結果にcurrent_fruitとdrop_rangeを追加。Python/check_unity_prediction.pyで次の操作用果物の種類・位置・移動範囲も照合。旧JSONとの比較互換性を維持。SourceSignatureはpreview/重力/simulated/質量/慣性も検査するよう拡張。
- MergeOverlapProbeにイチゴ合体→ブドウの3配置を追加し51配置へ。実行結果Python/merge_overlap_probe_20261020_163758_902.json：51/51通過、670.162ms、最終最大重なり深さ0.00502026、source_unchanged=true。壁/床なし、300tickの隔離ストレス試験であり、実ゲーム全条件の保証ではない。
- 修正前10落下（simulation_adaptation_before_20261021.json）：得点/種類9/10、厳密7/10、平均5.66979ms、最大位置誤差0.00880760（種類不一致の1件は位置対応不可）。修正後10落下（simulation_adaptation_after_20261021.json）：得点/種類/個数/game-over真偽/tick/次操作果物種類/範囲すべて10/10、厳密9/10。最大位置0.00112942world、速度0.00291312world/s、角度0.298187度。合体正例1（+6）一致。別々の乱数エピソードのため前後差を改善率とは解釈しない。game-over正例なし。
- 修正後の予測平均4.8037ms、中央値2.8746ms。平均内訳Scene生成0.19215ms、copy1.54889ms、物理2.71175ms、解放予約0.05142ms。解放完了までの非同期時間は含まない。
- 別途2秒horizonの同種2落下（simulation_adaptation_merge_20261021.json）：2/2厳密一致、実/予測とも合体+10、位置/速度/角度の最大誤差0、平均2.15725ms。
- 既存evaluate_unity_prediction.pyも5試行、x=0/0.5/1、25post ticksで実通信確認（eval_adapted_smoke_20261021、completed/eligible 5/5、除外0、実合体正例1）。旧1,000試行に追加/上書きせず別ディレクトリへ記録。大規模な予測精度評価は再実施していない。
- Runtime/Editor全C#をUnity付属Roslynでコンパイル成功、Python38テスト成功。Computer UseでPlay/隔離合体probe/Console確認/Stopを実施。修正後PlayのConsole例外0・警告0。接触履歴・Destroyと描画frame順序の既存制約は残り、validated_for_search=falseのまま。STEP 5未実装。


## 2026-10-21 ユーザー指定比率による果物Scale調整（第1段階）
- ユーザーの個別指示で10果物Prefabのroot Transform.localScaleのみ変更。籠の内幅=6.40031985を基準にColliderの直径/横幅を合わせる。りんごは変更せず、Scene・コード・物理設定・Collider形状/半径/Offset/有効状態・質量の設定値も変更しない。シミュレーター対応は調整完了連絡後。
- ブドウ (grap.prefab)：籠:果物=175:24、目標横幅=0.87775815、Scale XYZ=0.248333388。
- サクランボ (cherry.prefab)：籠:果物=175:12、目標横幅=0.43887908、Scale XYZ=0.088810558。
- オレンジ (orange.prefab)：籠:果物=175:26、目標横幅=0.95090466、Scale XYZ=0.669350624。
- いちご (storobary.prefab)：籠:果物=175:16、目標横幅=0.58517210、Scale XYZ=0.892669744。
- かき (kaki.prefab)：籠:果物=175:33、目標横幅=1.20691746、Scale XYZ=0.456446455。
- パイナップル (painaple.prefab)：籠:果物=175:68、目標横幅=2.48698143、Scale XYZ=1.276202332。
- メロン (melon.prefab)：籠:果物=175:68、目標横幅=2.48698143、Scale XYZ=0.545546288。
- スイカ (watermelon.prefab)：籠:果物=22:12.7、目標横幅=3.69473010、Scale XYZ=0.822984781。
- モモ (peach.prefab)：籠:果物=22:7.7、目標横幅=2.24011195、Scale XYZ=0.957816798。
- ナシ (nashi.prefab)：籠:果物=24:5、目標横幅=1.33339997、Scale XYZ=0.686021435。
- モモは有効CapsuleCollider2DのSize.xを使用しCapsule/縦横比/Directionを維持。円の半径式は使わない。実ゲームの生成時の回転Quaternion.identityにおける横幅を基準とし、転がりによる回転後の幅が一定になるという意味ではない。
- 10ファイルすべてScale行以外の内容不変・保存値での比率誤差relative2e-8以内を検査。Unityは停止中であることをComputer Useで確認。Editor内の未保存Sceneには触れず、Play動作/見た目/物理予測の再検証は未実施。コミット・Pushなし。

## 2026-10-21 接触後の果物だけをゲームオーバー対象にする修正（環境調整中）
- ユーザーから開始直後のgame-overと、保持果物がラインを越える条件を報告。ゲーム側のGameManager.cs/FruitEvolution.csを最小修正。手動変更されたScene・Prefab・PlayerController・TimeManager等には書き込みなし。シミュレーター本体は調整完了連絡前のため変更なし。
- FruitEvolution.HasCollidedをruntime状態として追加。保持/NEXTのIsPreviewはOnCollisionEnter2Dの対象外。落下後の通常衝突（壁・床・別の果物等）で接触済みになる。Trigger進入では接触済みにしない。合体生成果物は接触を原因として生まれるためHasCollided=trueを引き継ぐ。
- CanTriggerGameOver(height)：active・非preview・非merging・接触済み・Transform Y>heightを条件にする。GameManagerはFruitタグとSimulation==nullも確認する。元果物のDestroy待ちと隔離予測果物を判定から除外。高さの算出式/Transform位置での比較/得点/物理設定/手動操作は維持。
- MergeOverlapProbeにfresh未接触は低いラインでも対象外、接触合体後は対象、ラインと同じ高さは対象外、previewへ切替なら対象外のassertを追加。現在のPrefabで51配置×300tick成功。出力Python/merge_overlap_probe_20261021_053631_288.json。これは条件/接触/合体の検査であり、実ゲームのgame-over演出・再スタートまで通した正例テストではない。
- Runtime/Editor全C#のコンパイル成功（既存未使用フィールド警告3）、Python38テスト成功。UnityのPlay開始後、実UDPでgame_over=false、score=0、held=true、盤面0、time_scale=1を取得し、さらに0.6秒待ってもfalseを確認。Console例外0・警告0。Play停止確認済み。
- 第2段階でHasCollidedのruntimeコピー・予測GameOver条件・数値観測・必要な診断情報を新ルールに対応させる必要がある。現時点で既存の予測精度結果を新ルールの保証に用いない。環境全体の再調査とシミュレーター適応はユーザーの調整完了連絡後。
- コミット/Pushなし。Editorの未保存Sceneを保存/再読込せず保持した。

## 2026-10-21 手前画像の描画順・左右端の安全移動・梨/メロン比率
- ユーザー指示で描画順と端の不具合を修正。画像の加工/取り込み/配置/位置合わせは行わない。Sceneの変更は既存Background Canvas=-100、得点Canvas=40、ユーザー配置済みsuikaBackground_lyout SpriteRenderer=20のsortingOrderのみ。保存済みのTransform/画像参照は不変と機械検査。Player Prefabの描画順30、painaple Prefab=-10。全Sorting LayerはDefault。Scene/対象PrefabにSortingGroupなし。
- 保持果物は生成時にOrder=31へ（Playerより前）、落下時にPrefab本来の値へ復元。NEXT表示は30。背景のWorld SpaceとGameViewportは既存実装を利用し、Camera zoomやTransformは変更しない。前景の背景子配置、UI Image＋子Canvas Override Sortingの手順とPNG原寸/切抜寸法の合わせ方をdocs/RENDERING_AND_PLACEMENT.mdへ記載。新しい前景オブジェクトは作成せず、既存の配置も動かしていない。
- 端の原因：手動はrb.velocity＋壁triggerフラグだけで移動しAI安全範囲を通らず、落下前の安全確認もなく、手動では大きいNEXTの初期clampが未適用。固定ワープ境界も籠サイズの変更に追随しなかった。
- PlayerController：手動の横移動をFixedUpdateのinput*speed*fixedDeltaTimeにし、GetDropRange/TryMoveHeldToでclamp。キー/A/D/既存UDPの強弱入力値と速度設定は維持。Update追従後・生成直後・DropFruit直前にも同じ範囲/Distance検査を使用。移動範囲不明/重なり時には落下させない。固定境界での中央ワープを廃止し左右壁の内面と実形状で制限（旧Inspector閾値フィールドは互換のため残るが範囲制限には使わない）。既存の接触後game-over判定は変更/無効化していない。
- PlayerDropPlacement：手動/AI/将来予測のGetDropRangeForFruitを共用。左右2壁をX順に判定し、果物Colliderの実bounds/Offset/Scale/Circle/Capsuleと3*contactOffsetの余白を使用。壁回転/不足/曖昧/果物が入らない場合はfail closed。壁が保持果物の高さをカバーする現構成を前提とする。
- Held Fruit OffsetをInspector公開。既存Updateの値(-0.7,-0.42,-1)を初期値とし、SpawnFruitだけY=-0.39だった不一致も統一。保存されたPlayer位置/Scaleは変更しない。新しい大きな保持果物が端に入らないときはランタイムでPlayerと新果物だけ必要な分内側に置く。
- 追加指定：籠内幅6.40031985に対し梨35:1＝直径0.1828662814、Radius0.9718355、Scale XYZ0.094082940。メロン35:17＝直径3.1087267843、Radius2.2793496、Scale XYZ0.681932860。対象2PrefabのScale行以外は不変と検査。他果物のサイズとCollider/物理設定は変更なし。
- 新Editor/PlayerBoundaryProbe（PlayでTools/Suika/Run Player Boundary Probe、Ctrl+Shift+F11）：全11種類×両端22＋小果物の端から最大果物NEXTへの切替2＝24ケース。実際の手動FixedUpdateを直接100回呼び、native bounds/Collider.Distanceで非重なり、落下可、保持Order31/落下時Prefab order復元を検査。24/24成功。これはdefault physicsを100tick進めたテストではない。
- 普通のUnityEnv.step（予測比較は使用しない）でも新規resetを挟みx=0/1を4落下。type4左、type0右、type0左、type1右が全てdrop_success=true、applied_xは対応するmin/maxと一致、game_over=false。長時間の積み上げや正当なgame-over正例は今回は未実施。
- Runtime/Editor全C#コンパイル成功、Python38テスト成功。途中の追記スクリプトでUTF-8ファイルのCP932読取エラーが出たが、書込前に停止し、encoding明示で再実行して解決。最終PlayのConsoleエラー0・警告0。ウィンドウ960幅→1920幅の最大化でGameView縦横比を変え、構図/背景/Player/NEXT/得点の相対位置維持を目視確認。Stopし元のウィンドウ寸法へ戻した。
- GameViewportコード/物理設定/ゲームオーバーコード/SuikaPhysicsSimulator本体には今回書込なし。予測側のHasCollided等を含む全面対応はユーザーの環境調整完了後。Scene再読込は編集前の未保存マークがないことを確認して実施。コミット・Pushなし。


## 2026-10-21 梨の比率訂正と0.2秒の落下制限
- ユーザー訂正で梨は籠:直径=7:2へ。籠内幅6.40031985、Circle Radius0.9718355から目標直径1.8286628143、Scale XYZ0.940829397。梨PrefabはScale行のみ変更、Collider/質量/他果物/Sceneは変更なし。
- PlayerController.dropCooldownSeconds=0.2をInspector公開（Drop Cooldown Seconds）。成功した落下時点からTime.timeAsDoubleによるゲーム内時間で次回受付時刻を管理。保持/NEXT生成や音は制限中に追加発生しない。ResetForEpisodeで解除し新しいエピソードの最初の落下は即時可能。時間停止中は落下不可。
- TryDropAtも同じCanDropFruitで制限。UDP stepは目標位置で制限解除まで待ち、予約済みaction_idを重複実行しない。通常の落下後0.5秒の観測窓は変更しない。将来の予測には開始時点の残り待ち時間のコピーが必要（今回はSuikaPhysicsSimulatorへの書込なし、環境調整完了後に対応）。
- Editor/DropCooldownProbe（PlayでTools > Suika > Run Drop Cooldown Probe）を追加。Unity実行で同フレーム20回連打・0.2秒未満のフレームでの追加落下が拒否、0.22秒以降の落下成功、resetで即時受付に戻ることを確認。Consoleエラー0・警告0、Stop済み。途中でCtrl+Shift+F12がTMPメニューと競合したため、検証メニューのショートカットは除去しメニュー直接実行にした。
- Runtime/Editor全C#コンパイル成功。Python38テスト成功。UDP既存回帰3群と、新規の制限中待機→解除後1回落下（再送含む）回帰成功。コミット・Pushなし。


## 2026-10-21 落下間隔0.4秒と現在のゲーム環境への予測対応
- ユーザーがシミュレーター適応を明示許可。developで作業、コミット/Pushなし。ゲームの位置/Scale/形状/質量/重力/摩擦/進化/点数は変更なし。PlayerController初期値とPlayer Prefab、gameDisplay SceneのdropCooldownSecondsだけを0.4へ明示保存。コードだけ変更するとEditorの再コンパイル時に旧0.2が保持されたため、保存値を明示して再読込・実UDPで0.400000006を確認。再読込前に未保存Sceneマークなしを確認。
- SuikaPhysicsSimulator：実体の有効Circle/Capsule・実行時Rigidbody・壁床を既存Copyでコピーし、現在の共有GetDropRangeForFruitとAI Move Speedを利用。FruitEvolution.CopyPredictionStateFromでIsPreview/HasCollidedを明示継承（Instantiateではauto-propertyが復元されない）。予測game-overも実ゲームのCanTriggerGameOverを共用し、保持/NEXTを除外。合体は既存FruitEvolutionを共用し接触済みを継承。
- 予測の最初の物理更新時刻はTime.fixedTimeAsDouble+fixedDeltaTime。nextDropAllowedAtと比較し、目標到着後も制限中は落下せずSimulateを継続。待機予算をループ上限へ加算。落下後の0.5秒窓は実際の落下後から維持。Resultにcooldown_wait_steps/drop_cooldown_seconds/initial_cooldown_remaining追加。
- 数値観測：drop_cooldown_seconds/drop_cooldown_remaining、各果物has_collidedを追加。診断Frameにもhas_collidedを追加。SourceSignatureでも接触済みと落下許可時刻・設定値の不変を検査。Pythonの自動timeoutは移動と待機が並行するためmax(移動時間,残り待機)+落下後窓で算出しtimeScaleで換算。既存UDPのaction_id/再送/1個だけ落下は維持。
- C# Runtime/Editor全体コンパイル成功（既存未使用フィールド警告3）。Python39テスト成功、UDPライフサイクル/再送/待機/観測窓の回帰成功。Editorの0.4秒Probeで同フレーム20回および早期落下拒否、0.42秒以降受付、reset即時受付を確認。
- 最終保存値0.4での実UDP比較10試行（x=.65を8回、両端各1）：得点/種類個数/game-over/物理更新回数/次の保持果物と範囲は10/10一致、厳密数値基準は8/10。最大位置誤差0.00320562 world unit、速度0.10822645 unit/s、角度0.91485596度、角速度15.5564239度/s。落下X誤差最大1.78814e-7。平均5.73202ms、中央値2.74415ms（初回19.7069ms含む）。保存Python/simulation_env04_20261021_final.json。game-over正例は0件であり検出能力の保証ではない。接触中に開始する予測のcold-contact-cache等の既存制約は残り、完全一致・統計的精度改善は主張しない。
- CooldownPredictionProbeをDropCooldownProbe.csへ追加。テスト中のみ出現リストをサクランボに固定し、通常Drop直後にcompare_stepを同一呼出し内で予約。元リストは終了/例外時に復元しreset。0.4秒待機20tickを含む計121tickが実ゲームと一致、合体1回/加点1一致、source_unchanged=true。最大位置誤差1.90735e-6、速度/角度/角速度誤差0、予測3.8615ms。保存Python/cooldown_prediction_20261021_065710_742.json。未来NEXT以外の乱数は予測に渡さない。
- native隔離合体/接触/ゲームオーバー条件Probeは51ケース×300tick完走（Python/merge_overlap_probe_20261021_065813_815.json）。手動左右端/全11種類/大きいNEXTの安全範囲Probeも24/24成功（後者はdefault physicsを100tick進めるテストではない）。Play Consoleは新規例外0/警告0、停止済み。長時間積み上げ、game-over正例を含む実ゲーム比較、1000試行統計の再検証は未実施。
- 参考：明示保存前の比較Python/simulation_env04_20261021_normal.jsonとcooldown_prediction_20261021_065233_647.jsonはEditorが0.2を保持した段階の結果で、最終0.4の評価に含めない。ランダムな同種NEXTを探す旧merge-caseは10回で揃わず未実施となったため、上記の確定fixtureで代替。単発Python確認でsrc未追加のimportエラーが出たが、srcを明示して実UDP確認成功。既存の評価出力は削除/上書きなし。STEP 5は実装せず、予測精度の大規模評価は別途必要。


## 2026-10-21 STEP 4主要問題の改善・STEP 5設計案
- ユーザーの新方針：完全一致に固執せず、主要問題の改善/短時間検証後にSTEP 5を設計。実装は設計案への確認後。今回までの成果をdevelopへ通常commit/pushする許可を受領。
- GO条件/物理更新順は変更せず、Recorderにgame_over_candidate（同一物理フェーズの条件成立）を追加。確定フラグ、最初の成立Frame、step完了時の確定結果と区別。接触済み差も診断。cold-contact-cacheや描画/Destroy境界の予測誤差と試行111見逃しの根治未確認を明記。
- 命令受付/step完了で非重複の報酬区間を記録。step中/step間/進行中区間/旧episode reset時集計、得点保存則、read-only観測、再送の二重計上防止。Pythonで区間/保存則を検査し、評価summaryも最新episode累積値のみ集計。step返り値rewardへのgapの単純加算はしない。
- 手動通常入力0.5とSpeedからEffectiveAIMoveSpeedを導出、既定で自動追従。現設定で手動/AI/予測3.75。旧aiMoveSpeedは追従無効時の個別値として維持。
- Python46テスト、全Runtime/Editor C#compile、UDP/報酬ledger回帰成功。20試行実UDP比較は得点/合体20/20（正例5）、更新数20/20、参照平均6.111175ms。位置誤差最大0.066580675等は残る。速度・盤面・サンプル数が異なり旧500回との改善率は断定しない。
- 実際の思考待ち時間に自然加点3点が発生し、step合計20+open gap3=23点の保存則とreset旧episode集計保持を実UDP確認。native速度3.75計測/ライン上接触GO正例/候補判定→Update確定の記録/0.4秒待機・合体・ledgerも確認。最終Console例外0/警告0、Play停止。
- テスト途中のJSON null空オブジェクト受信拒否はpresentフラグとテストで解決。GO fixtureの初版はCollider offset差で接触しなかったため、テストのbounds.center配置のみ修正。詳細・関数・行番号・変更前後のコードはSTEP4_IMPROVEMENTS.md。生ログはローカルだけに保持。
- STEP5_DESIGN.mdは5候補、同一Unity受付で予測/評価/選択/step予約、単純得点/高さ/危険度/偏り評価、将来snapshot照合と判断部分交換を提案。未実装。DEVELOPMENT_PLAN.mdに数十手先/不確実性/複数AIモード/高速無描画/保存再開の長期目標を記録。STEP 6以降は開始せず。


## 2026-10-21 STEP 5：5候補の1手先探索と自動プレイ
- developの既存変更（STEP5_DESIGN.md）を保持し、設計承認後に実装。commit/pushなし。
- PlanningSettings、HeuristicEvaluator、StepPlannerを追加。同一ライブ盤面から独立PhysicsScene2Dで5候補×落下後25更新、H/D/Rと得点で評価。GO候補除外、全GO専用の生存時間/超過量フォールバック。床は既存bottomのBoxCollider2Dを明示参照する1行だけをSceneへ追加。Transform/Collider/物理設定/ゲームルールは変更なし。
- 公開済みの現在果物/NEXTをdecisionへ記録。保持/NEXTは高さ/占有対象外、未知の未来果物は不使用。候補数・時間・係数はInspector/Pythonから設定可能。
- UDP plan_stepとUnityEnv.plan_stepを既存stepのaction_id予約/再送キャッシュへ接続。予測/実行の移動・待機・落下後加点を分離。開始直前のGO競合も正常終端へ対応。
- play_one_step_ai.pyは開始時reset1回、GO/手数上限/Ctrl+Cで停止。タイムアウトは結果不明として停止し、勝手にresetループしない。JSONLはoutputs/へ保存しGit対象外。
- Python52テスト成功。Unity評価回帰（空/平坦/空中/跳ね返り、GO除外/全GO/失敗混在）成功。短時間の実通信: 連続5手、続いて15手75候補で全候補の同一初期盤面/元盤面不変/成功、報酬保存、合体・加点、選択位置への実落下を確認。15手時の探索全体平均26.59ms、最大43.95ms、最終33点。この得点は性能評価ではない。
- 同一action再送で同一decision/果物ID、設定変更同一IDのconflict、従来step、9候補50更新、Reset後のaction_id再開を実通信確認。Editor GO fixtureを実プレイへ追加し15手目で正常停止、GO維持と明示Reset復旧、右キー移動/Enter落下を確認。
- 検証中の問題: Editorの旧Sceneには新規床参照が未反映→未保存変更なしを確認する補助で再読込。初期GO fixtureがPrefabへRigidbodyを付け忘れて例外→通常ReleaseFruitBodyと同様に生成するよう検証コードを修正し再テスト成功。修正後セッションで新規例外なし。テスト由来の古いConsole履歴は消していない。
- 未検証: 長期得点/自然GOまでの完走、全GO実盤面の順位の有用性、係数/候補数/時間の統計比較。STEP 4の接触履歴・Destroy/描画境界誤差は残る。予測GO=falseを安全保証としない。STEP 6以降未実装。
- 手順: docs/STEP5_USAGE.md。生のスモークログはPython/outputs/step5_smoke.jsonl、step5_contact_smoke.jsonl、step5_terminal_smoke_fixed.jsonl。失敗した初期fixtureのログもローカルに保持。


## 2026-10-21 STEP 6：高さ減点削除・独立ゲームの並列実行
- developの既存STEP 5未コミット変更を保持。H²を評価から削除しV=reward/55-2D²-.2Rへ変更。height/height_penalty=0を分析互換として保存、古いweight_heightは無効化。D/R・GO除外・全GOフォールバックを維持。P/B/NEXT戦略等は将来構想として保留。
- GameManager/ScoreManager/EvolutionDatabaseのstatic、Unity Random、Time.timeScaleを共有しないよう独立Windows Player方式を採用。SuikaWorkerOptionsでゲームID・専用UDPポート・seedを起動前に設定。バックグラウンド実行を有効化。固定更新/重力/Collider/ゲームルールを変更しない。
- SuikaWorkerBuildでgameDisplayのみを明示ビルド。Build Settings登録・Scene・Prefabを変更しない。初回44.34秒、更新10.79秒で生成。TMPの自動生成fallback atlasがビルドでクリアされたため、作業開始時にcleanだった当該assetだけ元の内容へ復旧。既存ソース変更を戻していない。
- play_parallel_ai.py/parallel_play.pyで1〜4プロセス、専用UnityEnv・game_id受信検査・ポート事前検査・明示エピソード数・Ctrl+C停止・起動した子だけの解放。JSONLはゲーム別に排他作成、毎イベントflush+fsync。observed_beforeと受付時decision_source、state、公開現在果物/NEXT、行動、reward、step間/末尾加点、終端/打切り/最終得点、既存reward_accountingを記録。途中GOはterminal_observationとして落下actionの二重記録を回避する。異常時は結果不明を記録して自動Resetしない。
- Python61テスト成功。Unity評価回帰（旧height係数100でも減点なし、GO除外/全GO含む）成功。実Player画面付き1ゲーム5手=1.55手/秒、2ゲーム合計10手=3.30手/秒、描画なし4ゲーム合計20手=6.04手/秒（起動待ち除外）。起動込みは.53/1.51/4.85手/秒。少数測定・seed/起動cache/描画条件差があり長期性能保証ではない。
- 1/2/4ゲームで状態・seed・果物系列・stream/episode/PID・UDPポートの分離を確認。保存ログで混入/重複なし・報酬保存。2ゲーム×2エピソード×5手=20手でも有限Resetと保存則を確認。Playerログに新規例外なし。従来Editorのplan_stepも実通信成功。
- 実Player2個で片方Reset後に他方のepisode/果物が維持されることを確認。中央35手/左端70手の短時間試験では自然GOは発生せず、自然GOを成功扱いしない。別途Editor GO fixture+独立Playerで片方GO→停止→Resetの分離を確認。収集器のGO最終得点/step間GOは自動テストで確認。自然GOを含むデータの長期検証はユーザー側へ。
- 手順/比較/データ仕様はdocs/STEP6_USAGE.md、保存検査はcheck_parallel_data.py。生ログ/Player生成物はGit対象外。モデル学習、Value Network、MCTS、AIモードは未実装。commit/push/追加バックアップなし。
- 追加終了テスト：実2PlayerでCtrl+Cと同じKeyboardInterrupt処理を発火し、各4手をflushしてstopped/打切りで終了。全ログ保存則・未完了episodeなしを検査し、子Playerが残らないことを確認。Burstビルドが自動作成したProjectSettings/BurstAotSettings_StandaloneWindows.jsonとCommonBurstAotSettings.jsonはビルド既定値として保持（物理設定ではない）。


## 2026-10-21 評価のD減点削除・音声制御・1ゲーム映像試作
- developの既存変更を保持。V=reward/55-.2Rへ変更。H/D診断は残し、両penalty=0、通常同点判定からDも削除。旧weight_dangerは互換入力として0化。GO除外・全GOフォールバックは維持。
- SuikaAudioでプロセス別ON/OFF。画面付きは00のみON、headlessは全OFF。OFFでは効果音を生成せず、既存効果音も停止。起動引数と既存UDP上の独立revision制御を追加し、Python制御ファイルの要求/応答を記録。受信所有者は従来のUnityEnvのみ、action_idやResetには干渉しない。
- 描画済み画面→RenderTexture→AsyncGPUReadback→最新1フレーム共有メモリ→独立Tkinter Viewer（1ゲーム、640x360、目標15fps）。headlessは動画コンポーネント/RT/readback/MMF/Viewerなし。実行中OFFでは進行中要求だけ完了させて解放。Viewer終了はゲーム停止につながらない。4画面・STEP7/8未実装。
- Python66テスト、Unity評価回帰、1ゲーム35手、音声/映像切替14手×2、最終目視20手、4ゲーム×2episode×3手=24手、通常ビルド2ゲーム×2手成功。ログで報酬保存・UDP/ID分離、OFF時RT=0/readback停止、音声OFF時生成省略、Viewer先行終了後のゲーム継続を確認。自然GO完走/聴感/GPU使用率/長時間安定性は未検証。
- 試作問題：WriteArray共有メモリ書込約8ms→一括stream転送約.16〜.28msへ改善。DX11画像の上下反転を目視で発見し、Viewer反転を外して修正、実画面の正しい向きを確認。初回Computer Useアプリ許可待ちがtimeoutしたが、再開後に目視成功。途中保存時の一時compileエラーは解消し、最終compile/build成功。Console履歴は消していない。
- 同seed/1ゲーム/5候補/25更新/8手の比較：旧headless1.092、新headless1.092、画面付き動画OFF1.082、動画ON1.399手/秒。旧/新headlessの選択/得点は一致。動画ONの後半盤面は分岐したため高速化の証拠としない。Player working setは119.09/119.24/173.37/179.16MB。切替テストViewer CPU5.66%（1コア比）、最大38.16MB。GPU未測定。
- 最終目視303フレーム、更新中14.40fps、撮影→Tk設定平均44.78ms/p95 65.68ms。モニター発光遅延ではない。4画面へ段階拡張する候補としてAを提案するが、実装にはユーザー確認が必要で、4画面性能は未測定。
- 通常Step6と試作用Step6Preview Playerをビルド。ビルドによるTMP自動生成差分だけ作業前の内容へ復旧。Scene/Prefab/物理/GO比率.862は今回未変更。既存データ削除/バックアップ/commit/pushなし。
- 詳細な関数/行番号、実行/停止/制御コマンド、負荷比較、制約はdocs/PRESENTATION_PROTOTYPE.md。生ログはPython/outputs/preview_*。


## 2026-10-21 最大4画面デバッグViewer
- developの既存変更を保持しPythonのみ拡張。--view-gamesで表示数を実行数から分離。固有video_maps、1/2/3〜4枚の1画面/横2分割/2×2、Game ID/得点/GO/遅延表示。従来--view-game/--map/音声コマンドを維持。
- Viewer音声ON/OFFボタンは既存制御ファイル経路を使用しGame00以外を制御。測定サンプルを各4096件に制限。不正な複合制御要求の部分適用を防止。headlessでは新規RT/readback/Viewerなし。Unity/評価/物理/GO比率変更なし。
- Python71テスト成功。実4画面をComputer Useで確認、音声ON/OFFは他3ゲームのack確認。4ゲーム各16手×3条件=192手と目視各30手=120手、保存則・混入/重複なし、新規Player例外なし。表示1枚の非表示3ゲームで取得数/RT=0。Viewer先行終了後のゲーム完了/保存も確認。
- 合計手/秒：headless4=3.638、1枚=3.660、4枚=3.549。4枚は各13.92〜14.31fps、平均遅延40.62〜45.89ms。Viewer単体4枚CPU33.92%（1コア比）、最大54.26MB。GPU未測定。後半の盤面/選択が分岐し、速度差を純粋な表示コストや統計的劣化とは断定しない。
- 詳細/変更関数行番号/測定条件/起動・停止・再接続・再測定コマンドはDEBUG_VIEWER.md。自然GO/長時間安定性/他GPU/自動縮小/手数表示は未確認または未実装。STEP7/8、commit/push/追加バックアップなし。


## 2026-10-21 STEP7-A: offline Value Network
- developの既存変更を保持。value_data/model/train/checkpoint、value_network CLI、設定/専用requirementsを追加。Py3.12 .venvへtorch2.6.0+cpu、numpy2.2.3、matplotlib3.11.2。既存システムPythonは置換せず。
- 実GO完了episodeの実行後actual stateのみ、target=final-score。未完了/打切り/fixture等を除外、自然加点保存則・重複検査。未知・欠損をknownフラグで処理し、候補予測/ID/seed/最終得点を入力から排除。旧ログの外部fixture有無は独立証明できないという由来制約も保存。
- 24episode/3129状態（旧D方針）、train19episode2456状態seed12345/12346/12348、validation5episode673状態seed12347。30次元fruit→64→64→masked mean/max＋37次元global→128→64→Softplus、35713params。0/300果物・順序不変・未知NEXT対応。
- MSE/AdamW .001/batch128/FP32 CPU。実データ12更新で保存して終了、別プロセスでepoch途中から20epoch400更新まで再開。best epoch4検証MAE143.36/RMSE171.62、train平均定数baseline273.12/324.40。latest epoch20検証RMSE224.78へ悪化し過学習を記録。1seed検証で汎化保証なし。
- checkpointはoptimizer/scheduler/epoch/updates/order/cursor/各乱数/入力仕様/分割/データhash/設定/検証値を保持。世代保存とatomic latest/best、SHA256、破損fallback。78テスト、連続と中断再開の重み/optimizer/乱数一致、ptとpointer破損復旧、pip check成功。
- CPU推論（特徴作成込み）中央値1盤面.721ms、5盤面2.409ms、p95 1.165/3.753ms。実ゲーム5候補探索や通信は含まない。全曲線/比較/episode誤差をoutputs/へ保存。
- --seed autoと独立episode収集をPython側へ追加。既定のUnity継続RNG/Resetは変更せず、明示モードだけPlayerを各episode再起動。2ゲーム×2episode×2手を同seedで2回、保持/NEXT系列と保存則を確認。長時間収集なし。
- 手順/不足/関数行番号はSTEP7A_USAGE.md。Unity/物理/Collider/GO/評価式/Viewer/音声変更なし。学習モデルのゲーム接続、予測時間変更、MCTSなし。commit/push/追加バックアップ/既存ログ削除なし。


## 2026-10-21 Viewerのプレイ中切り替え
- video_viewer.py: ViewerLayout/show/toggle_fullscreen/leave_fullscreen/renderとfitted_sizeを追加。一覧/ゲーム別ボタン、ダブルクリック、F11/Esc、縦横比を保った拡縮。表示対象外の映像変換/描画を省略し、ゲーム操作・Reset・音声設定には触れない。起動時に映像設定したゲームだけ選択可能。
- tests/test_viewer_layout.py追加。実Tkウィンドウで4枚→各1枚→4枚、全画面/解除、画像の表示領域内サイズを検証。Python全80テスト成功（短時間）。今回の実ゲーム連携/負荷の再測定は未実施。撮影/共有メモリ転送は非表示でも継続。操作方法はDEBUG_VIEWER.md。
- develop既存変更保持。Unity/物理/AI/学習処理変更なし。commit/push/追加バックアップなし。
- 追加確認：4つの合成映像を実際の共有メモリからViewer本体で読み取り、1枚/一覧/全画面切替と終了まで成功。実Unity映像の再検証ではなく、性能・遅延測定にも使用しない。


## 2026-10-22 STEP7-B：本格収集の準備
- developの既存変更を保持。観測専用UDPTrainingMetadataを追加し、現在接触（HasCollidedとは別）/sleep/保持Y/取得時刻/合体中件数/Collider boundsと実効physics profile IDを保存。固定環境/全種assetとruntime形状・質量・慣性等はmetadata/game_XX.jsonへ集約。solver内部cache/未知の抽選/RNG stateは含めない。
- ユーザー承認とScene保存後、GO比率0.83を確認して既存EditorでSTEP6 Playerをビルド（17.54秒）。最初のbatch試行は既存Editor検出で拒否。既存Editor/実行ゲームは終了させず。ビルド生成TMP差分のみ開始時へ戻した。
- event schema2/metadata1/run4/collection2。旧ログ互換、必須metadata/GO比率照合、実seed確認、JSON null環境placeholder拒否、プロファイル参照と環境hash、得点保存則/終端ラベル検証を追加。audit_collection.pyで完了数・全得点・平均/最高・操作数・教師状態数・seed重複/欠損を集計。
- 変換は自然GOのactual post-action状態のみ、final-score教師。seedと先頭8果物系列の連結グループで70/15/15を準備。固定dataset/環境catalogを保存。Testは学習/early stop/best選択から除外し、明示した最終評価のみ。旧モデルとの外部Test比較はseed/episode/既知系列の重複を拒否。NN構造/入力次元/既存checkpointは維持。
- Python90テスト成功。旧value_seed_test01は8GO/1043状態/平均945.375/最高1201、重複seedなし。旧ログ互換として6/1/1episode（782/124/137状態）へ変換。新0.83での再学習ではない。
- 新Playerの短時間headless/独立seed/4映像テスト成功。742110〜113の保持/NEXT系列が2回で一致し、まとめた監査で4seed重複を検出。新runは打切りで教師0件。ON/OFF同seed各2ゲーム8手は2.376002/2.375650手毎秒、選択/得点一致、同ID位置差最大.22723world。非同期進行のため完全な同条件/bit一致とは主張しない。
- 実4画面とGame02選択はComputer Useで確認。実映像F11はウィンドウが利用不能となり未確認、F11/EscはTk自動テスト成功。Viewer/音声は未編集、Player新規例外なし。失敗した空メタデータ調査runも削除せず保存。
- 本格収集/実データ再学習/7-C/MCTSは未実施。100/200ゲームの起動・停止・監査・変換・将来の再学習/評価方法、全変更関数/限界はSTEP7B_USAGE.md。結果報告後に再学習を判断する。commit/push/追加バックアップ/既存データ削除なし。


## 2026-10-22 STEP7-B：100ゲームで再学習・性能評価
- user収集value_collect_100_01を再監査：100自然GO、途中0、平均884.39/最高1591/最低335、12501操作/状態、100seed重複なし、全GO=.83/current score-.2R/5候補/25更新/保存則正常。旧データ混合なし。
- value_data_100_01へ70/15/15episode（8705/1825/1971状態）を固定分割。35713param/30fruit+37global DeepSets仕様を維持し、CPU FP32/MSE/AdamW .001/batch128/seed2026で新規学習。
- 主モデル1update保存→終了→別プロセスresume成功。best Val MSE epoch3/update207、early stop23/update1587、172.95秒。best train MAE136.78/RMSE185.33、Val170.28/222.25、Test161.41/212.28。定数baseline Test297.05/353.13。latestのVal RMSE251.48まで悪化し過学習を確認、bestを採用。
- 得点のみ比較を同構造/教師/分割/設定で事前定義しVal選択（best7、early27、21.51秒）。両best/hashを固定してからTestを開き、以後retuneなし。得点のみTest187.24/235.85。15group bootstrap3000回のNN MAE95%CI116.91〜213.45、得点のみからのMAE改善CI2.34〜47.41点。
- 盤面入替でMAE168.28→177.23、順序反転差.000061点、unknown NEXT161.58。GO前非GO60状態は教師平均11.23→予測108.44、+97.20点の過大。7-CではGO除外を維持し、NNをGO判定に代用しない。
- CPU特徴生成込み中央値1盤面.686ms、5盤面2.233ms（物理/通信除く）。analyze_value_performance.py/testsを追加、全94テストと保存再開回帰成功。既存ML/ゲーム/物理/Viewer/音声/依存は未変更。旧checkpoint保持。
- 全seed/曲線/誤差/固定モデルhashはvalue_assessment_100_01。詳細STEP7B_TRAINING_REPORT.md、7-C設計STEP7C_DESIGN.md。Unity内CPU評価を第一候補とし、予測snapshot整合・出力parity・GO/fallback・未使用seed比較を先に要求。7-C実装/ゲーム操作/追加収集/commit/pushなし。


## 2026-10-22 STEP 7-C

- epoch3/bestを保存したままC# CPU Deep Setsを接続。heuristic/value選択、5候補Q=予測報酬+終了盤面V、GO除外/既存全GO fallback維持。実/予測の接触・sleep・Collider・保持Yを共通測定、未来NEXTは未知。
- Python98 tests、Unity24 golden/選択probe成功。実730候補のPython出力最大差.000122点、欠損0。未使用seed1組はheuristic1071/152手、value1091/146手、両自然GO・系列/報酬整合。終盤過大評価平均69.68点が残り、N=1では強さの結論を出さない。最終build後の4ゲーム×8手/Viewer4→1画面確認、例外0。自然GO比較は直前build、最終buildは短時間のみ。
- 新規比較/再集計・推論一致コマンドと制約はSTEP7C_USAGE.md。GO=.83/post25維持。追加学習・commit/pushなし。


## 2026-10-22 STEP 7-C 50組比較の集計修正

- Selected drop X mismatch18件（heuristic5/value13）は予測が落下前GOでapplied_x未設定0だったことが原因。両側落下済みだけを比較し、実際の命令/目標/範囲/落下位置検査は維持、閾値1e-5は変更なし。真の不一致はペア除外。別report-dirへ新規保存し既存結果の上書きを拒否。
- 保存済み100自然GO/12499手を監査。有効50組、除外0、報酬/seed/果物系列/環境整合。平均heuristic872.14/value850.56、差−21.58、seed-paired bootstrap95%CI[−118.60,+67.56]。高得点化の証拠は得られず。GO見逃し24/18、過剰予測3/8、step間GO各1は別記。
- 結果: Python/outputs/value_compare_50_20261022_164130_analysis_01。全18件・全50組はSTEP7C_COMPARISON_50_REPORT.md。ゲーム再実行・Unity/モデル変更・commit/pushなし。

- 最終検証: 新規回帰13件を含むPython111 tests成功。真の不一致ペアが両AIの平均/勝敗/CIから除外されることも確認。


## 2026-10-22 STEP8-A 2手先基盤

- native PathSessionで2手を連続実行。rootから短いprefix再生で枝を分離、公開NEXT以降はfruits[]一様slot分布で分岐。2手得点/heuristic/Valueのleafを選択可能。既存heuristic/value維持。Wall列挙のScene混入を修正、物理/GOルールは未変更。
- 実ゲーム比較はpost/idle更新を実測して整合。空盤面は両手一致。接触合体盤面は得点/種類/個数/GO一致するが最大2手後位置.036625・速度2.409224差。コピー直後の接触差、tick1から数値差を確認。完全一致未達。
- Python115 tests/native26 checks/既存Value golden成功。実9果物20経路171.84ms、Unity割当観測増加6.22MiB。prefix一致、source/RNG不変、Scene解放後0。4ゲーム×2手＋Viewer確認。詳細STEP8A_IMPLEMENTATION.md。
- 本格MCTS/長時間比較/学習/commit/pushなし。GO付近の追加追跡とframe/tick境界検証を次の優先事項とする。

- 最終通信確認: JsonUtilityのnull入れ子が通常観測へ約10KBの空診断を出す点を修正し、必要応答だけに付加。step8a_wire_smokeで診断・3leaf・従来mode成功。接触2手後位置差.033230/速度差.054157、先行試行の大きい誤差も報告書に保持。


2026-10-22 STEP8-B: PathSessionによるstochastic UCT初版（mcts/mcts_value）。反復/深さ/UCT係数設定、明示的chance/rollout/点単位backprop、GO除外/既存fallback、未知NEXT/隠れRNG非参照、末端cache。rewardのみ未落下Cをまとめ、2手20→4経路。Python118、native MCTS858 assertion、既存Path26、Value parity24、実UDP全5mode各2手、4ゲームx4手の整合性を確認。物理の2手接触位置差最大0.167343、自然GO正例不足で見逃し率未評価。大規模実験/commit/pushなし。詳細STEP8B_IMPLEMENTATION.md。

STEP8-B追加検証:64回/深さ4の実UDPを1手だけ実行、111,601byteのplanning分割応答を正常受信、64訪問と落下X一致を確認。step8b_large_reply/result.json。


2026-10-22 STEP8-C: Viewer停止を実測。同期MCTS中は実FixedUpdate/frame/UDP/video増分0。最終5条件56手（各phase2回/worker）、密集35果物でMCTS32/depth4は1game約830ms、4game約1057ms、headless約1057ms。Viewer PhotoImage再利用（copy単体中央値12.77→10.25ms）/画像年齢表示とopt-in計測を追加。2手traceで保持grapeのCOM/inertia固定を特定、予測preview copyだけ修正し空起点2手接触誤差0.167343→0。既存接触/GO誤差は残る。自然GO再構成で同tick52のGO不一致、標準25窓ではpred53/actual52の1tick差を確認。りんごtag fruitは両側GO対象外、ルール維持のため未修正。Python121/NativeMCTS861 assertion/Path26/Value parity24通過。最短drop設定.4秒、既存命令の観測間隔.404123秒。タイミング自由化/非同期は設計のみ。STEP8C_REPORT.md/STEP8C_TIMING_DESIGN.md参照。commit/push/長時間収集なし。


## 2026-10-22 STEP8-D
- 内訳計測後、GO対象参照のcache/条件順、ReadBoard一回走査、MCTS未使用出力省略のみ最適化。物理tick・乱数・探索順・GO条件・モデルは維持。
- 35果物32/d4、詳細計測なし中央値: 1ゲーム933.02→839.49ms、4ゲーム1240.89→1092.41ms。全盤面MCTS240＋Value8のフル状態A/B一致。
- Python125件、native MCTS861項目/Path26項目、Value parity24ケース成功。実通信72手の成功落下・得点保存則を確認。
- 同期メインスレッド停止/接触cacheの予測限界は残る。全体手数/秒向上は短時間実通信では実証せず。りんご小文字fruitタグは報告のみ。GPU/並列探索/非同期/タイミング行動未実装。commit/pushなし。詳細STEP8D_REPORT.md。


## 2026-10-22 STEP8-E
- りんごPrefabのfruit→Fruitだけ修正。GO比率.83/接触/Update条件/物理/Colliderは不変。rules_version=step8e-all-fruit-go-v2とPrefabタグを環境metadataへ追加。旧ログ/モデルは保持し新実験と区別。
- heuristic vs MCTS32/depth3/5候補/post25のpaired実験と監査・bootstrap CIを実装。既存座標検査を再利用、MCTS落下前GOのtarget_xログを補正。実合体数/最大果物/ゲーム実時間を追加記録。
- 自然GO smoke1組: H771/116手/130.016秒、M1400/164手/177.407秒。公開系列118一致、有効1除外0。n1で強さ判断/CIなし。HのGO見逃し1件、M0、過剰予測0。1手打切り負例は有効0/除外1で正常除外。
- Python135、ルール84/nativeMCTS861/Path26、Value parity24ケース成功。最終Playerビルド済み。10組実験はユーザー担当、Codexでは未実行。commit/pushなし。詳細STEP8E_REPORT.md。


## 2026-10-23 STEP8-F：フレーム分割＋将来tick予約（1ゲーム試作）

既存同期MCTSの同じループを分割し、ライブ物理/描画/Viewerを継続。将来Tへの無入力投影・凍結ルート複製・T+1でのゼロ許容差照合・2試行後の明示heuristic fallback・Reset/GOキャンセルを実装。ルールv2/GO0.83/25更新/既存モードを維持。
最終短時間試験は固定4要求中2採用（35果物2要求は失効しfallback）、連続4手は全てMCTS採用。自然加点6点をbetween_stepsに一度だけ記録。同期の最大Update間隔678/807msに対し新方式82/82ms、Viewer約14fps。ただし初期試作で待機中の単発1.55秒停止あり原因未特定。
Python139、native44+861+84+26成功。NEXTの無効ゼロ質量getter対処、自動慣性差7.45e-9/重心差1.86e-9の記録。接触盤面の投影誤差（最大位置0.0536/角度21.14度）と採用率は未解決。完成扱い・4ゲーム全面導入・長期性能比較はしない。commit/pushなし。詳細STEP8F_REPORT.md、結果Python/outputs/step8f_01。


## 2026-10-23 STEP8-G：予約待機の計測とadaptive試作
150tick予約が完成後約2.8ゲーム秒の待機を生むことを確認。Aのみ明示opt-in frames_adaptiveを追加。全反復・厳密照合を保持し、接触有無別の直近8探索から予約時間を校正。連続4手の実drop間隔平均6.141→2.340秒、ただし採用3/4→2/4で標準化しない。密集2要求は両方式採用0/2、要求待ち9.74/9.86→4.44/2.95秒、最大Update166msで82ms維持も未達。1.55秒停止は未再現。Python140/native1021/Value parity24・Playerビルド成功。B/C、許容誤差拡大、ゲーム/物理/モデル変更、長期比較なし。次は物理tick単位の中断と失効/候補再評価設計を優先。詳細STEP8G_REPORT.md、結果Python/outputs/step8g_01。commit/pushなし。


## 2026-10-23 STEP8-H：物理tick単位の中断（実験指定）
RunTicks/AdvanceSearchTicksで同一物理ループを中断・再開。frame_tick_slicing既定false、sync/従来frames維持。9固定条件（序盤/15/35果物×深さ4/5/6）で選択/UCT木/tick/系列/得点/GO/state digestが同期一致。密集の最大再開区間13ms前後→3.49/4.05/4.22ms、能動計算807/932/940ms。ライブ最大Updateは深さ4/5/6で79.65/120.97/245.54ms、別追加試験335.65ms（同期fallback286.71ms）で50ms未達。連続4手の採用は旧新とも3/4、実drop間隔平均6.039→6.111秒、操作遅延・失効は未解決。Python141/native1029/Value parity24、最終Build成功。次の方式はAのpost25観測待ちとの探索重複を設計し、fallback/開始準備の分割は別検証。標準化・4ゲーム展開・commit/pushなし。詳細STEP8H_REPORT.md、結果Python/outputs/step8h_01。


## 2026-10-23 STEP8-I：盤面依存5候補（実験指定）
grid既定を保持し、sync MCTS32/深さ4/5個/post25のboard-fiveを追加。実Colliderによる同種の上面/上部隙間から左右各1点、端と中央は維持。ノード再訪で配列を固定し、候補X/由来/生成時間を記録。変更前gridの4固定盤面・全20候補の選択/評価/得点/GO/物理tickを一致確認（変更前の全内部木は未保存）。密集で候補.349260へ変化、生成計0.63〜4.66ms。診断x.125の2手で15点に対し固定同位置系列は最大3点だが新候補は.125を拾えず、標準化しない。実通信各8手は双方26点3合体、座標差最大2.384e-7、報酬保存成立、自然GO0件で強さ比較から除外。Python150/native1029/幾何テスト/Value parity24/Build成功。1ゲームずつのpaired比較スクリプトを準備。物理/ルール/モデル/リアルタイム方式変更・4ゲーム新方式展開・commit/pushなし。詳細STEP8I_REPORT.md、結果Python/outputs/step8i_01。


## 2026-10-23 STEP8-J：固定9候補の全階層検証
既存grid count9を利用しMCTS本体変更なし。診断probeに5/32・9/32・9/64指定を追加。密集.125→.125は84tick/15点1合体再現、ただし32/64探索ともそのprefix訪問0、最終1.0。全12固定探索のroot保持/全階層grid確認、従来5の4盤面木/選択/tick一致。実通信同seed各8手15点1合体、報酬保存/座標一致、自然GO0で強さから除外。Python155/native1029/Build成功。新compare_grid_aiで1Playerずつ自然GOペア比較を準備。既定5保持、標準採用せず。物理/GO/モデル/UCT変更なし、commit/pushなし。詳細STEP8J_REPORT.md、結果Python/outputs/step8j_01とstep8j_smoke_01。


## 2026-10-24 STEP8-K：2手全探索による探索漏れ診断
同期MCTSの変更なし。診断probeで81通りをfresh rootからprefix再生。既知.125→.125は15点1合体、最善.5→0は18点2合体で固定5にも存在。MCTSの.125再訪は全て新chanceのため第2手以降random rollout、32/64とも既知prefix0件。一方.5→0はMCTSも試しており4手平均と2手最大は別。全探索1.177秒/153 Advance/7086tick、root再構築148ms・1手508ms・2手444ms。実通信各2手で15/18点と1/2合体再現、自然GO実験なし。Python164/native1029/Build成功、MCTS3条件の前回木/選択/tick一致と6基準ソースhash保持。次は軽量heuristic混合rolloutを別条件として検討し、同予算の自然GO比較を優先。標準5/sync維持。詳細STEP8K_REPORT.md、結果Python/outputs/step8k_01。commit/pushなし。


## 2026-10-24 STEP8-L：軽量幾何rollout（明示opt-in）
random既定・旧乱数順序を保持。Collider包絡の同種整列G−GO近傍Dでguided90/mixed50、共通chance表で比較。5/32密集GOサンプル13→5/12、全体825→850/824msだが18点prefix5→2/2。9/64の15点prefixはrandom3回、B/C0回。各4手実通信は10点対0点で自然GO0、強さ比較から除外。Python170/native1029/幾何テスト/Build成功。legacy3盤面のtree/選択/tick一致、標準化なし。次はchance分散へOpen-loopを診断限定で別設計する案。詳細STEP8L_REPORT.md、結果Python/outputs/step8l_01、step8l_smoke_01。commit/pushなし。


## 2026-10-24 STEP8-M：公開果物条件付きOpen-loop診断
保持/NEXTをキーに保ちaction履歴で共有するpublic_open_loopを明示opt-in。状態別GO/transition照合、Bの異状態leaf cache無効、fresh native prefix再生。3固定盤面32/depth4ではA_common/Bの全経路/tick/訪問同じ、共有0、B約5〜7%増で標準化しない。保持/NEXT区別・GO隔離・同キー異なるnative盤面の情報試験成功。各4手実通信は両0点、自然GO0で強さ集計から除外。Python179/native1029/Build成功、legacy3盤面一致。ユーザー実施rollout10組も再監査し全有効、random2163.5対guided1875.5、差−288/95%CI[-554.1,-8.2]。次は新chance生成をdecision Expansion枠から分離する1軸実験を推奨（未実装）。詳細STEP8M_REPORT.md、結果Python/outputs/step8m_01とstep8m_smoke_01。commit/pushなし。


## 2026-10-24 STEP8-N：chance後decision追加展開
legacy標準を保持しchance_decision opt-inを実装。1反復で最初の新chance後に最大1decision追加。5/32/深さ4共通chanceで登録edge17→51、2座標再訪は増えるが非root同一edge再訪0で高得点化未証明。密集836.7→910.8ms、5987→6461tick。9/64の15点prefix両3回。各8手UDPは両25点/2合体・保存則/座標成功、自然GO0で強さ集計から除外。Python189/native1029+展開境界/Build成功、旧A6条件一致。標準採用なし。次はchance維持の初展開配分を1軸診断する案。詳細STEP8N_REPORT.md。commit/pushなし。


## 2026-10-24 STEP8-O：未訪問action順序の独立seedシャッフル
index標準/legacy expansion保持。node生成時Fisher-Yates、chance/rollout乱数と分離。3盤面×3seed比較で非root初展開histogram[82,27,7,0,0]→[20,27,30,17,27]、深い同一edge再訪は両0。密集平均探索報酬27.04→19.96、GO40→49/96で高得点化未証明。各8手通信は17点/3合体対16点/2合体、座標/報酬保存成功、自然GO0。Python198/native1029+順序試験20seed/Build成功、index旧6条件・shuffle3盤面再実行一致。標準化・10組自然GO比較は見送り。次はroot候補と共通chanceを対応させる層化評価の単独設計を推奨。詳細STEP8O_REPORT.md。commit/pushなし。


## 2026-10-24 STEP8-P：root限定Coarse-to-Fine
coarse-root試作は粗5を1手評価し全anchor保持+2中点、root7/将来5。3盤面×3seedでgrid5/grid9/C比較。中盤追加.125選択例あり、密集平均探索報酬27.04/24.08/27.80、全体811/735/833ms（C生成41ms含む）で一貫した高得点化未証明。密集Cは.125不採用かつ将来5で15点系列不可、18点prefixは維持。各8手通信は両9点/2合体・座標/報酬監査成功、自然GO0で除外。Python204/native1029+候補試験/Build成功、既存12条件・C3再実行一致。標準grid5維持。次は少数の公開NEXT2手probeで選別信号/コスト検証する案。詳細STEP8P_REPORT.md。commit/pushなし。


## 2026-10-24 STEP8-Q：公開NEXTの25経路診断
診断専用SuikaNextPairProbe追加、既存探索/Coarse-to-Fineは不変。密集の各初手最大0/15/18/18/15、.5→0=18点/2合体再現。他2盤面は全0でR依存残る。密集.5/.75はpost25後に待つだけでpost50相当までに追加3点/1合体。25経路349ms+MCTS780ms=1128ms（約45%増）で前処理採用・C統合なし。全25を独立再生、公開B/非公開C不変/源盤面・score・tick保存を検証。Python212/native1029/Build成功、MCTS3盤面一致、既存11ソース不変。次は32反復内の2手組合せ被覆配分を別設計する案。詳細STEP8Q_REPORT.md。commit/pushなし。


2026-10-24 STEP8-R：時間整合性4条件×4時点の得点/合体一致、遅延+3を追加落下効果と区別。通信間の追加1〜5tickは連続予測に含まれない制約。32反復内15回2手被覆を比較用実装、密集2手系列17.33→19だが深さ4到達25→22.33/非root edge再訪0、標準採用なし。Python219/Unity1029/互換再現15件合格、各8手UDP成功。自然GO長時間比較は見送り。詳細STEP8R_REPORT.md。


2026-10-24 STEP8-S：既存MCTSの32/64/128/256回逐次自然GO比較・ゲーム単位再開ツール追加。入力上限だけ256へ拡張、アルゴリズム不変。固定3盤面×4条件×3回、旧32互換9件/全反復再現合格。密集平均828/1638/3216/6618ms。各8手UDPで公開果物列一致・監査合格、自然GO強さは未判断。Python233/Unity1029合格、標準32/深さ4維持。ユーザーはまず新seed各3ゲームの予備比較（STEP8S_REPORT.mdのA）、結果後に2条件10組を選定。commit/pushなし。


2026-10-24 STEP8-T：旧8-Sは自然GO6/20、seed75940364回150手stopped。旧Player152ファイル不変、必要な互換Python/C#106ファイルをcompat/step8s_20261024へ保存し旧再開preflight合格。新Step8T Playerへ分離、誤上書きguard追加。既定OFFの時間/段階追加/全decision候補追加を実装。32回3盤面の全state digest互換、adaptive継続prefix/候補追加再現合格。時間1秒超過1.35〜15.32ms、密集256でroot4+非root4追加。5モード各8手UDP成功、Python245/Unity1029+制御selftest合格。自然GO高得点化は未検証、標準fixed5/32/depth4維持。詳細STEP8T_REPORT.md。commit/pushなし。


2026-10-25 STEP8-U：旧8-Sは16自然GO/8ペアをhash・元ログ監査、32平均1792.125対64平均2179.375、差+387.25/paired bootstrap95%[-40.25,793.875]、64が6勝2敗で断定せず残4件は再開しない。別Step8U Player、128/深さ4のlegacy/grid9/widening逐次比較と実ゲーム専用スイカ/同時存在/ダブル観測を追加。固定3盤面×2回再現、密集判断3917/3963/4093ms、widen root3追加/非root0。記録ON/OFFの実衝突trace/110点一致、double1回記録。各8手UDP67点/5合体、自然GO0で強さ評価から除外。既存32全state digest一致、旧Player/compat411ファイル不変、Python255/native1029+event parity合格。新9ゲームはユーザー実行。標準変更・学習・commit/pushなし。詳細STEP8U_REPORT.md。


2026-10-25 STEP8-W：拡張予算opt-inで32〜32768回/最大120秒/深さ2〜256、同じ木の段階追加とsoft deadline、32未達no drop、各手開始前auto深さ2〜8（既定OFF）を追加。要約出力/深さ別訪問・再訪・rollout記録。旧32と3盤面全state digest一致、adaptive継続prefix/早期128終了/2秒超過1〜10ms確認。auto4→3→3→3とadaptive各4手UDP成功、Python260/native1029+境界テスト合格。手動16は序盤32反復のみ、256/32768完走/120秒負荷/自然GOの強さは未検証。旧Player456ファイル不変、標準変更なし。変更前60656eeをdevelopへpush。詳細STEP8W_REPORT.md。


2026-10-25 STEP8-X：比較用budgeted widening（訪問32/128・残予算・安全候補4訪問・5→7→9）とadaptive早期停止保護、4条件逐次比較/再開ツール追加。旧32回全探索3盤面一致、Python265/Unity1029+新selftest、各4手UDP成功。高得点化未確認、標準legacy維持。旧Player608ファイル不変、commit/pushなし。次はユーザーの3seed自然GO予備比較。局所高評価位置の重点細分化は今回と分離して検討。詳細STEP8X_REPORT.md。

2026-10-26 STEP8-AA：比較用importance予算配分を追加。複数checkpointと候補の同等性/不確実性・GO重要性を分離、Budgeted Widening連携。別Player Step8AA_02、旧760ファイル保護、272 Python/1029 Unity checksとGUI3手確認。高得点化・自然GO比較は未実施。詳細STEP8AA_REPORT.md。

2026-10-26 STEP8-AB：長時間劣化の原因を予測Scene非同期解放バックログとして再現。専用worldを同期解放、予測material/参照を解放。metadata要求ID/排他と任意GUI保持を追加。55手/120秒2回/GUI3手、278 Python/1029 Unity、96終端物理状態一致、旧1214ファイル保護。新Player Step8AB_02、詳細STEP8AB_REPORT.md。自然GO全編は未検証。


2026-10-26 STEP8-AC：長期価値のオフライン基盤を試作。自然GO110ゲーム/23,089状態/39seed群、Train77/Val17/Test16ゲーム。配置57特徴Deep Sets＋順位補助lossのTest MAE265.45、同データ従来構造再学習276.30、得点/個数ridge272.84。新旧再学習のseed-macro差95%区間は0を含み、GO直前過大評価とダブル教師0件が残る。実ゲーム/標準MCTSへ未接続。Python285テスト成功、Unity変更/収集/commit/pushなし。詳細STEP8AC_REPORT.md。


2026-10-27 STEP8-AE：収集専用fixed同期MCTSの240秒上限、2枠のゲーム別設定/seed選択・補充・時間停止・再開・監査、観測専用スイカ位置記録を追加。旧Player保護、新Step8AEへ別ビルド。Python295/Unity1029＋イベント物理一致、実通信20手でエラー0/Scene残留0。実時間240秒探索・一晩収集は未実施。旧MCTS/importance/AB解放維持、commit/pushなし。ユーザーはSTEP8AE_REPORT.mdの8時間コマンドで開始。
