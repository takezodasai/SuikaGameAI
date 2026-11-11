# 学習方策とランダムを混合するMCTS rollout

2026-11-03。学習・Unity内推論・通常開始から自然GOまで実装・検証した実験用モード。標準MCTSには採用しない。

## 自然GOの実測結果

事前固定した開発seed904734101、探索seed8191で1組のみ実行。128回・深さ4・固定5候補・同期。モデルと設定はゲーム結果を見て変更していない。

|指標|従来の一様rollout|学習方策50%混合|
|---|---:|---:|
|終了|自然GO|自然GO|
|最終得点|2,089|2,152|
|落下数|220|225|
|スイカ生成／ダブルスイカ|0／0|0／0|
|平均判断時間|2.112秒|2.292秒|
|p95判断時間|2.723秒|2.786秒|
|判断計算時間合計|464.59秒|515.68秒|
|ゲームwall時間|622.44秒|694.31秒|
|探索内物理tick合計|5,980,339|6,164,488|
|rollout行動数|57,394|59,893|
|学習方策使用数|0|29,205|
|全探索行動中のrollout割合|52.35%|52.99%|

開始公開状態は一致し、確認可能な果物列222個の共通prefixがすべて一致。両方式の探索は実ゲームの生成RNGを消費していない。以後の盤面と操作は異なるため、物理進行の完全共通性を意味しない。

新方式は＋63点・＋5落下だったが、独立seedは1群だけで、強さの改善やダブルスイカ到達率向上の証拠には不足する。平均判断時間は約8.5%増。途中盤面や最終NEXT抽選の省略条件も異なるため、時間差の全部を方策推論の負荷とはみなせない。

学習方策の使用率はrolloutの48.76%。実ゲーム全体の方策処理はsnapshot取得込み3,181.56ms、1判断平均14.14ms、1方策呼出平均約0.109ms。MCTS判断計算時間の約0.62%に相当し、推論そのものの負荷は小さい。モデルは4,904 bytes。実ゲーム中の推論fallback・技術エラーは0件。既知即時GOを選び、なお安全候補が存在するケースも0件。

ログ境界のretained Scene／pending unloadは両方式とも最大0。Unity allocatedの観測最大は新方式44,689,423 bytes、従来44,595,759 bytes。プロセス実メモリ全体や探索中の瞬間最大を測定した値ではなく、一般的な長時間リーク耐性を証明するものではない。

全387既存ソースのSHA256、既存学習データ3ファイルのSHA256に変更なし。保存モデルSHAは`81d9f3b581a7b0c7533096c01c63bdc57ab6c300f467e5c4206b42c60eb3111e`。現在実行中の収集には干渉していない。

## 実装

既存MctsPlanner.csの同期UCTでは、新規action/chance枝を展開した後の残り深さがrolloutになる。そこではランダム行動が選択され、生成済みdecision nodeでの選択には従来UCTが使われる。今回、独立クローンLearnedRolloutPlanner.csを追加し、rolloutでの行動選択だけを軽量方策と混合した。UCT、backup、root最終選択、報酬、物理計算は元の処理を使用する。

固定5候補、128回探索、深さ4、同期、落下後25tick。各rollout行動で確率0.5で学習方策の確率分布から抽選し、残りは従来の一様ランダム。混合判定には独立System.Random、行動・chance抽選には探索用System.Randomを使う。実ゲームのUnityEngine.Randomは使わない。mix=0では追加の探索用乱数を消費せず、従来選択と一致する。mixは0〜1で設定可能。

最終段のNEXTを物理得点に無関係として代表値にまとめる既存最適化は、NEXTを入力とする学習方策では成立しない。そのため学習rollout有効時だけこの省略を解除し、公開されたsimulated NEXTを既存と同じ確率で抽選する。未来系列を知って選択するのではなく、探索内で抽選された現在の公開状態から行動する。混合率0・従来MCTSは元の省略を維持する。

不正な公開状態、非有限の推論値、対応外候補数などではランダムへfallbackする。既存のtree内即時GO除外と最終候補選択は維持するが、rollout中の各候補を追加物理検証するわけではなく、将来GOしない保証はない。

## 学習

既存policy_success_01/datasetの通常ゲーム履歴を使用。固定5候補で検証済みの判断に限定し、既存Train/Validationのseed・初期8果物・group分割を維持。Testとhistorical_testの2,910判断は学習・評価から除外し、予約Test19との重複も拒否する。固定5候補以外など9,846判断は除外。新しい収集はしていない。

- Train：81自然GOゲーム、66seed群、17,311判断。
- Validation：16自然GOゲーム、15seed群、3,686判断。
- 特徴：公開盤面の種類別個数、位置・速度、現在得点、保持果物・公開NEXT、候補周辺の種類別密度や同種果物までの距離。人間の配置攻略法や追加報酬は導入しない。
- 213係数の線形candidate scorer＋softmax。固定スケール・範囲clip。既存ニューラル方策の再学習・大型化は行わない。
- 教師：root訪問分布75%＋MCTS最終選択one-hot25%。元seed群の総抽出重みをそろえ、既存の実探索回数由来quality_weightを適用。
- Adam、学習率0.03、L2=0.01、25epoch、seed20261103を事前固定。Validation CE最小のepochを選択。ハイパーパラメータ探索なし。
- 所要約20.74秒。未来seed・最終得点・将来returnは特徴量に含めない。

|評価|Train|Validation|
|---|---:|---:|
|教師分布cross entropy|1.59607|1.60015|
|MCTS最終選択との一致率（group/quality加重）|29.17%|28.55%|

Trainで作った固定選択頻度priorのValidation CEは1.60851。改善は小さく、強い方策の証拠ではない。これは既存の開発用Validationであり、新しい独立Testの性能ではない。1手方策単独の得点改善も主張しない。

## Playerとログ

使用Playerは `Unity/Builds/LearnedRollout_03/SuikaGameAI.exe`。既存Playerは保存し、新規Playerも01/02を残している。01の監査ログ不足を修正して02を作成、02の自然GO未完了試行はNEXT省略の問題を発見して停止し、03で再検証した。途中試行を自然GO教師や得点比較には含めない。モデルはその間も凍結し、得点を見た再学習やseed変更はしていない。

各判断の公開状態、root候補統計、選択座標、探索128回監査、物理tick数、tree/rollout行動数、深さ別rollout、学習・ランダム・fallback回数、学習行動分布、snapshot込み方策推論時間、モデルSHA、実ゲームイベント、得点、GO、Scene解放状況を保存。PythonとUnity間の方策推論通信は不要で、重みを起動時に読み込んでUnity内で推論する。

## 検証

- Python全487テスト成功（新規6件）。公開特徴量、未知未来情報の非使用、正規化、候補依存、NEXT入力、元MCTS不変、最終NEXT省略解除を検証。
- Unity既存ルール127、MCTS861、path26、合計1,014 checks成功。
- 新規方策parity74 checks成功。Python/Unity確率最大差8.33e−17、元状態・実ゲームRNG不変、不正geometry拒否。
- 03で3落下のmix=0と従来モードの公開盤面・root統計・物理tick・操作・RNGが一致。50%混合の同seed再実行も一致。長期・全seedの完全再現性を保証するものではない。
- 隔離した故障注入モデル（有限な巨大係数によりlogitをoverflow）で840回の不正推論がすべてランダムfallbackし、3落下を完了。これは短時間の安全処理検査であり、自然GO性能評価ではない。学習済み本モデルを変更していない。

通常試行開始時のrunnerでは、従来モードの`rollout_totals`が「学習モジュール未実行」の0を保存していたため、集計では全判断の`search.rollout_calls`から従来の57,394回を再構成した。元JSONは保持し、現行runnerの保存処理は修正した。旧A/Bアダプタ由来の補助カウンタも本比較には使わず、現行runnerでは削除している。正しい集計は`analysis/summary.json`を参照。

## 保存先と実行

`Python/outputs/learned_rollout_01/` に事前protocol、学習モデル・評価・parity、短時間検査、通常ゲーム、集計を保存する。

```powershell
Set-Location C:\SuikaGameAI\Python
$tag = (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
$out = "outputs\learned_rollout_play_$tag"
.\.venv\Scripts\python.exe .\play_learned_rollout.py `
    --model .\outputs\learned_rollout_01\training\model.json `
    --selector mixed --mixture 0.5 --seed 904734102 `
    --seconds 1500 --max-drops 1000 --output $out
```

`--selector legacy`で従来MCTS、`--selector mixed --mixture 0`でクローン側の一様rolloutに切替可能。1500秒・1000落下の上限で打ち切られた結果は自然GO得点に含めない。GUIの`--view`はCLIにあるが本タスクでは検証していない。既存標準AIを自動変更しない。

## 主要追加ファイル

- Python/learned_rollout.py：公開特徴量と確率。
- Python/train_rollout_policy.py：既存データ読込・分割監査・固定条件学習・保存。
- Python/play_learned_rollout.py：専用Player・MCTS判断・rollout回数監査、実ゲーム記録。
- Python/verify_rollout_native.py、Python/tests/test_learned_rollout.py：短時間回帰検査。
- Python/analyze_learned_rollout.py：自然GO試行の集計と保護ハッシュ確認。
- Unity/Assets/Scenes/Script/LearnedRolloutPolicy.cs：213係数の推論と混合・fallback。
- Unity/Assets/Scenes/Script/LearnedRolloutPlanner.cs：元MCTSから分離したrollout実験。
- Unity/Assets/Scenes/Script/SuikaLearnedRolloutLab.cs：通常ゲーム実行・監査ログ。
- Unity/Assets/Scenes/Script/SuikaLearnedRolloutParity.cs、Unity/Assets/Editor/SuikaLearnedRolloutBuild.cs：一致検査と独立ビルド。

既存ソース・Player・モデル・ログ・未commit変更を保護し、developを維持。commit/pushなし。

## 判断と残る問題

実装・学習・未来行動への接続・自然GO完走は達成した。今回の接続は最終候補を選び直す方式ではなく、rolloutの行動を変えた結果としてUCTの評価・訪問配分が変わる方式である。ただし得点＋63は1組の実現値にすぎず、現時点では標準変更を支持しない。

方策はMCTS模倣であり、最適な長期戦略やダブルスイカ成功returnを直接学習したものではない。Validationの改善も小さい。実ゲームと予測Sceneの既存誤差、実盤面とrollout盤面の分布差は残る。不正値fallbackは正常動作しても、有限値の「戦略的に悪い予測」を検出する機能や、校正済みの分布外判定は未実装である。

次に採否を判断するなら、このモデルを凍結したまま少数の未使用開発seedを事前固定し、同一思考時間でも得点が改善するかを確認する。今回の1組に合わせた学習・混合率調整や、大規模な追加収集は実施していない。
