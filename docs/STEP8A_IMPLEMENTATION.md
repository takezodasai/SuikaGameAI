# STEP 8-A：2手先物理予測の基盤（2026-10-22）

同じnative PhysicsScene2Dで2手を継続する基盤と少数候補のdepth-2 expectimaxを実装。本格MCTS/UCB/rollout/学習は未実装。実ゲームとの完全一致は達成していない。接触中の起点からは1更新目から誤差があり、深い探索やGO安全性を検証済みとはしない。

## 状態遷移と枝分離

- SuikaPhysicsSimulator.PathSessionが盤面、壁、床、保持物、接触キャッシュ、HasCollided、sleep、合体処理、score、次のtick時刻、drop許可時刻を保持。Advanceを繰り返し、2手目の開始時にJSONから作り直さない。
- 分岐は同じ実盤面から独立Sceneを作り、短いaction prefixだけを再生する。1手後のnative solver cacheは枝の中で継続する。Unityには接触impulse/cacheの完全なfork APIがないため、別枝の中間盤面をSerializeして同一状態と偽らない。episode開始から全履歴を再生する方式ではない。
- 同じx1のprefix snapshot（果物ID/type/運動/接触フラグ/保持/score/GO/tick）が全枝で一致することを検査。不一致・計算budget切れは命令を実行せず明示エラー。実盤面/score/Random.stateの不変性も確認する。
- 同時保持で予測用Wallまで実ゲームのFindObjectsOfTypeに混入する問題を発見。同じSceneのWallのみを使う条件を追加。壁やCollider自体は変更しない。
- Disposeは無効化してUnloadSceneAsyncを予約。テストで解放後の予測Scene数0を確認。root作成時にpending mergeがある場合は既存どおり拒否し、未完了合体を偽って再構築しない。Resetで無効になったrootは次の行動を拒否する。

## 25更新と次の意思決定

1手は移動＋必要なcooldown待ち＋落下したtick＋落下後25更新。25は静止条件ではない。次の保持物があり、GOでなくstep lockが解除された操作境界から2手目の移動を開始できる。drop cooldownが残っていても移動は開始し、目標で許可時刻まで待つ。Native試験でpost=1の短い境界でも正しく待機することを確認した。

ライブはLateUpdateで完了を返すため、1描画フレーム内に複数FixedUpdateが走れば25より多くなる場合があり、UDP往復や次の計算中にも入力までの時間差がある。ツリーではinter_step_wait_ticks（初期0）を明示し、WaitTicksでその間の物理・合体・加点も進める。移動中/待機中に物理を止めない。

比較用path_probeは実操作開始と同じUpdate内で独立したroot世界を確保する。2手が終わった後、実際のpost更新数と操作間idle更新数を使って保持したrootを再生し、時間条件を一致させる。これは正確性のための事後検証であり、事前の探索が将来の通信遅延を知っているという意味ではない。次のaccept時刻を完全に予測できるとはしない。

## NEXT・確率・得点単位

現在保持A/表示NEXT Bから開始。1手目でAを落とし、Bが保持物になりCが新NEXTとなる。Cはroot時点では未知なので、ChooseNextFruitのRandom.Range(0,fruits.Length)と同じ公開Prefab slotの一様分布を使う。重複slotは重複確率を持つ。実Random.stateは抽選しない。現在は5slotなので2候補×5chance×2候補=20経路。

Cの仮定オブジェクトは実ゲームと同じ落下tickで更新し、表示用bodyは物理停止・trigger・previewとして扱う。2手目はBを落としCが保持物になる。その先のDは未知（next=-1）。未公開の実Dは読まない。各chanceで2手目の候補を選んでから、その最良値を確率平均するため、rootが未来Cを知って最初の行動を選ぶ処理にはしない。検証時だけ、1手後に公開されたCと対応する事前コピーを照合する。

- reward：R1＋操作間待機加点＋R2。
- heuristic：上記得点 − score_scale×weight_roughness×R（初期55×.2）。既存heuristicの盤面項を得点単位へ換算し、獲得得点を二重加算しない。H/Dは追加しない。
- value：上記得点＋V(2手後の盤面)。既知GOの将来価値は0。モデルは元のepoch3のまま。

2手目では非GO候補を優先し、全GO時は既存の生存tick/excess/heuristic fallbackを利用。rootでは1手目GO除外を維持し、2手後のGO確率が小さい候補→期待得点が大きい候補の順で選ぶ。根拠のない高さやGO距離penaltyは追加しない。rootが全GOなら従来のfallback。future GO確率は予測器の推定であり安全保証ではない。

## 実ゲーム比較（最終通信版）

| 初期状態 | 手 | 位置最大差 | 速度最大差 | 角度最大差(度) | 角速度最大差(度/s) | 予測/実score | 予測/実ticks |
|---|---:|---:|---:|---:|---:|---|---|
| 空盤面 | 1 | 0.00000000 | 0.00000000 | 0.00000 | 0.00000 | 0/0 | 45/45 |
| 空盤面 | 2 | 0.00000000 | 0.00000000 | 0.00000 | 0.00000 | 0/0 | 64/64 |
| 8手後の接触・合体盤面 | 1 | 0.01183531 | 0.09409161 | 1.83234 | 2.82542 | 25/25 | 45/45 |
| 8手後の接触・合体盤面 | 2 | 0.03323010 | 0.05415666 | 6.00720 | 9.27217 | 31/31 | 65/65 |

上の2盤面では両手とも種類/個数/保持種類/得点/GOが一致。接触盤面は開始10点→1手後25点→2手後31点で、2手合計獲得21点（15＋6）が実/予測で一致。接触盤面は各手1合体ずつ一致。最終通信版では1手後の現在接触に1果物の違いがあり、HasCollided履歴/sleepは両手一致。2手後のNEXT Dはunknownで、NEXT一致とは計上しない。2手目の新しい生成IDはローカル負数なので、元IDが残る果物を優先し、新規果物はtype/近傍位置で対応付ける診断。新規IDの完全一致を保証する検査ではない。

追加の接触盤面テスト（step8a_contact_tree、最初から8手進めた別setup）では2手後の最大位置差0.013235/速度差0.004802、種類・個数・得点・GO一致、idle更新2。続けて実盤面9果物から20経路を探索し、prefix一致/source不変を確認。

前の短時間実行（step8a_smoke_final）では2手後の最大位置差.036625/速度差2.409224、角速度差21.5759も観測した。こちらも得点/種類/個数/GOは一致。実ゲームの受付時刻/接触盤面が異なる試行であり、通信の省略化によって物理精度が改善したという比較ではない。都合のよい最終試行だけで精度を判断しない。

## 誤差・GOに関する確認事項

- 接触盤面ではtraceのtick0で位置・速度は一致、接触情報は不一致。最初の数値・許容値超過はいずれもtick1。tick1の最大位置差.000476947、速度差.0233334。その試行の各描画フレームは物理更新1回で、移動・post数は一致。
- 確認済み：起点をcloneした瞬間の接触情報は実際と同じではない。native内部のcontact impulse/warm start/broadphase履歴をRigidbodyの数値コピーだけでは保持できない。ここから接触誤差が育つという説明に整合するが、Unity内部のどのcache項目だけが原因かまでは特定していない。
- 確認済みのコード差：実GameManager.CheckGameOverはUpdateで判定、予測はSimulateごと。実Destroyは描画frame末、予測はtick末の無効化。この違いは複数tick/frameで一時的なGOや合体後の再衝突を変え得る。今回の空盤面試行で最大2tick/frameも観測したが、GO候補の一時出現は0。今回の接触数値差を全てタイミングだけのせいにはしない。
- 正常なHasCollided=falseの上ライン果物はGOにしないこと、trueなら実/予測ともGO、terminal枝への次入力拒否は専用fixtureで確認。危険な実盤面でのGO見逃し改善率を示すテストは未実施。前回50組の見逃し24/18を今回直したとは主張しない。
- 診断にはfirst_trace_diagnostics（最初の不一致tick・初期接触・物体状態）、first/second_timing（frameごとのtick数・一時的GO候補）を保存。今回のGameManager/GO=.83/物理設定は変えていない。

## 計算時間とメモリ

| 盤面/評価 | 経路 | 探索時間ms | Unity割当メモリの観測増加MiB | 管理メモリ増加KiB |
|---|---:|---:|---:|---:|
| 合体fixture/reward | 20 | 59.35 | 5.48 | 184.0 |
| 合体fixture/heuristic | 20 | 52.90 | 5.48 | 136.0 |
| 合体fixture/value | 20 | 68.45 | 5.64 | 228.0 |
| 実盤面9果物/reward | 20 | 171.84 | 6.22 | 336.0 |

Profiler.GetTotalAllocatedMemoryLongとGC.GetTotalMemory(false)を使用。OS working set/GPUメモリの測定ではない。Unity割当は各経路の後でsampleした値で真の瞬間peakではない。Scene解放予約から完了までの物理オブジェクトを含む。モデル初回読込/非同期解放の完了時間は探索timer外。3方式を同じframeで実行すると解放待ちが積み上がるため64経路までに制限。解放後の予測Scene数0、Unity割当44,574,094 bytesを確認。長時間のメモリ耐久測定は未実施。

## テスト

- Python115 tests成功（新規4件：leaf/wait/互換設定/action_idとprobe応答）。
- native26検査成功：枝分離・1手prefix一致・warm native継続・合体/得点・操作間加点/clock・cooldown・NEXT更新・未知未来の拒否・GO接触フラグ・実GO・Reset失効・Scene全解放。
- 既存Value24 golden盤面のfeature差0、推論最大差.000061点、従来選択/GO fallback probe成功。
- 最終Playerの4ゲーム×2手＋4画面Viewerを確認。ゲームID/報酬整合、worker errorなし。heuristic/valueの各1手も確認。音声の聴取・長時間Viewer・長時間GO比較は未実施。
- 初回診断でambiguous_side_wallsを検出しScene filterで修正。最終Playerの例外0（headlessのshader unsupportedは既存の描画なしログ）。

## 使用方法

```powershell
cd C:\SuikaGameAI\Python
# 2手先、2候補、得点のみ。まず少数手で確認する。
.\.venv\Scripts\python.exe play_parallel_ai.py --games 1 --episodes 1 --max-steps 10 --ai-mode two_step --search-leaf reward --candidates 2 --headless --seed 743200 --output outputs/step8a_play_01
# --search-leaf heuristic または value で切替。--ai-mode heuristic/value は従来の1手先。
# 4画面は --games 4 にし、--headless を --view-games 4 に置換。
# 実測2手比較（空/接触盤面、warm root探索、各leaf/既存mode。短時間用）
.\.venv\Scripts\python.exe smoke_two_step.py --output outputs/step8a_check_01
```

候補数は--candidates（two_step省略時2、従来mode省略時5）。各階層同数、総経路n²×spawn slotsが64以下。初期post25、--post-drop-stepsで変更可能だが通常比較は25を維持。--inter-step-wait-ticks 0/1/…500で操作間の物理待機を指定。timeout/不一致/予算不足は成功にせず既存resetで復旧。出力先は新規フォルダを指定。PlayerはBuilds/Step6へ最終ビルド済み。

C# API例（chanceSlotは公開fruits[]の仮定index、実際の非公開抽選値ではない）：

```csharp
using (var path = new SuikaPhysicsSimulator.PathSession(player, manager, floor))
{
    var first = path.Advance(0.25f, 25, upcomingPrefabIndex: chanceSlot);
    if (!path.GameOver) path.WaitTicks(interStepTicks);
    if (path.CanAcceptAction) { var second = path.Advance(0.75f, 25); }
}
```

PathSessionそのものが復元可能なnative状態。Result/ValueSnapshot JSONから接触キャッシュを完全復元できるとはしない。

## 変更ファイルと役割

- SuikaPhysicsSimulator.cs: partial化、InitializePathでroot copy抽出、RunがPathStateのclock/held/NEXTを継続、床もlocal cloneを参照。旧Predict入口を維持。
- SuikaPredictionPath.cs（新規）: PathSession、Advance、WaitTicks、Snapshot、CanAcceptAction、Dispose、仮定NEXT生成。
- TwoStepPlanner.cs（新規）: 深さ2/公開chance分岐、LeafPoints、期待値・GO確率評価、prefix/source検査、timer/memory。
- PlayerDropPlacement.cs: Wall列挙のScene条件だけ追加。壁の数値/形状/サイズは未変更。
- StepPlanner.cs: two_step dispatch/settings、search_score/terminal_probability、normal比較。従来heuristic/valueとroot全GO fallbackを維持。
- UDPStateProtocol.cs: 空の任意診断を通常観測へ送らないようにNonSerialized＋必要応答での明示付加を使用。diagnostic無効時の約10KBの空構造を除去。planning.two_stepも有効な探索応答だけに付加。
- UDPPathComparison.cs（新規）: root保持、二つの実stepとの比較、GO/tick診断。UDPStepProtocol.csはopt-in hookのみ追加。
- SuikaPathSelfTest.cs（新規）: 明示CLI -suikaPathSelfTestだけで動く所有Player内のテスト。通常実行には追加しない。
- Python/src/suika_ai/unity_env.py: 新設定検証とopt-in path_probe転送。parallel_play.py: policy version記録。play_parallel_ai.py/play_one_step_ai.py: 新CLI。
- Python/smoke_two_step.py（新規）、tests/test_two_step.py（新規）。各Unity.metaはUnityが生成。

## MCTSへの拡張と残課題

次段階ではdecision node→chance node→decision nodeとして、PathSession.Advance/WaitTicksとLeafPointsを共通利用できる。root状態token＋action/chance prefixをnode履歴とし、深いleafを同じprefixから再生する。native cacheを持たないJSON hashだけで厳密な盤面同一性を主張しない。UCB/訪問回数/バックアップ/rollout/仮想損失などは今回未実装。

本格MCTS前に、GO付近の追跡fixture、複数tick/frame・Destroy/Update時刻差の検証、分岐prefixの長さに伴う誤差増幅、待機tickモデルの比較、解放待ち/メモリbudgetを確認する。GO判定を共通の論理tickへ揃える設計やframe scheduleを明示する設計は候補だが、実ゲームのタイミング変更に当たるため今回は行わない。起点のcache誤差の軽減も未解決。現状は2手先基盤の実験実装として扱い、完全に正確な探索器・高得点化検証済みとは扱わない。

成果物: Python/outputs/step8a_wire_smoke（最終通信版）、step8a_wire_build.log、step8a_smoke_final（先行計測）、step8a_contact_tree、step8a_native_final、step8a_four_view_smoke、step8a_build_final2.log。GO=.83、Collider/ゲームルール/モデル不変更、commit/push/追加バックアップなし。

最終通信版でも空盤面・接触盤面の2手比較、3 leaf、既存heuristic/valueの実通信が成功。既存modeのplanningに空のtwo_stepは含まれない。
