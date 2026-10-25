# STEP 7-C: Value Network導入（2026-10-22）

## 実装と評価時点

Unity 2022.3.21f1内のC# FP32 CPU推論。ONNX/Barracudaや追加UDP往復は不要。epoch3/bestの35713parametersを新規StreamingAssets JSONにexportした。元pt/best.jsonは未変更（SHA256 e7c4664a070c312c3790474cf5403cb0af2214be1803ad78b638ae1895735f6a）。JSON SHA256 7e95aee3f462afb9faa02843b9612bb018f0051b0c68349d1a89d508d2631d2c。配布する場合はPlayerのData/StreamingAssetsも含める。

共有MLP30→64→64、mean+max128とglobal37を結合、165→128→64→1/Softplus。出力を1000倍し得点単位にする。既知GOのVは0。

Q = (予測終了score − 予測開始score) + V(予測終了盤面)。移動/待機/落下後の加点を最初の項へ一度だけ含める。Vの教師は同じ時点からの残り得点で、即時得点や現在scoreを再加算しない。step間加点は既存reward_accountingへ別途記録。候補5、落下後25更新、GO=.83、物理/ゲームルールは維持。

- 通常は非GOかつdrop成功の候補からQ最大。Q差.001点以内はdrop_tickが少ない順、index順。従来heuristicのtie閾値は変更しない。
- 予測GOを除外。全候補GOは従来どおりGO tickが遅い順→terminal_excessが小さい順→従来heuristic値→index。Valueでこのfallbackを置き換えない。
- モデル/入力異常は明示エラー・命令不実行。予測失敗候補は選択対象外、全候補不明なら落下しない。resetや設定確認で復旧できる。異常時に別AIで黙って続行すると比較条件が混ざるため、旧設計のmodel異常時heuristic fallbackからこの点を変更した。
- model loadはプロセス内cache。実行中のJSON差替えは反映しない。別モデルを試す際はPlayerを再起動する。

## 特徴量の整合

`UDPTrainingMetadata.MeasureFruit`を実観測とlocal PhysicsScene2Dの両方で使用する。has_collidedは過去の接触履歴、touchingは今のRigidbody2D.GetContacts>0、sleepはIsSleeping、寸法はworld AABB半幅/半高、offsetはTransformVector。両者を混同しない。実体のCircle/Capsuleから測り、Prefab値で欠損を埋めない。

予測終了時の保持果物XY/Y既知、cooldown、AI速度、fixed_dt、score/GO、内壁left/right・floor→GO geometryも保存する。型順0..10、fruit30/global37の順序、位置/速度10/角速度360/score1000/count64/dt.02の正規化はPython encodeと同じ。サイズ/offset/接触/sleepのknownフラグを維持する。NNが使わないphysics_profile_idは予測へ複製しない。

落下後の保持果物は予測開始時に表示されたNEXT。落下後に新規抽選されるNEXTは-1/known=0。未公開の未来系列を参照しない。モデルは学習時の50%NEXT maskで未知NEXTを経験済み。実観測に比べNEXTの既知性が異なる点は仕様であり、未来情報で埋めない。物理sceneのcold contact cache誤差やlive Update/予測tick間のGO時刻差は別問題として残る。

## 起動（PowerShell）

```powershell
cd C:\SuikaGameAI\Python
# Value AI、4ゲーム、4画面、各1エピソード。自然GOまたは1000手で終了。
.\.venv\Scripts\python.exe play_parallel_ai.py --games 4 --episodes 1 --max-steps 1000 --view-games 4 --ai-mode value --seed 742600 --require-metadata --expected-go-ratio 0.83 --output outputs/value_play_01
# 従来AIは同じコマンドの --ai-mode heuristic。headlessなら --view-games 4 を --headless に置換。
# Unity Editor Playに接続し1エピソードだけ実行（並列Playerと同時使用しない）
.\.venv\Scripts\python.exe play_one_step_ai.py --ai-mode value --output outputs/value_editor_01.jsonl
```

Viewerの一覧/各gameボタン/F11、音声ON/OFFは従来のまま。Viewerを閉じてもゲームと保存は継続。収集停止は収集を起動したPowerShellでCtrl+C。自動Resetは明示したepisodes数の範囲だけ。--value-modelでexport済みJSONの絶対/相対pathを指定可能。指定なしは同梱epoch3 JSON。pt/best.jsonは直接Unityへ渡さない。

## 公平な比較（長時間実行はユーザー担当）

```powershell
cd C:\SuikaGameAI\Python
.\.venv\Scripts\python.exe compare_value_ai.py --pairs 30 --games 4 --seed 742700 --output outputs/value_compare_30_01
# 終了後の再集計（再プレイしない）
.\.venv\Scripts\python.exe compare_value_ai.py --output outputs/value_compare_30_01 --analyze-only --report-dir outputs/value_compare_30_01_analysis_01
Get-Content outputs/value_compare_30_01/comparison.json
```

30seed×両AI=60ゲーム。候補5/25更新/headless/同一exe・GO=.83。各エピソードは新規Player、同seedで両AIの果物系列の共通prefixを全手照合する。プロジェクト内のゲーム用Random.RangeはChooseNextFruitだけで、予測のsource_unchangedはRandom.stateも検査する。seedを比較方針別に変えず、batchごと実行順を交互にする。Training/Validation/Testのseed重複をsamples.jsonlから拒否（旧7-A既知seed12345〜12348も除外）。新しいdatasetを使ったモデルを比較する場合は --exclude-dataset も追加する。

comparison.jsonに各seedの得点・手数・GO・手当たりplanning_ms・推論ms・GO不一致/見逃し・step間GO・allGO fallback・報酬整合・系列一致を保存。自然GOでない/系列不一致/不整合はpaired得点差から除外し、0点扱いしない。seedごとの得点差で3000回paired bootstrap。1組だけなら95%CIを計算しない。得点平均/中央値/最高/最低は自然GO分であり、打切り数もpairsで確認する。

同seedでも方針によって盤面/移動時間/更新数は異なる。実時間・得点差だけで推論高速化や普遍的な強さを主張しない。GO直前のValue過大評価もlast5_value_diagnosticに保存（予測盤面と実盤面の物理誤差が混ざる診断）。学習済みVはheuristic方針の将来得点で、value方針の真の将来得点とは限らない。

## 実施結果

- Python98 tests成功。Unity数値/Value選択/GO除外/全GO fallback/順序不変性probe成功。最終batch build成功、コンパイル例外なし。
- 固定24盤面: 特徴量最大差0、推論最大差0.000061点。空/通常/多数/Circle/桃Capsule/回転/未知NEXT/GOを含む。
- 新seed742500の1組: heuristic1071点/152手/180.08秒、value1091点/146手/159.16秒。両方自然GO、全候補5件・source同一、共通146果物の系列一致、報酬整合。各1回allGO fallback、選択候補の予測/実GO不一致0。N=1で性能向上とは判断しない。
- Value実候補730件: Python最大差.000122点、平均差.0000210点、測定欠損0。C#推論中央値.8342ms/候補、最大3.4861ms。5候補planning平均heuristic45.55ms、value43.26msだが盤面/軌跡が違うためValueの方が速いとは判断しない。
- 終了直前の非GO4状態では将来得点を57.56〜76.63点（平均69.68点）過大評価。既知GOは0。追加ペナルティは導入せず、GO除外を維持。今回の見逃し0は将来の安全保証ではない。
- 最終Playerの4ゲーム×8手: 全32手、独立ID/報酬/環境確認成功。4画面と1画面切替をComputer Useで目視。全160候補Python最大差.000061点、欠損0。手数上限終了を自然GOにしない。
- Player例外0。headlessのshader unsupportedログは-nographics由来で、ゲーム例外と区別。音声の聴取・長時間Viewer・手動キー操作の実機再テストは未実施。ゲーム本体の操作コードは今回未変更。

データ: Python/outputs/value_7c_pair_smoke_01/{comparison.json,live_parity.json}、value_7c_viewer_smoke_01、value_7c_parity/unity.json、value_7c_final_build.log。最終のtie閾値/選択回帰追加後のPlayerは4ゲーム短時間確認済み。自然GOの1組はその直前ビルド（Q差tie閾値1e-6点）であり、最終ビルドの自然GO比較ではない。

## ファイル・関数

- Unity/Assets/Scenes/Script/SuikaValueNetwork.cs: ValueSnapshot、Load、Encode、Predict/ PredictEncoded（新規CPU推論）。
- UDPTrainingMetadata.cs: FillFruitMetadata、MeasureFruit（実観測/予測共通測定）。
- SuikaPhysicsSimulator.cs: ReadBoard、Run（予測snapshot・保持Y・NEXT未知・cooldown）。
- StepPlanner.cs: PlanningSettings.Validate、Plan、BetterNormal（mode、Q、model識別/時間/候補snapshot）。BetterTerminalは既存処理維持。
- Unity/Assets/Editor/SuikaValueProbe.cs: Run/TestAndBuild（golden/選択テスト）。StreamingAssetsのmodel/parity JSONと各.metaを追加。
- Python/export_value_unity.py: export（元モデルを変更せずJSON/fixtures新規生成）。
- Python/check_value_parity.py: check（実候補をPython再推論、NEXT漏洩/二重加算/欠損を検査）。
- Python/compare_value_ai.py: main/summarize（未使用seed、paired実行/集計）。
- Python/play_parallel_ai.py、play_one_step_ai.py: main（--ai-mode/--value-model）。src/suika_ai/unity_env.py: validate_planning_settings（後方互換の設定検証）。parallel_play.py: run_parallel（policy記録）。tests/test_value_live.py: 新規4 tests。

既存未コミット変更は保持。commit/push/新学習/MCTSなし。buildが更新するTMP fallbackの生成キャッシュは作業開始時から変更ありのためGit版へ戻していない。長時間比較でpaired得点差とGO見逃しを確認するまでValueを全面採用しない。
