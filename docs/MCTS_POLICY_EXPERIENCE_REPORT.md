# MCTS経験からの方策学習 初期実装（2026-10-28）

## 結論
完了ゲームの監査、判断開始時の教師データ、小型方策モデル2種の学習、保存/再開/推論、独立seedのTest評価、イベント/追加報酬台帳基盤まで実施。ゲーム操作/MCTSへの接続は行わない。Deep Setsは単純モデルを上回らず、強化成功・時短で同等のゲーム得点・戦略発見とは判断しない。

既存収集は停止/設定変更/Player差替えしない。現行収集フォルダovernight_diverse_20261028_034614_c83571bcの保存設定は2worker・30秒上限・11時間・drainであった（変更していない）。既存SyncOptimized_03の実行2プロセスを維持。Python依存は既存torch2.6.0+cpu/numpy/matplotlibを使用し、学習CPU1thread。高速化差分、既存MCTS/AB解放/通信、物理/GO0.83/環境IDを維持。develop、commit/pushなし。

## データと監査
出力 `Python/outputs/policy_experience_01/`。source_inventory.jsonで開始時点の116ログを固定。自然GO確定済みだけ読み、得点/step間報酬/末尾加点の保存則、episode ID、行動ID、入力状態ID、保持/NEXTの一致、root訪問数、適用X（既存修正に合わせnormalized許容1e-4）、環境を検証。旧Test16ゲーム、未完了2ゲームを除外。98ゲーム20,671判断。71件の通常selectedではない/部分/未検証の計画は模倣教師から除外した（全候補GO時の正当なfallbackもこの対象となり得る。不良ゲームと断定せず原ログは保持）。失敗ゲーム全体は除外せず利用。

|分割|ゲーム|判断|seed/初期8果物系列グループ|
|---|---:|---:|---:|
|Train|79|16,809|29|
|Validation|17|3,356|6|
|Test|2|506|2|

旧ACのTrain/Validationを保持し、旧AC/旧ValueNetのTest seed/初期系列は今回へ混ぜない。新しいTestは未使用だった自然GOゲーム seed858516742（224判断、最終2145点）と858516744（282判断、最終2987点）。同seed/初期8果物系列はunion groupで分割。2ゲームしかなく、506状態を独立標本506個と解釈しない。Validationは既存開発群の再利用であり、新しい独立Validationではない。評価計画をevaluation_plan.jsonで学習前に固定、Validationだけでepochを選択し、Test評価後に設定再調整しない。

原ログ/旧モデル/旧Playerを上書きしない。完了ログSHA256/元metadataの参照をmanifestへ保存し、派生states/records/featuresのhashを検証。初回prepareはplanner.statusの語彙の扱いを修正して作り直し、未完のdatasetは保持。dataset_v2が正本。収集データの変更/削除ではない。

## 入出力と教師
入力は正確なdecision_sourceの果物種類/位置/速度/角度/角速度/接触済み情報、保持果物、公開NEXT、現在得点、移動速度、dt、盤面geometryと候補X。落下後盤面、最終得点、探索seed、訪問数、予測された未来NEXTを入力にしない。各果物30特徴、全体37特徴の既存正規化（位置は壁幅/床〜GOライン、速度/10、角速度/360、得点/1000、個数/64、欠損flag）を再利用。

重要：decision_sourceには保持y/cooldown、Collider実測/touching/sleep metadataがなく、全て既知flag0としている。現在の環境assetから実測値を捏造していない。生ログのpost stateには情報があるが、別時点の情報をroot入力へ流用しない。将来の接続には同じmask仕様を守るか、次回の正確なroot metadata収集で再学習が必要。

候補特徴は正規化x、x²、保持xとの正規化値の差（candidateは合法範囲、heldは壁幅で正規化するため実距離ではない）、左右端flagの5個。各候補へ同じheadを適用するため候補数/順序可変。今回5候補10,825件、7候補71件、8候補4,742件、9候補5,033件。候補paddingをsoftmaxから除外。果物順序への不変性、候補順序への同変性、空盤面/200果物/未知NEXT/5・9候補をテスト。

A単純モデル：全体37+候補5→64→64→1、6,977parameter。果物集合を使わない（全体には果物数等を含む）。
B方策モデル：果物30→64→64共有MLP、masked mean+max＝128、全体37+候補5を結合した170→128→64→1、36,353parameter。出力は候補logit/softmax。成功確率や将来得点そのものではない。
Cは元MCTSの選択/訪問/平均評価を参照教師とする。自己一致100%は定義上の値で、MCTSが最適である証拠ではない。

Loss=訪問分布CE + 0.25×最終選択CE。選択時のGO除外/tie処理と訪問分布のargmaxが必ずしも同じではないため両方を保存する。Trainはseed group→episode→state均等抽出、loss重みclip(sqrt(実反復/128),0.5,2)。重みと0.25係数は初期仮説であり最適値ではない。深さが深いだけで高品質と見なさない。要求/実回数・深さ・探索seed・上限ms・打切り理由・root値・実報酬・step間加点・post state・観測returnをrecordsに保持する。将来得点は自然GOの最終得点−当該時点の得点、報酬を再加算しない。未選択候補へ実ゲームのreturnを付けない。

## 学習と評価
AdamW、lr1e-3、batch128、FP32、CPU1thread、最大20epoch、Validation停滞4epochで停止。各モデル9epoch実行、bestは両方epoch5。単純モデル45.16秒、DeepSets62.09秒。Testを見て学習し直していない。

|分割|方式|選択一致|Top2一致|訪問分布KL（小が良）|訪問順位pair一致|
|---|---|---:|---:|---:|---:|
|train|position_prior|18.28%|34.62%|0.18122|53.64%|
|train|globals|21.55%|39.73%|0.10787|55.43%|
|train|deepsets|21.60%|39.68%|0.10793|55.43%|
|validation|position_prior|16.00%|31.85%|0.18600|53.90%|
|validation|globals|20.59%|38.38%|0.08720|56.49%|
|validation|deepsets|20.38%|37.51%|0.08720|56.19%|
|test|position_prior|17.79%|35.18%|0.49579|51.36%|
|test|globals|29.45%|52.57%|0.48423|57.56%|
|test|deepsets|28.85%|52.17%|0.48367|56.82%|

TestのMCTS平均評価値のpair順位一致は単純57.34%、DeepSets56.50%。これはMCTSの予測値との比較であり、未選択行動の実ゲーム価値の正解ではない。Test seed-group macro一致は単純29.22%、DeepSets28.55%。2seedのため僅差の優劣/汎化を断定しない。全Test506件で実反復>=1024。per_seed.csv/predictions.csv/learning_curve.pngへ詳細保存。

果物geometry/motionの事前指定ablationでDeepSets一致は28.85→28.06%、KLは0.48367→0.48301。盤面情報を強く活用したという一貫した証拠ではない。Train一致21.60%、Val20.38%と低く、大きな過学習gapというより教師情報/表現/学習不足が残る。Visit KLだけを成功指標にしない。

教師分布の平均正規化entropyはTrain0.939、Val0.952と平坦。最大訪問数同点はTrain23.78%、Val26.31%。高探索>=1024のTrainは424/16,809件、Valは0件に対し、Testは高探索/深さ6・12の2ゲーム。教師設定分布のずれが大きく、強いMCTSの模倣ができたとは言えない。現在の低反復収集は盤面多様化には有用だが、強い方策教師の量とは分ける必要がある。

CPU1thread・1盤面5候補のforward中央値：単純0.428ms（p95 0.723）、DeepSets0.929ms（p95 1.275）。前処理/通信/物理探索を含まない。収集稼働中の測定であり、モデルが同じゲーム得点をこの時間で出せるという意味ではない。

## 保存・再開
各モデルcheckpoints/best.jsonとlatest.json（hash付きpointer＋世代pt）を別管理。model/optimizer/scheduler/epoch/更新数/config/input仕様/候補仕様/データfingerprint/分割/乱数/sampler状態を保存。atomic書込＋破損時の前世代fallbackを既存機構で再利用。epoch末再開。別呼出の1epoch保存→2epoch再開が連続2epochと全parameter一致するテストを実施。推論CLIを別プロセスで実行。旧ValueNetとは出力/headが異なりcheckpoint互換なし、旧モデルは保持。

## イベント・追加報酬
評価可能な旧/新実ゲーム98件のうち、スイカ生成は11/82ゲーム、16件は記録不明。スイカ2個共存0/82、ダブル0/82。スイカ+メロン1個は保存snapshotで1件の成立を確認し、他97件の未観測は不明。スイカ+メロン2個は確認0件/不明98件。共存の不明を未達成と扱わない。synthetic probeの成功を実ゲーム成功データへ混ぜない。

新SuikaLearningMilestonesは実ゲームのDrop/Mergeからメロン/スイカ数を原子的に更新し、5目標の初回到達を各1回だけ記録。新フィールドepisode_events.learningに後方互換で追加。既存v1 events/score/合体/GO/乱数/物理は維持。位置/角に対する報酬や目標は一切追加しない。外部fixtureで生成を追跡できない場合はknown=falseにして捏造しない。

別Player Unity/Builds/LearningEvents_02/SuikaGameAI.exe（01の初期検証版も保護）。現在の収集Playerへ差替えない。実際の合体callbackによる専用人工盤面で、スイカ1+メロン2が成立した後同じtick内でメロンが合体してスイカ2になる瞬間も記録できた。イベントON/OFFで物理traceと得点110が一致。これは人工の記録テストであり自然プレイの達成例ではない。

learning_events.pyとrewards CLIが、後から指定する重みで実ゲームのcallback記録へ1目標1回の学習報酬台帳を生成する。ゲーム得点とは別。doubleを他より小さく設定する重みは拒否。初期reward_weights.disabled.jsonは全0で無効化し、数値を最適値として固定しない。snapshotのみの共存は正確な発生時刻が不明なので報酬を割り当てない。現段階の方策lossには追加報酬を使用しない。台帳と元episode/action/sourceで過去の状態へ戻れるが、旧rootに正確な時刻がない場合の報酬割当を捏造しない。

## 価値モデルと統合設計
旧AC modelはそのまま保持し、今回は再学習しない。追加の完了4ゲームだけでは、独立Testを確保すると新Trainは2ゲームにとどまり、価値精度改善を主張できない。旧モデルのGO直前過大評価、異なる行動のcounterfactual評価が直接教師化されていないこと、behavior-policy混合、未来盤面と実測状態の特徴欠損差、ダブル成功例0が残る。新しい実測return・イベント補助目標を用いる改善は別のValidation/新holdoutで検証する。

将来は方策priorで有望な候補を提示し、各候補の最低探索機会と既存GO除外/allGO fallbackを残し、物理探索＋価値leafを比較オプションで接続する。教師の平均評価値を実測Qと見なさない。報酬は探索内の増分＋leaf評価時点以後の価値に分け二重計上しない。未知NEXTを実値として入力せずmask/公開分布を使う。現在の単純UCTへ無断でpriorを混ぜない。今回は接続しない。

次の優先課題は、（1）正確な判断開始時metadataを次回収集用に充実させる設計、（2）多様な盤面の一部に高探索・複数探索seedで安定した方策教師を得る計画、（3）高探索教師の独立Validation群を追加すること。現在収集を止めない。今回のTestは既に評価済みなので、結果を見て調整する次のモデルに新しいTest群を確保する。候補相対の果物特徴/小型attention等の表現改善は、その後別試作とする。大規模収集/学習を今回は実行しない。

## テストと保護
Python326テスト成功。21新規で入力時点/公開NEXT、座標/訪問数保存、hash/seed分割、果物/候補の順序、空/大量果物/未知NEXT、保存→再開完全一致、イベントunknown/重複/報酬分離等を確認。Unity127 rules+861 MCTS+26 path+58 frame=1072チェック、さらに実合体のイベントON/OFF比較成功。保護27ファイル（旧Player exe/DLL、旧価値checkpoint、既存MCTS/物理予測/最適化/AB解放）のhash不変。自然GOの追加ゲーム比較、学習モデルによるゲーム操作、GPU化、新しい高速化、commit/pushは行わない。

## 主な変更ファイル
- Python/src/suika_ai/policy_data.py：監査、厳密なdecision_source、教師/分割/packed dataset。
- policy_model.py：候補条件付き小型DeepSets/単純モデル、padding。
- policy_train.py：CPU学習、Validation選択、checkpoint/resume。
- policy_metrics.py：模倣・KL・候補pair順位。
- learning_events.py：旧イベントのunknown保持、学習報酬台帳。
- Python/train_mcts_policy.py：prepare/train/evaluate/predict/rewards CLI。
- Python/tests/test_mcts_policy.py：新規21テスト。
- Unity/Assets/Scenes/Script/SuikaLearningMilestones.cs：観測専用目標台帳。
- SuikaEpisodeEvents.cs：後方互換learningフィールド。
- SuikaEpisodeEventProbe.cs / SuikaRulesSelfTest.cs：瞬間共存、1回制御、ON/OFF検証。
- Unity/Assets/Editor/SuikaWorkerBuild.cs：新しい場所への保護ビルド。

## 実行方法（収集を操作しない）
```powershell
Set-Location C:\SuikaGameAI\Python
.\.venv\Scripts\python.exe .\train_mcts_policy.py predict --dataset outputs\policy_experience_01\dataset_v2 --model outputs\policy_experience_01\deepsets --indices 0 100
```
学習途中で中断した新方策modelを同じ条件で再開する場合：
```powershell
.\.venv\Scripts\python.exe .\train_mcts_policy.py train --dataset outputs\policy_experience_01\dataset_v2 --output outputs\policy_experience_01\deepsets --kind deepsets --epochs 20 --resume
```
今回の学習はearly stop済みのため、上記で追加学習を強制しない。評価済みTestを見て設定を調整しない。

追加報酬の重みはdisabled.jsonを別名へコピーして検討し、新しい出力へ台帳を生成する：
```powershell
.\.venv\Scripts\python.exe .\train_mcts_policy.py rewards --dataset outputs\policy_experience_01\dataset_v2 --weights <新しい重みJSONのパス> --output <未使用の台帳JSONパス>
```
収集の既存Player/フォルダをresume時に新Playerへ差し替えない。新しい観測Playerは次回の新規収集でのみ使用する。
