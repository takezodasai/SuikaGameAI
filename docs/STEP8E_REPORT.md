# STEP 8-E：GO整合性とheuristic/MCTS比較（2026-10-22）

## 実施結果

りんごのタグ不整合をPrefab一行で修正し、旧データとは別のルール版 `step8e-all-fruit-go-v2` として記録する。MCTSのUCT/rollout/報酬/乱数/探索予算/STEP8-D最適化は維持。Value Networkを使わない比較スクリプトを追加した。develop、commit/pushなし。既存ログ・モデルの上書き/削除なし。

## GO修正の根拠と影響

- `Unity/Assets/Scenes/Prefab/apple.prefab:19` だけが `fruit`、他10種類が `Fruit` だった。
- `GameManager.cs:49–50` は `Simulation==null && CompareTag("Fruit") && CanTriggerGameOver(height)`。`FruitEvolution.cs:26` の条件はactive・非preview・非merge・HasCollided・中心Y>GO線。りんごを除外する種類別例外はなく、資料にも例外指定はない。意図しないタグ差と判断した。
- Prefabの `m_TagString: fruit` を `Fruit` に修正。GameManager/CanTriggerGameOver/予測GOの条件・実行タイミングには変更なし。Scene側のタグ上書きも確認した。
- 予測のコピーは元Prefab/実オブジェクトのタグを保ち、STEP8-DのRegisterFruitも正しいタグを登録する。合体生成のりんごにも同じPrefabが使われるため両側で修正が効く。
- GOラインはSceneの0.83（world Y約3.299999714）、接触済み、preview/merge除外、中心座標の厳密な `>` を維持。実ゲームUpdateと予測tick単位という既存タイミング差も維持。
- 重力・サイズ・Collider・質量・進化先・得点・出現分布・速度・cooldownを変更していない。

旧データの0.83でも、りんごがラインを超えてもGOにしなかったルールだった。新しい得点は以前の50組等とそのまま比較できない。旧データや重みは保持し、今回の主比較へ混ぜない。旧Valueは同じ入力形状で動作できても、新GO条件下で較正されたモデルではない。Value/mcts_valueモードは残しているが今回使わず、再学習もしていない。

環境metadataへ `rules_version` と各Prefabの `game_object_tag` を追加。既存metadata schema1に後方互換で追加し、未知の値を実測として補っていない。Pythonの環境SHA256にもこれらが含まれる。旧Playerは最初の環境取得で拒否する。GO以外も含めペア間の環境ID・実行ファイルSHA256を検査する。

## 比較の仕様

- `Python/compare_mcts_ai.py`。heuristicとmcts専用。heuristicは得点増分/55−0.2R。MCTSはValueなし、32反復・最大深さ3・探索seed8191。
- 両者5候補 `[0,.25,.5,.75,1]`、既存のCollider/壁の安全範囲・滑らかな移動、cooldown0.4、post_drop_steps25。通常のReset/plan_step/UDPを再利用。
- 一つのゲームにつき新しいPlayer。ゲーム開始からResetを1回、自然GOまで実行し、意図しないGO後Resetはしない。最大3000操作の安全上限はあるが、到達時は打切りとして除外する。
- 通常実験は同じseed範囲を両モードで使用し、最大4独立ゲームずつ。batchごとにheuristic先/MCTS先を交互にして順番を偏らせない。
- 既存 `compare_value_ai.validate_selected_action` をそのまま再利用。落下前GOの適用座標0を実際の落下座標と比較しない過去の修正を維持。本当の座標差、違う候補、範囲外は引き続き不正として除外する。
- MCTSのroot候補には、落下前GOでも正規化Xとroot安全範囲から定まる `target_x` を記録するよう一箇所修正。従来の「落下できないのでapplied_x=0」から目標座標まで0に見えてしまうログを訂正しただけで、選択/移動/UCT/報酬を変えない。
- 各MCTS応答で完了32反復、深さ3、root訪問数合計32、全5候補評価、source/RNG/prefix検証を確認。
- 中断・worker_error・欠損・seed/系列/環境/実行ファイルの不一致・得点保存則違反・本当の座標不一致はペアを除外し、理由を残す。全予定seedを集計し、未開始ゲームも黙って捨てない。
- 不完全な比較は `status=incomplete_or_invalid`、有効/除外数を表示してPython終了コード2。結果ファイルは失敗時にも残す。正常は `status=completed`。

## 同じseedの妥当性

`SuikaWorkerOptions.Initialize:42` でUnity RNGを初期化。通常ランタイムの抽選は `PlayerController.ChooseNextFruit:183` のRandom.Rangeのみ。Startと同じ1回のResetで両者が同じ数を消費し、その後は成功した落下1回につきNEXT抽選1回。失敗/落下前GOは追加抽選しない。合体と横移動は抽選しない。heuristic予測はlive RNG不変を確認、MCTSは独自System.Randomで公開Prefabスロット分布をサンプルし、未公開の未来NEXT/Unity RNGを読まない。既存nativeテストでhidden RNGを変えても探索が変わらないことを確認している。

したがって異なる手数や移動時間でも「成功したn個目の落下」の果物は共通系列になる。初期の保持/NEXTと、実落下後に初めて公開されたNEXTを連結して比較する。片方の終了後の未公開値を推測して比較しない。短い側の実際に見えた全prefixが一致することを要求する。単にworker seed文字列が同じだけで合格にしない。

ただし両AIは異なる位置/移動時間を選ぶので、同じ盤面・同じ実時間に同じ果物を落とす実験ではない。同期思考時間、次フレームのFixedUpdateまとめ実行、UDP受信までの自然な進行もある。今回比較するのは同じ合法な時間仕様での実ゲーム総合性能であり、思考時間をゼロにした純粋な方策だけの比較ではない。

## 保存内容と統計

ゲームごとのmode/seed/最終得点/操作数/成功落下数/実合体数/最大生成・落下果物/終了理由/GO混同行列/計算時間/ゲーム実時間をcomparison.jsonへ保存。各手の状態・現在/NEXT・報酬・step間加点・選択候補・MCTS木統計は既存JSONLで保持。新しい合体/最大果物カウンターは実ゲームだけ更新し、予測で増やさない。最大果物は保持/NEXTではなく、実際に落としたか合体で作った種類の最大値。スイカ同士の消滅も合体1回として数える。

`game_wall_seconds` はReset開始から最終観測取得まで（Player起動時間を除く）。各手にstep呼出し実時間も追加。計算時間はゲームごとの平均を先に作って同じ重みで比較し、全操作をプールした値は記述統計として別記する。

主な集計は平均/中央値/最高/最低/勝敗/seedごとの差 `mcts−heuristic` /平均差/95%区間。ゲーム間を独立とし、同seedの2AIは対応ありの1ペアとして扱う。10000回のpaired-seed bootstrap percentile区間。操作/状態を独立標本として再標本化しない。n<2はCIなし。10組のCIは探索的で、外れ値やseedによる幅も見る。

GO混同行列は「選択した直近の25post-drop-tick予測」と「実際の返却状態」の比較。MCTSの奥の仮想枝GOを実プレイの正解として数えない。操作間GOは別件数で保存。GOの正例数もTP/FNとして確認できる。

## 短時間実通信の結果

seed747000、1組、各ゲーム180秒上限のsmoke。時間節約のため2モードを同時に実行し、`purpose=pipeline_smoke_not_strength` と明記した。両方とも上限前に自然GOとなり、有効1組・除外0。強さ比較の本実験データとは区別する。

|項目|heuristic|MCTS|
|---|---:|---:|
|最終得点|771|1400|
|操作/成功落下|116/116|164/164|
|実合体数|77|140|
|最大果物|type8 パイナップル|type8 パイナップル|
|実ゲーム完了時間|130.016秒|177.407秒|
|平均計算時間/手|41.23ms|365.14ms|
|GO見逃し(FN)|1|0|
|GO過剰予測(FP)|0|0|
|GO的中(TP)|0|1|
|操作間GO|0|0|

得点差+629、MCTS勝利1組。ただし1組なので95%CIは出さず、MCTSが強い証拠とは扱わない。共通する公開果物118個が一致し、環境ID/バイナリ/実行設定/得点保存/座標整合性も通過。最終盤面数39/24が成功落下−実合体数116−77 / 164−140とも一致（スイカ消滅がない今回の場合）。

heuristicの見逃しでは実状態の接触済みブドウ(type2)の中心Y=3.306842、GO線約3.299999714でGO成立。今回tickごとの原因追跡はしていないため、接触cache/UpdateとFixedUpdate差のどれが原因かは断定しない。りんご修正はルール整合性を直したもので、動的な物理予測誤差は残る。MCTSも正例1件だけでありGO精度100%とは言えない。

最終コード/Playerの通常バッチ起動も、seed747100で各1手だけ実通信確認。両方step_limitで終了し、有効0・除外1・final_scoreなし、CIなし、終了コード2となることを検証。これを自然GOとして集計していない。

## 自動テスト・ビルド

- Python全135テスト通過。集計の最後の明示係数/終了status調整後も関連9テストを再実行し成功。seed/系列/旧ルール/本当の座標不一致/上書き拒否/打切り/少数CIの回帰を含む。
- Unity最終Player：ルール84項目、既存MCTS861項目、Path26項目通過。項目数でありゲーム数ではない。
- 全11種類のタグ、接触前、preview、ライン上ちょうど、接触後ライン超過を検証。実ゲームの既存CheckGameOverと独立予測の判定を確認。type4同士→りんごの合体、既存得点15、合体後のタグ/接触済み条件、カウンター1回、Reset、予測中の実スコア/カウンター非干渉も検証。
- release_build.logでTestAndBuild成功。Value parity24例、特徴誤差0、点数最大誤差0.00006103515625。既存モデルはSHA256 `7e95aee3f462afb9faa02843b9612bb018f0051b0c68349d1a89d508d2631d2c` のまま。新規学習なし（ユニットテスト内の一時的な合成データテストを除く）。
- 最終Player `C:/SuikaGameAI/Unity/Builds/Step6/SuikaGameAI.exe` を再ビルド済み。Scene/物理設定/Collider/Viewer/音声/並列数の変更なし。
- スモーク/ネイティブの新規C#例外・worker_errorなし。nographicsのunsupported shaderログは従来どおり。

## 10組・20ゲームの実行コマンド

PowerShellで実行。最新ビルドを使う。`--smoke-seconds` は付けない。seed748000〜748009、最大4ゲーム、2モードをbatchで交互に実行する。保存先は日時＋GUIDで毎回別。

```powershell
cd C:\SuikaGameAI\Python
$comparisonOutput = "outputs\mcts_compare_10_{0}_{1}" -f (Get-Date -Format "yyyyMMdd_HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0,8))
.\.venv\Scripts\python.exe .\compare_mcts_ai.py --exe ..\Unity\Builds\Step6\SuikaGameAI.exe --pairs 10 --games 4 --seed 748000 --base-port 33000 --max-steps 3000 --output $comparisonOutput
```

終了時に集計を表示し、`$comparisonOutput\comparison.json` と `paired_scores.csv` に保存する。`status=completed`、`eligible_pairs=10`、`excluded_pairs=0` を確認し、2ファイルを結果報告に使う。rawログやmetadataも残る。seedを変えた別実験は `--seed` を変更する。同seedで再実行した結果を独立20組として混ぜない。

中断はCtrl+C。実行中の操作が完了してログをflushし、所有Playerだけを終了する。中断・失敗・3000操作上限は自然GOにせず除外する。手動で古いログを書き換えて正常扱いしない。

再集計のみ（ゲームを再実行しない、解析先も新規）：

```powershell
$comparisonReport = "{0}_report_{1}" -f $comparisonOutput, ([guid]::NewGuid().ToString("N").Substring(0,8))
.\.venv\Scripts\python.exe .\compare_mcts_ai.py --analyze-only --output $comparisonOutput --report-dir $comparisonReport
```

別PowerShellを開いた場合は `$comparisonOutput` に以前の実験フォルダのパスを設定する。既存comparison.jsonを上書きする再集計は拒否する。

## 変更ファイル・関数・行番号

|ファイル|変更箇所|
|---|---|
|Unity/Assets/Scenes/Prefab/apple.prefab:19|タグ一行のみ|
|Unity/Assets/Scenes/Script/ScoreManager.cs:12/:14/:15/:103|EpisodeMergeCount/MaxFruitType、RecordDroppedFruit/RecordMerge、ResetScoreで統計リセット|
|Unity/Assets/Scenes/Script/FruitEvolution.cs:82/:128|実ゲームだけ合体完了を記録。合体ロジックは不変|
|Unity/Assets/Scenes/Script/PlayerController.cs:169 DropFruit|実落下の種類を最大果物カウンターへ記録|
|Unity/Assets/Scenes/Script/UDPStateProtocol.cs:99 SendPacket|実カウンターの観測追加|
|Unity/Assets/Scenes/Script/UDPTrainingMetadata.cs:38/:42/:62/:155|果物タグ、ルール版、統計knownフラグ/観測フィールド、環境保存|
|Unity/Assets/Scenes/Script/MctsPlanner.cs:163 PlanCore|落下前GOでもrootの意図したtarget_xを記録。アルゴリズム不変|
|Unity/Assets/Scenes/Script/SuikaRulesSelfTest.cs:29 Start（新規、.meta追加）|CLI指定時だけルール回帰を実行|
|Python/compare_mcts_ai.py:15/:22/:35/:104/:164（新規）|paired_ci/public_series/episode/summarize/main|
|Python/src/suika_ai/parallel_play.py:75/:188|collect_worker/run_parallelに任意のルール版検査・短時間上限、step/episode実時間を後方互換で追加|
|Python/src/suika_ai/collection_metadata.py:19/:32|任意のexpected_rules_version。古いPlayerを最初の環境応答で拒否|
|Python/tests/test_compare_mcts_ai.py（新規）|9項目の比較回帰|
|Python/tests/test_parallel_play.py:129|wall_limitをGOにしない回帰|
|docs/STEP8E_REPORT.md、DEVELOPMENT_LOG.md、DEVELOPMENT_PLAN.md|今回の結果と次の判断条件|

## 次に優先すること

まず上記10組の結果を見て、対応のある得点差・勝敗・CI・計算時間・GO正例数と見逃しを判断する。差が曖昧なら同設定で新seedを追加し、都合の良いseedだけ選ばない。現時点で反復数/深さ/評価を増減しない。

次に、GO見逃しを固定盤面/tick比較で再現して探索が誤差を利用していないか確認する。その後にrollout/葉評価/予測時間/タイミングを一項目ずつ比較する。今回の一勝や、深く探索するという理由だけで強いと結論しない。Valueの再導入は新ルールのデータで再検証した後。

## 保存場所

`C:/SuikaGameAI/Python/outputs/step8e_01/`：自然GOのrawはsmoke_pair、最終集計はsmoke_audit_final、1手打切りの負例はtruncation_smoke、最終native回帰はrelease_regression、ビルド成功はrelease_build.log。途中の旧解析/検証も上書き・削除していない。今後の10組は上記コマンドで別フォルダへ保存する。
