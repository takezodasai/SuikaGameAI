# STEP 7-B：収集準備（2026-10-22）

今回の担当範囲は状態保存・データ監査・分割・評価手順の準備。100〜200ゲームの本格収集と再学習はユーザーが結果を報告してから行う。Value Networkのゲーム接続（7-C）・MCTS・物理予測時間の延長は未実装。

## 起動前

- develop、Unity 2022.3.21f1。ユーザー確認後、Sceneの2箇所のGameOverScreenRatioを0.83に統一し、保存済みSceneからSTEP6 Playerを再ビルド済み。
- 評価は `V=score_gain/55 - .2R`、5候補・落下後25物理更新・既存GO除外/フォールバック・操作間隔を維持。Collider・重力・果物のサイズ等は変更しない。
- Unity EditorのPlayは不要。以下のコマンドが必要なPlayerを起動する。実行中の他のゲームは終了させない。ポート18000〜18007を使用中なら、この収集側へ `--base-port 25000` 等を付ける。
- `--require-metadata --expected-go-ratio 0.83` により、古いPlayerやGO比率違いで収集を進めない。Scene/C#を後で変更した場合、保存・Play停止後にUnityのTools > Suika > Build STEP6 Windows Playerで再ビルドする。

## 100ゲームを収集

PowerShellへコピーする。出力名は既存フォルダと重ならない名前にする。

```powershell
cd C:\SuikaGameAI\Python
python play_parallel_ai.py --games 4 --episodes 25 --max-steps 1000 --headless --seed auto --independent-episode-seeds --candidates 5 --post-drop-steps 25 --require-metadata --expected-go-ratio 0.83 --output outputs/value_collect_100_01
```

4worker×25episode=100ゲームを試行する。200ゲームなら `--episodes 50` と別出力名 `outputs/value_collect_200_01` に変更する。1000手到達・Ctrl+C・通信エラーは自然GO完了と区別されるため、必ず100件の学習可能episodeが得られる保証ではない。

停止は収集PowerShellでCtrl+C。完了済み行はflush/fsync済み。実行途中のstepは完了またはタイムアウトまで待つ。未完了episodeに最終得点ラベルを付けない。再実行は新しい出力先を指定する（収集の途中再開は今回未実装）。

## 集計

```powershell
python audit_collection.py --input outputs/value_collect_100_01 --output outputs/value_collect_100_01_audit
```

`report.json` とExcelでも開ける `episodes.csv` を作成する。確認項目：

- `completed_games`：検証済みの自然GO完了数。`truncated_games`、`incomplete_games`、無効episodeは別。
- `episodes_detail` / CSV：各ゲームの最終得点、seed、手数、状態数、方針、GO比率。
- `average_score` / `max_score`、`total_actions` / `usable_states`。
- `integrity_ok` / `issues` / `warnings`：混入、重複action、報酬保存則、GO/打切りラベル、物理プロファイル参照、末尾不完全行等。
- `duplicate_seeds` / `duplicate_episodes` / `correlation_group_count`：独立標本と誤解しないための情報。
- `field_coverage`：現在接触・sleep・Colliderサイズ・保持Yの既知件数。欠損を実測0に置き換えない。

複数収集間のseed重複も検出できる：

```powershell
python audit_collection.py --input outputs/value_collect_100_01 outputs/value_collect_200_01 --output outputs/value_collections_combined_audit01
```

同じworkerでRNGを継続する旧モードのseed反復は、必ずしも同一episodeの重複を意味しない。同じseed/初期系列は相関グループとして扱う。内容が同一の8手以上の軌跡は教師データ側で重複除外する（1〜7手の完全一致は偶然もあるため、同一IDでない限り重複と断定しない）。

## seedの再現

`--seed auto` の実際のbase_seedは `collection.json` に保存する。episode番号i（0始まり）、worker番号jに対し `base_seed+i*games+j`。全スケジュール、候補数、予測時間、係数を保存し、子run.jsonへ実seed/実行設定/PlayerのSHA256を保存する。

各episodeは新しいPlayerで開始する。UnityのReset内のRNG処理を変更せず、Sceneの初回生成→通信準備→Resetという既存の順番を維持する。単に既存プロセスをResetするだけでは同じ初期乱数状態へ戻らない。

再現例（元の収集と同じPlayer・設定を使い、別出力先へ）：

```powershell
$col = Get-Content outputs/value_collect_100_01/collection.json -Raw | ConvertFrom-Json
python play_parallel_ai.py --games $col.games --episodes $col.episodes --max-steps 1000 --headless --seed $col.base_seed --independent-episode-seeds --candidates 5 --post-drop-steps 25 --require-metadata --expected-go-ratio 0.83 --output outputs/value_collect_replay01
```

これは元の25episodeを再実行する長時間コマンドなので必要時のみ使う。先頭だけ確認するなら `--episodes 1 --max-steps 5` にする。設定をカスタム変更していた場合、元run.jsonのsettings/実行形式/ビルドGUIDも一致させる。現在の非同期実時間方式は、同じseedでも状態/操作受付のタイミング・物理状態のbit一致を保証しない。

## 保存する情報

JSONLのイベントschema_version=2（旧1も読む）、UDP protocol_version=2を維持してmetadata_schema_version=1を追加。run.jsonはschema4、collection.jsonはschema2。旧run/collectionも読める。

- 毎状態：物理時刻/ゲーム時刻/実時間、取得フェーズ、合体処理中の果物数、保持果物Y/既知フラグ。
- 各盤面果物：過去衝突履歴HasCollidedとは別の現在接触 `touching`、`sleeping`、実効Colliderのworld AABB半幅/半高、world offset、物理プロファイルID、既知フラグ。
- `touching`は最後の物理更新の非trigger接触。HasCollidedは過去の衝突履歴。幾何的な見かけの重なりや「将来接触する」を意味しない。
- 固定環境とプロファイルは `metadata/game_XX.json` へまとめ、state.environment_idで参照する。環境のSHA256・PhysicsProfileのIDを検証する。新しい実効プロファイルが出た時だけ読み取り専用のenvironment要求でカタログを更新し、atomic書き換えする。
- 固定情報：Unityバージョン/ビルドGUID、重力、物理反復回数/接触offset/sleep閾値等、壁/床の位置・形状・サイズ、GO比率とworld高さ/判定ルール、移動速度/保持offset/操作間隔、既存得点表、レイヤー衝突マスク。
- プロファイル：有効Circleのradius、桃Capsuleのsize/direction、Collider offsetとscale、実効materialの摩擦/反発、mass/inertia/centerOfMass/drag/gravityScale/bodyType/constraints等。Colliderが無効な旧Polygonは含めない。
- Prefabの全11種類の静的設定を保存するが、未来の抽選結果/乱数状態は保存・入力しない。Prefabのinertia等はasset上の値であり、実体の慣性の実測値とは区別する。実体の果物はruntime profile IDを参照する。
- 設定は収集中に変更しない前提でinstanceのプロファイルをキャッシュする。変更する場合は停止・新ビルド・新runで収集する。

見送ったもの：solverのwarm-start/接触impulse履歴、Box2D内部cache、進行中の合体キューの完全複製、未知Colliderの全頂点、RNG state。これらを復元可能なMarkov状態とは主張しない。合体中の消去予定果物は従来どおり通常盤面リストから外し、その存在をmerge countに記録する。取得フェーズが衝突callback内の場合もあり、物理更新終了直後・安定状態とは限らない。今回PhysicsScene2Dシミュレーターは変更しない。

## 教師データへの変換

収集結果の監査後に実行する。これは学習ではない。

```powershell
.\.venv\Scripts\python.exe value_network.py prepare --input outputs/value_collect_100_01 --output outputs/value_data_100_01 --validation-fraction 0.15 --test-fraction 0.15 --split-seed 2026 --policy step5-v3-score-roughness --go-ratio 0.83
```

- 教師は自然GO final_score − 実際の実行後score。step間の加点・最後の自然加点は保存則で検査し、教師に再加算しない。未選択候補は教師にしない。
- 同じseed、同じ観測済み先頭8果物系列をUnion-Findで連結したepisodeグループを約70/15/15へ分離する。状態数の比率は必ずしも70/15/15ではない。3分割には少なくとも3グループが必要。
- 8果物より短いepisodeの系列は不明とし、seedでまとめる。異なるseedでも相関が残る可能性はある。単純な状態のランダム分割はしない。
- このdataset/manifestを固定して以後のモデル選択に使う。入力を追加してprepareをやり直すと分割が変わり得る。過去のTestを学習へ移す運用はしない。
- schema1/2の旧JSONLを読めるが、旧環境のGO比率はログから確認できなければ不明。上記のgo-ratioフィルターは不明/0.83以外を除外する。旧資料の値を実測として埋めない。
- policyフィルターで旧D減点AIを区別する。混合実験は別datasetへ作り、環境差・方針差も記録して比較する。
- dataset.manifestのenvironmentsへ固定環境/physics_profilesをまとめて保持する。元runを移しても型/形状/質量などを参照できる。入力にはID/seed/最終得点/先頭系列は入れない。
- Valueの入力仕様は従来の30 fruit特徴＋37 global特徴のまま。既存のsize/contact/sleep/heldY既知フラグに新実測を利用する。質量/慣性/正確なCapsule形状/merge pending/取得時刻をNNの新次元へ入れるのは次段階。旧モデル/チェックポイントは保持し、欠損が多い旧データで学んだモデルへ新既知特徴を渡した際の分布差に注意する。

## 再学習・評価（収集結果を確認してから）

以下は将来用の手順。今回、本格再学習は実施していない。

```powershell
.\.venv\Scripts\python.exe value_network.py train --data outputs/value_data_100_01 --output outputs/value_train_100_01 --config value_config.json --epochs 30
# 中断後、同じdataset/出力/設定から再開
.\.venv\Scripts\python.exe value_network.py train --data outputs/value_data_100_01 --output outputs/value_train_100_01 --resume --epochs 30
# モデルの選択・過学習確認にはValidationだけを使用
.\.venv\Scripts\python.exe value_network.py evaluate --data outputs/value_data_100_01 --model outputs/value_train_100_01 --checkpoint best --split validation --output outputs/value_val_100_01
# モデル/設定を確定した後にだけTestを開く
.\.venv\Scripts\python.exe value_network.py evaluate --data outputs/value_data_100_01 --model outputs/value_train_100_01 --checkpoint best --split test --output outputs/value_test_100_01
```

学習中のloss/early stop/scheduler/best選択と学習終了時の自動レポートはTrain/Validationのみ。Test MAEを見て設定を選ばない。

`metrics.json`にはMAE/RMSE/bias、学習側平均の定数baseline、episode別誤差、episode macro MAE、得点帯/果物数帯/GO前5操作/過大予測上位20件。`predictions.csv`は各状態の教師/予測/誤差/seed/方針。学習曲線PNG/SVG/CSVも従来どおり保存する。既知GOは出力0なので、非GOとGO直前も分けて判断する。

旧モデルを新しい固定Testへ最終比較する場合のみ：

```powershell
.\.venv\Scripts\python.exe value_network.py evaluate --data outputs/value_data_100_01 --model outputs/value_smoke_01 --checkpoint best --split test --external-test --output outputs/value_old_on_new_test01
```

元モデルのrun.json/元datasetが必要。元学習・検証のseed/episode/分かる先頭系列と重複するTestは拒否する。baselineには元モデル学習側の平均を使う。旧ログから系列を復元できない場合はその件数を警告として記録する。環境・方針の分布差を含む比較であり、モデル構造だけの優劣と解釈しない。通常evaluateはdataset指紋違いを拒否し、external-testは明示的Test専用に限定する。

## 今回の検証と限界

- Python全90テスト成功。旧ログ/new schema、ターゲット、自然GO/途中終了、加点の二重計上防止、seed/系列の連結、3分割、欠損フラグ、Capsuleカタログ保持、Testの自動評価除外、外部Testのseed/系列漏洩拒否、保存再開/推論/Viewer既存テストを含む。学習テストは一時的な小さな仮データのみ。
- 新Playerの2ゲーム×4手、独立seedモード2ゲーム×2episode×2手を2回、追加観測ON/OFF各2ゲーム×8手、実Viewer4ゲーム×16手を実施。すべて短時間で打切り、学習教師へ0件として除外。失敗した調査runも削除せず保存。
- seed742110〜742113の保持/NEXT系列は再実行で4episodeとも一致。両runをまとめて監査すると4seedの重複を検出できた。
- 現在接触/sleep/Collider/保持Yの実保存、Circle×10種類・桃Capsule×1種類のasset定義を確認。今回の少数手で桃が盤面へ出現した際のruntime慣性までは未確認。
- 既存ユーザーログvalue_seed_test01は8自然GO、1043状態、平均945.375・最高1201、seed重複0、保存則OK。変換はTrain6episode782状態/Validation1episode124状態/Test1episode137状態。新0.83環境の精度ではなく、旧ログ互換の検証。
- 観測OFF→ON（同ビルド/seed742120/2ゲーム/5候補/25更新/各8手）：2.376002→2.375650手/秒、差約−0.015%。ゲームごとの行動/得点は8手一致。位置の最大差0 / .22723world unit（同ID果物の対応分）を観測。追加問い合わせ中にも実ゲームが進む非同期タイミングがあり、完全に同じ物理初期状態の速度比較ではない。最初の位置差はGame01の2手目で、両方とも落下後25更新/全26更新だったが、step間の固定時刻の経過はOFF=.10秒/ON=.08秒で1更新分異なっていた。短い1回の比較で性能の非劣化を保証しない。旧コードそのものの同条件再ビルド比較はしていない。
- 同比較のJSONLは約49.10→49.97KB/手（初期盤面）。従来8ゲームの平均は約130手/ゲーム、ログ計72.1MB。後半は候補ごとの果物情報で増える。100ゲームは概ね1〜2時間/1〜3GB、200ゲームは2〜4時間/2〜6GBを仮の目安とする。新GO比率/PC/盤面/長さで変化するので実測集計を優先する。今回の空き容量は約52.5GB。
- 実Viewerで独立4盤面の得点更新とGame02単独表示を確認。実映像でのF11操作時には対象ウィンドウが利用できなくなり、今回の実映像全画面確認は未完了。F11/Esc/一覧復帰は既存の実Tk自動テストで成功。Viewer/音声コード自体は今回変更しない。Playerログに新規例外なし。
- Unity Editorでビルド成功（17.54秒）。初回バッチ起動は既存Editor検出で拒否されたため、既存Editorを使用。ユーザーが未保存Sceneを保存してから実行した。ビルドによるTMPの自動glyph生成差分のみ作業開始時の内容へ復旧し、既存変更を保持。
- 実通信の途中でJsonUtilityのnullクラスがschema_version=1の空環境として見える問題を発見。unity_version/build_guid/dt/profile/boundaryの実データ確認で除外するよう修正し、同条件ONテストを完了。失敗ログstep7b_metadata_on_01は調査資料として残す。

生検証ログ/結果：Python/outputs/step7b_checks_01.json、step7b_smoke_01、step7b_seed_smoke_01、step7b_seed_replay_01、step7b_metadata_off_01、step7b_metadata_on_02、step7b_viewer_smoke_01、value_seed_test01_audit_7b、step7b_legacy_split_01。

## 変更したファイル・主要関数

| ファイル | 関数・位置 |
|---|---|
| Unity/Assets/Scenes/Script/UDPTrainingMetadata.cs（新規＋.meta） | DescribeShapes L75 / RegisterPhysicsProfile L93 / FillFruitMetadata L111 / CaptureTrainingEnvironment L141 / FillTrainingSnapshot L169 |
| Unity/Assets/Scenes/Script/UDPStateProtocol.cs | BeginEpisode / HandleCommand / SendPacket、観測型をpartial化 |
| Unity/Assets/Scenes/gameDisplay.unity | ユーザー承認のGameOverScreenRatio=0.83（2箇所）。その他のユーザー保存変更は保持 |
| Python/src/suika_ai/unity_env.py | get_environment L208 |
| Python/src/suika_ai/collection_metadata.py（新規） | CollectionMetadata.refresh L25 / attach L39 |
| Python/src/suika_ai/collection_audit.py（新規） | load_environment L11 / initial_sequence L20 / episode_signature L32 / correlation_groups L43 / audit L71 / save_audit L163 |
| Python/audit_collection.py（新規） | main |
| Python/src/suika_ai/parallel_play.py | collect_worker L75 / run_parallel L183 / validate_run L253 / run_seeded_episodes L311 |
| Python/play_parallel_ai.py | main：メタデータ要求/GO比率確認/診断用OFF設定 |
| Python/src/suika_ai/value_data.py | validate_episode L26 / prepare L71 / encode L178 / load_dataset L212 |
| Python/src/suika_ai/value_train.py | evaluate L44 / external_test_context / train：Testの保存と除外、集計拡張 |
| Python/value_network.py | main：policy/GO比率/3分割・Test/外部Test評価引数 |
| Python/tests/test_collection_audit.py（新規） | 10件の監査/分割/互換/外部Testテスト |

本資料、DEVELOPMENT_LOG、DEVELOPMENT_PLANを更新。commit/push/追加バックアップ/既存ログ・チェックポイント削除は行わない。

## 7-Cへ進む条件

ユーザーが新0.83環境で自然GOデータを収集し、監査結果・policy/環境別件数・seed/系列グループ分割を確認する。その後の許可で再学習し、定数baselineに対するValidation/Test誤差、過学習、過大評価、GO直前の弱点、5候補CPU推論時間を評価する。Testグループが少ないときは最終汎化性能を断定しない。実ゲーム得点の優劣は7-Cで同条件・複数seedの比較を行って判断する。ValueのオフラインMAEが下がっただけで自動的にゲーム操作へ接続しない。
