# 未選択行動の分岐教師生成：Job 18・29

2026-11-01。新規モデルの学習・MCTS変更・Unityビルド・commit/pushは行っていない。

## 結論

2つの近似盤面から、初手2候補×共通未来2系列、計8ゲームを自然GOまで実行した。総実験時間1,759.984秒（約29分20秒）、打ち切り0、未着手0。観測可能な同一初期状態から、未選択行動の実現returnを収集する基盤として動作した。

Job 18では代替候補が2系列とも高得点。Job 29では未来系列によって順位が反転した。2独立root・各2未来なので、最善手や新方式の優位性を確定するデータではない。今回は教師生成のみで、学習や標準AIへの接続はしていない。

## 1. 出典と近似状態

元セッション: `Python/outputs/overnight_4workers_20261101_093658_8b91fc4d`。

|root|元ゲームseed|採用観測action|元tick|初期得点|果物数|初期スイカ|
|---|---:|---:|---:|---:|---:|---:|
|Job 18|913410018|164|9169|1837|12|1|
|Job 29|913410029|211|11386|2311|18|1|

自然GO・得点保存則の監査済み元ゲームから、最初にスイカが存在する非終端の落下後観測を抽出。Job 29の生成イベントはdrop210だが、採用した観測はaction211。物理tickそのものの直後ではなく、記録上で初めて利用できるスイカ生成後盤面である。

位置・速度・回転・角速度・公開保持果物/NEXT・cooldownなどを既存fixture形式へ保存した。欠損として補完した主要観測項目は0件。採用盤面に破棄待ちの `is_merging` 果物はなかった。

ただし接触solverキャッシュ、native sleep timer、元Unity RNG、元のframe scheduleは完全復元できない。元tickをそのまま再開したのではなく、fresh processのcoldな近似盤面を相対tick0から進める。過去のゲームそのものの反実仮想とは扱わない。

予約Test19のseedと初期8果物系列に一致しないことを確認した。source hash・元seed・初期8系列・元action/tickを保存。元ゲーム、旧Player、モデルは読み取りのみ。

## 2. 候補選定（結果を見る前に固定）

従来の同期MCTS128回・深さ4・固定5候補・random rollout・search seed8191を使用。

|root|条件|座標|訪問数|内部平均評価|
|---|---|---:|---:|---:|
|Job 18|A 推奨|1.0|33|36.060606|
|Job 18|B 代替|0.75|31|35.354839|
|Job 29|A 推奨|0.25|40|60.500000|
|Job 29|B 代替|0|39|60.230769|

AはMCTSの選択。Bはそれ以外の探索済み・落下成功・即時GO予測でない候補のうち平均評価最大。候補は各rootのselection.jsonへ保存し、その後の結果を見て変更していない。他の3候補の実現returnは未測定であり、A/Bの勝者を固定5候補全体の最善手とは呼ばない。

これらの内部評価は有限深さの報酬推定であり、自然GOまでの追加得点とは評価範囲が違う。内部値と最終returnの絶対差を予測MAEとしては扱わない。

## 3. 再現性・情報の扱い

各rootでAの初手・同じ未来seedを使って、3落下をfresh processで2回実行した。

- 両rootとも、ログ上の初期状態全項目が完全一致。
- 3落下すべてで、記録された盤面全項目・落下tick・command・RNG・選択・root探索統計が一致。
- 保持果物のx/y、cooldown、速度・回転・角速度・記録された接触/sleep関連情報も確認。
- 未来seedだけを2026110101→2026110102に変えたsurveyでも、初回のroot統計と選択は一致。未公開Cを初回判断に使っていないことと整合する。
- 全8本試行の570判断で、探索前後の実ゲーム状態・Unity RNG不変のassertが成功。

ゲーム側の将来生成はUnity RNGを新しい実験用future seedで初期化し、MCTSは別のsearch seed8191を使う。元ゲームseedは出典であり、元の未公開未来列を再現したとは主張しない。判断にはその時点の公開保持果物とNEXTを使う。未来seed・RNG stateはモデル入力にしない。

実際の候補ペアでも全ログ初期状態・相対tick・初期Unity RNGが一致し、共通観測可能な果物列は次の長さで一致した。

|root|future seed|一致した公開果物列長|
|---|---:|---:|
|Job 18|2026110101|94|
|Job 18|2026110102|85|
|Job 29|2026110101|16|
|Job 29|2026110102|38|

これは短い方の試行が観測できた範囲。片方がGOした後の未観測未来まで一致を実測したとはいわない。長期の同条件returnを複数回再実行したわけでもなく、完全なnative決定性や長期再現性の保証はない。

位置を変えると移動時間も変わる。Job 18の初回落下tickはA60/B40、Job 29はA3/B16だった。両系列で同じ値。比較する行動は、既存ルールどおりその座標まで移動して落下する操作であり、同じ絶対tickで瞬間的に置く介入ではない。

## 4. 自然GO結果

|root|未来seed|A追加得点|B追加得点|B−A|A落下数|B落下数|
|---|---:|---:|---:|---:|---:|---:|
|Job 18|2026110101|776|1271|+495|92|139|
|Job 18|2026110102|651|836|+185|83|98|
|Job 29|2026110101|498|127|−371|56|14|
|Job 29|2026110102|247|407|+160|36|51|

全8ゲーム自然GO・実行エラー0。accepted dropsはGO直前の落下を含む。570判断に対し落下569回であり、GOまでに落下へ到達しない判断も区別している。追加得点は各試行の初期得点を差し引いた実測値。元ゲームの最終得点やMCTS内部の得点予測から生成した値ではない。

|root|A平均追加得点|B平均追加得点|B−A平均|A平均生存落下|B平均生存落下|
|---|---:|---:|---:|---:|---:|
|Job 18|713.5|1053.5|+340|87.5|118.5|
|Job 29|372.5|267|−105.5|46|32.5|

Job 18は、短期MCTSでは僅かに低評価だったBが、2つの未来で長期returnと生存を上回った。一方、Job 29は未来によって候補順位が反転した。単一未来の勝者を確定的な教師にすると不安定になる実例である。2rootだけなので、統計的優位性やMCTS全般の欠陥は断定しない。

新規スイカ生成、2個目の生成、2個共存、ダブルスイカはいずれも全8試行で0。初期のスイカ1個は成功として加算していない。これらの負の結果は当該方策・未来で未達という意味で、盤面から達成不能という意味ではない。

## 5. 計算時間

|root|未来|A実行秒|B実行秒|A平均判断ms|B平均判断ms|
|---|---:|---:|---:|---:|---:|
|Job 18|0101|273.922|448.921|2159.35|2472.45|
|Job 18|0102|221.828|292.687|1952.96|2278.40|
|Job 29|0101|172.296|36.562|2401.30|1875.23|
|Job 29|0102|105.672|150.250|2175.53|2168.32|

最初のペア722.843秒を測り、残り47分以上あることを確認して続行。各ゲーム600秒、総実験3600秒を上限とした。最終1759.984秒、予算による未実行・打ち切りは0。

本試行合計1702.138秒、自然GO return 1件当たり平均212.77秒、候補差1件（同未来A/B）当たり平均425.53秒。診断込みでは4ペアを約29分20秒で取得。盤面・生存長で大きく変わり、最初のペアだけなら約12分。どの盤面でも一定速度で教師を作れるとは限らない。

全570判断で指定128反復、root訪問合計128、固定5候補を確認。実落下座標の最大丸め差は約5.96e-8 world unit。初手のみforced、2手目以降は全てnative MCTS選択と一致。全行でscore−initial_score=additional_score。ログ観測点の予測Scene残留最大0。

## 6. 再利用ツールとデータ

新規追加:

- `Python/branch_action_teacher.py`: prepare=64行、run_trial=122行、compare_trials=175行、run_study=210行、analyze=276行。
- `Python/export_branch_teacher.py`: example=9行、export=33行。学習用入力と結果/provenanceを分離。
- `Python/tests/test_branch_action_teacher.py` と `Python/tests/test_branch_teacher_export.py`。

使用Playerは既存 `Unity/Builds/StagedAction_02`。名前にStagedが含まれるが、設定は **mode=baseline**。StagedRootMctsPlannerや動的候補を有効化せず、従来StepPlanner/MCTSを呼んだ。新しいUnityビルドは不要だった。

成果物: `Python/outputs/branch_teacher_jobs18_29_01`

- `teacher.json` / `teacher.csv`: 候補別自然GO結果、内部統計、再現性、継続方針。
- `examples.jsonl`: 観測盤面＋実行した座標をinput、自然GO追加得点をlabelにした8例。
- `pair_targets.json`: 未来ごとの差とroot別の標本平均。真の最適行動ラベルではない。
- `strict_initial_checks.json` / `quality_audit.json`: 初期全項目・座標・得点保存・保護hash監査。
- 各試行の `trace.jsonl` / `config.json` / `provenance.json` / `launch.json` / `result.json`。

入力には果物・保持果物/NEXT・現在得点・物理条件と候補座標だけを入れ、未来seed、RNG、最終得点、将来イベントは含めない。Player hash・実際のPlanningSettings・続行方針はprovenanceとして保存。途中打ち切りはreturn=None、outcome_known=Falseとして扱う設計であり、0点や失敗ラベルを推測で付けない。

split_keysに元game seedと元初期8系列を保存。いずれかが共通する元データ・root・候補・未来・再実行を同じ連結グループへまとめてから分割する。今回は全てdevelopment diagnosticで、独立TestやTrainとして自動投入していない。

### 別の元ゲームで実行する例

以下は新規実験を開始するコマンド例であり、今回追加実行はしていない。出力先は必ず新しい名前にする。

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\branch_teacher_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)

.\.venv\Scripts\python.exe .\branch_action_teacher.py prepare `
    --source .\outputs\overnight_4workers_20261101_093658_8b91fc4d `
    --jobs 18 29 --future-seeds 2026110103 2026110104 `
    --output $out --total-seconds 3600 --game-seconds 600

.\.venv\Scripts\python.exe .\branch_action_teacher.py run --output $out
.\.venv\Scripts\python.exe .\export_branch_teacher.py --output $out
```

別盤面は `--source` / `--jobs`、別未来は `--future-seeds` を指定する。候補を明示したい場合は、新規prepareで作成したplan.jsonの各rootの `positions` を `[A座標,B座標]` に実行前に設定する（0〜1、例0.37も指定可能）。今回の4座標以外の品質や一般化能力を検証したわけではない。明示座標の場合、recommended/alternativeというファイル名は条件A/Bの識別名となり、実際のMCTS推奨とは区別する。

続行はplan.jsonの `continuation` でkind、iterations、depth、search_seedを明示する。現在対応するkindは `legacy_mcts`、32〜256回・深さ2〜16。今回は128/4/8191で固定した。heuristicや学習モデル等の別kindは未対応で、指定するとエラーにする。Player adapterなしに任意のAIを使えるとは主張しない。

実験済みplanや結果は編集しない。runの重複実行は既存execution_startへの上書きを拒否する。ゲーム単位で結果を残し、停止後も完了分を保持する。自動再開ではなく、部分データは別名でanalyzeできる。

## 7. 検証・次の判断

- Python既存＋新規テスト436件成功。
- 既存PlayerのUnity rules127、MCTS861、path26、計1014 checks成功。
- 既存ソース、元ゲームログ、凍結モデル、旧収集Player、新実験で再利用したassemblyのhash変更なし。
- develop維持。収集プロセスは開始時に稼働しておらず、中断・設定変更はしていない。新規学習・commit/pushなし。

独立rootを増やす価値はある。未選択行動が高いreturnを得たケースと、未来で順位が反転したケースを、出典・続行方針付きで取得できたためである。

次は同じ2rootだけへ大量の未来を追加してモデルを作るのではなく、新しい独立元ゲーム群からrootを増やす。判断が不安定なrootには追加未来も必要。十分なroot数を確保してから候補間return差・順位の学習を比較する。今回の8例を独立8盤面と扱わず、2rootで新Q/Vを学習しない。

なお、今回はスイカ2個目への成功経験を得ていない。生存・追加得点の教師は得たが、ダブルスイカ達成法が学習可能になったとまでは判断しない。近似Labから実ゲームへ一般化するかは、将来のモデルを未使用seedの自然GOで評価して確認する。
