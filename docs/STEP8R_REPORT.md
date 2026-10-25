# STEP 8-R：物理時間と2手探索配分の診断（2026-10-24）

## 結論

従来の固定5候補・同期MCTSを標準として維持する。試作は opt-in の `pair_coverage_iterations=15`。2手系列の被覆は増えたが、密集盤面の深い探索・探索内得点には一貫した改善がなく、自然GO10組比較を開始する根拠は得られなかった。長時間実験は行っていない。

## 1. 時間整合性

- `PlayerController.CanDropFruit`（29行）：保持果物が存在、時間進行中、`Time.timeAsDouble >= nextDropAllowedAt`。
- `DropFruit`（139行以降、170行で期限設定）：実落下からcooldown=0.4秒。NEXTから次の保持果物を生成する。今回の保存環境のAI移動速度は3.75 world unit/ゲーム秒、fixedDeltaTimeは約0.02秒。
- `UDPStepProtocol` のFixedUpdate側処理：合法範囲へのMoveTowards、目標到着とcooldown成立後に既存落下処理。post_drop_stepsは実落下後から計数。描画フレーム内に複数FixedUpdateがある場合、返却時tickが指定値を上回る余地がある。
- `SuikaPhysicsSimulator.RunTicks`（368行以降）：同じ更新幅で移動・cooldown・落下・落下後25tickを進める。`SuikaPredictionPath.PathSession` は nextTick/allowed を次階層へ継承し、階層ごとに時刻をリセットしない。
- **25tickは次の意思決定までの総時間でも、静止待ち時間でもない。落下後の観測窓である。** 各階層には移動・cooldown・落下tickも含まれる。階層数が同じでも位置により総時間が異なる。
- 今回の実ゲーム測定で最初に落下可能になったのは落下から21tick後（約0.42秒）。設定は0.4秒のまま。floatの0.4と20×fixedDeltaTimeの微小差による境界の可能性があるため、20tickと断定しない。条件・値は変更していない。

### 同じ総経過tickでの比較

35果物、初期得点785。Aは1個落下後に待つ。Bは同じ初手の25post-tick後から次の公開果物をx=0へ移動・落下。各時点は**初手の実落下を0**とする。独立予測と実ゲームは次表の得点・合体数がすべて一致した。

|初手|条件|25tick 得点/合体|50tick|75tick|100tick|
|---|---|---|---|---|---|
|0.5|A：待機|785/0|788/1|788/1|788/1|
|0.5|B：次を0へ|785/0|788/1|788/1|824/3|
|0.75|A：待機|785/0|788/1|788/1|788/1|
|0.75|B：次を0へ|785/0|788/1|788/1|788/1|

- x=.5 の遅延合体+3は30tick後。次の落下は60tick後、追加合体+15は85tick後、+21は93tick後。100tick時点のB−Aは+36点・+2合体。ただし差は介入による盤面変化の総効果であり、個別の合体を厳密に因果帰属したものではない。
- x=.75 の遅延合体+3は44tick後、次の落下は79tick後。100tickまではB−A=0。予測の次の+15は103tick後で、今回の実ゲーム比較窓100tickの外。**103tickの実ゲーム一致は未確認**。
- 通常の2手予測終了は x=.5→0 が初手落下後85tick、x=.75→0 が104tick。前回の18点は+3の遅延合体も含むため「2手目だけが18点を生んだ」とは言えない。
- 初手の絶対drop tickは .5=1、.75=19。2手目はそれぞれ61、98。予測・実ゲームで一致。実ゲーム側は通常のFixedUpdate/物理/衝突処理を実行し、診断用入力だけを制御した。進行中の物理は停止していない（fixtureロード時のみ一時停止）。

### 残る差・検証の限界

4条件×4時点で得点・合体数・GO状態・果物lineage集合が一致。ただしGO正例は0であり、GO見逃し率を検証した結果ではない。最大位置誤差0.03305 world unit、最大速度誤差0.20918 world unit/秒、最大角度誤差7.24955度。物理状態の完全一致はしていない。接触キャッシュ等の既知の制約を解消したものではない。

この比較は保存盤面を再構築し、同じFixedUpdate入力規則で時間を合わせたもの。既存の接触内部履歴を保存・復元できる検証ではない。Native側が2手完了まで104tickに進む場合も、比較は共通の100tick以内に限定した。

各8手UDP試験ではpost windowは全16手とも25tickだった。一方、応答から次のrequestまで従来1〜4tick・試作1〜5tick進んだ。**即座に次階層へ進むMCTSには実通信の間の待機時間が入らない**。同期探索の実時間消費とゲーム内物理tickも同一ではない。今回は重大な固定tick計数ミスは確認しなかったが、ネットワーク・描画・catch-up時間まで一般に一致する保証はない。GOが実ゲームUpdate/予測側tickで判定される既知の順序差も残す。

## 2. 試作の設計

設定 `pair_coverage_iterations` は既定0。15を指定すると、最初の15反復を5初手×3次手に割り当て、残り17反復は既存の通常探索。初手0/.25/.5/.75/1を順に一巡し、次手を0、.5、1の順で変える。25まで設定可能だが今回比較したのは15のみで、最適値とは主張しない。

- 各反復は2手で打ち切らず、既存と同じ最大深さ4まで進める。GO時だけ終端処理。
- 2手目は現在公開NEXTの果物。未知果物は既存分布からサンプル。比較では既存common-chance表を両方式で共用した。対応反復・深さで同じサンプルを用いるが、選択経路が違うので同じ未来盤面とは言わない。
- 行動選択の上書きは初めの2手だけ。既存の乱数行動抽選を先に行うため、不要な乱数消費順の変更を抑える。
- 木で既に不正/即GOと分かる強制候補は上書きしない。新規経路やrolloutのGOは通常の物理予測で検出する。
- UCT式、報酬、逆伝播、chance木、legacy展開の境界は維持。**強制した2手目がrolloutなら木に新しいaction edgeを追加しない**。これは8-Nの追加展開とは異なる。
- 木の実訪問edgeだけに既存コードで1回逆伝播する。結果の二重加算や追加25経路の外部計算はしない。
- 初期の15試行はCの種類で割当を変えない幅優先の診断。Cによるchance条件自体は保持し、残り通常探索では公開されたCに応じた行動判断が可能。異なる物理盤面のキャッシュを共有しない。
- 同期・固定5・chance・random・legacy展開・index初展開・1ゲームのみで許可する。既存の分割/候補/rolloutモードは保存し、試作との未検証併用は入力エラーとする。

## 3. 固定盤面の比較

序盤0果物、中盤15果物、密集35果物。探索seed8191/8192/8193、各32反復・深さ4。下表は3seedの平均で、独立した自然GOゲーム3件ではない。平均returnは探索が実際に訪れた経路の値であり、選択行動の真の期待値やゲーム最終得点ではない。

|盤面|方式|異なる2手系列|3手到達/32|4手到達/32|平均探索return 点|実物理tick|総時間ms|
|---|---|---:|---:|---:|---:|---:|---:|
|early_fixture|legacy|18.00|32.00|32.00|0.18|6967.33|173.34|
|early_fixture|coverage15|18.67|32.00|32.00|0.10|7107.00|170.81|
|mid_fixture|legacy|19.33|32.00|32.00|1.06|6786.67|531.18|
|mid_fixture|coverage15|20.33|32.00|32.00|1.14|6951.67|560.06|
|dense_safe_fixture|legacy|17.33|28.67|25.00|27.04|5787.67|854.17|
|dense_safe_fixture|coverage15|19.00|25.33|22.33|23.77|5575.33|788.64|

### seed別の判断とroot訪問

候補順は0/.25/.5/.75/1。各候補のmean・分散・chance訪問、2手目5×5行列、rollout開始深さ、ノード数、全経路は `outputs/step8r_01/analysis.json` に保存した。

|盤面|seed|方式|選択x|root訪問数|GO終端反復/32|最大合体数|
|---|---:|---|---:|---|---:|---:|
|early_fixture|8191|legacy|0.25|[6, 7, 6, 7, 6]|0|1|
|early_fixture|8191|coverage15|0.25|[7, 7, 6, 6, 6]|0|1|
|early_fixture|8192|legacy|0.25|[6, 7, 6, 6, 7]|0|1|
|early_fixture|8192|coverage15|0.25|[6, 7, 6, 6, 7]|0|1|
|early_fixture|8193|legacy|0.25|[6, 7, 6, 6, 7]|0|1|
|early_fixture|8193|coverage15|0.75|[7, 6, 6, 7, 6]|0|1|
|mid_fixture|8191|legacy|0.5|[6, 7, 7, 6, 6]|0|2|
|mid_fixture|8191|coverage15|0.5|[6, 7, 7, 6, 6]|0|2|
|mid_fixture|8192|legacy|0.5|[7, 6, 7, 6, 6]|0|1|
|mid_fixture|8192|coverage15|1.0|[6, 7, 6, 6, 7]|0|1|
|mid_fixture|8193|legacy|0.25|[7, 7, 6, 6, 6]|0|2|
|mid_fixture|8193|coverage15|0.25|[7, 7, 6, 6, 6]|0|2|
|dense_safe_fixture|8191|legacy|0.5|[7, 4, 10, 5, 6]|13|5|
|dense_safe_fixture|8191|coverage15|0.75|[4, 5, 7, 9, 7]|17|7|
|dense_safe_fixture|8192|legacy|0.75|[5, 5, 6, 10, 6]|10|7|
|dense_safe_fixture|8192|coverage15|0.75|[5, 4, 7, 9, 7]|13|6|
|dense_safe_fixture|8193|legacy|0.5|[4, 4, 10, 7, 7]|17|7|
|dense_safe_fixture|8193|coverage15|0.5|[6, 4, 8, 6, 8]|18|4|

- 試作は全9検索で予定した15種類を実行。しかし最終的な系列数が必ず増えるわけではなく、序盤seed8191では21→18。全18検索で同じ非root action edgeへの再訪は0回のまま。
- 密集盤面のGO終端反復は3seed合計40→48、深さ4到達は75→67。これらは訪れた経路の違いであり、実ゲームのGO確率悪化を推定する統計ではない。
- 既知の .5→0 は従来でも3seedそれぞれ5/2/5回、試作3/3/4回探索。seed8191試作は反復2で通り、その4手結果は39点3合体GOなし。従来も反復6で通り同39点3合体。2手目終了の18点と4手評価を混同しない。特定経路を選ぶような重み調整はしていない。
- 密集盤面の試作は探索内平均returnが2/3seedで下がった。系列被覆だけでは価値改善にならない。
- 同じ物理tick予算に近づける補助比較も保存した。各ペアの少ない側のtick数を上限に完全反復prefixで切った**事後診断**であり、別に時間制限実行した実験ではない。密集seed8191は従来29反復/5423tick/平均27.34点に対し試作32/5571/23.31、8192は30/5588/30.60対32/5660/24.97、8193は32/5348/22.34対31/5280/22.52。近いtickでも一貫した改善なし。
- 総時間にはMCTSのScene構築/再生/解放要求等を含む。試作の密集時間短縮はGO終端増加・tick減少を伴い、同量の物理計算が高速化したという結果ではない。逐次実行・ウォームアップ・GCの影響があるため、単一測定から数%の優劣を確定しない。
- Unity sampled peakは同一Player内の検索順で序盤49.9〜95.1MiB、中盤54.1〜109.1MiB、密集95.4〜170.6MiB。検索間の破棄待ちオブジェクトやdiagnostic report保持を含む。各検索GC0差3〜13回。これはOSプロセス最大メモリや方式単独の常駐量ではなく、順序と分離できないため新方式のリーク/省メモリの証明には使わない。

## 4. 短時間の実ゲーム・回帰テスト

- Player再ビルド成功。Unity 2022.3.21f1。develop維持、commit/pushなし。
- Python unittest 219件合格（今回追加7件）。設定制約、1ゲーム制約、強制順序、深さ4 return、木の訪問数再計算、ログ改変検出、方式間の設定差を確認。
- Unity組込みselftest：MCTS861、rules84、path26、frame58、計1029チェック合格。schedule全25組の一意性等もTimingProbe起動時に確認。
- 既存8-Pの固定5検索との互換性12件・試作の再実行3件、計15件で選択・ノード統計・全反復の経路/果物サンプル/得点/合体/GO/tick/state digestが一致（時間と今回追加ログ欄は除外）。0設定で旧結果を保つ。
- 8手×各方式、同seed757300、1ゲームずつUDP実通信。全16手落下成功、選択/適用座標、得点保存則、果物系列、探索trace監査合格。予測GO/実GOは全手falseであり、自然GO検証ではない。異常終了なし、新しい例外なし。
- 従来8手15点1合体、試作8手18点2合体。手数上限終了として自然GO比較から除外。平均判断時間308.44/298.35ms。Player実時間7.875/12.265秒、落下間隔の違いもあり、得点/秒の優劣を主張しない。
- ゲーム/物理に直接関係する既存9ファイルの作業開始時hashは不変。CandidateProbeだけは設定読み渡し2箇所を変更。既存のdirty変更を巻き戻していない。新しい画像/Scene/Collider/GO設定変更なし。Viewer GUIは操作しておらず、録画品質・4ゲームでの新方式は未検証。

## 5. 採否と次の優先事項

**標準採用しない。** 初期被覆は達成したが、深いedgeの蓄積は改善せず、4手評価・GO・seed安定性・実得点向上の根拠が不足。ユーザー指定の「明確な改善の兆候がある場合のみ10組比較」に達していないため、自然GO10組の新コマンドは提供/実行しない。

次に優先するのは、**root候補を共通chanceと対応する予算で比較し、分散と操作間の追加tickに対する順位感度を測る診断**。今回の15回強制割当をさらに調整するより、候補の期待値がサンプル/時間条件でどの程度変わるか確認する方が採否の根拠になる。例えば通信間隔相当0/数tickを同じ条件で変え、遅延合体・GO・root順位を比較する。新しいペナルティ追加やゲームの時間固定はせず、実測分布を先に得る。今回は未実装。

## 6. ユーザー向け短時間再検証

長時間の自然GO比較ではなく、各8手の監査付き再現コマンド。出力先は毎回新規。

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\step8r_smoke_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_coverage_ai.py --smoke --pairs 1 --max-steps 8 --seed 757300 --base-port 39000 --output $out
```

集計は `coverage_comparison.json`。`smoke_completed_not_strength`、自然GO有効ペア0、手数上限除外1が正常。全ログを残し、不整合があればエラーにする。既存の通常プレイは追加引数なしで従来方式。試作はCLI `--pair-coverage-iterations 15`、既定0。

保存済みの固定盤面/時間比較を再集計（新しい出力名へ）：

```powershell
.\.venv\Scripts\python.exe .\analyze_coverage_probe.py .\outputs\step8r_01\fixed.jsonl --output .\outputs\step8r_01\analysis_recheck.json
.\.venv\Scripts\python.exe .\analyze_timing_alignment.py .\outputs\step8r_01\timing.jsonl --output .\outputs\step8r_01\timing_recheck.json
```

## 7. 変更ファイルと入口（現在の行番号）

- `Unity/Assets/Scenes/Script/MctsPlanner.cs` — CoverageAction：97,234 / bool coverage=：181 / if(coverage&&depth<2)：233。
- `Unity/Assets/Scenes/Script/StepPlanner.cs` — public int pair_coverage_iterations：33 / if(pair_coverage_iterations<0：41。
- `Unity/Assets/Scenes/Script/SuikaCandidateProbe.cs` — class Search：8 / var settings=new PlanningSettings：184。
- `Unity/Assets/Scenes/Script/SuikaTimingProbe.cs` — static Row Native：26 / void FixedUpdate：46 / IEnumerator Start：59。
- `Python/src/suika_ai/unity_env.py` — pair_coverage_iterations=0：416 / if type(values["pair_coverage_iterations"])：423。
- `Python/src/suika_ai/parallel_play.py` — settings["pair_coverage_iterations"]>0：197。
- `Python/play_parallel_ai.py` — --pair-coverage-iterations：44 / settings.update(pair_coverage_iterations：63。
- `Python/analyze_two_step_probe.py` — def trace_search：5。
- `Python/analyze_coverage_probe.py` — def analyze：6。
- `Python/analyze_timing_alignment.py` — def analyze：37。
- `Python/compare_coverage_ai.py` — def settings：9 / def summarize：32 / def main：81。
- `Python/tests/test_pair_coverage.py` — def test_：10,13,17,27,29,32,36。

ほかに新規TimingProbe.cs.meta、docs/DEVELOPMENT_LOG.mdとdocs/DEVELOPMENT_PLAN.mdの簡潔な追記。本報告および新規outputs/step8r_01・step8r_smoke_01の検証資料。既存出力は上書きしていない。
