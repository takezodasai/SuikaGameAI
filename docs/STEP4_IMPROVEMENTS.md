# STEP 4改善報告（2026-10-21）

STEP 5は設計のみ。ゲームオーバーの条件緩和や余分なSimulateは行わず、物理設定/ゲームルールを維持。現在までの手動調整・既存の未コミット変更も保持する。

## 変更ファイル・関数と行番号

- [Unity/Assets/Scenes/Script/PredictionDiagnostics.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/PredictionDiagnostics.cs:52) — `Recorder.Capture / Begin / Compare`、52行から。旧：物理更新直後の確定フラグだけを比較。新：同一時点のGO条件成立を別に記録し、最初の成立Frame・接触済み差・step完了時の確定フラグも残す。判定式/物理更新順は変更しない。
- [Unity/Assets/Scenes/Script/UDPStateProtocol.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/UDPStateProtocol.cs:178) — `BeginEpisode / SendPacket / ResetRewardAccounting / BeginRewardStep / EndRewardStep / ReadRewardAccounting / CaptureEpisodeRewardSummary`、178行から。旧：step外の加点区間なし。新：時刻/物理時刻/得点境界を持つ非重複区間と累積集計。Readは副作用なし。reset前に旧集計を保存。
- [Unity/Assets/Scenes/Script/UDPStepProtocol.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/UDPStepProtocol.cs:168) — `HandleStep / CompleteStep`、168行から。旧：stepScoreBeforeからの差分のみ。新：受付でgapを閉じstep区間を開始、完了でstepを閉じる。再送分岐は開始処理を通らず、完了返信も凍結キャッシュ。診断完了後に報酬区間を確定。
- [Unity/Assets/Scenes/Script/PlayerDropPlacement.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/PlayerDropPlacement.cs:11) — `EffectiveAIMoveSpeed / NormalMoveInput`、11行から。旧：aiMoveSpeed=2.5が独立。新：既定で通常キー入力係数×Speedに追従。チェックを外す場合だけ従来のAI個別設定を使用。
- [Unity/Assets/Scenes/Script/PlayerController.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/PlayerController.cs:97) — `MoveLeft / MoveRight`、97行から。旧：入力係数±0.5の数値。新：同じ値の共通定数±NormalMoveInput。通常キーの移動量は変更しない。
- [Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:193) — `Predict / Run`、193行から。旧：aiMoveSpeed参照と確定フラグ相当の診断。新：EffectiveAIMoveSpeed参照、ゲームオーバー高さを持つRecorder。接触履歴を捏造する物理更新等は追加しない。
- [Unity/Assets/Scenes/Script/GameManager.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/GameManager.cs:92) — `ResetGame`、92行から。旧：そのまま得点を初期化。新：初期化前に旧エピソードの報酬集計を保存。Update/CheckGameOver/GameOverの条件・実行順は今回変更なし。
- [Python/src/suika_ai/unity_env.py](C:/SuikaGameAI/Python/src/suika_ai/unity_env.py:59) — `parse_state / validate_reward_accounting / step`、59行から。旧：数値観測とstep報酬のみ。新：区間差分、時間順序、得点保存則、エピソード整合性を検査しinfoへledgerを渡す。rewardの返り値はstep中の差分のまま。
- [Python/src/suika_ai/prediction_evaluation.py](C:/SuikaGameAI/Python/src/suika_ai/prediction_evaluation.py:221) — `reward_accounting_summary / summarize`、221行から。旧：step外報酬の集計なし。新：エピソードごとの最新累積値だけを採用。繰り返し観測の累積値を加算せず、進行中のstep/gapも別項目として集計。
- [Unity/Assets/Editor/DropCooldownProbe.cs](C:/SuikaGameAI/Unity/Assets/Editor/DropCooldownProbe.cs:147) — `CooldownPredictionProbe.Tick / Step4ContractProbe.Run / Tick`、147行から。待機・合体後のledgerを検査。手動の実FixedUpdateの移動量とAI速度、ライン上の異種果物衝突によるGOの成立/確定フェーズを検査。
- [Unity/Tools/Test-UdpLifecycle.ps1](C:/SuikaGameAI/Unity/Tools/Test-UdpLifecycle.ps1:45) — `回帰テストと最小stub`、45行から。実際の通信/ledgerをコンパイルして、gap、step、進行中加点、二重読取、resetを検査。
- [Python/tests/test_reward_accounting.py](C:/SuikaGameAI/Python/tests/test_reward_accounting.py:22) — `RewardAccountingTests`、22行から。新規。欠落/二重計上/不正な時刻/エピソード不一致/Unity空オブジェクト/累積集計の重複を検査。

Player.prefabはmatchKeyboardMoveSpeed=1を保存。.gitignoreにはローカル評価出力の除外を追加。DEVELOPMENT_PLAN.md/DEVELOPMENT_LOG.mdを更新し、STEP5_DESIGN.mdは承認待ち設計案として追加。今回のcommitには以前の環境調整（全果物Prefab、Scene、背景前景PNGと.meta、Viewport・共有Collider、安全範囲、関連テスト/説明）も含む。実験JSON/JSONL/CSVは含めない。

## 変更前後の重要箇所

以前のGO診断：
```csharp
// PredictionDiagnostics.Compare：取得時点が違う確定フラグだけを見ていた
game_over_match = a.game_over == p.game_over;
bool failed = ... || !e.game_over_match || ...;
```

変更後（Recorder.Capture/Compare）：
```csharp
if (gameOverHeight.HasValue && fruit.CompareTag("Fruit") &&
    fruit.CanTriggerGameOver(gameOverHeight.Value)) candidate = true;
// Frame.game_over は従来の確定フラグ、Frame.game_over_candidate は物理更新直後の条件成立
game_over_candidate_match = a.game_over_candidate == p.game_over_candidate;
if (f.has_collided != other.has_collided) e.contact_eligibility_match = false;
// failed は同一フェーズのcandidateと接触済みも比較。確定フラグの比較結果も消さず残す。
```

`first_game_over_candidate_actual/prediction`には最初の成立Frameを保存。存在は`actual/predicted_game_over_candidate_observed`で判別。`actual/predicted_completion_game_over`はstep完了時の結果。通常のstate.game_over、予測Result.game_over、評価のGO見逃し集計は従来通りで、見かけの精度を上げるための除外/置換はしない。

以前の報酬：
```csharp
stepScoreBefore = ScoreManager.Instance.GetScore();
activeStep.reward = ScoreManager.Instance.GetScore() - stepScoreBefore;
```

変更後：上のstep報酬定義を維持し、別に受付/完了の境界を記録する。
```csharp
BeginRewardStep(message.action_id, stepScoreBefore); // 直前のgapを閉じる
EndRewardStep(ScoreManager.Instance.GetScore());     // stepを閉じる
// ReadRewardAccounting：観測を読むだけでは確定合計を増やさない
conserved = score == rewardStartScore + stepRewardTotal + betweenRewardTotal + open.reward;
```

`between_steps`のaction_idは0。直後の行動の成果とは主張しない。区間ごとにgame_time_start/end、fixed_time_start/end、score_before/after/rewardを持つ。未終了区間もopen_intervalに表示し、reset時はprevious_episode_reward_accountingへ旧集計を保存する。Pythonのstep返り値rewardにはgapを自動加算しない。

UnityのJsonUtilityはnullクラスを空のオブジェクトとして出力するため、RewardInterval/RewardAccountingには明示的なpresentを追加。present=falseの過去区間を実データとして解釈しない。

以前のAI速度：
```csharp
public float aiMoveSpeed = 2.5f;
float speed = playerController.aiMoveSpeed;
```

変更後：
```csharp
public bool matchKeyboardMoveSpeed = true;
public const float NormalMoveInput = 0.5f;
public float EffectiveAIMoveSpeed {
    get { return matchKeyboardMoveSpeed ? Mathf.Abs(speed * NormalMoveInput) : aiMoveSpeed; }
}
// AI操作・UDP観測・予測はEffectiveAIMoveSpeedを使用
```

InspectorのMatch Keyboard Move Speedが既定で有効。Speed=7.5なら3.75 world unit/game second。AI Move Speed欄はチェック無効時の個別設定であり、有効時の実効速度ではない。Speedを後で変えるとAI/予測も追従する。

## 検証結果

- Python46テスト成功。Runtime/Editor全C#コンパイル成功（既存の未使用フィールド警告3）。UDP実装の再送/待機/観測窓/lifecycleに加え、実ledgerの非重複区間・観測の二重読取・reset保持の回帰成功。
- 実UDP比較20試行完走（5位置、1エピソード）。得点/合体有無/合体種類個数/合体系譜20/20一致、合体正例5試行。更新回数も20/20一致、AI速度は全件3.75。自然なGO正例はこの20試行では0件。
- 予測と実ゲームの最大位置誤差0.066580675 world unit、速度0.191958669 unit/s、角度26.544621度、角速度13.888664度/s。位置の試行最大値中央値0.000964270。接触による物理状態の完全一致は得られていない。
- 診断なしの参照予測時間：平均6.111175ms、中央値5.4393ms、p95 11.068155ms、最大16.678ms（生成/コピー/計算/解放予約を含み、非同期解放の完了時間は含まない）。
- 以前の500回の得点一致96.2%と今回20/20は、速度・盤面・手数・標本数が異なる。改善率や統計的な非劣化は主張できない。長時間/密集盤面/GO正例を含む再評価はユーザー担当。出力Python/eval_step4_improved_20_20261021/はローカル保持のみ。
- 20手終了後、自然な盤面の合体で20→23点になった実UDP観測を取得。step_reward_total=20、between_steps_reward_total=0、open_interval.phase=between_steps、open_interval.reward=3、conserved=true。reset後のprevious_episode_reward_accountingにも23点分が保持された。新しいエピソードは0点。
- Step4ContractProbe：手動の実FixedUpdateを10回実行して3.75を計測、AI/予測の実効値3.75と一致。現行Prefabの異種果物2個をライン上で接触させ、物理直後candidate=true/確定flag=false、続くUpdateで実GO=trueを確認。元の条件/更新順を維持し、終了後にreset。これは制御した正例fixtureであり自然な長時間積み上げ試験ではない。
- 最終ソースでCooldownPredictionProbe成功：0.4秒制限中の20待機更新を含む総121更新が実ゲームと一致、合体1回/加点1、source_unchanged=true、ledger=1点で保存則成立。出力Python/cooldown_prediction_20261021_083147_219.json。
- 検証途中にnullのJSON空オブジェクトでPythonが観測を拒否した問題をpresentフラグと回帰テストで修正。GO fixture初版は異なるCollider.offsetを考慮せず実際に接触せずtimeout。テストの配置だけをbounds.centerで整合させ、Collider.Distanceで重なりを確認して成功。ゲームの物理形状/位置設定はこのために変更していない。

## 限界とSTEP 5への判断

試行111の過去の接触履歴は保存データから完全に復元できず、見逃しが根治したとは主張しない。公開物理状態は一致していても接触履歴/solver内部情報はコピーされず、物理更新と描画フレームの境界・Destroyの時点も異なる。現行のGO条件そのものを変更しない以上、位置/接触時刻の誤差による見逃しは残り得る。今回は記録フェーズと診断の整合性を改善した。

Unityは命令待ち中も進む。報酬ledgerはその区間を記録するが、古い盤面に基づくAI判断を防ぐ機能ではない。STEP 5案では同じUnity命令受付内で複数候補を評価・選択・step予約する。Pythonへ判断を往復させる場合のsnapshot token/physics_revision照合は将来設計で、未実装。

主要機能と報酬区間・速度の短時間確認は成功し、完全一致を必須としない新方針の下でSTEP 5の設計レビューへ進める。最終的な精度の非劣化保証は長期検証待ち。STEP 5の実装は承認前に開始しない。詳細案はSTEP5_DESIGN.md。
