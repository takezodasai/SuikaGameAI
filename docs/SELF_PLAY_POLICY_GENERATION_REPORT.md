# 自己プレイから次世代方策を学習する夜間実行基盤

2026-11-03。プレイ、保存、実測結果による重み付き学習、別世代モデルの保存、新モデルを使った実行まで完成・短時間検証した。8時間の本実行は開始していない。標準MCTS、旧Player、元ログ・モデル・未commit変更は維持し、commit/pushなし。

## 就寝前の実行

PowerShellを `C:\SuikaGameAI\Python` に移動し、次の1コマンドを実行する。

```powershell
.\.venv\Scripts\python.exe .\selfplay_rollout.py collect --workers 4 --hours 8
```

初期設定は深さ4・256反復・固定5候補・同期MCTS、学習rollout50%混合。現在の旧世代モデル `outputs\learned_rollout_01\training\model.json` を使用する。最新生成モデルへ自動で切り替わらない。専用Playerは `Unity\Builds\PolicySelfPlay_01\SuikaGameAI.exe`。旧Playerを上書きしていない。

保存先は毎回 `C:\SuikaGameAI\Python\outputs\rollout_selfplay_日時_UUID` に自動生成し、開始時の `Output:` に絶対パスを表示する。既存フォルダへの新規実行は拒否する。進捗はコンソールに約1分間隔、runtime.jsonに約5秒間隔で保存する。

8時間は新規ジョブを投入する時間予算。終了時刻になったら新規投入だけを止め、実行中ゲームを完了まで待つdrain方式。その後、自然GO履歴があれば次世代方策を自動学習・別ファイル保存する。学習済みモデルの自動昇格は行わない。

したがって全処理終了は8時間を超えうる。安全上限は1ゲーム4時間／100,000落下、進捗ログの無応答watchdog720秒。これらに達したゲームは打ち切り・技術失敗として扱い、自然GO最終returnには使わない。同期探索中はゲーム側時間上限を判断境界で確認するため、1判断分の超過はありうる。720秒はUDPメタデータ応答タイムアウトではなく、この新ツールのログ進捗監視である。

ワーカーは1〜4。実行中の既存Playerがあれば新規起動を拒否し、停止・変更しない。ポート44000〜44007の空きを確認し、必要なら `--base-port 44400` のように変更する。各Playerは別プロセス、別ポート、別ジョブフォルダ。優先度はBelowNormal。

## 停止・再開・翌朝

Ctrl+Cを1回：新規ジョブ投入を止め、現在のゲームは続行する。もう1回：このツールが起動したPlayerだけを停止し、部分ログ・最後の観測状態を保存する。

再開は、表示された保存先を指定する。

```powershell
.\.venv\Scripts\python.exe .\selfplay_rollout.py collect --output "C:\SuikaGameAI\Python\outputs\rollout_selfplay_実際のフォルダ名" --resume
```

完了ジョブは再実行しない。未完了ジョブは同じゲームseed・探索seedで新しいattemptへゲーム開始から再実行する。Unity内部の接触履歴を含む途中状態の厳密再開ではない。停止前のログを上書きしない。古いattemptの終了コードが不明な場合も、推測で正常終了とせず保守的に再実行する。技術失敗は原則最大2attempt、ユーザーによる途中停止はこの失敗回数に含めない。3回連続技術失敗で新規投入を止める。

再開後も元の世代・Player・探索設定を維持し、8時間の残り予算を使う。8時間を使い切ったセッションを追加延長する機能ではない。さらに収集する場合は新しいcollectセッションを作る。

翌朝の結果確認（読み取り集計、実行中にも使用可）：

```powershell
.\.venv\Scripts\python.exe .\selfplay_rollout.py summary --output "C:\SuikaGameAI\Python\outputs\rollout_selfplay_実際のフォルダ名"
```

自然GO数、平均・中央値・最高・最低得点、スイカ／ダブルスイカ、途中終了、現在のジョブ、次世代モデル保存先を表示する。途中終了の得点を0点として平均に混ぜない。

学習だけをやり直す場合：

```powershell
.\.venv\Scripts\python.exe .\selfplay_rollout.py train --output "C:\SuikaGameAI\Python\outputs\rollout_selfplay_実際のフォルダ名"
```

同じ親モデル・経験・学習レシピなら既存の完成世代を再利用し、重複学習・上書きしない。学習途中停止では旧モデルと履歴を保持し、新しい学習attemptへ最初から再実行する。

## 学習の変更

旧モデルはMCTS訪問分布75%＋MCTS最終選択25%を教師とした模倣学習。新方式はこの土台に、実際の自然GOまでの結果を反映する。

`G = 自然GOの最終得点 − 判断開始時の得点`

進行段階・盤面難度を考慮するため、公開状態53特徴の小型ridgeで残り得点の基準値b(s)を学習する。現在得点、果物数・種類、盤面高さ・速度、局所密度、保持果物・公開NEXTなどを使用する。Trainは元seed／初期8果物系列のgroupごとに3-fold cross-fitし、自分と同groupの結果を見た基準値で自分の重みを決めない。Validationの基準値はTrainだけで学習する。

`w = clip(exp((G − b_crossfit(s)) / τ), 0.5, 2.0)`

τはTrain残差のrobust scale、最低100点。方策損失は「訪問分布CE×0.75＋選択行動CE×0.25×w」を正規化したもの。独立seed群の状態数で正規化し、実反復数由来の教師品質重みを別途適用する。成功ゲームを丸ごと正解にするのではなく、状態に対する予想以上／以下の実測結果で重みを変える。失敗側も最低0.5を残し、元の訪問分布教師も維持する。

213係数の既存方策構造を維持し、親モデルの重みから25epoch、Adam lr0.01、親重みへの小さな正則化0.01で更新。Validationの重み付き損失でepoch選択。人間の配置攻略法や追加得点ルールは導入しない。

これは実測結果を利用する重み付き模倣学習であり、真の行動優位性を直接観測したpolicy gradientではない。Gは後続MCTS、未知果物の運、盤面条件にも依存する。状態基準値を引いても、未選択行動との因果比較ができるわけではない。

## データと世代管理

完了済みの自然GO・正常終了・探索監査成功・既知actor SHAのゲームだけを使用する。途中終了は履歴を保持するが、G=0などの仮ラベルを付けない。判断しても実落下に至らなかった行動は方策教師に使わない。最後の落下後や操作間に生じた加点も、最終得点−判断時得点に含む。

新しい経験と既存の固定Train/Validation通常ゲーム履歴をreplayとして使用。既存Testとhistorical_testは学習・モデル選択から除外し、予約Test19はseedと初期8果物系列で除外する。ライブ収集ではTest19系列が判明した時点で隔離する。新規seedは保存済みjob/configや既存データのseedを読み取りで除外し、ランダムに選んだ新しい範囲を使用。ゲーム生成seedと探索seedは分離して保存する。

分割は元seedまたは初期8果物系列を共有するgroup単位。既存Train/Validationは維持し、自己プレイ側の割当をsplit_registry.jsonへ保存して再学習で動かさない。最初の少数新規groupはTrain、その後は固定hashで約20%をValidationへ割り当てる。新しい独立Testを評価したものではない。

各ゲームの最初にactorを1回読み込み、ゲーム中は変更しない。セッションの親モデル・Player SHAも固定。収集終了後のモデルは `generations\gen_指紋\model.json` に別保存。latest_training.jsonは生成候補への参照であり、稼働actorを変えるものではない。

次世代で試す場合は、新しいcollectに明示的に `--model "生成されたmodel.jsonの絶対パス"` を指定する。旧世代へ戻す場合は `--model` を省略、または旧モデルのパスを指定する。実ゲームで有利と確認するまで新モデルを標準採用しない。

主な保存物：

- collection.json：actor、Player、環境ルールID、設定、使用済みseed除外情報。
- jobs/job_*/job.json：ゲームseed・探索seed・元group。
- attempt_*/trace.jsonl：公開盤面、保持果物/NEXT、候補統計、実落下、物理tick、得点・実イベント、rollout回数・モデルSHA。
- attempt_*/result.json、途中終了時のlast_observed_state.json：終了分類と観測状態。厳密復元可能とはしない。
- runtime.json、collector_events.jsonl、resources.jsonl、summary.json、games.csv：進捗・資源・ゲーム単位集計。
- generations/gen_*/experience.jsonl：公開入力と、将来return・重みなどの教師を分離したデータ。未来情報を推論入力には使わない。
- training_plan.json、state_baseline.json、evaluation.json、model.json、complete.json：世代単位の学習と完成確認。

## 今回の確認結果

8時間本実行・大量自然GOゲームは行っていない。確認用出力は `Python/outputs/selfplay_generation_01/`。

|確認|結果|
|---|---|
|親モデルで2ワーカー|各3落下、256反復／深さ4、ログ・終了結果保存|
|新モデルで4ワーカー|4台同時、各1落下、256反復、全台で新SHA・学習rollout使用を確認|
|途中終了の扱い|手数上限は自然GO=false、final_score=null、return学習対象外|
|完了ジョブのresume|新attemptの重複実行なし|
|技術失敗・再実行|テスト用所有Playerだけを停止、部分状態を保存し同seedのattempt_001で再実行|
|短い時間上限|新規ジョブ投入停止、既存ゲームを強制終了せず終了まで待機|
|モデル更新|学習・保存・再読込・Unityでの推論／実落下まで確認|
|同じ教師の再学習指示|already_trained、世代ファイル増加・モデル上書きなし|
|Python|498テスト成功（新規11件）|
|Unity|既存1,014＋方策一致74＝1,088 checks成功|

失敗試験で、最後のワーカー終了後に次の割当をせず終了する新規collectorの不具合を発見・修正した。修正後、1枠での自動retryと、別呼出しのresumeの両方を実行確認。過去ログは保持した。

学習確認では、新規短時間テストの打切りゲームは使わず、以前の学習rollout版が自然GOした実ゲーム1件（225判断、128反復、2,152点）を再利用した。夜間本番の256反復データを既に大量収集したという意味ではない。

既存replay 20,997判断＋自己プレイ225判断を用い、Trainは82ゲーム・67群・17,536判断、Validationは16ゲーム・15群・3,686判断。学習は約23.92秒。パラメータ変更L2=0.2190、重みは0.5〜2.0となり、実測結果が実際に勾配へ反映された。

|同一Validation|親モデル|新モデル|
|---|---:|---:|
|重み付き損失|1.598109|1.598343|
|模倣CE|1.600164|1.600429|
|MCTS選択一致率|28.56%|27.80%|

今回の新モデルはわずかに悪化し、性能改善の証拠はない。別ファイルとして保存し、4ワーカーでの読み込み・実行だけを確認した。夜間コマンドのデフォルトは親モデルのまま。新モデルの自然GO得点・スイカ率は今回は未測定である。

確認用の新モデル：
`Python/outputs/selfplay_generation_01/two_worker_smoke/generations/gen_041b50b6a7eb/model.json`

新SHA：`a0d4eff44b862f8ae383a64b89b1c75d687cc0b90fb2ce539db663f025164695`。
親SHA：`81d9f3b581a7b0c7533096c01c63bdc57ab6c300f467e5c4206b42c60eb3111e`。

## 変更と限界

追加：Python/selfplay_rollout.py（CLI）、rollout_selfplay.py（収集・復旧・監査）、rollout_experience_learning.py（結果重み付き学習）、tests/test_rollout_selfplay.py。
追加：Unity/Assets/Scenes/Script/SuikaPolicySelfPlayLab.cs、Unity/Assets/Editor/SuikaPolicySelfPlayBuild.cs。

専用Labは既存学習rollout Labから分離し、起動flagと安全上限を拡張しただけ。標準MCTS、LearnedRolloutPlanner/Policy、物理・ルール・既存Playerは変更していない。

未検証：4並列8時間の安定性、終盤の実処理量、新しい結果重み付き方策の自然GO性能。物理予測Sceneの既存誤差、教師方針の混在、少ない自己プレイ群による高分散も残る。今回完成したのは自己経験で次世代候補を作る経路であり、世代を重ねれば必ず強くなるという保証ではない。
