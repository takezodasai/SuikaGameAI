# 成功経験の抽出割合比較とデータ更新（2026-10-28）

## 結論
既存Deep Sets 36,353parameter、特徴/正規化/教師loss/初期seedを維持し、追加データと成功抽出倍率1/2/4を比較。Validation選択はB_success2。ただし成功限定のVal一致は通常を超えず、Test全体の+0.54ppもseed bootstrap区間が0を含む。4倍は一致率を下げた。データ更新だけ/成功重みだけで一貫した改善や実ゲーム高得点化を確認したとは言えない。MCTSへ未接続、ゲーム実験追加なし。

## 1. 最新データと保護
開始時にinventory.jsonへ自然GO/valid_for_return_learning/errorsなしの57新ゲームを固定。現在進行中のログを追いかけて追加しない。各新ゲームを再読し、episode/行動/状態ID、得点/step間加点/末尾加点、自然GO、root訪問数、公開NEXT/保持果物、選択/適用座標、環境一致、イベント整合性を監査。旧98ゲームはhash検証済みのpackedデータを再利用し、16GBの旧原ログを不要に再解析しない。旧原ログは変更しない。

新しい学習・選択・独立Test対象は153ゲーム33,247判断。さらに旧policy Test2ゲーム506判断をhistorical_testとして別枠保存し、学習/Validation/今回Test評価に使わない。packedデータ全体は155ゲーム33,753判断。旧AC/旧ValueNet Test群は引き続き隔離。既存Train/Validationの所属を維持し、新規seed/初期8果物系列はcorrelation groupで同じ側にまとめる。

|分割|ゲーム|判断数|seed群|スイカ成功ゲーム / 成功seed群|イベント不明ゲーム|
|---|---:|---:|---:|---:|---:|
|train|116|25,138|66|19 / 17|14|
|validation|26|5,705|15|6 / 6|2|
|test|11|2,404|11|2 / 2|0|
|historical_test|2|506|2|1 / 1|0|

新しいTestは57新群から成功/得点を使わず20%＝11群を無作為選択。その後、自然Validationに15%＝9新群を無作為選択。成功Val群3以上を不足時だけ補充する事前規則としたが、自然抽出だけで成功6群が得られ、追加の成功偏重Validationは0群。旧Val6群＋新9群＝15群。Testは結果を見て選び直していない。成功限定評価は自然分布の全体評価と別に示す。群単位での結果であり、5,705状態を独立5,705標本と解釈しない。

指定の高得点ゲーム：Job7 seed767323286/3135点とJob47 seed767323326/3106点はTrain、Job35 seed767323314/3056点とJob50 seed767323329/3126点はValidation。すべて利用。新Testには今回3000点超えゲームは入らなかったため、その領域の独立汎化は未確認。

## 2. 学習方式
モデル/feature/candidate conditioningは前回と同じ（果物30→64→64、mean/max、全体37+候補5、170→128→64→1）。CNN/GNN/新しい配置評価を追加しない。方策入力は判断開始時の公開盤面と候補Xだけ。未来ラベル/成功フラグ/最終得点は入力へ入れない。

A通常：従来のseed群→ゲーム→状態の均等抽出。
B成功2倍：同じ基礎確率に、スイカ成功が確定したゲームだけ倍率2を掛けて全体を正規化。
C成功4倍：同じ操作を倍率4で実施。

記録不明ゲームは成功倍率1のまま保持し、未生成の負例と断定しない。全ゲーム/全状態のMCTS訪問分布と選択ラベルは変更しない。成功ゲーム内の誤った判断も模倣対象になり得る。成功への貢献や全行動の正しさを認定する処理ではない。

実探索回数によるquality loss重みclip(sqrt(n/128),0.5,2)は従来どおり。成功倍率は抽出確率だけで、lossへ二重に掛けない。loss＝訪問分布CE+0.25選択CE。AdamW/lr1e-3/batch128/FP32/CPU1thread、初期seed20261028、最大20epoch/patience4、共通Validationでepoch選択。sampling倍率だけを変更。quality倍率は最適性が証明されたものではない。

|方式|成功状態の期待抽出割合|実際の抽出割合|実行epoch / best epoch|学習時間|
|---|---:|---:|---:|---:|
|A_normal|19.32%|19.46%|5 / 1|60.53秒|
|B_success2|32.38%|32.42%|12 / 8|149.58秒|
|C_success4|48.92%|48.78%|7 / 3|81.08秒|

共通の早期停止規則を使ったため最終更新回数は異なる。倍率だけでなく、最良epochまでの学習量も違い、改善をすべて「成功例の増加だけ」に因果帰属しない。Trainの損失は抽出分布が違うため方式間で単純比較しない。

## 3. Validation（全体26ゲーム/15群、成功6ゲーム/6群）
|方式|選択一致|Top2|訪問分布KL↓|成功ゲーム一致|未生成ゲーム一致|
|---|---:|---:|---:|---:|---:|
|A_normal|22.05%|41.40%|0.11549|24.76%|20.15%|
|B_success2|22.89%|42.30%|0.11674|24.64%|21.41%|
|C_success4|21.30%|40.67%|0.11587|24.27%|19.44%|
|previous_model|21.96%|40.89%|0.11607|24.33%|20.34%|

未生成評価はイベントknownかつ未生成の18ゲーム、成功不明2ゲームは別集計。Bは全体+0.84ppだが、成功限定は−0.12pp。Cは全体−0.75pp。B成功Train一致28.02%に対し成功Val24.64%で、重点学習によるTrain側への適合/分布差に注意。Aは成功Train24.72%、Val24.76%。

Validationのseed/episode macro CE+0.25選択CEを事前選択基準としてBを選択してからTestを開いた。B−Aの群macro一致差は+0.48pp、群bootstrap95%区間[−0.57,+1.54]pp。0を含む。いくつかの指標だけを選んで改善と断定しない。

## 4. 新Test（11ゲーム/11群、成功2ゲーム/2群）
|方式|選択一致|Top2|訪問分布KL↓|成功ゲーム一致|未生成ゲーム一致|
|---|---:|---:|---:|---:|---:|
|A_normal|25.79%|48.50%|0.14536|23.85%|26.33%|
|B_success2|26.33%|47.00%|0.14642|26.73%|26.22%|
|C_success4|25.17%|48.54%|0.14524|23.27%|25.69%|
|previous_model|25.17%|47.09%|0.14592|23.46%|25.64%|

成功限定520状態/2群、未生成1884状態/9群。旧モデルは同じ新Test上での固定checkpoint診断であり、旧Test28.85%と直接比較していない。旧モデル25.17→新A25.79%と僅かに上がったが、群macro差の95%区間[−0.31,+1.45]ppは0を含む。データ更新＋分割改善の一貫した精度改善とは言えない。

B−Aの群macro一致差+0.45pp、95%区間[−1.08,+1.99]pp。C−Aは−0.65pp、区間[−1.62,+0.38]pp。いずれも0を含む。2000回の群単位paired bootstrapで、状態独立の仮定は使わない。小標本/複数比較未補正の記述的区間。

BはTest成功一致を23.85→26.73%へ上げたが、Val成功では改善せず、Test Top2とKLはAより悪化。Cは一貫した改善なし。Bを比較用候補として残すが、標準AI/実ゲームへ採用しない。高得点・スイカ/ダブル達成率の改善は未測定。

## 5. 高探索教師の不足
実探索>=1024の判断はTrain424件/2ゲーム/2群だけ。Validationと新Testは0件。旧Testの高探索2群は保護し、今回のモデル選択/評価へ流用しなかった。従って、高探索MCTSに対する未知seedの模倣改善は評価できない。新しい128/256/512回の自然GOゲームが高得点だったことを、探索回数だけで教師の最適性を保証する理由にしない。

## 6. 次期価値学習用ラベル
正本は value_targets_final.jsonl / value_target_summary_final.json。判断開始時と実際の落下後の2phase、計67,506状態分（うち保護旧Test1012状態は学習対象外）。元のpolicy dataset/学習checkpointは変更せず、別ラベルファイルへ書いた。初期value_targets.jsonlは保守的な中間出力として保持し、最終版は全実測terminal board/記録済みsnapshotの正の証拠も使う。

各状態の追加得点＝自然GO最終得点−その状態の得点。step報酬や自然加点を再加算しない。未選択候補に実測returnを付けない。判断前と落下後は別の評価時点である。全67,506件で得点保存則を確認。終端状態は未来区間なし。

スイカ生成/doubleは時点以後の発生、共存はその時点より後のcallback/保存盤面で成立が確認されたかをラベル化。元の行動方針の下で観測した結果で、最適returnや必ず達成できる確率ではない。source drop数の順序または保存得点の増加で将来と確定できるeventを使う。元ログに正確なsource clockがなく、同じdrop数・同じ得点などで前後が決められない場合はunknown。保存盤面の共存は正の証拠にだけ使い、未観測を失敗にしない。瞬間的な共存が消えていた可能性を残す。

Train判断開始時25,138状態のラベル内訳：
|教師|正例/追加得点>0|負例/0点|不明|
|---|---:|---:|---:|
|追加得点|25,023|115|0|
|将来スイカ生成|3,773|18,339|3,026|
|将来スイカ＋メロン1|0|0|25,138|
|将来スイカ＋メロン2|0|0|25,138|
|将来スイカ2個共存|0|22,122|3,016|
|将来ダブル|0|22,122|3,016|

WM+メロン1はValidationの2ゲームと保護旧Testの1ゲームでsnapshot成立を確認したが、Trainに確認済み成功はない。これを理由にTestをTrainへ移さない。2個共存/ダブルは実データの成功0なので、全負例で高い正解率を出しても成功戦略を獲得したとは言えない。旧ログの共存未観測をnegativeにしてはならない。

次の価値モデルでは、まず既存value encoder/headを再利用し、正確な追加得点とknown-mask付き将来スイカ生成を対象にするのが現実的。score/count baseline・旧モデルとの比較、予測誤差に加え順位/確率calibration、seed分割、GO直前過大評価を検証する。共存/ダブルの頭は記録可能性と正例が揃うまで有効性を主張しない。次回新規収集で既に用意したLearningEvents_02の連続イベント記録を利用する案を検討するが、現在収集は切り替えない。

単に成功倍率をさらに増やすより、将来得点/生成確率という結果を学ぶ方向を優先する。同盤面の異なる行動比較には、正確な分岐状態と独立した結果が必要で、同ゲームのfinal scoreを未選択行動へ配ることはしない。MCTS root平均値は予測教師であり実ゲームのcounterfactual正解ではない。

## 7. 実装・検証・保護
- Python/src/suika_ai/policy_success_data.py：旧packedデータ再利用、最新完了ログ監査、履歴保護/結果を見ない新Test選択、成功Valの不足時補充、mask付き将来ラベル。
- Python/src/suika_ai/policy_train.py：成功倍率をsamplerだけへ追加（既定1）。既存quality loss維持、抽出率ログ、旧configに倍率キーがなくても1として再開可能。
- Python/train_mcts_policy.py：任意の1/2/4倍指定。既存コマンドの既定は従来相当。
- Python/compare_policy_success.py：固定3方式の学習/Val選択/1回だけの新Test評価/ラベル出力。世代checkpointのhashを検証し、新モデルはdataset fingerprintも確認。旧モデルの同一新Test診断は別扱い。
- Python/tests/test_policy_success.py：新規20テスト。旧split保護・同seed/初期系列・結果と独立したTest抽出・倍率1の旧式一致・倍率がlabels/quality/inputを変えない・unknown・未来時点・追加得点保存等。

Python346テスト成功（python_tests_final2.log）。既存の保存→終了→再開のparameter一致テストも成功。Unity/MCTS/物理/GO/Viewer/収集/Playerは今回変更せず、新しいビルドやゲームは実行しない。既存モデル/旧dataset/高速化の未commit変更はhashで保護。develop、commit/pushなし。依存追加なし、CPU1thread。現在の収集を停止/再開/設定変更しない。

## 8. 再利用
PowerShellで予測だけを行う（収集は操作しない）：
```powershell
Set-Location C:\SuikaGameAI\Python
.\.venv\Scripts\python.exe .\train_mcts_policy.py predict --dataset outputs\policy_success_01\dataset --model outputs\policy_success_01\B_success2 --indices 0 100
```
中断したBだけ同じ条件で再開する場合：
```powershell
.\.venv\Scripts\python.exe .\train_mcts_policy.py train --dataset outputs\policy_success_01\dataset --output outputs\policy_success_01\B_success2 --kind deepsets --epochs 20 --success-multiplier 2 --resume
```
今回はearly stop済みなので追加学習は行わない。完了結果はvalidation.json、test_evaluation.json、各split/seedのCSV、sampling_audit.json、learning_curve.png、各モデルのcheckpoints/best.json/latest.json。今回の新Testも既に評価済みなので、これを見て次期モデルを調整する場合は別の未使用Testを確保する。
