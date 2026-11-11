# 旧AC評価監査・実ゲーム操作再生・価値教師の改善（2026-10-28）

## 結論

- 新規Test5ゲームと旧ACの学習データに、保存済みseed・初期8果物列の重複は見つからなかった。checkpointが参照したdataset manifestのhashも一致した。MAE186.1対235.8は、同じ未学習Test入力での比較として有効。ただし5ゲームの実現return誤差であり、一般的な強さ・学習法の優劣の確定ではない。
- 同じPlayer内でResetして操作tickだけ再現しても、24落下後の物理状態は一致しなかった。**起動seedを固定した新規Player同士の再実行**では、今回の24落下・1,526tickで公開された物理値が完全一致した。Reset-only再生とfresh-process再生を区別すべき。
- fresh-process方式で、2seed・8落下の同一prefixを検証し、9落下目を2候補に分岐できた。以降4落下の実測部分得点を得たが、自然GOの教師は0件。未来系列は各root1本であり、不確実性・最善手は未確定。
- 既存自然GOデータはMC教師として利用できる。一方、packed配列に終端状態がない操作間GOがTrainに3件あった。TDへ転用する際は元ログの実測終端とtail rewardを加える必要がある。終端を推測で付けなかった。
- 今回は学習・モデル選択・MCTS統合を行っていない。既存MCTS・物理・ゲームルールは変更せず、旧Test、Player、モデル、ログ、未commit変更を保持。commit/pushなし。

全成果物は `Python/outputs/replay_value_audit_01`。Playerは別保存の `Unity/Builds/ReplayAudit_01` / `ReplayAudit_02`。後者は単一prefix実行にも対応する。

## 1. 旧ACとTestの独立性

旧AC checkpoint：`step8ac_01/geometry/checkpoints/e00002_u000000258_2b75efbb.pt`。
sha256：`df0882714302d9abe621d0c9c21d6e599ffc1ae4b45a2ad371ef451e1a9ebc10`。

checkpoint内のdataset fingerprintと旧manifestの実ファイルhashが一致。通常再学習Aについても同様に確認。Testの初期8列は元の実ゲームログから再抽出し、旧AC全110ゲーム（Train77・Validation17・Test16）のmanifestと照合した。旧側の初期列欠損は0件。

| Test seed | 元ログから再抽出した最初の8果物 | 旧ACとのseed/初期8列一致 |
|---|---|---|
|405582781|0,3,2,0,0,4,0,1|0件|
|405582785|4,3,3,0,0,4,0,4|0件|
|405582792|2,4,2,1,1,1,3,0|0件|
|405582794|2,3,1,3,4,4,4,2|0件|
|405582801|4,3,0,0,4,3,4,3|0件|

同じ空盤面や短い共通局面が生じること自体は、ゲーム単位の漏洩とは区別する。公開NEXT以降の実現果物や最終得点はモデル入力に含めていない。

現在のValidation30ゲームには、旧ACのモデル選択に使ったValidation17ゲームが含まれる（旧Train/Testからの移入は0）。したがってValidationを旧ACに対する完全な未使用評価とは呼べない。新Test5件は両モデルに未使用だった。今回の再推論は凍結済み結果の監査・誤差分解だけであり、Testからcheckpoint・重み・ハイパーパラメータを調整していない。

### 評価の公平さと、原因の切り分けは別

両者は同じ43009パラメータのgeometryモデルで、同じTest入力・点数単位・terminal除外条件で比較した。一方、Train/Validation構成、初期化seed（20261027対20261029）、学習上限（30対10）、patience（6対3）が違う。旧学習にはReduceLROnPlateauもある。したがって、差を「新データだけの影響」「モデル構造の限界」と断定する対照実験ではない。選択epochは旧2、新A3。

旧Train最終得点平均2038.7、新Train2081.3。新Trainは探索設定・続行方針が混在する。データ追加が単純に悪かったことを、この平均差やTest5件だけから証明したものではない。

## 2. MAE差の発生箇所

既知terminalを除く974状態。状態数は独立試行数ではなく、独立ゲームは5件。

| seed | 実ゲーム最終得点 | 状態数 | 旧AC MAE | 新A MAE | 新A−旧AC |
|---|---:|---:|---:|---:|---:|
|405582781|2268|244|187.9|183.3|−4.6|
|405582785|1772|170|273.4|361.7|+88.4|
|405582792|2028|203|135.2|129.6|−5.7|
|405582794|1762|181|198.2|244.2|+46.0|
|405582801|1725|176|145.9|300.8|+154.9|
|全状態で集計|—|974|186.1|235.8|+49.6|

新Aが2ゲームで小幅改善、旧ACが3ゲームで良かった。seed405582801と405582785だけで、全状態MAE差の約87.5%を説明する。前者の寄与は+27.99点、後者は+15.43点（全974状態の分母で計算）。

| Test内の局面 | 状態数/ゲーム数 | 旧AC MAE | 新A MAE |
|---|---:|---:|---:|
|GO直前の最後4非terminal観測|20/5|220.4|195.6|
|現在得点2000以上|35/2|108.8|90.4|
|現在得点3000以上|0/0|評価不能|評価不能|
|実現した将来追加得点1000以上|470/5|207.6|269.2|
|スイカ存在の初回観測前後|0/0|評価不能|評価不能|

Test全体の符号付きbiasは旧+66.0、新+147.6。差の中心はGO直前だけではなく、将来returnがまだ大きい局面での過大評価。例えばseed405582801の7操作目は、現在16点、実現追加1709点に対し旧1816.2点、新2418.1点を予測した。

GO直前の平均は新Aの方が小さいが、seed405582785では375.5→444.8と悪化。平均だけでは局面ごとの問題を覆い隠す。

Validationにはスイカ初回存在観測前後が各45状態/9ゲームある。旧AC MAEは前556.3/後203.9、新Aは前532.9/後205.2。現在3000点以上は29状態/2ゲームで116.9対50.1。ただしこれはモデル選択用Validationであり、Testの不足を補った最終評価とはしない。また「初回存在を観測した前後」は、全生成・消滅イベントの完全な時刻復元ではない。

これらの結果は、モデルの構造・学習法・教師のどれか1つを原因として特定しない。単一軌跡のMCラベルには、未知果物・後続方針の違いによる実現値のばらつきがある。候補間の期待値や最適returnとは別の量である。

## 3. ゲーム開始からの実ゲーム再生

### 方法と範囲

独立したActionReplayProbeで実ゲームのResetから操作を実行した。予測PhysicsSceneや途中盤面の再構成は使用していない。合法移動とTryDropAt、元のcooldown、合体、得点、GO処理をそのまま使う。

初期操作列は `.25,.75,.5,0,1,.37` の繰り返し。基準実行で移動開始・落下・25tick後の完了tickを記録し、再実行は元のstart/drop tickで操作する。不正なタイミングなら失敗として止める。物理tick直後・Update前に位置、速度、回転、sleep、COM/慣性、接触点・impulse、合体イベント、保持果物、NEXT、得点、GO、RNGを観測した。

**これは今回新しく定義した操作列の再生であり、過去のMCTS100手ゲームを完全再生したものではない。** 後続の分岐もMCTSによる続行ではなく、共通の固定操作による短い診断である。

### 同一Player内Reset-only

2seed（99117/99118）、12落下を基準＋2再生。操作tick・果物列・得点・合体・最終GOは一致したが、数値はbit一致ではなかった。seed99117の1再生で最大角度差.01125度（診断閾値.01度）まで増加した。

さらに24落下へ延長した結果：

| Reset seed | 最大位置差 | 最大速度差 | 最大回転差 | 接触集合不一致tick数 | 得点 |
|---|---:|---:|---:|---:|---|
|99117|.01199|.49789|4.900度|83|125対125|
|99118|.07967|2.25891|11.784度|131|78対78|

いずれも操作tick・RNG・保持/NEXT・合体イベント・得点は一致した。sleepの不一致もseed99117で20tickあった。最初の微小な運動差は約421tick、複数接触する6〜7操作目から。callback順の差も観測したが、必ず運動差より前に起きたわけではなく、唯一の原因として断定しない。

相対fixed時刻は一致したが、FixedUpdateを何回まとめてからUpdateが来るかは一致していなかった。ResetではScene全体、native allocator、接触solverの履歴、Updateのまとまりまで初期化しない。どの内部状態が支配的かは未同定。

### 起動seed固定＋新規Player

startup seed=99116、Reset seed=99117、24落下を、新規Player2回で比較した。最初の基準実行同士は全1,526tickで、位置・速度・回転・角速度・質量・COM/慣性・接触点/normal/impulse・イベント・RNGが一致した。観測IDとrender frame番号は物理値から区別した。

同じ2つの新規Player内でも、各々2回目のReset-only再生では同じ大きさの誤差が再現した。新規プロセスで開始条件をそろえる方法は有望。特定のnative内部状態の原因まで証明したわけではないため、既存Resetや物理を推測で修正していない。

startup seedとReset直前のRNGを分けて記録することが重要。通常の収集では、PlayerController.Startが果物を生成してからPythonのResetが行われる。worker seedだけを再設定して「同じゲームの最初」と呼んではいけない。

密集35果物・100手以上・自然GO付近に対するfresh-process再生は未検証。GOはUpdateで確定するため、物理tickだけの一致でGO確定時相まで保証しない。

## 4. 実ゲームでの小規模分岐

各候補に新規Playerを使用。2seedとも、最初の8落下の全tick・全公開body値・接触impulse・イベント・RNGが一致したことを確認した。prefixは485tick/482tick。9落下目をx=0または.5に分岐し、その後は同じ固定座標 `[0,1,.37]` で3落下続行した。

現在果物/公開NEXTはどちらのrootもtype3/type4。未来はNative RNGのまま進め、候補間で同じ果物系列になっていることを事後確認。操作方針は事前固定座標であり、未来果物やRNGを参照していない。

| root seed | root得点 | 候補x | 4落下までの実測追加得点 | root以降tick | 自然GO |
|---|---:|---:|---:|---:|---|
|99117|0|0|29|281|未到達・打ち切り|
|99117|0|.5|19|279|未到達・打ち切り|
|99118|3|0|77|272|未到達・打ち切り|
|99118|3|.5|56|270|未到達・打ち切り|

両rootでx=0の部分得点が高かったが、自然GOまでの最善手ではない。各rootの未来系列は1本だけで、chanceによる分散や95%CIを推定できない。root間2件の差を十分な独立実験とは扱わない。

同じ4落下でも移動により総tickが2tick違う。得点差には待機中の遅延合体も含まれ、純粋な配置だけの寄与とは分離していない。実ゲームの合法行動の結果ではあるが、打ち切り境界の影響はある。

保存ラベルは `source=actual_game`、`return_kind=censored_four_drop_actual_return`、`mc_return_known=false`。自然GO学習サンプルは0。旧MCデータへ混ぜず、学習にも使っていない。分岐prefixが一致しない場合は分析ツールが候補ラベル作成を拒否する。

### 計算コスト

12落下の基準＋再生試験94.25秒、24落下試験122.78秒、fresh-process対照2回計123.63秒、小分岐4回計66.0秒。全て1Playerずつ、独立seedは2群。合計約6分47秒の限定診断で、最大24落下、自然GO収集は行っていない。

fresh-processでは24落下の実ゲーム進行が約30.6秒。再生はprefix中のMCTSを計算し直さないため、その探索コストは省ける。しかし物理tickは省略していない。比較候補K、未来系列Mなら、おおむね `K*M*(prefix再生時間+続行時間)` が必要。通常収集より自動的に速い方法ではなく、同一局面内の比較による情報価値が目的である。

高価値の遅い局面で少数分岐する使い方が候補。大量収集の置換や70/20/10等の固定配分は、まだ正当化できない。

## 5. 旧ログからの再生に不足するもの

既存ログにはrequest/movement/drop/completion tick、落下位置、drop_game_time等が既にある。全ての操作時刻が欠落しているわけではない。

一方、旧ログだけで厳密に保証できないものがある：

- 起動・各Reset直前のUnity RNG.state、既に消費した果物draw数、Resetの通算tick基準。
- 各tickの実際の移動入力・適用位置、各Update間に何回FixedUpdateが走ったか。
- 合体・Destroy要求・実Destroy・GO条件成立・GO確定の各phaseとtick。
- 観測値だけでは再設定できない接触cache、native sleep timer、内部COM自動計算履歴。

今後の再生用ログは、worker seedとepisode reset RNGを別管理し、環境/build GUID・Assembly-CSharp hash・asset識別、観測phaseを保存する。Unityのexe hashだけではスクリプトのbuild同一性を十分に表せない。未来RNGは診断専用で、モデル入力にしない。

旧ゲームの正確な復元に固執するより、**新しいfresh-process基準を作り、prefix全tickの検証に合格した局面だけ分岐教師化する**方が現実的。今回の新規prefix検証は、この方向の初期確認である。元ゲームと一致しなければ「新たな基準プレイ」として記録し、元ゲームの完全再現と偽らない。

## 6. 終端処理と次の価値教師

### TDへ転用するときの実際の不足

MCデータのTrain3ゲーム（seed763100、761118、767323310）は自然GO完了しているが、最後のpacked post-action状態ではgame_over=falseだった。操作間にGOになり、実測終端は元ログのepisode_endにある。

これはMC教師が誤っているという意味ではない。最終得点−当該得点は正しい。特にseed767323310では最後のpacked得点1797、自然GO最終1803で、tailに6点がある。最後のpacked状態をGOに書き換えたり、bootstrap=0としてtailを落とすとTD教師を誤る。

元ログのgame_over=true / truncated=false / reason=game_over、最終得点と状態得点の一致を確認して、別の `td/observed_terminals.jsonl` に実測終端3件を保存した。既存packed配列は変更していない。TD helperは終端欠損・打ち切り・split/episode混入・得点保存則違反を拒否する。

Train28,441 / Validation6,561の非終端状態について、1/3/5観測先の組を監査した。3-stepでterminalへ到達する組は396/90。TestはこのTD準備に使用していない。horizonは観測遷移数であって、秒や必ず成功した落下数ではない。

### 学習方法の比較

| 方法 | 利点 | 今回の判断 |
|---|---|---|
|MC return|自然GOの実現追加得点を直接学べる。bootstrap誤差がない|基準として維持。ただし単一未来・混合行動方針のノイズがある|
|n-step TD|既存の実ゲーム軌跡を再利用でき、分岐ゲーム不要|次の小規模比較の第一候補。終端・tail・観測phaseを先に正す|
|Afterstate|行動直後の物理結果と将来のchanceを分けて学べる可能性|phase定義が必要。現在の25tick後データは新NEXTが公開済みで、古典的なchance前afterstateと同一ではない|
|同一root順位|行動差を直接教師にでき、共通未来で分散を減らせる可能性|fresh-process基盤は有望。今回の4落下ラベルを長期最善手として訓練しない|
|追加得点＋GO head|得点機会と終了リスクを分けられる|危険度のhorizon/phaseを明記。自動ペナルティや安全保証として使わない|

TDの点数単位を統一した例：

`y_t = (S_{t+n} - S_t) + 1[実測非終端] * stop_gradient(V_target(s_{t+n}))`

最終得点を目的とするので最初はgamma=1。差分はstep rewardだけでなく、操作間の得点も含むscore差から作る。既知の実測GOではbootstrapを必ず0にする。現在のvalueが過大評価する場合、TDはそれを増幅する可能性がある。凍結/遅いtarget、MC anchorとの比較を行い、「TDなら必ず改善」と決めつけない。

同じ設定に近いデータの切り出しも可能。探索128・深さ4・5候補・wideningなし・collection時間上限なしの設定はTrain20/Validation5ゲーム。混合教師と分けた診断候補だが、データ数は小さい。実探索回数・Player識別も引き続き確認する。

## 7. 次に行う作業

最初の1つは、**終端補完・操作間reward・観測phaseを固定した実ゲーム軌跡で、同じ小型モデルのMC対3-step TDを比較すること**を推奨する。既存Test5件を再び調整に使わず、checkpoint選択はValidation、最終確認は新たな独立seed群を一度固定して行う。

理由は、同一rootの長期教師がまだなく、TDは既存自然GOデータだけで小さく検証できるため。モデル構造の大型化より先に、学習法・行動方針・ラベル時相を統制できる。

分岐基盤は並行した将来課題として保持する。次に拡張するなら、1候補1新規Player、固定startup/reset契約、prefixの実行時照合、固定したMCTS続行方針、複数の共通未来、自然GOと打ち切りの厳密区別。特に密集・GO付近のprefix検証に合格しない結果は教師から除く。全ての分岐・未来・再実行は元root seedグループと同じsplitにまとめる。

## 8. 実装と検証

新規の主なファイル：

- `Python/audit_value_independence.py`：checkpoint/data独立性・seed別誤差。
- `Unity/Assets/Scenes/Script/SuikaActionReplayProbe.cs`：実ゲームのresetからのtick操作・記録。
- `Unity/Assets/Editor/SuikaReplayAuditBuild.cs`：別フォルダへのbuild、上書き拒否。
- `Python/run_action_replay_audit.py`：1Playerずつの上限付き実行、startup seed・任意分岐x。
- `Python/analyze_action_replay.py`：tickごとの数値・接触・イベント検証。
- `Python/analyze_actual_branches.py`：共通prefix/未来の照合、打ち切り実測ラベル。
- `Python/src/suika_ai/temporal_value_targets.py`、`Python/audit_td_readiness.py`：終端を推測しないn-step組と教師監査。
- `Python/tests/test_action_replay_analysis.py`、`test_temporal_value_targets.py`：回帰テスト。

Python385テスト成功。新PlayerでMCTS861・rules127・path26のnativeテスト成功。従来32回MCTSは3固定盤面で選択位置・全候補・全nodes・全iterationsが旧Player結果と一致。

旧AC/newAのweight・manifest、過去Player、実行中の収集は変更していない。今回は大規模学習も自然GOまでの新規実験も行っていない。

### 再生診断コマンド（短時間）

```powershell
Set-Location C:\SuikaGameAI\Python
$tag = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8)
$out = "outputs\replay_check_$tag"
$env:PYTHONPATH = 'src;.'
.\.venv\Scripts\python.exe .\run_action_replay_audit.py `
  --exe ..\Unity\Builds\ReplayAudit_02\SuikaGameAI.exe `
  --output $out --seeds 99117 --startup-seed 99116 `
  --drops 12 --repeats 2 --timeout 60 --base-port 41980
.\.venv\Scripts\python.exe .\analyze_action_replay.py `
  --input "$out\ticks.jsonl" --output "$out\analysis.json"
```

これは同じPlayer内のReset-only再生の診断。新規プロセス同士の比較とは異なる。fresh-processの基準を作る場合は`--repeats 1`で別フォルダに個別実行し、そのprefix同士を検証する。得点一致だけで成功扱いしない。
