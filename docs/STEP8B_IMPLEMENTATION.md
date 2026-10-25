# STEP 8-B 初期MCTS（2026-10-22）

## 範囲と状態

developで実装。commit/pushなし。PhysicsScene2D/PathSessionを再利用し、ゲーム本体のルール、Collider、物理設定、GO比率0.83、post_drop_steps=25、epoch3モデルは変更していない。長時間ゲーム/大量比較/学習は実行していない。
初期MCTSは動作するが、接触時の物理誤差・GO見逃しは解決していない。高得点化や探索回数に対する単調な性能向上は未確認。

## アルゴリズム

- 決定ノードの各行動にN（訪問数）、W（得点単位のreturn合計）、Q=W/Nを保持。
- 未訪問の行動を先に試し、その後 `Q/point_scale + C*sqrt(log(N_parent)/N_action)` でUCT選択する。既知の直後GOは安全な代替がある限り除外。内部でも全候補GOなら既存の生存時間/超過量/heuristicの順のフォールバック。
- 新しい行動/確率結果を1つ展開した後は、一様な行動rolloutで指定深さまで進める。各手は実ゲームと同じ速度の移動、cooldown、落下、25更新。任意のinter_step_wait_ticksも物理時間として進める。
- 公開済みAとNEXT Bはそのまま使用。その後のC/Dは `PlayerController.ChooseNextFruit()` の `Random.Range(0,fruits.Length)` と同じ公開Prefabスロット一様分布。重複種類のスロットがあればその重みも維持。探索専用System.Random(seed)で抽選し、Unityの実RNGを参照/変更しない。
- 行動エッジの下に確率スロット別の子ノードを持ち、確率結果をUCTで選ばない。抽選の到着回数と、子で実際に選択した回数はarrivals/visitsで区別。
- rewardモードでは最終手の後の未落下保持果物は得点/物理に関係しないので、その直前の未知出現をまとめる（chance_slots=-2、代表slot0）。最後のさらに先のNEXTは-1（未知）。Valueモードは保持果物が評価に影響するため、その分岐を省略しない。
- mcts: `return = 終点score - 各ノードの行動前score`。
- mcts_value: 上記に `V(終点)` を一度加算。GO葉ではV=0。移動中/待機中/合体の加点はscore差に一度だけ入る。UCT以外はすべて得点単位で、55は得点を減らす係数ではなく探索項との比較スケール。
- 最終行動は直後GOを除外した上でroot訪問数最大、同数なら平均得点最大。全root GOの場合は既存フォールバック。深いrolloutのGO率は診断として保存し、根拠のない高さ/GO近接ペナルティは追加していない。

参考: [UCT原論文（Kocsis/Szepesvari）](https://sites.ualberta.ca/~szepesva/papers/ecml06.pdf)。有限回の本環境での強さや誤差のあるシミュレーターでの保証を意味しない。

## 独立性・計算再利用

各反復で現実の同じ盤面から新しいPathSessionを作り、選んだ短いprefixをネイティブ世界内で連続再生する。途中JSONから接触cacheを再構築したとは扱わない。ライブの盤面/スコア/RNG不変、同じノードの開始状態、同じ行動の物理結果が確率結果を変えても一致することを検査し、不一致は操作を中止する。
同一履歴で既に計算した最終手の結果・Value葉は再利用可能。中間状態を復元せず、末端の数値結果だけ再利用する。iteration.ticksは論理的な総更新数、simulated_ticks/total_physics_ticksは今回本当にSimulateした数、skipped_physics_ticksは省略数。SceneのUnloadはフレーム終わりなので同一Plan中のメモリは反復数とともに増える。
設定上限は反復2〜128（候補数以上）、深さ1〜8、候補2〜31。上限付近や密集盤面の計算速度/メモリは未保証。planning_budget_ms超過時は部分探索を成功扱いせず失敗し、未確定の行動は実行しない。UDP再送のaction_id重複防止は既存処理を使用。同期探索中はそのPlayerのフレーム進行が待つ（既存方式）。高速化や任意深度のcache forkは今回実装していない。

## STEP8-Aの重複

TwoStepPlanner rewardのCは2手目後に保持されるだけで落下しない。既定ではCをまとめ、候補2なら20→4経路。診断用two_step_exhaustive_reward=trueで旧全C列挙を残した。
人工的な接触/合体盤面で全Cの2手獲得点・GO・物理tick数・合体数、同じ入力の盤面位置/速度/角度/角速度が一致し、選択位置も一致。今回同一プロセスの測定は20経路69.56ms→4経路33.57ms（少数計測、起動/JITの影響あり）。Value/heuristicの旧列挙は変更していない。

## 短時間テスト

- Python unittest:118テスト通過（既存モデルは再学習せず、合成データによる既存保存再開テストを含む）。
- Unity EditorのValue入力/推論parity24盤面と既存StepPlannerProbe通過。最終Playerビルド成功。
- MCTSネイティブselftest:858 assertion通過（858個の独立した実ゲームではない）。UCTの選択集中、訪問/return保存、GO除外/全GO、未知NEXT、枝独立性、隠れ実RNGを変えても同じ探索、葉cache、Scene解放など。
- 既存PathSession selftest26項目通過。
- 実UDP: mcts/mcts_value/heuristic/value/two_stepを各2手、計10手。正しい正規化位置、連続step、Reset、source不変を確認。選択候補の直後GOと実GOの不一致0/10。ただしGO正例0なので見逃し率は評価不能。
- 4ゲーム×4手（mcts16回/深さ3/5候補）の独立Player/Viewerを確認。16手、得点・報酬保存則すべて成立、4画面をComputer Useで確認。手数上限終了であり自然GO完了ではない。Viewer/音声のコードは変更なし。録画なしheadless実通信も上記スモークで確認。
- 最終追加:64回/深さ4を実UDPで1手実行し、約111,601byteのplanning診断を分割受信できた。64訪問の保存と実際の落下Xを確認。計画345.84ms（別の空盤面でありfixture表との速度比較には使わない）。成果物step8b_large_reply/result.json。
- 新しい例外/AssertionはテストPlayerログで検出されなかった。手動キーボードの実操作と自然GOまでの完走は今回未実施。

成果物:
- Python/outputs/step8b_native_cached/result.json（最終MCTS）
- Python/outputs/step8b_path_regression/result.json
- Python/outputs/step8b_udp/results.json（実通信/物理比較）
- Python/outputs/step8b_four_view（4ゲームログ）
- Python/outputs/step8b_cache_build.log, step8b_editor_regression.log

## 時間・メモリ（5候補、25更新、同一の2果物合体fixture）

各設定1回。起動/通信/描画を含まないPlan時間。メモリはUnity allocatorの計画開始からのサンプル最大増分であり、OS working setではない。異なる反復予算で抽選/探索行動が変わるので、純粋な同一経路の速度比ではない。

| 最大深さ | 反復数 | 時間ms | Unity増分MiB | 葉cache hit |
|---|---:|---:|---:|---:|
| 2 | 16 | 50.17 | 4.41 | 0 |
| 2 | 32 | 88.68 | 8.89 | 2 |
| 2 | 64 | 141.08 | 17.60 | 34 |
| 3 | 16 | 74.51 | 4.42 | 0 |
| 3 | 32 | 138.70 | 9.03 | 0 |
| 3 | 64 | 294.33 | 17.91 | 0 |
| 4 | 16 | 98.75 | 4.51 | 0 |
| 4 | 32 | 215.48 | 9.23 | 0 |
| 4 | 64 | 422.80 | 18.29 | 0 |

mcts_valueは深さ3/16回64.12ms、約4.22MiB。root source不変。全Sceneは非同期解放後0個。
深さ2/64回は末端34回、1827物理tickを再利用。深さ3/4では64回でも今回cache hitなし。
最大深さ4は全rolloutが4手を評価する意味で、木全体を4手分列挙済みではない。64反復時も展開済み決定ノードの最大depthは2、残りはrollout。public chanceによる分岐が大きく、少数反復では木の深い部分を十分に学べない。
人工fixtureでは2/3手のreward平均は全候補1点で優劣がつかず、4手では候補ごとに異なるreturnを観測。反復増加による実得点改善は今回測定していない。node.visits/mean_points/sd_points/terminal_returns、chance訪問、選択位置をログから確認できる。sdは記述統計で、相関する適応探索サンプルの独立標本CIではない。

## 実ゲームとの物理比較とGOの制約

同一rootから2手連続、同じ入力/公開C、実測したpost tickと手間idle tickを使用。4比較時点すべてで種類・個数、得点、合体数、GO、更新数一致。2手目後のNEXT Dは未知として除外（next_type_match=falseを既知情報の失敗扱いしない）。新生成果物は種類/近傍位置対応で、元IDを共有したという主張ではない。

| 起点 | 手 | 最大位置差(Unity単位) | 最大速度差(単位/s) | 最大角度差(deg) | 最大角速度差(deg/s) | 得点/合体数 actual=pred |
|---|---:|---:|---:|---:|---:|---|
| 空盤面 | 1 | 0.000000119 | 0 | 0 | 0 | 0 / 0 |
| 空盤面 | 2 | 0.167343 | 0.364645 | 23.6330 | 50.4230 | 0 / 0 |
| 10手後の接触/合体盤面 | 1 | 0.003853 | 0.014045 | 3.0134 | 30.3598 | 28 / 1 |
| 同上 | 2 | 0.014628 | 0.067480 | 6.3675 | 9.6035 | 28 / 0 |

接触盤面は初期の接触情報が異なり、数値誤差は最初の物理tick、比較許容誤差超過は6tick目。1renderにつき最大1physics tickだったため、この数値誤差をUpdateの複数物理tickまとめだけで説明できない。
空盤面の第1手traceは数値誤差なしでも、第2手の接触後に大きな差が生じた。したがって既存接触履歴のコピー欠落だけを唯一の原因とは断定できない。接触の初期化/ネイティブSceneの生成順/衝突応答とcallback順の影響の分離は未完了。第2手は終点比較であり、誤差が始まった正確なtickまでは今回記録していない。

GOの条件そのものは共有FruitEvolution.CanTriggerGameOver（active、非preview、非merging、HasCollided、中心y>line）。ただし実GameManager.Update（GameManager.cs:31/43）と予測の各Simulate後（SuikaPhysicsSimulator.cs:394）の判定時刻、実Destroyのframe末とローカルFlushRemovalのtick末が異なる。根元のsolver cacheもコピーできない。これらの既存制約は今回変更していない。
GO付近の人工正例1盤面では全root GO/探索終了/実ゲームGOが一致。自然な危険盤面のGO見逃し頻度は測れず、既知のSTEP7-C/8-Aの問題が解消したとは扱わない。探索は葉/直後GOを処理するが、誤った予測を利用し得る。上記0.167の誤差もあるため、今は大規模な強さ比較を推奨しない。次は接触直前・GO直前rootを少数固定し、2手目以降のtick別contact/merge/GO traceを比較する。

## 起動方法（PowerShell）

```powershell
cd C:\SuikaGameAI\Python
# まず少数手。HeadlessにはViewerを同時指定しない。
.\.venv\Scripts\python.exe play_parallel_ai.py --games 1 --episodes 1 --max-steps 20 --ai-mode mcts --candidates 5 --mcts-iterations 32 --mcts-max-depth 3 --mcts-exploration 1.41421356 --mcts-point-scale 55 --mcts-seed 8191 --post-drop-steps 25 --headless --seed 744000 --require-metadata --expected-go-ratio 0.83 --output outputs/mcts_trial_01
# 監査
.\.venv\Scripts\python.exe check_parallel_data.py outputs/mcts_trial_01
# 比較可能な16/32/64回の短い実験（各出力は新規フォルダ）
foreach ($n in 16,32,64) {
  .\.venv\Scripts\python.exe play_parallel_ai.py --games 1 --episodes 1 --max-steps 10 --ai-mode mcts --candidates 5 --mcts-iterations $n --mcts-max-depth 3 --headless --seed 744001 --require-metadata --expected-go-ratio 0.83 --output "outputs/mcts_n${n}_01"
}
# 4画面（描画有効Player、--headlessは付けない）
.\.venv\Scripts\python.exe play_parallel_ai.py --games 4 --episodes 1 --max-steps 20 --ai-mode mcts --candidates 5 --mcts-iterations 16 --mcts-max-depth 3 --view-games 4 --seed 744010 --output outputs/mcts_view_01
# 2手の実通信/物理比較スモークを再実行
.\.venv\Scripts\python.exe smoke_mcts.py --output outputs/mcts_smoke_user_01 --seed 744020 --warmup 10
```

Value併用は `--ai-mode mcts_value`。既存 `heuristic` / `value` / `two_step --search-leaf reward|heuristic|value` を維持。Editor起動中の1ゲームは play_one_step_ai.py に同じMCTS引数を渡せる（Player起動は不要、Editorを先にPlay、同ポートの他クライアントは停止）。停止Ctrl+C、Viewer終了はプレイ停止とは別。自然GOまで見たい場合はmax-stepsを1000等へ明示的に増やす（GOで停止し、episodes=1なら自動Reset反復しない）。

各実験は同seed/同候補/同post horizonで揃えるが、異なる思考時間の物理進行と行動が変わるため最終得点の独立標本比較に注意。長時間比較前に上記物理不一致を調べる。

ログ: 各game_XX.jsonlのtransition.info.planning.mctsにnode/各候補のN/Q/ばらつき/GO回数/確率子、iterationの入力・乱数slot・報酬・tick・葉V・時間・cache有無を保存。一般Candidate.selection_scoreは平均点であり、最終選択はreport.selection_ruleに記載した訪問数優先。平均点が最大でない候補を選ぶことは仕様。

## 変更箇所

- Unity/Assets/Scenes/Script/MctsPlanner.cs（新規+meta）: Select、Plan、Edge.Add、各診断DTO。
- 同/StepPlanner.cs: PlanningSettings.Validate/Freeze、Planのモードdispatch、optional mcts report。
- 同/TwoStepPlanner.cs: Candidateを共用可能にし、Planのreward C重複を削減、診断用旧列挙を維持。
- 同/UDPStateProtocol.cs: SendSnapshotに有効時だけmctsを付加。JsonUtilityによる未使用reportの既定オブジェクト膨張を避ける。
- 同/SuikaMctsSelfTest.cs（新規+meta）: 数学/物理/GO/隠れRNG/再利用/性能診断。
- 同/SuikaPathSelfTest.cs: reward列挙数変更に合わせた既存検証期待値のみ。
- Unity/Assets/Editor/SuikaValueProbe.cs: 診断出力を時刻+GUIDのCreateNewにして再ビルドで古い診断を上書きしない。最初のビルドでは従来処理によりvalue_7c_parity/unity.jsonが再生成された（収集ログ/モデルではない）。その後この処理を修正。
- Python/src/suika_ai/unity_env.py: validate_planning_settings、モード/型/範囲検査。従来のstep retry/idempotence/timeoutは維持（既定のplanning猶予30秒、超過時はresetが必要）。
- Python/src/suika_ai/parallel_play.py: run_parallelの評価方式manifestのみ。
- Python/play_parallel_ai.py / play_one_step_ai.py: mainのmodeとMCTS引数。
- Python/smoke_mcts.py（新規）: bounded実通信、2手比較。
- Python/tests/test_mcts.py（新規）、test_value_live.py: MCTS設定検証と旧「mcts拒否」の期待をunknown mode拒否へ更新。
- 本資料、DEVELOPMENT_LOG/PLAN追記。

Scene/Prefab/物理設定は編集していない。Unityのビルド生成物と既存TMPフォールバック生成アセットはEditorにより更新され得るため、もともとの未コミット変更をGitの状態に戻していない。
