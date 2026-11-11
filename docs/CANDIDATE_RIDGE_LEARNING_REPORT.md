# 候補差分ridge学習・実ゲーム動作報告

2026-11-02。学習、保存・再読み込み、Python/Unity推論、A/B選択、通常ゲーム開始から自然GOまで実装・実行した。標準MCTSへの採用はしない。既存395ファイルのSHA256は全件一致し、既存分岐教師・Player・モデルを変更していない。developを維持、commit/pushなし。

## 実装と教師

3つの既存canonical ranking.jsonlを使用。19盤面・19独立元seed群、35の盤面×未来条件。96ゲームの反復測定は6盤面として集約済みの監査データを使用し、独立教師として水増ししない。元seedまたは初期8果物系列で連結する行は同じgroupにする。重複盤面は統合し、教師が衝突する重複や続行方針の混在、予約Test19群は拒否する。既存の残り8試行は再開していない。

教師は共通未来系列ごとの自然GO追加得点差B−Aの平均。近似再構成盤面における特定のMCTS続行方針の実測結果であり、歴史的元ゲームの厳密な反実仮想や最適行動ラベルではない。未来系列の少なさによる不確実性は残る。

20個の公開特徴量：果物数、盤面高さ・平均高さ・速度・面積密度、大果物割合、スイカ数、保持果物、公開NEXT、現在得点、A/B座標、root平均報酬差・訪問比率差・標準偏差・終端率、A/B周辺の面積差・同種果物までの水平距離差。特定配置への報酬は追加していない。盤面高さは観測幾何量であり、真のGO確率ではない。未来seed・最終得点・実測return・元seedは入力特徴量に含めない。

ridgeは標準化特徴20個＋切片の21予測係数。正則化alpha=10、切片は非正則化。各元seed群の総学習重みを1にする。設定は事前protocol.jsonで固定し、結果を見た調整や探索はしていない。モデルJSONは13,494 bytesで、正規化係数・不確実性計算用行列も含む。学習一式は約0.084秒。

## 評価（開発用のみ）

元seed群を丸ごと抜く19-fold交差検証。標準化・残差・モデルは各foldのTrainだけで算出。全盤面は過去の分析対象であり、未使用独立Testではない。

|選択方式|平均選択追加得点|常にAとの差|候補順位一致率|
|---|---:|---:|---:|
|常にA|692.51|0.00|42.1%|
|常にB|738.72|+46.21|57.9%|
|ridge＋保留条件|662.80|−29.71|31.6%|

ridgeの差分MAEは302.16点、B選択は6/19盤面。平均値は独立元seed群単位。少数盤面であるうえ、今回のモデルに改善は確認できない。同じ19盤面を繰り返し調整するより、今後は別の独立rootで候補差の教師を増やす必要がある。

## 実ゲームへの接続

既存MCTS128回・深さ4・固定5候補・同期・random rollout・落下後25tickをそのまま実行する。Aは既存の最終推奨。BはA以外で訪問済み、落下成功、即時GOでない候補のうち平均報酬最大。同点なら訪問数最大、その後index最小。この既存規則は変更していない。

モデルは探索終了後、最後の実行座標だけを変更する。予測B−Aが0.25×不確実性proxyを超え、標準化特徴の最大絶対値が6以下の場合だけBを選ぶ。その他、Bなし・同座標・既知即時GOではAを維持。不確実性は学習残差とleverageに基づく尺度であり、校正済み信頼区間・統計的保証ではない。学習済みモデルが未知局面に強いと保証する条件でもない。

専用Player：`Unity/Builds/CandidateRidge_02/SuikaGameAI.exe`。専用起動flagによるopt-in。既存Playerの挙動とデフォルト設定は変更しない。初版CandidateRidge_01は新規installer flagの指定不一致により0手で終了したため、追加したinstallerだけを修正して別フォルダに02を作成した。初版の出力も保存。

## 通常ゲームの実測

事前固定した開発seed 904733101で1ゲーム実行。モデルは学習後に凍結し、結果による再学習なし。第2seedは第1ゲームが技術失敗・打ち切りの場合だけ使う計画であり、実行していない。

|指標|結果|
|---|---:|
|終了|自然GO|
|最終得点|1,950|
|落下数／判断数|214／214|
|モデル推論数|211|
|B選択／実際の推奨変更落下|26／26|
|スイカ生成／ダブルスイカ|0／0|
|ゲームwall時間|639.17秒|
|MCTS平均／p95|2,279.76／3,029.25 ms|
|特徴量抽出平均|0.00488 ms|
|ridge演算平均|0.00296 ms|

推論内訳はB選択26、外挿保留106、不確実性保留29、A予測50、有効Bなし3。推論時間はsnapshot作成・ログ・MCTSを含まず、ゲームwall時間には含む。Pythonの特徴量計算を除く1000回推論平均0.0405 ms、p95 0.0639 ms。

全判断でPythonとUnityの特徴・予測・選択、128探索とroot訪問数、元状態不変、得点保存を照合した。観測したretained scene/pending unloadは最大0。長時間メモリ試験の代替ではない。

1ゲームの完走と実際の26回の判断変更を確認したが、対応する従来MCTSのフルゲームは今回実行していない。1,950点を改善の証拠とは扱わない。3落下のfixture試験は学習盤面での作動確認であり、独立性能評価ではない。

注：ゲーム実行時に読み込まれたrunnerのresult.jsonには、eligible_B_decisions/fallback_decisionsという補助カウンタ名の取り違えがあった。元ログは保持し、analysis/summary.jsonはtraceから正しく再集計した。B選択26・変更落下26のカウンタは当初から正しい。新runnerの補助カウンタは修正済み。

## テストと保護確認

- Python unittest全481件成功（新規9件含む）。未来情報混入・重複・seed連結・予約Test・標準化・保存読込・不確実性保留・即時GO除外・起動flagを検証。
- Unity既存検査1,024 checks：ルール127、MCTS861、path26、代替候補10。全成功。
- 新規Python/Unity parity420 checks成功。特徴最大誤差5.20e−16、予測2.27e−13、不確実性8.53e−14。
- 旧StagedAction_02と新Playerのlegacy設定で3落下の観測prefix・探索統計一致。全ゲーム・全seedの同一性を主張するものではない。
- 既存395ファイルと3教師データのSHA一致、保存モデルSHAも一致。既存ソース・MCTS・物理・ルールの変更なし。
- GUI表示は本タスク未検証。実測ゲームはheadless。新規大量収集はなし。

## 主要追加ファイル

|ファイル|処理|
|---|---|
|Python/candidate_ridge.py:17|公開特徴量、45:教師読込・group、75:ridge、87:推論、117:学習|
|Python/train_candidate_ridge.py|凍結protocolから学習|
|Python/infer_candidate_ridge.py|公開JSONから単独推論|
|Python/play_candidate_ridge.py:39|専用Player起動・監査・保存|
|Python/analyze_candidate_ridge.py|実ゲームの再集計と予測照合|
|Python/tests/test_candidate_ridge.py|9回帰テスト|
|Unity/Assets/Scenes/Script/CandidateRidgeModel.cs:43|Unity float64特徴・推論|
|Unity/Assets/Scenes/Script/SuikaCandidateRidgeLab.cs:70|探索後A/B選択、実落下、ログ|
|Unity/Assets/Scenes/Script/SuikaCandidateRidgeParity.cs|Python/Unity一致検査|
|Unity/Assets/Editor/SuikaCandidateRidgeBuild.cs|別Playerへのビルド|

## 保存先・実行方法

`Python/outputs/candidate_ridge_01/` にprotocol、training/model.json、training/training_rows.jsonl、交差検証結果、parity、テストログ、normal_904733101の全判断と終了記録、analysis、verification.jsonを保存。training_rowsでは公開入力と教師・出所を別項目に保存し、特徴量は入力からのみ生成する。

追加の動作確認をユーザーが実行する場合（1200秒・1000落下で打ち切りうる。自然GO以外は有効最終returnにしない）：

```powershell
Set-Location C:\SuikaGameAI\Python
$tag = (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
$out = "outputs\ridge_play_$tag"
.\.venv\Scripts\python.exe .\play_candidate_ridge.py `
    --model .\outputs\candidate_ridge_01\training\model.json `
    --selector ridge --seed 904733102 `
    --seconds 1200 --max-drops 1000 --output $out
```

`--selector legacy`で同じ専用Playerの従来選択に切替可能。既存標準AIに自動適用されない。

## 次の判断

実装完了と性能改善は別である。現モデルは標準採用しない。小型差分モデルという接続先は動作するため、次は独立rootの追加と、少数未来系列による差分ラベルの不確実性・学習分布不足を改善する。既存19盤面での追加調整を繰り返すことは優先しない。最終採否は方式固定後の未使用盤面／自然GO比較で判断する。
