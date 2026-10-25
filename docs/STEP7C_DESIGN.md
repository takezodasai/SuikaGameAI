# STEP 7-C 導入案（2026-10-22、設計のみ）

今回の承認は再学習・評価まで。ゲーム操作への接続、Unityコード/Packages変更、モデルexportは行っていない。

## 推奨：既存5候補予測＋Unity内CPU推論

現在のネットワークは35713パラメータのDense/ReLU/mean/max/Softplusだけ。Pythonの学習/checkpointを正本とし、将来7-Cでは入力仕様と重みを版番号・SHA256付きでexportし、Unity内CPUで同期評価する方式を第一候補とする。小さなC#評価器なら可変果物数を切り捨てず扱え、追加UDP往復を避けられる。ただしC#実装の速度・数値一致はまだ未測定であり、Pythonから自動生成したgolden入力/出力の一致検証を導入前の必須条件にする。

代替はONNX＋対応するUnity推論runtime。現Packages/manifest.jsonには推論packageがなく、今回は導入しない。PyTorchはONNXへのgraph exportを提供し、Barracuda 3.0の公式演算子一覧にはReduceMax/ReduceMean/Whereがある一方、Shapeはconstant shapesのみという制約がある。mask、空盤面、-inf、動的果物数の変換は実機検証が必要。「ONNXへ出せばそのまま一致する」とは判断しない。

一次資料：
- https://docs.pytorch.org/docs/2.6/onnx.html
- https://docs.unity3d.com/Packages/com.unity.barracuda@3.0/manual/SupportedOperators.html

既存Python PyTorchを推論serverにする案も可能。ただし往復待ちの間に実ゲームが進むため、同じ候補元盤面に対して選択できたかをtoken/episode/state/fruit IDで確認し、不一致は再計画する必要がある。Time.timeScaleで勝手に盤面を止める方式は採らない。初版はUnity内の同期評価を推奨する。将来Python MCTSからは同じ重みと入力仕様で直接評価できる構成にする。

## 必要な既存コードの接続箇所

- SuikaPhysicsSimulator.cs ReadBoard（L180）：現在は種類/位置/速度/回転/角速度/HasCollidedが中心。予測側の現在接触・sleep・Collider AABB/offsetを、local sceneが生存している間に観測と同じ定義で取得する必要がある。今回は未変更。
- SuikaPhysicsSimulator.cs Run（L253）：移動＋cooldown待ち＋落下＋既存post_drop_steps=25を維持し、完了時点のcurrent_fruit、geometry、cooldown、speed、固定dtを含むコンパクトsnapshotを生成する。
- StepPlanner.cs Plan（L125）：現在はResultの果物配列をCandidateへ残していない。5候補すべてを同一sourceから予測し、snapshotを保存/評価してからChoose（L173）で選ぶ。予測失敗/GOの除外と全候補GO時の既存フォールバックは維持する。
- JSON量/GCを抑えるため、通常実行では全候補の完全ログ保存を必須にしない。検証時だけsnapshotと評価内訳を残し、候補用オブジェクトは従来どおり破棄/再利用する。

## 入力時点・NEXT・報酬の定義

source時点の得点S0、候補の既存step完了時点得点S1、同じ時点の状態s1を使い、

Q(s,a) = (S1 - S0) + V_points(s1)

とする。Vの出力は最終得点ではなく、s1からの残り獲得得点。両項は生の得点単位で、55で割る係数や0.2Rをそのまま混ぜない。NNの内部出力だけ1000倍してpointへ戻す。予測中の移動/cooldown/落下後の加点は(S1-S0)へ一度だけ含め、現在のsource前のstep間加点や、S1以後の自然加点を再加算しない。教師(final−S1)にはS1以後の自然加点が既に含まれている。

既存Simulatorのdrop tickとpost counter、実ゲームの完了cached snapshotの境界をgolden比較で一致させる。25更新は静止までの待機ではない。移動時間を省略した評価にはしない。

予測後に保持する果物はsourceで表示されていたNEXTなので既知。一方、その後に新たに表示されるNEXTは予測時点では未知であり、next_fruit_type=-1、next_known=0とする。sourceのNEXTを「予測後NEXT」として使い回したり、Unity RNGを先読みしない。今回モデルは学習時50%のNEXTマスクを使い、Testの全NEXT非表示でもMAE161.58（通常161.41）だった。

## 同じ数値を使うための検証

1. InputSpec v1、30 fruit/37 globalの順序、world座標基準、velocity/10、omega/360、score/1000、count/64等を固定する。
2. 観測と予測でAABB/offset/接触/HasCollided/sleep/保持Yの意味とknownフラグを揃える。Prefabから未知の実体値を補完しない。
3. 0/1/通常/300果物、Circle/桃Capsule、unknown NEXT、既知GO、回転、padのgolden snapshotをPythonとUnityへ渡す。
4. feature vectorとmaskの一致を先に検査し、FP32出力差は当面0.01点以下を合格目標とする（未達なら原因調査）。Q差が数値誤差より小さい場合のtie-breakも定義する。
5. 5候補のsource token・種類・果物数・移動/drop/post更新数・加点区間を確認する。物理sceneのcold contact cache誤差はNN推論誤差と区別する。

現在のSimulatorに近い欠損マスクを実観測Testへ適用すると、MAE167.77、通常入力との平均予測差51.93点だった。この数値は本物の予測sceneの正確性ではなく、欠損による入力差の診断。無条件で既知フラグをfalseにして接続するより、必要な測定値を揃えることを優先する。

## 計算時間

今回のCPU PyTorch測定（1thread、44果物まで）：1盤面は特徴生成込み中央値0.686ms/p95 1.047ms、5盤面batchは2.233ms/p95 3.216ms。forwardのみ5盤面中央値0.328ms。通信・Unity物理予測・C#処理は含まず、Unity側の時間の保証には使わない。7-C時に実際の5候補全処理とheadless4ゲームの速度を計測する。GTX1070のGPU環境整備は初版では不要と考える。

## 誤評価への対策と公平な比較

- 予測GOは従来どおり除外。既知GOのV=0も維持。全候補GO時は既存処理。
- schema/shape/mask不一致、NaN/Infinity、model読み込み失敗、予測失敗、source不一致では、不正なNN出力を採用せず従来AIへfallbackして記録する。
- GO直前の過大評価（非GOの終盤60状態で平均+97.20点）は残る。NNをGO判定の代わりにしない。
- このVは現在のheuristic行動方針でのMonte Carlo将来得点であり、最適な将来得点ではない。新しいNN方針で訪れる盤面には分布差がある。実行後の新方針データによる改善は、別途許可を得て行う。
- 実ゲームへの導入を許可されたら、未使用の30seed程度で小規模なpaired比較から始め、後で100seedへ拡大する。同じビルド/GO=.83/5候補/25更新/速度/操作間隔/headless条件とし、モデルを固定する。
- 同じseedの初期果物系列を対応させ、最終得点・中央値・最高点・手数・打切り率・平均step時間・step間経過時間・fallback/GO見逃しを記録。差はepisode/seed単位のpaired bootstrapで評価する。別々のゲーム進行を同じ盤面と誤認しない。
- offline Testを見てモデルを再選択しない。実ゲーム比較もTestとは別のseedにする。未選択候補へ実際の最終得点を教師として付けない。
- 位置/予測値のMAEが大きくても、同じsourceの候補間で誤差が相殺する場合がある。逆に小さな評価差で順位が逆転する場合もある。今回のoffline MAEだけでは行動順位・最終得点の改善は証明できない。

## 判断

限定した7-Cの検証実装へ進む根拠は得られたが、即時全面置換や高得点化の保証はしない。最初は「予測snapshot整合→Unity/Python出力一致→GO除外/fallback維持→未使用seedで実ゲーム比較」の順に進める。今回はここまでを設計として残し、接続コードは実装しない。


## 2026-10-22 実装時の確定事項

STEP 7-C実装・短時間検証はSTEP7C_USAGE.mdへ記録。CPU C#推論、共通metadata測定、Qは得点単位。model/schema異常時はheuristicへ黙って切り替えず、比較条件保護のため明示エラーで命令不実行とした。予測GO除外と全GO fallbackは変更しない。Value Q差.001点以内はdrop tick/indexの順でtie break（旧heuristic閾値は維持）。学習・物理・GO条件は変更しない。
