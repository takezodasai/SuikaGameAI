# STEP 8-C 信頼性・Viewer調査（2026-10-22）

## 結論

停止の主因は、UnityのUDP受信Updateから同期実行するMCTS。探索中に通常のFixedUpdate・frame・UDP送信・映像出版の増分がすべて0であることを実測した。Time.timeScaleを0にする停止ではなく、メインループに戻れない停止。Viewerだけの描画停止ではない。
現行の15fps映像上限に加え、終盤相当35果物では1手約0.8〜1.1秒のMCTS停止が発生する。Viewerの画像コピーを改善したが根本停止は未解消。非同期探索・落下タイミングの自由化は設計のみで、実装していない。

予測では保持ブドウの重心/慣性を誤って固定する具体的な不具合を確認し、予測コピーだけ修正。空盤面起点の2手目床接触の位置差0.167343→0になった。既存接触盤面・GO発生tickの誤差は残る。

## 実測条件と限界

成果物はPython/outputs/step8c_01。developを維持しcommit/pushなし。Scene/Prefab/物理設定/GO0.83/評価関数/モデルは編集していない。全AIモードとViewer操作を維持。
最終採用データはfinal_performance（各workerで序盤2手、密集盤面2回、計56手）。5候補、MCTS32回、深さ4、post25、seed744100+worker番号、音声OFF。1条件で完走ゲームは収集していない。
密集盤面は旧50組ログの実際の35果物配置・速度・回転・HasCollidedを現Prefabで再構成。自然に進んだゲームのsolver cacheや睡眠タイマーは復元できない。コマンド受理までの実物理更新も少し異なり、5条件は厳密な同一ネイティブ状態の対照実験ではない。同一workerの繰返しも独立標本ではない。n=2/8なのでp95は実質最大値で、母集団の安定した尾部推定ではない。学習/長時間得点比較は未実施。

最初の診断再構成ではNEXTのFruit.originalPrefab不足で例外が出た。また一律のFruitタグ設定では旧りんごタグを再現できていなかった。診断コードだけ修正し、baseline/baseline_02は最終比較には採用していない。ファイルは削除せず保持。

## 5条件比較

時間はStepPlannerの計画時間ms。FPSは全短時間試験の新規画像Tk提出fps（active_display_fps）であり、序盤/終盤別や実モニターのphoton fpsではない。CPUは所有Player+Viewer合計の論理12CPU全体に対する平均、OS全体CPU使用率ではない。メモリは0.2秒間隔で標本化した同時working set合計最大MiB。

| 条件 | 序盤/密集n | 序盤中央値ms | 密集中央値ms | 密集p95=最大ms | Viewer fps | CPU | メモリMiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| heuristic / 1 / Viewer | 2/2 | 50.3 | 140.9 | 234.8 | 13.4 | 5.2% | 183 |
| heuristic / 4 / Viewer | 8/8 | 51.2 | 63.3 | 80.0 | 11.6–12.3 | 18.0% | 716 |
| mcts / 1 / Viewer | 2/2 | 209.7 | 830.0 | 856.1 | 9.5 | 8.0% | 199 |
| mcts / 4 / Viewer | 8/8 | 388.4 | 1057.1 | 1085.5 | 8.4–9.6 | 24.3% | 788 |
| mcts / 4 / headless | 8/8 | 381.9 | 1057.3 | 1111.2 | — | 43.7% | 554 |

- 全計画でメインスレッドIDが開始時と同じ。FixedUpdate/frame/UDP/video出版増分0。探索が局所PhysicsSceneを進めても、実ゲームの物理時計は進まない。
- 4ゲームは別プロセスなので各ゲームの停止時刻は独立。CPU競合を含む並列条件で計画時間が増えており、Viewerなしでも密集約1.06秒。headlessが必ず高速になる結果ではない。CPU平均は全論理CPUの飽和を示しておらず、OSスケジューリング/物理内容/描画待機をそれぞれ単独原因として証明したものではない。
- 4ゲームMCTS+Viewer:通常Updateの最大間隔1094ms、FixedUpdateの壁時計最大間隔1100ms。headlessでは1113/1140ms。Time.maximumDeltaTime約0.333秒の上限もあるため、復帰時に複数FixedUpdateを実行しても壁時計停止の全時間を即座に追いつくとは限らない。
- 映像は640x360、CaptureLoopの1/15秒間隔。capture CPU p95は全条件約0.14〜0.23ms、共有メモリ出版CPU p95約0.56〜0.73ms。ここは1秒停止の主因ではない。
- GPU readback要求からUnity callbackまでの時間は通常中央値約13ms。4ゲームMCTSでは最大1096ms。この時間はメインスレッドに戻る待ちも含み、GPU処理そのものが1秒かかったと解釈しない。
- Viewer共有メモリreadは短く、出版→Tk提出p95は約57〜126ms、Tk画像変換/表示提出p95は約23〜79ms。Viewer側にもコストとjitterはある。ソース映像停止中の保持画像年齢は4ゲームMCTSで最大1162ms。出版済みフレームの待ち行列ではない。
- odd/even sequenceで書込み中フレームを捨て、最新1枚だけ読む設計。Viewerが遅れると中間画像を飛ばす。古い映像を順番に再生して追いつこうとするキューはない。
- 計画中にGC回数増加を確認（最終4ゲームMCTS+Viewerの16計画でGC.CollectionCount(0)増分237）。GC pauseの個別時間は測っておらず、GCだけを主因とは断定しない。Profiler計画中Unity allocator増分最大約15.14MiB、回帰テスト後予測Scene残数0。長時間のメモリリーク有無はこの短い試験では判断できない。

詳細なp50/p95/max、capture/readback/publish、Viewerのread/submit/保持画像年齢、GC/CPU/メモリはperformance_summary.json。JSONL/資源標本も保存。

## 低リスクな改善

ViewerLayout.renderで表示用PhotoImageを同じ表示倍率なら再利用する。赤→青の実画素更新とオブジェクト同一性、1/4切替・F11/Escapeをテストした。コピー単体60回（最初5回除外）の計測では中央値12.774→10.245ms、p95 16.714→14.857ms。約20%のコピー時間削減であり、ゲーム全体や4画面fpsが20%向上したという意味ではない。比較はviewer_copy_microbench.json。
更新が止まった時の表示を「更新待ち・最終映像○ms前」にし、OFF/終了と決めつけない。計測用の取得/転送/表示/保持画像年齢を追加。通常はRuntimeProbeのコンポーネントもログ出力も作らない。映像無効時のreadbackやViewer処理も従来どおり存在しない。

## 予測の原因切分けと修正

修正前physics_trace:空盤面起点第1手の落下tick20から、実ブドウの慣性0.0963074118/COM(0.0596805,0.0027757)に対し予測は慣性1/COM(0,0)。自由落下中は軌道差がほぼなく、第2手tick38の最初の床接触で初めて位置差0.00462/速度差0.227/回転差1.126degが発生、終点位置差0.167343となった。両側で同じ床接触イベントが起き、質量差0、慣性差0.903693だった。これは接触cache欠落だけでは説明できない、確認できた物性不一致。
SuikaPhysicsSimulator.Copyが保持/表示用trigger bodyの仮COM/慣性を明示代入し、solid化した時の計算を固定していた。盤面の解決済みbodyは従来どおりコピーし、previewだけは仮COM/慣性を固定しない。実ゲームの設定/物性やDropFruitは変更していない。

修正後physics_after_mass（同seed744200・同入力）:

| 起点/手 | 最大位置差 | 最大速度差 | 最大角度差deg | 最大角速度差deg/s | score/種類数/GO |
|---|---:|---:|---:|---:|---|
| 空盤面 1 | 0 | 0 | 0 | 0 | 一致 |
| 空盤面 2・床接触 | 0 | 0 | 0 | 0 | 一致 |
| 10手後接触盤面 1 | 0.086143 | 0.545586 | 12.5883 | 56.4699 | 一致 |
| 同上 2・3合体 | 0.027476 | 0.204154 | 12.4771 | 14.6128 | 一致 |

空盤面2手は初期入力/果物系列を揃えた因果確認になる。一方、10手後盤面は通信間idleや実物理進行もあり、修正前後で厳密に同じnative起点ではないため、数値が小さくなった分すべてを修正効果とは扱わない。接触起点では最初の数値差が1tick目、第2手開始では既に差が存在。solver contact/impulse履歴、生成/削除順、render境界の寄与の完全分離は未完了。

比較診断も修正した。元の正IDが見つからない場合に、同種類の近くの別果物を代用して成功扱いしない。新生成の負IDだけ近傍種類対応。第2手のtraceを新たに採取し、変化開始tick・イベント・COM/慣性・transform位置とタグ適格性も記録する。

## GOの検証

両側はFruitEvolution.CanTriggerGameOverとタグFruitを使用。ただし実ゲームはGameManager.Update、予測はSimulate後。Destroyのrender末/予測FlushRemovalのtick末、cold rootの接触履歴不足も残る。
現在apple.prefabのタグは小文字fruit。他の通常果物はFruit。りんごは両側ともGO対象外。上にある接触済みbodyだけでGOを判定してはいけない。アーカイブでbody y>lineだった3件はいずれもりんごで、これだけから初期GO判定漏れとは断定できない。タグは今回変更していない。

旧50組の全ログを読み直した分類（現在MCTSのエラー率ではない）:

| モード | 落下後GO | 落下前GO | 操作間GO | 選択候補のGO見逃し | GO過剰予測 |
|---|---:|---:|---:|---:|---:|
| heuristic | 45 | 4 | 1 | 24 | 3 |
| value | 41 | 8 | 1 | 18 | 8 |

新規の短時間再構成試験:
- 旧GO見逃しの自然盤面43果物:第1手では実/予測とも非GO、次の手の1tick目で両側GO。元の見逃しがそのまま再現されたとは扱わない（native cache/RNG/実時間履歴を復元できない）。
- 自然な終盤38果物:実ゲームは52tick目（落下後12tick）で新しく落としたブドウf39がf7に接触し、HasCollidedが立って中心y=3.47384>line3.3となりGO。
- 同じ52tickまでの予測はy=3.43392、接触なし/HasCollided=falseでGOを見逃した。最初の軌道差は1tick目。両者ともGO条件は同じで、接触成立時刻の差がGO適格性の差になった。最大位置差0.03994、速度差2.04082。
- ただしこれは実GOに揃えて予測も12post tickで止めた比較。別の同一root内compare_stepで通常25post tickを上限に予測すると、予測は53tick目（post13）でGO、実ゲームは52（post12）でGOだった。標準窓で永久にGOを見逃したのではなく、少なくともこの再構成例では1tick遅延だった。
- したがって「同tickのGO不一致」と「MCTS標準予測窓での候補GO見逃し」は分ける必要がある。自然GOまでMCTSを多数完走していないため、今回MCTSの自然見逃し率や過剰予測率は推定しない。強さの大規模比較も未実施。

詳細:archived_go_analysis.json、go_initial_predicate.json（body座標条件の診断でありタグを含む完全GO式ではない）、go_reconstruction、go_full_horizon。

## MCTS探索そのもの

MctsSelfTestの861 assertion、既存PathSession26項目、Python121テスト通過。UCTで良いreturnに訪問が集中する、全root候補の訪問、報酬の保存、未知NEXT/実RNGの非参照、枝独立性、固定seed再現、全GOフォールバック、末端cache、Scene解放、preview物性一致とID比較を検証した。861は独立した実ゲーム数ではない。
同じ実ゲームを1frameも動かさないfixed_sweep（35果物、5候補、post25、探索seed8191）:

| 最大深さ | 反復 | 計画ms | 選択x |
|---|---:|---:|---:|
| 3 | 16 | 392.3 | 0.75 |
| 3 | 32 | 774.4 | 1.00 |
| 3 | 64 | 1582.8 | 0.75 |
| 4 | 16 | 488.9 | 1.00 |
| 4 | 32 | 1063.4 | 1.00 |
| 4 | 64 | 2245.4 | 0.75 |

全6計画でfixed/frame/UDP/video増分0。rootのN合計は反復数、return単位は得点。Qは各ノード開始scoreからの増分+葉Value一度のみ。未知出現は行動UCTとは別の一様Prefab-slot抽選。標準モードと固定seedの回帰は通過したが、この単一盤面の選択位置変化だけから強くなったとは言えない。
rootのterminal_returnsは探索policyで変わる深いrolloutのGO回数で、直後GOのbooleanや独立試行の確率推定とは異なる。物理GO誤差が探索に利用されるリスクは残る。新しい高さ/危険度ペナルティは追加していない。

## 非同期化の設計と次の優先順位（未実装）

Unity APIは一般にthread-safeではない。PathSessionはInstantiate/CreateScene/Collider/Rigidbody/Simulate/Destroyを使うため、Task.Runに移すだけの実装をしない。単なるawaitもUnitySynchronizationContextではメインスレッドに戻る。
1. 推奨はライブPlayerと独立予測workerを分離する設計の確定。worker側もUnityのmain threadで物理を実行する。数値rootを送る方式では既存のcold-cache制約を引き継ぐ。
2. ライブは探索中も進むので、古いrootの答えをそのまま実行しない。episode/held ID/root tick/予約落下tick/期限を付け、実行時の状態と安全範囲を照合。間にGO/Reset/手動変更/期限超過があれば破棄する。
3. 想定思考時間を物理時間として予測し、入力の移動開始・落下予定時刻まで含める必要がある。計算が間に合わない場合の扱いも仕様化する。報酬の思考中/移動中/落下後の境界と二重計上を定義する。
4. coroutineで小分けにすると描画は戻せるが、その間に実盤面が進んでrootが古くなる。同じ整合性問題があり、yieldを足すだけでは正確な解決にならない。
5. 予測workerのCPU/メモリ/通信コスト、4ゲームへの公平な予算配分、取消/終了時のScene解放を小数ゲームで先に検証。今回これらは実装していない。

当面の表示用設定として16回/深さ3へ下げると計算時間は減らせるが、今回の密集盤面でも約392msで、滑らかな映像を保証しない。planning_budget_msは現実装では超過すると失敗する設定であり、単純なfpsリミッターとして使わない。15fps上限の変更やViewer描画基盤の刷新も今回は行っていない。

最優先の次作業は「探索とライブ進行を分離するための時計・予約入力・結果失効条件の設計確認」。並行して、自然なGO直前のlive rootを少数保存し、同tick/同窓の差を分けたGO回帰を蓄積する。落下タイミング設計はSTEP8C_TIMING_DESIGN.md。ゲームルールとしてのりんごタグ修正は別途判断が必要。

参考一次資料:
- [Unity 2022.3: async/thread制約](https://docs.unity3d.com/2022.3/Documentation/Manual/overview-of-dot-net-in-unity.html)
- [maximumDeltaTime](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Time-maximumDeltaTime.html)
- [Rigidbody2D.inertia](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Rigidbody2D-inertia.html)

## 変更ファイルと再測定

Unity/Assets/Scenes/Script/: SuikaRuntimeProbe.cs（新規+meta、明示flag時だけ計測/盤面再構成/固定root sweep）、UDPStepProtocol.cs（計画scope）、UDPStateProtocol.cs（probe専用command/送信数）、SuikaVideo.cs（既存header空き領域に計測値）、PredictionDiagnostics.cs（transform/tag）、UDPPathComparison.cs（第2手traceと正ID厳密比較）、SuikaPredictionPath.cs（継続trace）、SuikaPhysicsSimulator.cs（preview COM/慣性コピー修正）、SuikaMctsSelfTest.cs（回帰）。
Python/: src/suika_ai/video_viewer.py、tests/test_viewer_layout.py、tests/test_runtime_metrics.py（新規）、diagnose_runtime.py（新規、最大5標本/phaseのbounded測定）、analyze_runtime.py（新規）、diagnose_prediction.py（新規）。docsの本報告/タイミング設計/開発記録。既存ログ・モデルは削除/上書きしていない。Editorが既存のTMP生成assetを更新し得るため、その未コミット変更をGitへ戻していない。

```powershell
cd C:\SuikaGameAI\Python
# 新しい出力名にする。5条件、少数手のみ。
.\.venv\Scripts\python.exe diagnose_runtime.py --output outputs/runtime_check_user_01 --fixture outputs/step8c_01/dense_safe_fixture.json --samples 2
.\.venv\Scripts\python.exe analyze_runtime.py --input outputs/runtime_check_user_01 --output outputs/runtime_check_user_01_summary.json
# 単一条件だけ確認
.\.venv\Scripts\python.exe diagnose_runtime.py --output outputs/runtime_m4_user_01 --fixture outputs/step8c_01/dense_safe_fixture.json --samples 2 --condition m4v
# 同じseedで通常の2手比較
.\.venv\Scripts\python.exe smoke_mcts.py --output outputs/physics_user_01 --seed 744200 --warmup 10
# GO付近の再構成。完全なnative-state replayではない。
.\.venv\Scripts\python.exe diagnose_prediction.py --output outputs/go_probe_user_01 --fixture outputs/step8c_01/near_go_fixture.json
```
