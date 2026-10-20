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
