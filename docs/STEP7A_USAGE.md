# STEP7-A: offline Value Network

2026-10-21 / C:\SuikaGameAI / develop。データ変換・学習・検証・保存再開・CPU推論まで。Unity本体、GO、Collider、物理設定、予測時間、評価関数、Viewer、音声制御は変更していない。現在のAIはV=reward/55-.2Rのまま。モデルによるゲーム操作・MCTSは未実装。commit/push/追加バックアップなし。

## 環境と最初の実行

Python3.12の専用Python/.venvへ、既存pyproject依存範囲内のtorch2.6.0+cpu、numpy2.2.3と、曲線用matplotlib3.11.2を導入済み。requirements-value.txtに固定。既存のシステムPythonやゲームの収集環境は置換していない。

```powershell
cd C:\SuikaGameAI\Python
# 新PCでのみ。既存.venvは作成し直さずそのまま使う
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-value.txt
# 既にある学習済みbestをCPUで試す（学習は開始しない）
.\.venv\Scripts\python.exe value_network.py infer --data outputs/value_data_01 --model outputs/value_smoke_01 --index 1784
# 表示されていない将来NEXTは未知として扱える
.\.venv\Scripts\python.exe value_network.py infer --data outputs/value_data_01 --model outputs/value_smoke_01 --index 1784 --unknown-next
# 1盤面・5盤面のCPU推論時間
.\.venv\Scripts\python.exe value_network.py benchmark --data outputs/value_data_01 --model outputs/value_smoke_01
```

.venvとoutputsはGit対象外。学習用ライブラリをインストールしなくても従来の並列収集は実行できる。

## 変換

```powershell
.\.venv\Scripts\python.exe value_network.py prepare --input outputs --output outputs/value_data_run02
# 必要な収集runだけ指定する場合
.\.venv\Scripts\python.exe value_network.py prepare --input outputs/parallel_test02 --output outputs/value_data_selected02
```

出力は未作成のフォルダ名にする。元ログの編集・削除なし。各run.jsonのworker別JSONLを読み、episode_startからepisode_endまで検査。GO=true、truncated=false、reason=game_over、final_scoreと実状態の得点一致、保存則、実行済みactionの一意性・受付成功・状態ID所属を確認する。途中停止、通信異常、手数打切り、未完了episodeは教師にしない。fixture/probe/smokeと明示されたrunも除外。壊れた末尾1行だけなら以前の完了episodeを残し、途中行の破損ならworker snapshotを除外する。

教師は各実行済み操作後のactual stateに対するfinal_score-current_score。step間/末尾自然加点は保存則で検査するが教師へ再加算しない。候補の予測状態や未選択候補に同じ最終得点を付けない。入力には候補情報・前episodeの報酬などを残さず、実状態の必要項目だけを保存する。未来の未表示NEXT・seed・果物ID・最終得点・ファイル名はモデル入力にしない。

旧schema_version省略/1をフィールドで読み、未知のmajor schemaは除外。必須の種類・位置・速度・角度・角速度が欠けるepisodeは除外する。サイズ、offset、接触履歴、現在接触、sleep、保持Y等は、取得可否フラグで扱い、現在Prefabから過去の実測値を作らない。

重要：古いログには外部fixtureの混入を独立に証明するフィールドがない。今回使った24episodeは通常のparallel_run01/parallel_test01/parallel_test02のGO終了記録で、明示fixtureは除外済み。変換manifestにもこの由来制約を記録した。未知の出所のログを自然GOとして保証するものではない。

worker起動seedをグループとして、同一seedの全episodeを同じ側へ分割。今回train=12345/12346/12348（19episode、2456状態）、validation=12347（5episode、673状態）。全24episode・3129状態は旧step5-v2-no-height方針であり、現在のAIの汎化性能・最適価値を示すものではない。連続episodeのRNG依存も同じグループへまとめた。隣り合う異なる整数seedまで一律に同じグループにする設計ではない。

出力：samples.jsonl（state/geometry/target/group/split等）、manifest.json（split、元ファイルhash、policy、除外理由、入力仕様）。入力と教師は分離してencodeする。読み込み時もdataset hashとepisode/seed分割を検査する。新しい変換結果は新しい学習runで使い、既存学習の--resumeへ別データを渡さない。

## 特徴量と構造

設計時27/32次元案から、旧ログの欠損を明示するフラグを増やし、果物30次元・全体37次元にした。小型の構造は維持。

果物30：type one-hot11、x/y2、vx/vy2、sin/cos(angle)2、angular_velocity1、has_collidedとknown2、Collider半サイズ2とknown1、offset2とknown1、touchingとknown2、sleepingとknown2。

全体37：保持type11、NEXT type11、保持有無、NEXT既知、保持X/YとY既知、現在得点、cooldownとknown、移動速度とknown、dtとknown、果物数、GO、geometry既知。

- 有効な壁/床/GO情報があればXを籠の内幅、Yを床〜GO高さで正規化。得点/教師は1000、速度は10world/s、角速度は360deg/s、個数は64、dtは.02sで割る。0〜1への切り捨てはしない。
- 壁/床情報がない場合だけ、原点0・10world単位を符号化の基準としgeometry_known=0。これは実測した籠の寸法の代用ではなく、明示したfallback座標符号化。
- 欠損は値0＋known=0。falseの実測値は値0＋known=1なので区別できる。
- NEXT未知はone-hot全0＋next_known=0。学習時50%のサンプルで既知NEXTも隠し、未知入力を経験させる。未知NEXTへ実際の将来抽選を入れない。
- 今回の74291果物レコードでは接触履歴は全件あり、サイズ/offset/現在接触/sleepは全件欠損。質量・慣性・合体処理待ちも観測できず、入力から除外。完全な物理状態ではない。

共有MLP30→64→64（ReLU）、masked mean/maxで128次元、全体37と結合して165→128→64→1（ReLU、最後Softplus）。出力×1000が残り獲得得点。既知GOは出力0。35713パラメータ。可変個数はbatch最大数までpaddingしmask。空盤面はpadding1件を全mask、集約0。個数上限を49に固定せず、300個と並び順入替・padding独立性をテスト済み。

## 学習・再開

```powershell
# 新規run：最初は短時間制限付き
.\.venv\Scripts\python.exe value_network.py train --data outputs/value_data_run02 --output outputs/value_run02 --config value_config.json --max-seconds 60
# 同じデータ・同じrunから続ける（epochsは総epoch上限）
.\.venv\Scripts\python.exe value_network.py train --data outputs/value_data_run02 --output outputs/value_run02 --resume --epochs 30 --max-seconds 60
# 最良モデルを評価。評価出力名も新しい名前にする
.\.venv\Scripts\python.exe value_network.py evaluate --data outputs/value_data_run02 --model outputs/value_run02 --checkpoint best --output outputs/value_eval02
```

既定MSE、AdamW、lr=.001、batch128、FP32、CPU1thread。value_config.jsonでepochs/lr/batch_size/optimizer/loss/weight_decay/ネット幅/seed/未知NEXT比率/scheduler/早期停止/保存秒数を設定。optimizerはadamw/adam/sgd、lossはmse/huberを選べる。現段階はfp32のみ。既存ゲームのscore_scale55は変更しない。

--max-updatesは累計更新数の停止上限、--max-secondsは今回の学習loop上限（起動・評価・保存時間は別）。Ctrl+Cは更新途中で無理に切らずoptimizer更新境界で保存する。電源断では最後の正常保存から復帰。強制停止直前の未保存更新までは復元できない。

チェックポイントにはmodel/optimizer/scheduler/epoch/updates/order/cursor/epoch途中loss/history/早期停止/Python・NumPy・Torch乱数/設定/入力仕様/データhash/分割/検証値/ライブラリ版を保存。初期状態、各epoch、5分間隔、正常停止時に保存する。latestは学習継続用、bestは検証最良用。初回epoch検証前はbestがないので--checkpoint latestを使用する。

更新番号付きの世代ファイルを一時書込→flush/fsync→rename、SHA256付きmetadataとlatest/bestポインタを原子的に更新。破損なら正常世代へfallbackして理由を出す。過去世代は自動削除しない。再開は同じdataset/input/torch/numpy版を要求し、設定変更はepochs上限のみ許す。別データでの重み継承・追加学習はSTEP7-Bで設計する。同一環境での再開は検証したが異なるCPU/版でbit一致を保証しない。

## 実行結果

outputs/value_data_01を使用し、outputs/value_smoke_01で最初12更新・epoch0途中で保存/プロセス終了。その後別Pythonプロセスで再起動し20epoch/400更新まで再開。学習loopに45秒上限を設定し、長時間学習は行っていない。

bestはepoch4/80更新。以下はポイント単位：

| 対象 | MAE | RMSE | normalized MSE |
|---|---:|---:|---:|
| best学習2456状態 | 176.86 | 216.49 | .04687 |
| best検証673状態 | 143.36 | 171.62 | .02945 |
| 定数baseline検証 | 273.12 | 324.40 | .10524 |
| latest epoch20学習 | 83.56 | 117.80 | .01388 |
| latest epoch20検証 | 196.00 | 224.78 | .05052 |

baselineは学習側のみの将来得点平均535.54を全状態に返す。検証教師から平均を計算していない。モデルはbaselineを上回ったが、epoch4以降は学習誤差が下がって検証誤差が悪化し、過学習の傾向が明確。検証は1seed・同じworkerの5連続episodeで、673独立試行とは見なさず統計的な汎化性能を主張しない。

検証episodeごとのbest MAE/RMSE：127.48/146.40、71.22/97.37、208.39/225.27、97.57/115.79、218.64/233.51。全episode詳細はmetrics.jsonに保存。検証最大絶対誤差は394.83点（教師1155、予測760.17、16果物・現在63点）。

検証index1784：9果物、教師930、既知NEXT予測975.56、未知NEXT予測962.55。これは1標本の数値動作例で、未知NEXTを隠したときに必ず正確になることを示さない。

CPU1thread、warmup10回・計測100回：

| 入力 | forward中央値/p95 | 特徴作成+batch+forward中央値/p95 |
|---|---|---|
| 1盤面49果物 | .261/.363ms | .721/1.165ms |
| 5盤面49/48/47/47/47果物 | .377/.543ms | 2.409/3.753ms |

5盤面は既存データの盤面をbatch評価した計測で、Unityの5候補予測や通信は含まない。学習済みAIの実ゲーム得点は今回は測っていない。

## テスト・保存ファイル

Python78テスト成功、pip check成功。教師計算（自然加点二重加算なし）、打切り/重複/破損/未受付action拒否、seedグループ分割、未来情報除去、欠損、未知NEXT、空/300個/順序不変/padding、保存再開、破損pt/ポインタfallbackを検証。小さいデータでは連続学習と途中再開のmodel/optimizer/scheduler/乱数/順序が一致。実データも別プロセスから再開成功。

- outputs/value_smoke_01/checkpoints：世代ファイル、latest.json、best.json。
- outputs/value_smoke_01/inference_benchmark.json：速度生値。
- outputs/value_best_eval_final/metrics.json、predictions.csv：bestの集計・episode別誤差・教師と予測。
- outputs/value_latest_eval_final/learning_curve.png/svg、learning_curve.csv：全20epochの曲線。
- outputs/value_seed_smoke_01、value_seed_replay_01：seed試験の元ログ。

## 新seedで収集する

既存の--seed整数指定は維持。既定12345も維持。通常はUnityプロセス起動時にだけRandom.InitStateし、同じworkerの次episodeでは現在の乱数状態を継続する。Unity Resetへ再seed処理は追加していない。episode_startへworker_seed/rng_mode/episode_number/収集settingsを追記した。

--seed autoで毎実行のbase_seedを選ぶ。実際に使ったseedはrun.jsonへ保存。新しい--independent-episode-seedsは学習用の明示オプションで、各episodeごとに自分のPlayerを再生成する。episode i・worker jはbase_seed+i*games+j。collection.jsonへ全スケジュール、子フォルダのrun.jsonへ実際のseed/PIDを記録。Viewer付きでは使わず、従来のViewer経路は維持する。再起動コストがあるが、Unity内部の乱数/Reset仕様を変えず再現可能なepisode開始を実現する。

短時間確認：2ゲーム×2episode×各2手、731003〜731006を使用。同じ設定で再実行し、4episodeの保持/NEXT系列が一致、全ログの報酬保存を確認。物理状態のbit単位一致までは保証しない。この試験は打切りなので学習教師にはしない。

以下はユーザーが後で行う長時間収集用。今回は実行していない：

```powershell
python play_parallel_ai.py --games 4 --episodes 25 --max-steps 1000 --headless --seed auto --independent-episode-seeds --output outputs/value_collect01
# 収集後、今回の新データだけを別の変換出力へ
.\.venv\Scripts\python.exe value_network.py prepare --input outputs/value_collect01 --output outputs/value_new_data01
```

再現するときはcollection.jsonのbase_seedを--seedへ指定する。1手先AI/予測25更新は変更していない。途中打切りがあればconverterが除外する。--independent-episode-seedsを使わない従来の連続RNGも引き続き使用可能。

## STEP7-Bへ向けた課題

現在の完了データは旧D減点方針の少数seedで、サイズ/現在接触/処理待ち等も欠ける。現方針と多様な新seedで自然GOまで収集し、別seedで評価する。必要ならUnity観測の追加フィールドを別途承認して取得する。新しい既知フラグや物理設定を含むデータは分布が変わるため、そのまま旧モデルの性能を保証しない。

STEP7-Aの「変換→学習→保存→再開→CPU推論」は確認済み。STEP7-Bは新データ品質と分割を確認し、過学習と学習曲線を見ながら進める。ゲーム接続はSTEP7-C、MCTSはSTEP8。今回Valueモデルでゲーム操作していない。

## 変更ファイル・関数

| ファイル | 主な関数と開始行 |
|---|---|
| `Python/value_network.py` | def main L8 |
| `Python/src/suika_ai/value_data.py` | def validate_episode L26 / def prepare L71 / def encode L142 / def load_dataset L174 |
| `Python/src/suika_ai/value_model.py` | class ValueNetwork L6 / def batch L20 / def predict L29 |
| `Python/src/suika_ai/value_checkpoint.py` | def atomic_bytes L10 / def save_checkpoint L16 / def load_checkpoint L28 |
| `Python/src/suika_ai/value_train.py` | def train L69 / def evaluate L44 / def write_reports L56 / def load_model L137 / def benchmark L143 |
| `Python/src/suika_ai/parallel_play.py` | def collect_worker L75 / def resolve_collection_seed L285 / def run_seeded_episodes L295 |
| `Python/play_parallel_ai.py` | def main L12 |
| `Python/tests/test_value_data.py` | class ValueDataTests L18 |
| `Python/tests/test_value_model.py` | class ValueModelTests L11 |

設定/依存定義：Python/value_config.json、Python/requirements-value.txt。今回の資料は本ファイル、DEVELOPMENT_LOG.md、DEVELOPMENT_PLAN.md、STEP6_USAGE.md。Unityファイル変更なし。
