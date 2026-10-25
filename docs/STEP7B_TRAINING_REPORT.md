# STEP 7-B 再学習・性能評価（2026-10-22）

## 結果

今回の100ゲームだけで新規に学習したValue Networkは、Test MAE161.41/RMSE212.28点。平均将来得点の定数baseline297.05/353.13、得点のみ比較モデル187.24/235.85を下回った。Testを見てepochや係数を変更していない。ゲーム操作への接続は未実装。

## データ監査

入力：Python/outputs/value_collect_100_01。既存監査を保持し、value_collect_100_01_reaudit_01へ再監査した。

- 100episodeすべて自然GO、途中終了/未完了0。
- 平均884.39点、最高1591点、最低335点。
- 12501操作/12501教師状態。board fruit記録289282件の接触/sleep/Collider情報、12501状態の保持Yが既知。
- unique seed100、重複seed/episode/軌跡/初期8果物系列の結合による重複グループなし。100相関グループ。
- 報酬保存則/step間加点/末尾加点/終端ラベル/プロファイル参照/環境hashすべて正常。除外0。
- 全100件GO=.8299999833（float表現の.83）、同一build GUID=2a82b91e2ffc4a63ab40e18dc188fe33。
- policy=step5-v3-score-roughness、weight_H=0、weight_D=0、roughness=.2、score_scale55、候補5、post_drop_steps25。旧D減点/GO=.862のデータは混ぜていない。
- 教師は自然GOのfinal_score−actual post-action score。未選択候補の予測値を教師にせず、自然加点を二重加算していない。

## 固定分割

Python/outputs/value_data_100_01、split_seed2026。episode/seed/先頭8果物系列の連結グループごとに70/15/15へ分割。

| 分割 | episode/seed/group | 状態数 | 平均最終得点 | 最低/最高 |
|---|---:|---:|---:|---:|
| Train | 70 | 8705 | 876.34 | 335/1591 |
| Validation | 15 | 1825 | 834.80 | 431/1478 |
| Test | 15 | 1971 | 971.53 | 539/1453 |

100seedは1650863096〜1650863195。各分割の全seedはoutputs/value_assessment_100_01/split_seeds.json、全episode/手数/得点はsplit_episodes.csv。状態単位のランダム分割ではない。Testは選択後に一度開き、その後の処理は診断・報告だけ（再学習・retuneなし）。Testの平均最終得点が他分割より高く、今回の15ゲームだけで普遍的な汎化性能とは断定できない。

## モデル・入力

既存ValueNetworkをそのまま使用。35713parameters、fruit30→64→64(ReLU共有MLP)→masked mean+max(128)＋global37→165→128→64→1(Softplus)。既知GOは出力0。可変個数、pad mask、空盤面を扱う。

fruitは11種類one-hot、位置、速度、sin/cos角度、角速度、HasCollided履歴/既知、AABB半幅/半高/既知、offset/既知、現在接触/既知、sleep/既知。globalは保持/表示NEXT、存在/既知、保持XY/Y既知、現在score、cooldown/speed/dtと既知、count、GO、geometry既知。NEXTは学習時50%マスクで未知状態も学習。

位置/サイズは実際の内壁幅とfloor→GO高さで正規化。score/target1000、速度10、角速度360、count64、dt .02。欠損は0＋known=0。ID/seed/最終得点/未来の抽選/先頭系列を特徴量へ入れない。質量/慣性/正確なCapsule形状はcatalogに保持するが、今回NNの追加次元にはしない。型/局所サイズ/動的情報を既存仕様で利用し、checkpoint/input_spec=value-v1-missing-awareの互換性を維持した。

## 学習と保存・再開

PyTorch2.6.0+cpu / numpy2.2.3、CPU1thread、FP32、MSE、AdamW、lr .001、weight_decay .0001、batch128、seed2026。最大30epoch、Validation MSEでbest選択、20epoch改善なしで早期停止。schedulerはpatience5/factor.5。

主モデルは1更新で保存・終了してから、別プロセスでepoch途中から再開した。best=epoch3/update207（sha256 e7c4664a070c312c3790474cf5403cb0af2214be1803ad78b638ae1895735f6a）。epoch23/update1587で早期停止。起動・データ読込・途中保存/終了・再開・評価を含む壁時計172.95秒。GPU環境の変更なし。

比較用に、同じ100ゲーム/教師/分割/構造/設定で、入力を現在得点と既知GOのみに制限したモデルを追加学習。これは意図的な入力マスクによる診断で、空の実盤面として収集したデータではない。best epoch7、early stop27、21.51秒。両モデルのbestを評価前にevaluation_plan.jsonへcheckpoint/hashとともに固定した。

latest/bestを分離し、モデル・optimizer・scheduler・epoch/update・batch順序/cursor・Python/NumPy/Torch乱数・入力仕様・分割・データ指紋・履歴を従来形式で保存。保存再開/破損fallbackの回帰テスト成功。以前のvalue_smoke_01や既存checkpointは上書きしていない。

## 精度（best epoch3）

| 分割 | NN MAE | NN RMSE | 定数baseline MAE | 定数baseline RMSE |
|---|---:|---:|---:|---:|
| Train | 136.78 | 185.33 | 271.69 | 328.88 |
| Validation | 170.28 | 222.25 | 267.92 | 326.39 |
| Test | 161.41 | 212.28 | 297.05 | 353.13 |

定数baselineはTrain状態の将来得点平均501.831を全状態に返す。Testの教師から平均を計算していない。

Testの追加比較：得点のみNN187.24/235.85、Trainのepisode最終得点平均876.343−現在得点（0下限、既知GO0）の単純baseline192.77/240.57。NNは定数baselineに対してMAE45.7%減、得点のみNNに対して13.8%減。

Testのseed/初期系列グループを単位に3000回bootstrap（1971状態を独立と仮定しない）：
- NN MAE95%区間116.91〜213.45点、RMSE143.30〜279.56点。
- 定数baselineからのMAE減少：105.42〜162.33点。
- 得点のみNNからのMAE減少：2.34〜47.41点。
- episode macro MAE156.76点。15グループだけの条件付き区間であり、別環境/方針/seed群へ無条件に外挿しない。

旧STEP7-Aの143.36点は異なるデータ・seed・GOライン・分割で測った値であり、今回との単純な改善/悪化判定に使わない。今回、旧モデルをこのTestへ評価してはいない。

## 過学習

epoch3 Train MSE=.03435、Validation=.04939。latest23ではTrain=.01983へ改善する一方Validation=.06324へ悪化し、Val MAE201.33/RMSE251.48。明確な過学習があり、latestではなくbest3を採用した。全23epochの曲線はoutputs/value_assessment_100_01/learning_curve.png/svg/csv（元学習フォルダにも保存）。

## 盤面情報を使っているか

- 同一構造・同一教師・同一分割の得点のみNNよりTest MAEが25.84点小さい。これは盤面＋保持/NEXT等の追加情報が役立つ証拠だが、純粋に位置情報だけの効果を分離した実験ではない。
- 同じ果物数・100点score帯で別episodeの実盤面と入れ替える診断：1794状態のMAE168.28→177.23、平均予測変化58.77点。globalは保持。盤面への感度を確認したが、保持と盤面の組合せが不自然になるため厳密な因果効果とは解釈しない。
- 同じ盤面の果物順を逆転した最大出力差は.000061点。FP32の丸め誤差程度。
- NEXTをすべて未知にするとTest MAE161.58、平均予測変化10.41点。未知NEXTを実測の種類0などに補完せず、known=0として処理できる。
- 予測sceneの不足項目に近いマスク（NEXT/現在接触/sleep/形状サイズ/offset/保持Yを欠損）ではMAE167.77/RMSE211.12、通常との平均出力差51.93点。実際の予測sceneの精度ではなく入力欠損の診断で、7-Cで観測と予測の特徴定義を揃える必要がある。

## Testの誤差分布

| 現在score帯 | 状態/episode数 | MAE | RMSE |
|---|---:|---:|---:|
| 0〜499 | 1118/15 | 182.93 | 238.23 |
| 500〜999 | 725/15 | 144.59 | 183.53 |
| 1000以上 | 128/8 | 68.63 | 86.10 |

| 盤面果物数 | 状態/episode数 | MAE | RMSE |
|---|---:|---:|---:|
| 1〜9 | 254/15 | 206.39 | 247.79 |
| 10〜19 | 528/15 | 169.69 | 214.92 |
| 20〜39 | 1159/15 | 150.11 | 204.80 |
| 40以上 | 30/7 | 71.24 | 87.05 |

序盤や少数果物で誤差が大きい。見えていない将来の抽選や後のプレイ結果により、同じような初期盤面でも実現最終得点は変わる。教師は1回の実現値であり、Vの本来の期待値との誤差だけではない。果物数とscore/残り時間は相関するので、上記だけで果物数が原因とは断定しない。Test全体bias=-46.96点で過小寄りだが、GO直前では逆に過大になる。

既知GO15状態はモデルの定義で0。非GOだけでは1956状態/MAE162.64。終了前5操作から既知GOを除いた60状態（15episode）は教師平均11.23点に対し予測平均108.44点、MAE/bias +97.20、RMSE101.85。60件すべて過大方向。GO付近の危険性をValueの値だけで置き換えてはいけない。

### 具体例（Test、独立episodeから抜粋）

| seed / action | 現在score / 果物数 | 教師将来得点 | NN予測 | 誤差 |
|---|---|---:|---:|---:|
| 1650863102 / 19 | 165 / 7個 | 374 | 819.81 | +445.81 |
| 1650863192 / 67 | 552 / 17個 | 360 | 747.88 | +387.88 |
| 1650863107 / 62 | 352 / 28個 | 1101 | 396.83 | -704.17 |

1つ目はGOまで67操作あり、即時のライン危険というより、その後の実現得点と期待値の大きな差。2つ目は17個中10個が小型果物。3つ目は最終1453点へ伸びたepisodeを過小評価。これらは小型果物の因果的な悪さや合体不具合の証拠ではない。全episode誤差、上位過大予測、予測/教師scatterはassessment.json/metrics.json/predictions.csv/test_predictions.pngを参照。

## 推論と計算時間

CPU1thread、warmup10/100回測定、Testの大きい盤面（最大44果物）を使用。

| 入力 | forward中央値/p95 | 特徴生成＋batch＋forward中央値/p95 |
|---|---:|---:|
| 1盤面 | .254/.462ms | .686/1.047ms |
| 5盤面batch | .328/.491ms | 2.233/3.216ms |

Python CPUで十分短い。Unity物理・UDP・Unity側実装の処理時間は含まない。主学習/保存再開172.95秒、比較学習21.51秒、最終評価/診断約8.53秒（図保存を除く）。監査/JSONL変換の時間は学習時間に含めない。

## 保存先・確認コマンド

- 主モデル：Python/outputs/value_train_100_01/checkpoints/best.json（epoch3）とlatest.json（epoch23）。実体ptはpointerのfileで指定。
- 教師：Python/outputs/value_data_100_01。
- 正式評価：Python/outputs/value_assessment_100_01。evaluation_plan.json、assessment.json、metrics.json、predictions.csv、split_seeds.json、split_episodes.csv、learning_curve.png/svg/csv、test_predictions.png/svg。
- 得点のみ診断：value_score_only_data_100_01 / value_score_only_train_100_01。実盤面の空データとして他の学習へ混ぜない。

```powershell
cd C:\SuikaGameAI\Python
.\.venv\Scripts\python.exe value_network.py infer --data outputs/value_data_100_01 --model outputs/value_train_100_01 --checkpoint best --index 0
.\.venv\Scripts\python.exe value_network.py benchmark --data outputs/value_data_100_01 --model outputs/value_train_100_01 --checkpoint best
```

今回は保存後の再開を実際に実施済み。epoch数を増やす再学習やTestでのモデル選び直しは今回行わない。

## 変更とテスト

本番ゲーム/学習モデル/訓練処理は変更せず、分析用Python/analyze_value_performance.py（assess、score_only、masked_snapshot、cluster_intervals、board_shuffled、plots）とtests/test_value_assessment.pyを追加。全94テスト成功。保存→終了→別プロセス再開を実データで確認し、既存の連続学習対再開の重み/optimizer/RNG一致・破損fallbackテストも成功。今回はUnity操作/新しいゲーム収集は実施しない。

本資料/STEP7C_DESIGN.md/DEVELOPMENT_LOG/DEVELOPMENT_PLANを更新。既存ログ/モデル/未commit変更を保持、commit/push/追加backupなし。入力仕様の変更なし。GPU/依存package導入なし。

## STEP 7-Cの判断

限定した導入・比較実験へ進む根拠は得られた。未選択5候補のValue精度/行動順位/実ゲーム得点の改善はまだ未検証であり、全面置換は推奨しない。まず予測snapshotの不足を埋め、同じ入力でUnity/Pythonの出力を合わせ、GO除外/fallbackを維持したうえで未使用seedによるpaired実ゲーム比較を行う。設計詳細はSTEP7C_DESIGN.md。今回は接続せず終了する。
