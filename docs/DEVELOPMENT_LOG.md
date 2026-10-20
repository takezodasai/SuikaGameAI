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
