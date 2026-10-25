# STEP 8-T：適応型MCTS比較基盤（2026-10-24）

## 結論

従来MCTSを既定として維持し、時間制限・段階的追加探索・固定9候補・訪問数に応じた候補追加を単独比較できるようにした。新方式の自然GO高得点化は未検証で、標準採用しない。新Playerは **Unity/Builds/Step8T/SuikaGameAI.exe**。旧8-Sの **Builds/Step6** は変更しない。

最終目標は最終得点の向上とダブルスイカの安定達成。今回、長期価値モデル・新規学習・リアルタイム化・Viewer改修は行っていない。

## 1. 中断したSTEP 8-S

対象 `Python/outputs/budget_compare_20261024_220548_138aaaf4`。

|seed|32回|64回|
|---|---:|---:|
|759400|1981・自然GO|2037・自然GO|
|759401|1671・自然GO|2612・自然GO|
|759402|1844・自然GO|1455・自然GO|
|759403|未開始|150手でstopped、自然GOではない|

20ゲーム中6ゲーム（3ペア）が正常に保存され、全6件の元ログhash・設定・環境監査が通った。残り14件は1件中断、13件未開始。6ゲームだけで方式の優劣は判断しない。

8-SのPython実験プロセスは確認時0。別の古いgrid5対grid9実験のPlayer PID9736が残っていた。8-Sとは異なるポート/出力先で、停止・変更はしていない。今回の時間測定に対する背景負荷の可能性は残る。

### 再開環境の保護

- 必要な旧Pythonコードと旧UnityランタイムC#ソースを `Python/compat/step8s_20261024` に保存。一般的な追加バックアップではなく、中断実験専用の互換実行版。
- `version_manifest.json` に保存106ファイル、旧Player全152ファイルのhash、Pythonバージョン、旧実験パスを記録。
- 新機能は別のStep8Tへビルド。旧Player全152ファイルと互換ソースは作業後もhashが不変。
- 旧Pythonを別プロセスで実際にimportし、旧settingsの完全一致・Player exe/Assembly一致・完了6件の読み込みを確認。**旧実験そのものは再開していない**。
- 元の現行Pythonには新設定が増えたため、8-Sの再開には以下の互換用コマンドを使う。元planや結果ファイルは変更していない。
- 誤って旧Playerを上書きしないよう、旧Build STEP6メニューは互換manifestがある間ビルドを拒否する。新しいビルドは Tools/Suika/Build STEP8T Adaptive Player。保護パス判定をビルドなしでテスト済み。

```powershell
Set-Location C:\SuikaGameAI\Python
.\.venv\Scripts\python.exe .\compat\step8s_20261024\compare_mcts_budget.py --resume --output .\outputs\budget_compare_20261024_220548_138aaaf4
```

これで完了6件をskipし、中断したseed759403/64回を新attemptで最初から実行する。ゲーム途中の物理状態を復元する再開ではない。旧未完了150手ログは残す。

## 2. 従来構造と維持したもの

独立PhysicsScene2DのPathSessionを反復ごとに構築し、同じrootから経路を再生する。UCTでdecision actionを選び、公開果物slotの分布でchanceをサンプル、新規edge/chance後は従来どおりrandom rolloutへ進む。各実訪問edgeに `最終予測score - そのedge開始時score + leaf_value` を1回逆伝播する。

通常mctsのleaf_valueは0で、探索範囲の追加得点が評価対象。mcts_valueだけが終端でないleafに既存ValueNetの将来得点を加える。今回の新しいallocation機能はmcts/rewardで検証し、mcts_valueとの組合せは初版では受け付けない。既存の固定mcts_value・その他モードは残る。

GO即時候補の除外・全候補GOの従来fallback・未知NEXTの分布・出現確率・物理幅・post25・GO比率0.83・rules step8e-all-fruit-go-v2は維持。同期なので探索中の実ゲーム描画/更新停止は従来どおりで、今回は解消していない。

## 3. 切り替えと独立設定

|比較profile|内容|既定との差|
|---|---|---|
|legacy|従来の固定回数MCTS|なし|
|time|実時間上限または反復安全上限まで|mcts_budget_mode=time|
|adaptive|同じ木を保持して段階追加、安定/時間/回数で終了|mcts_budget_mode=adaptive|
|grid9|全探索階層で固定9位置|candidate_count=9|
|widening|root/非rootのdecision候補を順次追加|mcts_widening=true|

既定はfixed/32回/固定5。比較CLIの深さは4。`--depth 6` / `--depth 8` は既存深さ設定を再利用する。深さの自動変更は実装しない。

- `--iterations`：fixed profileの反復数（従来の2〜256制約を維持）。
- `--max-iterations`：time/adaptiveの安全上限、2〜4096。初版既定256。
- `--time-limit`：time/adaptiveの実経過秒上限。5/15/30/60秒などを指定可能、内部安全上限3600秒。初版既定5秒。
- `--candidates`：通常gridの候補数。profile grid9は常に9、wideningは必ず初期5。
- `--widen-after` / `--widen-max`：候補追加に必要な訪問数基準/最大候補数。
- その他adaptive判定係数はPlanningSettings/UnityEnv.plan_stepのJSON設定として公開する。CLI初版はその既定値を使用する。

**時間指定は最大値であり最低思考時間ではない。** 5秒指定でも256反復に先に到達すればそこで終了する。より長く探索させる場合は反復上限も上げる。4096反復/60秒等の実負荷は今回測っていないため、まず256以下で比較する。

## 4. 時間制限

Stopwatchの実経過時間を各反復開始前に確認し、完了済み反復の木と統計を使って選択する。従来のplanning_budget_msのように、時間超過で全探索結果を破棄する実装にはしていない。

ただし、**1反復の途中では停止しない**。その反復内の移動・物理・合体・GO・逆伝播を完了してから止める。結果組み立て/metric処理も加わるため厳密なhard deadlineではない。`budget_stop_reason`、`completed_iterations`、`iteration_cap`、`time_limit_ms`、`time_overrun_ms`を記録。UDP転送・果物の実移動・落下後待機は判断時間の外。

根の一部しか試せなかった場合、未訪問候補はsuccess=falseのplaceholderとし、実際に評価済みの候補から選ぶ。未訪問を安全とみなさない。1反復も完了できない場合は `completed_iterations=0; no drop` の明確なエラーとし、自動で任意位置へ落としたりResetしたりしない。安全候補を得られなければ無理に落下しない。

## 5. 追加探索：木と統計を維持する

同一PlanFramesのroot/nodes/RNGを保ったまま32→64→128→256…と続ける。32を捨てて64を最初からやり直さない。反復ごとの状態は従来どおり独立PathSessionで再生し、不正に接触キャッシュを共有しない。木の保持は**同じ判断内**であり、次の実ゲーム手まで木を使い回す機能ではない。

初期判定基準：

1. 最初の32回は基準点として必ず継続する。
2. 次のcheckpointで、選択候補が前回と同じ。
3. 安全候補がそれぞれ最低4訪問。
4. 選択候補の平均値変化が3点以内。
5. 選択候補の探索内終端率が0.1以下。
6. 選択候補と平均値最大の競合候補の差が、合成standard error×1以上。

各基準は `adaptive_initial_iterations`、`adaptive_min_action_visits`、`adaptive_value_tolerance`、`adaptive_max_terminal_rate`、`adaptive_uncertainty_multiplier` で変更可能。0点同士でも、値が安定し分散0なら停止可能なので、僅差だから必ず追加する方式ではない。

standard errorは同じ木で相関したサンプルから計算した**経験的な停止指標**であり、統計的に正しい独立標本CIや最善手の保証ではない。3点/0.1等も最適値ではなく比較用の初期値。GOペナルティやゲームルールを変える係数ではない。

checkpointごとに選択x、訪問数、平均値、gap、standard error、平均変化、終端率、継続理由を残す。capと安定判定が同時成立する場合もあるため、completed==capなら早期節約とは数えない。

## 6. 候補追加

訪問数に応じて候補数を制限する [Progressive Wideningの研究](https://www.ijcai.org/Proceedings/16/Papers/104.pdf) を参考に、比較用の軽量なnode-local方式を実装した。

- 初期5位置は保持し、既存index/Edgeを並び替えない。追加時は配列末尾へ新Edgeをappendし、既存の訪問・報酬・chance子を保つ。
- 追加済み数をk、基準訪問数をTとし、`node.visits >= T*(k+1)^2`、候補上限未満、既存の安全候補が最低訪問数を満たした場合だけ1候補追加する。既定T=10、min訪問1、最大9、最小間隔0.03125。
- 隣接位置の中点だけを追加する。奇数回目は `区間幅 * (1 + clip(max(両端平均得点)/55, 0, 1))` の大きい区間、偶数回目は最も広い区間を選ぶ。同点はseed/node ID/追加数から決め、chance/rollout乱数を消費しない。
- 有望区間と広い未分割区間を交互に扱い、極端な集中を避ける。係数1やclipは初期設計であり、実得点で最適化された重みではない。
- 位置は正規化0〜1、重複/最小間隔を検査し、既存の果物Collider・壁に基づく合法範囲変換を通す。壁やColliderを変更しない。
- rootだけでなく、条件を満たす全decision nodeで同じ処理を行う。random rolloutは従来の初期gridから選ぶままとし、新方式で幾何rolloutへ置換しない。
- 初期32回ではrootの追加が中心。非rootには十分な訪問が必要で、常に全ノードが9候補になるという意味ではない。

密集256反復ではrootへ .875/.125/.625/.375 を追加し、将来decisionの4ノードにも中点を追加できた。合計8追加。rootだけのCoarse-to-Fineとは異なる。同じroot indexの物理状態が変わらないよう既存座標は保持する。

## 7. 固定盤面の結果

最終診断は保存盤面のロード後に余分な実ゲームフレームを進めず実行。最初の診断は2フレーム進んでいたため、旧fixtureとの厳密比較には使わず、修正後のfixed_verified.jsonlを正式結果にする。

以下のtimeは1秒上限、adaptiveは初期32/最大128/5秒上限。全て深さ4、seed8191。時間は単回の診断値で、方式の速度優劣を確定する比較ではない。

|盤面|方式|実反復|判断ms|停止理由|追加数（非root）|実物理tick|
|---|---|---:|---:|---|---:|---:|
|early_fixture|legacy|32|185.69|iteration_limit|0（0）|7282|
|early_fixture|time|199|1003.37|time_limit|0（0）|43101|
|early_fixture|adaptive|128|651.96|iteration_limit|0（0）|27434|
|early_fixture|grid9|32|166.91|iteration_limit|0（0）|6789|
|early_fixture|widen|32|157.76|iteration_limit|1（0）|7047|
|early_fixture|widen256|256|1302.68|iteration_limit|4（0）|55147|
|mid_fixture|legacy|32|529.31|iteration_limit|0（0）|6867|
|mid_fixture|time|61|1001.35|time_limit|0（0）|13049|
|mid_fixture|adaptive|128|2105.06|adaptive_stable|0（0）|26729|
|mid_fixture|grid9|32|515.46|iteration_limit|0（0）|6714|
|mid_fixture|widen|32|550.86|iteration_limit|1（0）|7082|
|mid_fixture|widen256|256|4249.06|iteration_limit|4（0）|53482|
|dense_safe_fixture|legacy|32|813.94|iteration_limit|0（0）|5818|
|dense_safe_fixture|time|40|1015.32|time_limit|0（0）|7210|
|dense_safe_fixture|adaptive|128|3159.39|iteration_limit|0（0）|22216|
|dense_safe_fixture|grid9|32|763.13|iteration_limit|0（0）|5506|
|dense_safe_fixture|widen|32|835.38|iteration_limit|1（0）|5809|
|dense_safe_fixture|widen256|256|6360.25|iteration_limit|8（4）|43629|

- 1秒上限の超過は序盤3.37ms、中盤1.35ms、密集15.32ms。別負荷/より深い反復でこの値以内を保証しない。
- 1マイクロ秒の極小上限は全3盤面で0反復・no dropエラー。これを成功した判断として扱わない。
- adaptiveの中盤128は安定判定とcapが同時成立したため、早期終了効果ではない。序盤は候補差の不確実性、密集は値変化で継続しcapへ到達。
- adaptiveの全反復の行動/果物sample/得点/合体/GO/tickは、固定128の同じprefixに一致。木を捨てて再開始していないことを確認。
- widening256は各盤面2回、ノード統計・全経路・得点・合体・GO・tick・追加イベントが一致。時間上限モードは同seedでも負荷で完了反復数が変わるため、完全な判断再現を保証しない。固定seed・固定完了反復prefixとして比較する。
- 従来32回は別の既存CandidateProbeでも3盤面を実行し、旧8-Rの全反復state digest、経路、得点、合体、GO、tick、ノード統計、選択xが一致。
- 深さ6/8も各3盤面で8反復ずつ正常に実行。深さの自動調整や深さ8の実得点改善は未検証。
- 新制御のネイティブselftestで既存edge保持・非root追加・候補重複防止・初回継続・値変動/GO時継続等を確認。
- Unity allocated sampled peakは診断全体で約50〜1096MiB。複数検索を同じフレーム内で連続実行し、破棄待ち・診断保持を含む。単一モードの常駐量/OS working setとして解釈しない。各検索の値はanalysis.json、実ゲーム各プロセスの値はresult.jsonに記録。4096反復/60秒のメモリ負荷は未検証。

## 8. 各8手の実通信

単一Playerを順番に起動し、同ゲームseed760300/探索seed8191で5条件。time/adaptiveは短時間試験用に1秒/最大256。全40操作で正常落下・座標一致・得点/報酬/合体・公開果物列・訪問統計・実物理tick数の監査が通った。全条件は同じ公開果物prefixだった。

|profile|8手時点の得点|合体数|実反復数の範囲|平均判断ms|判断p95 ms|判断時間合計 秒|
|---|---:|---:|---:|---:|---:|---:|
|legacy|16|2|32〜32|295.14|358.84|2.361|
|time|15|1|84〜181|1005.70|1010.64|8.046|
|adaptive|15|1|64〜175|941.81|1009.84|7.534|
|grid9|15|1|32〜32|286.98|344.34|2.296|
|widening|16|2|32〜32|290.50|359.82|2.324|

adaptiveは8手中1手で64回・adaptive_stableとして終了し、他7手は時間上限。全てstep_limit終了で自然GO比較から除外。GO正例0なので、見逃し率/過剰予測の性能評価はできない。8手の得点差は高得点化の証拠ではない。完了5ゲームを再起動せずskipする再開確認も合格。

Python245テスト、Unity既存MCTS861/rules84/path26/frames58（計1029チェック）合格。新しい制御selftestも合格。GUIでのViewer/録画テストは実施していない。

## 9. 保存・学習用情報

既存JSONLを維持して、各transitionのobserved_before/decision_source/stateに盤面・種類・位置・速度・接触等、現在果物/NEXT、選択x、報酬/step間報酬、GO、seed、環境metadataを保存。planningには全候補、訪問数、平均値、実反復、深さ、思考時間、追加候補イベント、checkpoint理由を保存する。episode_endの自然GO/最終得点/最大果物も既存どおり。

新しい学習専用データ書出しは追加しなかった（既存情報で大部分が取得可能）。したがって新しいデータ収集機能が既定ONになる変更はしていない。自然GOログだけに `最終得点−その状態score` を付け、未選択候補に実測教師値を付けない方針を維持する。

不足は**スイカ生成の累積回数とスイカ同士の合体回数**。現在のEpisodeMaxFruitType=10だけでは、1個/2個/ダブル成功を区別できない。そのため今回の結果はdouble_watermelon_known=false、success=nullとし、成功していないと捏造しない。

将来の任意telemetryとして、実ゲームのRecordMerge(fromType,createdType)から生成type別累積数とfromType10→-1の回数を保存する案を推奨。第1/第2スイカ率は累積生成数>=1/>=2、ダブル成功は10同士の合体回数>=1で定義できる。予測側のイベントを実ゲームの成功数へ加算しない。今回は未実装。

比較結果は8-Sのゲーム単位集計を再利用し、JSON/CSVへ保存。actual_iterationsとcheckpoint/追加履歴はJSON/元JSONL、CSVには条件名・実反復の平均/最小/最大等を保存。手数上限は自然GOに数えず、paired game/seed単位bootstrap CIを使う。新実験はPython実装・Player exe/Assembly hashを保存し、変更後の同一実験再開は拒否する。途中ゲームは新attempt、完了ゲームはhash検証してskip、二重起動はOSロックで拒否。

## 10. 長期戦略とロードマップ

現mcts/rewardのleaf評価は0で、4手等の予測窓で得られた得点を中心に比較する。数十手後の生存や大きな果物配置、ダブル到達を直接評価するモデルはない。さらに、現在のゲームではtype10同士は消滅するが得点加算なし（FruitEvolution）。今回はこのルールを変えない。スイカ合体は空間を空けて将来得点へつながり得るが、未検証のダブルbonusを新報酬へ勝手に加えない。

次の段階では短期物理rewardと `将来追加得点V(leaf)` を合わせる既存mcts_valueの接続点を再利用する。Vはleaf時点から先の点数で学習し、移動中・予測中の得点を再加算しない。生存確率/残り手数/ダブル到達は補助診断として別出力し、最終的な採否は実ゲーム得点で行う。

旧ValueNetは従来AI超えが確認されておらず、旧GOタグ仕様など環境差にも注意する。新環境の自然GOデータ、未知NEXTのmask、実盤面と予測盤面の特徴量整合を確認した後で再学習/再導入を別途検証する。今回のadaptive制御は評価ネットワークと別モジュールであり、将来の学習leafを阻害しないが、新機能とmcts_valueの併用は追加検証が必要。

方策モデルは可変候補ごとのx・盤面特徴から訪問分布を予測する構成が候補。入力順/候補数を固定5へ閉じ込めず、訪問分布のmaskや未訪問を扱う。MCTSの教師分布と実ゲームの最終得点を区別し、同episode/同系列をTrain/Validation/Testへ跨がせない。大規模学習は今回開始しない。

今後の順序：①計算量・候補・追加探索を単独評価 → ②短期物理+長期盤面価値/生存/配置を検討 → ③方策/価値の学習補助を実ゲーム検証 → ④有望機能だけ組み合わせて最終得点・高得点率・スイカ率・ダブル率・GO/時間を比較 → ⑤判断品質を維持してリアルタイム化/配信。今回は①の比較基盤まで。

## 11. 実行コマンド

まずは旧8-Sの未完了14件を上記互換コマンドで完了させることを推奨。その結果を確認してから新Playerで単独機能を比較する。旧Player結果を新Playerの同一ペアへ混ぜない。

### 新8-T：legacy対adaptive、各3ゲーム（実行はユーザー判断）

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\adaptive_pilot_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_adaptive_mcts.py --profiles legacy adaptive --games 3 --seed 760400 --iterations 32 --depth 4 --time-limit 5 --max-iterations 128 --max-steps 3000 --output $out
```

以下も**1機能ずつ**実行可能。

```powershell
# 最大思考5秒。回数も上限4096へ広げる（負荷が大きいので必要時のみ）
$out = "outputs\time_pilot_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_adaptive_mcts.py --profiles legacy time --games 3 --seed 760500 --time-limit 5 --max-iterations 4096 --output $out

# 固定5対9、32回・深さ4
$out = "outputs\grid9_pilot_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_adaptive_mcts.py --profiles legacy grid9 --games 3 --seed 760600 --output $out

# 32回のまま候補追加だけON（非rootの追加は少なくなる）
$out = "outputs\widen_pilot_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_adaptive_mcts.py --profiles legacy widening --games 3 --seed 760700 --iterations 32 --depth 4 --widen-after 10 --widen-max 9 --output $out
```

非root追加も実ゲームで比較するなら、両方式とも `--iterations 256` 等に揃える別実験が必要で、計算時間は大きくなる。自然GO性能は未測定なので、現段階で大量実験を推奨する意味ではない。

8-T再開（A/Bで設定した$outを使用。別PowerShellではRead-Hostで保存先を入力）：

```powershell
.\.venv\Scripts\python.exe .\compare_adaptive_mcts.py --resume --output $out
# 集計だけなら、新しいreports番号へ保存
.\.venv\Scripts\python.exe .\compare_adaptive_mcts.py --analyze-only --output $out
```

最新の `reports/<最大番号>/comparison.json` とgames.csv/comparisons.csv/pairs.csv/summary.csvを確認する。手数上限/中断/異常は除外理由を残し、自然GO完了として水増ししない。3seedは予備実験に過ぎない。

## 12. 未実装・未確認・採否

- 新NN学習、長期配置評価、新規GOペナルティ、ダブルの実測counter、深さ自動調整、異なる実ゲーム手への木再利用は未実装。
- 時間上限はsoft。1反復中断、4096反復/60秒の実負荷、深い探索の自然GO得点、GO見逃し正例、高得点/ダブル到達率は未確認。
- 同seedでも時間制限は負荷により反復数が変わる。未知果物の確率モデルは同じでも、探索方式/時間の違いで同じsample消費順にはならない。
- 対応は1ゲーム逐次。4ゲーム/Viewerへ新方式を展開しない。既存の4ゲーム/Viewer/フレーム分割/既存AIモードは維持。
- 1機能で安全な判断が得られない場合は明示エラーで止まり、勝手なheuristic fallback/自動Resetで正常扱いしない。
- **新方式は全て比較用。高得点化の採否は自然GO比較を待つ。**

## 13. 変更ファイル・関数・行番号

- `Unity/Assets/Scenes/Script/StepPlanner.cs`：public string mcts_budget_mode 34 / MctsAdaptiveControl.Validate 48。
- `Unity/Assets/Scenes/Script/MctsPlanner.cs`：if(s.mcts_widening)n.positions 95 / bool flexible= 179 / if(flexible&&timer 187 / MctsAdaptiveControl.TryWiden 219 / MctsAdaptiveControl.Assess 357 / completed_iterations==0 364。
- `Unity/Assets/Scenes/Script/MctsAdaptiveControl.cs`：static void Validate 13 / InitialPositions 24 / TryWiden 27 / Checkpoint Assess 44。
- `Unity/Assets/Scenes/Script/SuikaAdaptiveProbe.cs`：static void SelfTests 14 / IEnumerator Start 26。
- `Unity/Assets/Editor/SuikaWorkerBuild.cs`：BuildAdaptive 15 / IsProtectedDestination 16,22,27 / CheckProtectedBuildGuard 21。
- `Python/src/suika_ai/unity_env.py`：PLANNING_DEFAULTS.update 417 / flexible=values 431。
- `Python/src/suika_ai/parallel_play.py`：settings["mcts_budget_mode"] 197。
- `Python/adaptive_profiles.py`：def profile 6 / def audit_decision 11。
- `Python/compare_adaptive_mcts.py`：def audit_game 10 / def run 24 / def make_plan 43 / def main 54。
- `Python/analyze_two_step_probe.py`：widening=settings 8 / def apply_additions 9。
- `Python/analyze_adaptive_probe.py`：def analyze 10。
- `Python/compare_mcts_ai.py`：def episode 35 / flexible_mcts 35,73,78,79。
- `Python/compare_mcts_budget.py`：r.get('condition' 100 / fields=['condition' 118。
- `Python/tests/test_adaptive_mcts.py`：class AdaptiveMctsTests 8。

新規C#の.metaはUnity生成。docs/DEVELOPMENT_LOG.md / DEVELOPMENT_PLAN.mdに今回の結果と将来ロードマップを追記。成果物はPython/outputs/step8t_01、step8t_smoke_01。既存ログ・モデル・Scene・Prefab・物理設定は変更していない。commit/pushなし。
