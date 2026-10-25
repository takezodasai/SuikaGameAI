# STEP8-O：未訪問actionの展開順序診断

2026-10-24 / C:\SuikaGameAI / develop / commit・pushなし。

## 結論

**shuffleを比較用に実装したが、標準はindexのまま維持する。** 左端優先は軽減した。しかし深い同一action edgeへの再訪は全9比較条件で両方式0回。密集盤面の探索内平均得点は3seedすべて低下、GOサンプルも増えた。高得点化の証拠はなく、10組自然GO比較は急がない。今回は各8手までの通信確認のみ実施した。

## 1. 従来処理

MctsPlanner.Selectはroot/非root共通。安全な候補が存在する場合は既知のGO/落下不可edgeを避け、visits==0の最小indexを返す。全合法候補が訪問済みなら従来どおり mean/point_scale + C sqrt(log(node.visits)/edge.visits) を使い、同値は既存配列順のまま。全GOフォールバックも既存処理。

chance子はdecision状態nodeとして生成される。従来expansion_policy=legacyでは生成直後rolloutとなり、再到着して初めてそのnodeの未訪問actionを選ぶ。rolloutは既存rng.Next(candidate_count)で選ぶため、今回のシャッフルとは独立。GOを予知して候補を避ける追加物理計算は行わない。

予算32ではrootは5候補すべて訪問できるが、chance子は到着回数が少なく、最小indexの初展開が偏る。最終選択は従来どおりroot訪問数優先、平均得点でtie-breakする。

## 2. 実装

設定 action_order_policy=index|shuffle を追加（既定index）。各decision node作成時にFisher-Yatesで1個の順列を生成し、Selectでその順にvisits==0の合法edgeを探す。毎回のランダム抽選や重複初展開ではない。訪問済みのUCT式・tie-breakは変更していない。rootにも同じ規則を使用する。

```csharp
var shuffle=new System.Random(unchecked(seed*1000003 ^ nodeId*9176 ^ 0x4D435453));
for(int i=count-1;i>0;i--) {
    int j=shuffle.Next(i+1);
    int tmp=order[i]; order[i]=order[j]; order[j]=tmp;
}
```

探索seedとnode IDだけから決まる専用stream。chance/rollout用System.Random、実ゲームUnityEngine.Randomを消費しない。未来果物・位置・得点・GOから順序を作らない。node IDは実際に生成した探索履歴で決まり、異方式間の同じIDが同じ意味の状態とは限らない。同一build・同一seed/初期盤面/設定での再現性を検証した。

試作はsync/chance-tree/grid/random/legacy expansion/1ゲームに限定し、8N追加展開やOpen-loopなどとの同時使用は拒否する。既存モード自体は削除していない。

## 3. 固定盤面の条件

序盤・中盤・密集35果物の3盤面を、探索seed8191/8192/8193で比較。ゲーム盤面と公開A/Bは固定し、seedは探索内部だけ変更した。固定5候補・32反復・深さ4・post25・random rollout・legacy expansion。未知果物は両方式共通の iteration×depth 表から既存の公開出現分布でサンプル（mcts_common_chance=true）。

シャッフルはchanceの乱数を消費しない。ただし経路/rollout開始深さ/GO終了が変われば、使われるchanceの個数とrollout乱数の消費順は変わる。共通表でサンプル条件を制御した比較であり、全て同じ未来を探索したとは扱わない。

## 4. rootの判断・訪問数（xは0, .25, .5, .75, 1の順）

|盤面|seed|A選択x|B選択x|A root訪問数|B root訪問数|
|---|---:|---:|---:|---|---|
|序盤0果物|8191|0.25|1.0|[6, 7, 6, 7, 6]|[6, 7, 6, 6, 7]|
|序盤0果物|8192|0.25|0.5|[6, 7, 6, 6, 7]|[7, 6, 7, 6, 6]|
|序盤0果物|8193|0.25|0.0|[6, 7, 6, 6, 7]|[7, 6, 6, 6, 7]|
|中盤15果物|8191|0.5|0.25|[6, 7, 7, 6, 6]|[6, 7, 7, 6, 6]|
|中盤15果物|8192|0.5|0.25|[7, 6, 7, 6, 6]|[6, 8, 6, 6, 6]|
|中盤15果物|8193|0.25|0.75|[7, 7, 6, 6, 6]|[6, 7, 6, 7, 6]|
|密集35果物|8191|0.5|0.75|[7, 4, 10, 5, 6]|[6, 6, 6, 8, 6]|
|密集35果物|8192|0.75|1.0|[5, 5, 6, 10, 6]|[6, 5, 7, 6, 8]|
|密集35果物|8193|0.5|1.0|[4, 4, 10, 7, 7]|[4, 5, 7, 6, 10]|

rootは全条件で全5候補訪問済み。順序変更だけでも初期サンプルの対応やUCT以降の統計が変わり、最終選択は変わりうる。選択が変わったことは改善の証拠ではない。序盤Aは全seed .25、Bは1/.5/0、中盤Aは.5/.5/.25、Bは.25/.25/.75、密集Aは.5/.75/.5、Bは.75/1/1で、判断の安定性が改善したとは言えない。

## 5. 非rootの初展開偏り・再訪

|盤面（3seed合算）|A 非root初展開histogram|B 同histogram|A 2座標prefix再訪合計|B 同|
|---|---|---|---:|---:|
|序盤0果物|[27, 9, 2, 0, 0]|[8, 9, 10, 5, 8]|42|35|
|中盤15果物|[28, 11, 1, 0, 0]|[6, 9, 12, 7, 10]|38|36|
|密集35果物|[27, 7, 4, 0, 0]|[6, 9, 8, 5, 9]|44|41|

全盤面合算A=[82,27,7,0,0]、B=[20,27,30,17,27]。左端の割合70.7%→16.5%、右側2候補への初展開0%→36.4%。ただし9検索を独立した9ゲームと見なす統計ではなく、少数の固定盤面/探索seedに関する記述結果である。各nodeの順列を先に作る性質とnative20seed試験も併せて確認した。

**非rootの同一action edge再訪はA/Bとも全条件0回。** 同じnodeへの再到着はあるが、別の未訪問actionを初展開する段階で予算を使い切る。同じ2座標を通る回数もchance/物理状態を区別しないため、同じ枝の期待値蓄積とは異なる。今回、chanceによる分散を解決できたとは言えない。

木に登録された行動は最大2手目まで（3/4手目の登録0）。ただしrolloutを含む物理予測は最大4手。GOで途中終了した経路はそこで止める。全反復のphase、node/edge訪問、行動/chance列、root平均得点は analysis.json に保存した。

左右反転盤面は今回は作成していない。果物stateのx/vx/角度だけ反転しても、PrefabのCollider offset/非対称形状・壁・床・生成位置まで鏡映した物理状態にはならないため、厳密な対称性試験として扱わない。偏りの直接集計と3seed比較を優先した。

## 6. 探索結果・物理コスト

|盤面|方式|平均探索報酬|平均合体数/反復|GO反復合計/96|平均物理tick|平均全体ms|
|---|---|---:|---:|---:|---:|---:|
|序盤0果物|index|0.177|0.094|0|6967.3|190.81|
|序盤0果物|shuffle|0.188|0.104|0|6833.7|168.07|
|中盤15果物|index|1.062|0.198|0|6786.7|527.99|
|中盤15果物|shuffle|1.469|0.198|0|6680.0|517.75|
|密集35果物|index|27.042|2.323|40|5787.7|808.59|
|密集35果物|shuffle|19.958|1.729|49|5372.0|758.87|

密集seed別の平均探索報酬はA 28.406/30.375/22.344、B 17.5/25.375/17。選択root自体の1手GO予測は全てfalse。探索内GOは40→49反復に増えたが、これはGO予測精度ではなく探索した経路の違い。

Bの密集時間は約6.1%短いが、tickも約7.2%少なく、早いGOや短い移動で仕事量が減っている。高速化成功とは扱わない。時間測定は各条件1回、A→B順でwarmup/GC/CPU変動もあり、純粋なシャッフル overhead を分離した速度比較ではない。

近い物理予算の事後比較（完了した反復prefixだけ）では、密集Aはseed順29/29/30回に対しB32回。A平均探索報酬27.345/30.310/21.3、B17.5/25.375/17で、今回の密集盤面ではBの優位は出なかった。これは別の時間制限実行ではない。

密集探索中Unity割当の開始→sampled peak増分はA14.16～15.78MiB、B14.16～17.81MiB。GC0はA9/7/5、B9/6/5。nodeごとのint[5]を追加するが、これらの値からリークや真のprocess peakを判断しない。

## 7. 既知経路

現在のPlayerで2手診断を再実行し、0.125→0.125は15点・1合体・84tick、0.5→0は18点・2合体・86tick、両GO falseを再現。既存cooldown・移動・公開A/B・post25を使用し、native root/live/乱数不変も確認した。

固定5候補で15点経路は候補にない。密集の18点座標prefix通過数はA 5/2/5回、B 1/2/1回。9候補/64反復/seed8191の別診断では、15点prefix A3/B1、18点prefix A5/B2。最終選択A .625/B .5、探索内平均得点24.484/17.781、GO31/36、tick10611/9632、全体1549.39/1410.69ms。非root同一edge再訪は両0。

これらは「先頭2座標を通った回数」。その後4手まで進んだ報酬が必ず15/18点になるわけではない。既知経路を選ぶように式や重みを調整していない。9候補/64回は5/32と同じ計算コストの比較ではない。

## 8. 再現性・回帰・実通信

- 既存indexは8Nの3盤面×common chance有無=6条件で、action/chance列・得点・合体・GO・tick・木統計が一致。
- shuffleを別Playerで再実行し、3盤面で同seedの全経路・順列・訪問数・得点・GO・tick・選択が一致。
- Python198テスト成功。新規9テストは設定・組合せ禁止・1ゲーム制限・順列欠損/重複・初展開順監査・既存ログ互換・長時間比較ガードなど。
- Unity MCTS861/rules84/path26/frames58=1029チェック成功。native順序試験は20seedで全候補1回ずつの初展開、同seed一致、全訪問後UCT一致、GO候補除外、node別streamを確認。コンパイル/Value parity/Player build成功。
- 保護対象のゲーム/物理6ソースSHA256は作業開始時と一致。GO .83、環境step8e-all-fruit-go-v2は実通信メタデータ監査成功。既存ログ/モデルは変更していない。

同じゲームseed755300、各8手、1Playerずつ順次実行。indexは17点/3合体/平均判断275.27ms、shuffleは16点/2合体/279.59ms。各8落下成功、選択座標一致、得点保存則/公開果物系列一致、新しいworker例外なし。両ともGOなしで手数上限終了し、自然GO比較の有効ペアは0と記録。GO見逃し/過剰予測0件だがGO正例0なので精度評価はできない。

## 9. 変更ファイル・関数・行番号

|ファイル|関数/位置|内容|
|---|---|---|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/MctsPlanner.cs:26|Node|順列をnodeで保持|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/MctsPlanner.cs:55|Select|初訪問だけ順列順、既訪問UCT維持|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/MctsPlanner.cs:85|ShuffledOrder/SearchNode|独立seedのFisher-Yatesとnode生成|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/MctsPlanner.cs:145|PlanFrames、356 NodeMetric|root/chance子の生成、順列をログへ追加|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/StepPlanner.cs:31|PlanningSettings/Validate|index既定、shuffleの対応範囲検証|
|C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaCandidateProbe.cs:8|Search、GeometryTests、Start|探索seed/order設定とnative試験|
|C:/SuikaGameAI/Python/src/suika_ai/unity_env.py:416|PLANNING_DEFAULTS/validate_planning_settings|設定追加・既存互換|
|C:/SuikaGameAI/Python/src/suika_ai/parallel_play.py:197|run_parallel|新試作の複数ゲーム利用を拒否|
|C:/SuikaGameAI/Python/play_parallel_ai.py:44|main|--action-order-policyを追加|
|C:/SuikaGameAI/Python/analyze_two_step_probe.py:6|trace_search|順列・初展開・root UCT・visit/returnを監査、旧ログ互換|
|C:/SuikaGameAI/Python/analyze_order_probe.py:6|analyze/main|3seed別の偏り・再訪・GO・物理tick・計算時間・予算比較|
|C:/SuikaGameAI/Python/compare_order_ai.py:9|settings/validate_geometry/summarize/main|同seedの各8手比較、整合性監査、途中終了を自然GOから除外|
|C:/SuikaGameAI/Python/tests/test_action_order.py:10|OrderTests|新規9回帰テスト|
|C:/SuikaGameAI/docs/STEP8O_REPORT.md|本書|実測・制限・次の判断|
|C:/SuikaGameAI/docs/DEVELOPMENT_LOG.md、DEVELOPMENT_PLAN.md|末尾追記|簡潔な結果と次の方針|

## 10. ユーザー用コマンド

今回の結果では自然GOの10組比較を推奨しない。比較専用scriptも--smokeのみ許可し、長時間比較を誤って開始しないようにしている。次のコマンドは同seedで両方式を各8手ずつ検証する。Playerはビルド済み。

```powershell
Set-Location C:\SuikaGameAI\Python
$out = "outputs\order_smoke_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\compare_order_ai.py --smoke --pairs 1 --max-steps 8 --seed 755300 --base-port 38800 --output $out
```

order_comparison.json/order_pairs.csvに監査結果、各方式のJSONL/manifest/Player logを保存する。手数上限は自然GOとして扱わず、強さ用の統計は空になるのが正常。途中停止後の集計は--analyze-onlyと新規--report-dirを利用可能。

固定盤面の既存結果を再集計する場合（入力ログを変更しない）:

```powershell
$report = "outputs\order_fixed_audit_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".json"
.\.venv\Scripts\python.exe .\analyze_order_probe.py .\outputs\step8o_01\fixed.jsonl --output $report
```

CLIの既定は--action-order-policy index。shuffleは明示指定のみ。比較条件の探索seedは8191、固定診断では8191/8192/8193。ゲームseedと探索seedを区別する。既存の通常CLIは維持するが、現時点でshuffleを標準プレイに推奨しない。

## 11. 次の推奨

標準採用しない。今回、順序の偏りは除去できたが深いaction統計は蓄積しなかった。chance分散が残るという仮説は支持されるが、それだけが高得点を制限する原因と断定はしない。物理予測誤差と短いhorizonも既知の制約である。

次は「root候補の評価に共通chance系列を対応付ける層化評価」を1軸で設計・比較することを推奨する。例えば同じ仮想未来果物系列を5つのroot actionに対応させ、限られた予算内でroot間の差を低分散で比較する。物理状態は各試行で独立再生し、未知分布を変えず非公開情報は使わない。これは未訪問順序変更や現在のiteration×depth共通表とは異なるroot配分設計で、今回未実装。まず固定盤面で同tick/同時間、選択のseed感度を測り、その後に自然GO得点で判断する。

chanceノードの予算集中は同一edge再訪を促せるが、結果の偏った再利用やNEXT適応の損失を起こさない設計が必要。Coarse-to-Fineは位置解像度不足を狙う方法で、固定5の18点経路を既に持っている今回の統計分散への直接対策とは異なる。複数の改善を同時には実装しない。

出力: C:/SuikaGameAI/Python/outputs/step8o_01 と C:/SuikaGameAI/Python/outputs/step8o_smoke_01。長時間実験・再学習・Viewer変更・4ゲームへの試作展開は未実施。
