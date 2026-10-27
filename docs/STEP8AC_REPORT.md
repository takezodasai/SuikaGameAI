# STEP 8-AC：長期価値モデルのオフライン試作（2026-10-26）

## 結論

小型モデルのデータ作成・学習・保存再開・CPU推論・独立Test評価まで実施した。MCTSには接続していない。Test MAEは新モデル265.45点、同じデータで従来構造を再学習したモデル276.30点、得点＋果物数だけのridge272.84点。独立単位をseedにすると新旧再学習モデルのMAE差は−3.72点、近似bootstrap95%区間[−15.08,+5.97]で0を含む。

順位付けは新モデル66.47%だが、条件が一致したTestは4seedのみ。Validationでは新61.09%、従来構造再学習61.90%で一貫した改善ではない。GO直前の過大評価も残る。高得点化・ダブルスイカ戦略を獲得したとは判断せず、標準MCTSとimportanceを維持する。

## 1. ログ監査と利用範囲

- 主対象：budget_compare_20261024_220548_138aaaf4、placement_long_20261025_034450_25dabcbd、allocation_compare_20261025_191427_486b4db4、importance_stable系列、legacy_sync系列。
- 自然GO・得点保存則・操作受理・UID・状態／環境カタログを検証できた110ゲーム、23,089状態、346,105果物レコード、39seed/初期系列グループ。
- 内訳：budget18、placement78、allocation12、importance1、legacy_sync1。保存完了記録から確認し、progressは使っていない。実験の再開・停止はしていない。
- 主対象の中断2・worker_error2・完了記録なし1は教師化しなかった。自然GO以外にfinal_scoreを推定して付与していない。
- 拡張監査で独立プレビュー／thinkingの自然GO4ゲーム・890状態も確認。総監査114ゲーム・23,979状態。主対象の分割と学習を固定した後に発見したため、今回のTrain/Validation/Testへ後付けで混ぜず、audit_summary.jsonに別枠で記録した。これは不良データという意味ではない。
- 全利用データは物理環境fingerprint 50deed681ae35f9c3ce6a7f1e5728ddeaa6227511d777697b84a6d9aeb1cb673、rules_version=step8e-all-fruit-go-v2、GO比率0.8299999833。同じbuild GUIDかではなく、壁・果物asset・物理定数・ルールの実内容を比較。Unityバージョン／ビルドGUID等の非物理識別情報は別途元カタログに保持。
- 全状態で果物の種類・位置・速度・角度・角速度と現在果物／公開NEXTが取得できた。全346,105果物レコードで接触済み・touching・sleeping・Collider測定情報あり。23,089操作にroot探索統計がある。これらは原ログに残し、候補や未来サンプルはモデル入力にしない。
- 入力欠損には従来のknown flagを継承。存在しない接触情報等を実測値に補完していない。

イベントはsource=actual_gameかつknown=trueのみ採用。92ゲームで確認可能、18ゲームは不明。スイカ生成10ゲーム（10/92）、合計10個、2個目生成0/92、ダブル成功0/92。不明18件を未達成と数えていない。

## 2. 教師と保存形式

教師 G_t = 実際の自然GO最終得点 − 実際に選ばれた操作後状態の現在得点。実行した方策による観測returnであり、最適行動を取った場合の達成可能最高得点ではない。step報酬とstep間加点を再加算しない。未選択候補・予測盤面にはこの教師を付けない。

対象最終得点は1,174〜3,147点。Game ID/episode ID/seed/方策設定は監査・分割・層別評価用に保持し、ネット入力にはしない。最終得点と教師も入力から分離。NEXTは保存時に画面公開されていたもののみ。学習時は50%を未知扱いにする既存方式を維持。

新規出力：Python/outputs/step8ac_01/

- dataset/states.jsonl：実際の操作後状態、geometry、教師、出典。分割はrecords.jsonlが正本。
- dataset/records.jsonl：episode/seed/group/split、現在得点、教師、操作ID、方策、果物数等。
- dataset/fruits.f32＋offsets.npy：果物数可変の連結30特徴、ragged offset。
- dataset/globals.npy：37特徴、targets.npy：G/1000。
- dataset/manifest.json：元ログSHA256、派生ファイルSHA256、環境、分割、除外理由、イベントの監査情報。
- 生ログは行単位で読み、巨大なMCTS traceを学習用メモリへ保持しない。チェックポイントはデータmanifestのfingerprintに固定し、読込時に核心データのhashも検証する。
- records.steps_to_goは終端までの保存記録数（当該記録を含む）であり、物理tickではない。GO直前評価はこれの単純閾値ではなく、各episodeの最後の非終端5記録で計算する。操作間GOも含む。supplemental.jsonがこの補正集計の正本。

## 3. 分割と学習方法

|分割|ゲーム|状態|seed/系列グループ|
|---|---:|---:|---:|
|Train|77|16,439|27|
|Validation|17|3,370|6|
|Test|16|3,280|6|

split seed=20261027。同一ゲームseedと初期8果物系列をunion group化してから分割。同じseedのlegacy/grid9/widening等も同じ側になる。全seedと分割はmanifestに保存。旧ValueNetが学習・選択に使ったseed/初期系列との重複をTrain固定するガードを設けたが、今回該当は0組。

Train seed：759400,759401,759402,759405,759406,759407,759408,761100,761102,761103,761106,761108,761109,761111,761112,761115,761116,761118,761119,761120,761121,761122,761124,761125,763100,763101,763102。
Validation：759404,761101,761105,761107,761110,761114。
Test：759403,761104,761113,761117,761123,765100。

Trainはseedグループ→episode→状態を均等に選ぶ置換抽出。長いゲームや同seed3方式が過大な学習重みを持つことを緩和。MSE、AdamW、lr1e-3、weight_decay1e-4、batch128、FP32、CPU1thread、最大30epoch、Validation停滞6epochで終了。ReduceLROnPlateau(patience3,factor0.5)。最良checkpointはValidationのseedグループmacro MSEのみで選択。

Testを開く前にevaluation_plan.jsonへ比較モデルと条件を固定。Test結果を見て構造・係数・epochを再調整していない。各epochのlatest/bestはatomic pointer＋hash検証付き。モデル、optimizer、scheduler、epoch/updates、設定、split、入力仕様、乱数、sampling generatorを保存。今回の再開境界はepoch末。epoch途中の厳密再開は未実装。

## 4. モデル

従来構造の再学習対照：果物30→64→64共有MLP、masked mean＋masked max、全体37と連結→128→64→1、Softplus。35,713パラメータ。

新モデル：同じDeep Setsに現時点の配置57特徴を追加、連結222→128→64→1。43,009パラメータ。保持果物・NEXTは盤面占有に含めず全体特徴として渡す。

追加57特徴：8区画のCollider上端skyline、接触済み果物だけのskyline8、種類別AABB面積合計11、種類別最近同種ペア距離11、ペア存在11、最高body中心／上端／高さ標準偏差／接触済み割合／sleep割合／平均速度／サイズ既知割合／geometry既知の8。Collider offsetを反映。面積はAABB合計でunion面積ではない。ペア距離は盤面正規化座標上の距離で、実世界等方距離ではない。密集や配置を見る低コスト近似であり、合体可能性を保証しない。

位置・Collider寸法は壁内幅と床〜GOライン高さで正規化、速度/10、角速度/360、角度sin/cos、得点/1000、果物数/64、fixedDeltaTime/.02。追加高さ／距離は[0,2]clip後/2。Train/Testからラベル依存の正規化定数を推定しない。0果物・可変数・未知NEXT・順序不変性に対応。出力はG/1000で学習し、推論時に×1000して得点単位。既知GOは厳密に0。

新モデルのみ補助順位lossを追加：
L = MSE(Ghat/1000,G/1000) + 0.05 * mean softplus(−sign(G_i−G_j)*(v_i−v_j)/0.25)。
異なるseedグループ、現在得点差≤100点、教師差≥100点のbatch内pairだけ使う。0.05等は初期診断設定であり最適値ではない。配置追加とloss変更を同時に試したため、改善を個々の変更へ分解して主張はできない。

旧入力37+30のcheckpointと新37+57+30は互換でない。kind、入力仕様を保存し、既存Unity用v1 exportに新モデルを渡さない。

## 5. 評価結果

表は保存状態ごとのMAE/RMSE（点）。checkpoint選択には別のseed-group macro MSEを使った。

|モデル|Train MAE/RMSE|Validation MAE/RMSE|Test MAE/RMSE|Test順位正答率|
|---|---:|---:|---:|---:|
|Train平均return|581.47/691.87|537.07/627.74|565.83/670.63|50.00%|
|Train平均最終得点−現在得点|308.33/390.20|270.12/351.75|285.24/394.34|53.13%|
|現在得点＋果物数 ridge|289.90/372.48|233.14/305.02|272.84/371.20|63.34%|
|旧epoch3固定ValueNet|667.91/817.85|548.61/671.38|598.06/748.66|59.06%|
|従来構造を再学習|261.47/351.31|240.00/306.69|276.30/376.77|59.47%|
|新配置＋順位モデル|269.62/353.31|237.56/303.20|265.45/360.95|66.47%|

順位評価は異なるseedの盤面同士で、同じ方策設定、現在得点100点bin、同じ保持果物／NEXT、教師差100点以上に限定。予測差1点未満は同点0.5。Test1,214pair、1,370状態、4seed（placementの761104/761113/761117/761123）。全Test6seedが順位比較に使えたわけではない。1,214pairを独立標本と数えていない。seed単位の重みbootstrapで新モデル正答率95%区間[56.41%,78.89%]。観測された異なる盤面のreturn順位であり、同じ盤面からの反実仮想行動順位ではない。

Validation順位は新61.09%／従来再学習61.90%／ridge63.89%。新モデルが一貫して勝っているとは言えない。混合方策を許すsecondary順位は別にevaluation.jsonへ保存。全状態Spearmanにはゲーム進行に伴うG減少という簡単な相関が含まれるため、主根拠にしない。

Testのseed-group macro MAE：従来再学習280.03→新276.31（差−3.72、95%bootstrap[−15.08,+5.97]）。ridgeとの差の補足比較は−9.06、区間[−17.61,−0.50]だが6seedの探索的分析であり、有意性や実ゲーム高得点化の確証としない。

新モデルのGO直前5記録×16ゲーム＝80状態はMAE218.62点、bias+218.62点。従来再学習は+202.03、旧固定は+53.70。全体誤差を下げても終盤の過大評価が改善するとは限らない。既知GO出力0でも直前状態は別問題。

Testの果物位置・速度・寸法等を除き配置57特徴をTrain平均へ置換した診断では新MAE423.66へ悪化（通常265.45）。盤面特徴に依存していることと整合するが、入力分布を壊す診断なので長期戦略の因果的な獲得証明ではない。

従来再学習はepoch3が最良、9で終了。新モデルはepoch2が最良、8で終了。学習誤差が下がってもValidationが悪化する過学習傾向。optimizer学習区間は各13.22秒／12.72秒（データ読込・配置特徴前計算を除く）。全評価40.73秒。学習曲線とTest散布図はevaluation.png、全予測はpredictions.csv、score/果物数/方策/GO帯はtest_bands.csv、episode別はtest_episodes.csv、過大評価上位はoverestimates.csv。GO最後5記録の補正はsupplemental.jsonを参照。

CPU推論：新モデルforwardのみ1盤面中央値0.230ms／5盤面0.289ms。31果物等の入力dictからencode＋配置57特徴＋paddingまで含めると1盤面1.53ms、5盤面6.71ms（JSON/Unity IPC除く）。ベンチマーク環境の短時間値で、実ゲーム速度保証ではない。

## 6. 以前のValueNetが強さを改善できなかった理由

旧モデルはGO0.83でもりんごGO修正前の100 heuristicゲーム、今回とは方策・得点分布・ルール版が違う。旧Test MAE161.41は今回の598.06と同一条件ではなく、悪化・改善の直接比較はできない。今回の同データ再学習対照を置くことで、旧モデルとの差を構造だけの効果と誤認しない。

STEP7-Cの50pairはheuristic872.14/value850.56、value−heuristic−21.58点、95%区間[−118.60,+67.56]。誤差が小さくても候補順位・GO直前の偏り・予測leafとの分布差により行動改善しない可能性がある。単一の原因を実証した結果ではない。Monte Carlo教師も当時の実行AIのreturnであり最適価値ではなかった。

## 7. 不足するデータと次の作業

110ゲームでも独立39組、Test6組しかない。78ゲームが128回探索の3候補方式に集中し、importance自然GOは1ゲームだけ。現在の強い探索設定へ対応した価値関数の評価は不足。スイカ状態は少なくダブル成功教師は0、3,147点を超える高得点領域もない。ここからダブル達成確率を学習すると全0のモデルになり得る。

推奨する次の作業は、**既存データからGO直前の過大評価を検証する専用セットと評価を固定し、未使用seedのimportance／標準MCTSの自然GOログを少量ずつ追加する計画を立てること**。終盤・大果物・スイカ後状態の監査を優先し、単純ridgeと現モデルを再度比較する。収集は今回は実行していない。追加4プレビューを使う場合も、既存Testへ恣意的に足さず新しい分割計画を宣言する。

## 8. MCTSへの統合設計（未実装）

既存MctsPlannerは得点単位のreturnを逆伝播し、UCT内部だけ明示scaleで除算する（MctsPlanner.cs:58,357〜363）。将来のleaf adapterも得点単位で統一する：
Q_visit = (S_leaf − S_visit) + V_remaining(s_leaf)。
Gの基準はleafに保存された現在得点。そこまでに得た合体得点をVへ再加算しない。既知／予測GOのleafはV=0とし、現在の予測GO候補除外・全GOfallbackはそのまま。

次の接続前条件：
1. PythonとUnityで30/37/57特徴の順序・Collider offset・欠損flag・normalizationを一致させ、固定盤面の数値比較をする。新checkpointは旧Unity推論器に直接読ませない。
2. 25tick後の教師状態と、MCTSのcooldown／次操作可能境界のleaf時点を区別。移動待ち中加点もS_leafへ含め、現在果物と公開NEXTの時点を一致させる。未公開NEXTはone-hot0＋known0。実ゲームと予測の接触キャッシュ差は価値モデルで解決した扱いにしない。
3. 元環境・観測欠損・果物数／得点域・方策ごとの分布外判定を持つ。今回の単一モデルは校正されたconfidenceを出さない。単なる出力値や候補差を自信と扱わず、Validationで校正を確認してから、未対応時は既存reward-only評価へfallbackする。根拠のない高さ／GO近接減点は追加しない。
4. 実際に選ばれた操作の予測leafと実状態を比較してからshadow評価へ進み、その後に別seed自然GO対応比較。offline順位向上だけでは有効化しない。

## 9. 実装ファイルと検証

- Python/src/suika_ai/long_value_data.py：build（行33）streaming監査・packed dataset、load（行127）hash／分割検証。
- Python/src/suika_ai/long_value_model.py：geometry_features（行13）、GeometryValueNetwork（行38）、PackedBoards（行49）、infer（行68）。
- Python/src/suika_ai/long_value_train.py：rank_loss（行23）、train（行31）、load_trained（行75）。
- Python/src/suika_ai/long_value_metrics.py：point_metrics（行27）、matched_pairs（行33）、ranking_metrics（行52）、near_terminal_ids（行70）。
- Python/train_long_value.py：plan（行21）、fit_baselines（行35）、evaluate（行47）、main（行107）。
- Python/tests/test_long_value.py：7テスト。教師／保存則／中断拒否／未来ラベル不使用／可変数・0個・未知NEXT／順序不変／順位pair／GO直前抽出／epoch再開一致／split leakage拒否。
- Python/tests/test_unity_step.py：既存再送テストのみ模擬時計に変更。旧テストは実時間0.27秒に対して0.25秒後の再送を要求し、全テストで2回失敗、単独では成功した。GC／スケジューリングが20ms窓をまたぐ影響を除いた。通信実装は変更していない。
- 最終Python285テスト成功（7.485秒）。実際のcheckpoint保存→別train呼出で再開し、連続2epochとの全パラメータ完全一致を確認。推論専用CLIを別プロセスで確認。
- Unityコード・Player・MCTS・importance制御・Scene解放は変更なし。今回Unityビルド／実通信／自然GO実験は行っていない。
- 旧epoch3のbest.jsonと参照ptのSHA256不変を確認。過去データ／旧Playerは読取のみ。develop維持、commit/pushなし。

## 10. 再利用コマンド

保存済みモデルのオフライン推論（ゲームは起動しない）：
```powershell
Set-Location C:\SuikaGameAI\Python
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe .\train_long_value.py predict --dataset outputs\step8ac_01\dataset --output outputs\step8ac_01 --kind geometry --indices 0 100
```

新たな学習を別出力で再現する場合のみ（今回の評価済みTestを見ての再調整には使わない）：
```powershell
Set-Location C:\SuikaGameAI\Python
$env:PYTHONPATH = "$PWD\src"
$out = "outputs\long_value_reproduce_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\train_long_value.py plan --dataset outputs\step8ac_01\dataset --output $out
.\.venv\Scripts\python.exe .\train_long_value.py train --dataset outputs\step8ac_01\dataset --output $out --kind v1
.\.venv\Scripts\python.exe .\train_long_value.py train --dataset outputs\step8ac_01\dataset --output $out --kind geometry
.\.venv\Scripts\python.exe .\train_long_value.py evaluate --dataset outputs\step8ac_01\dataset --output $out
```
学習中断時は同じtrainコマンドへ --resume を追加。Test評価済み出力への追加学習／評価上書きはCLIで拒否する。今のモデルを実ゲームで使うスイッチはまだ追加していない。
