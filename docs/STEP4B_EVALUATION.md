# STEP 4-B：予測精度の収集・集計・コード解説

2026-10-20。developの既存未コミット変更を保持した上で追加した。物理設定、進化・得点規則、通常step、UDP再送仕様は変更していない。コミット/Pushなし。STEP 5の探索AIは未実装。

## 実装したもの

- `Python/evaluate_unity_prediction.py`：回数・入力列・エピソード長・診断horizonを指定する収集CLI。compare_stepで実ゲームも1手進む。
- `Python/src/suika_ai/prediction_evaluation.py`：実ゲーム接続不要の集計関数。物理誤差、合体、reward、終端、時間を評価。
- `Python/tests/test_prediction_evaluation.py`：13件の新テスト。既存19件と合計32件成功（0.463秒）。
- Unityの小変更：`PredictionDiagnostics.Report/Compare`が最後の実測・予測Frameも返す。`SuikaPhysicsSimulator.Result/Run`が予測開始時の可視NEXTの型とゲームオーバー高さを返す。計算自体は変更しない。
- `docs/UDP_PROTOCOL.md`と`docs/DEVELOPMENT_LOG.md`を追記。本資料を追加。

開始前からSimulator、診断、UDP、Python比較、開発資料等の変更が存在した。それらを今回新規に作ったものとは扱わない。旧check_unity_prediction.py、UnityEnv、UDPStepProtocol、FruitEvolutionの処理は今回変更していない。

## データの意味と比較の公平性

`trials.jsonl`は1行1試行の追記ファイル。raw応答と計算済みmetricsを保存する。各行にexperiment_id、episode_id、stream_id、action_id、index、episode_step、操作x、UTC、horizonを記録する。

`previous_observation`は直前にPythonが受信した参考観測で、時間が経過し得る。**予測開始時の正確な公開snapshotは、state.prediction.diagnostics.initial_actual**を使う。Colliderや接触キャッシュを完全保存したJSONではない。可視NEXTはprediction.initial_next_fruit_type、移動速度はstep_result.movement_speed、dt/time_scaleは返却state、初期スコアはinitial_actual.scoreにある。

`compare_step`はUnityの同一Updateで先に予測を計算してから本物のstepを始める。Unity側のsource_unchanged検査を使い、本物のスコア/果物/乱数を予測が変更していないことを確認する。診断なしreferenceと診断ありpredictionの果物配列・score・game_overが完全に同じかも検査する。

eligibleの条件：公開初期値、固定dt、移動回数、全物理更新回数、落下後回数、診断の記録長、dropの有無/位置、スコア差分が整合し、記録が途中で切れていないこと。条件不一致はrawに残し、通常の精度集計から除外し理由を表示する。

物理値は両者ともPhysics2DFixedUpdate/Simulate直後のfinal Frameから取る。プレビューと合体元の削除待ちは除く。返却score/game_overは本物の完了応答と予測Resultから取る。GameManagerのUpdate判定と物理直後のFrameに位相差があるため、Frame.game_overだけを本物の最終終端と誤認しない。

終端で一方だけ早く停止すると更新数不一致になり得る。そこで通常集計とは別に、**game_over_all_completed_screening**と**terminal_disagreements_for_review**へ全完了試行の終端差を残す。これは除外で見逃しを隠さないための点検表であり、時刻不一致を含む数値をそのまま同期間の精度と断定しない。タイムアウト等はstatus=failedで残し、成功扱いしない。

## 数値の定義

### 物理誤差とID

既存果物は`f{ObservationId}`、合体果物は`m(親alias,親alias)`という既存診断aliasで対応付ける。世界ごとの新生成IDや近い位置だけで対応を推定しない。共通aliasで種類も等しいものだけ誤差を計算する。

- 位置：sqrt((xp−xa)^2+(yp−ya)^2)、Unityワールド単位。
- 速度：sqrt((vxp−vxa)^2+(vyp−vya)^2)、単位/秒。
- 角度：abs((anglep−anglea+180)%360−180)、度。359度と1度なら2度差（説明例）。
- 角速度：abs(wp−wa)、度/秒。

対応不明はpartial_lineage_onlyとし、不足/余分/種類不一致aliasを別記する。対応できた果物だけの分布と、対応が完全な試行だけの最大誤差分布を分ける。途中にID/種類の不一致がある時系列最大誤差も、完全対応の時系列分布から除外する。対応できない果物を0誤差として埋めない。

distributionは平均・中央値・最小・最大・P95・P99・ヒストグラムを返す。P95等はソートした観測値の線形補間。少数標本のP95は真の母集団P95の保証ではない。per_fruitは果物数で重みが変わる分布で、独立標本数ではない。

### 合体と連鎖

記録済みmergeイベントから親の系譜、合体前型、進化先、tickを読む。進化先-1はスイカ同士の消滅。生成Prefab数ではなくイベント数で合体回数を数える。

合体有無、種類/進化先の多重集合、親系譜、合体回数、連鎖有無を比較する。連鎖は**今回の観測期間中に生成された合体果物がさらに合体**したもの（aliasにm(が入れ子）。観測開始前に既に合体していた履歴は初期aliasに含まれない。

actual_positive（実測で合体あり）とactual_negativeを分け、recall=TP/(TP+FN)、precision=TP/(TP+FP)も返す。TPは実測/予測とも合体あり、FNは実測だけ合体あり、FPは予測だけ合体あり。合体前型→進化先別の発生数も集計する。イベントの厳密なtick一致は合体内容一致と別で、rawイベントに保存する。

### 得点

reward=完了score−予測開始時score。誤差d=予測reward−実測reward。完全一致はd=0、MAE=mean(abs(d))、最大誤差=max(abs(d))、過大予測はd>0、過小予測はd<0。実測reward=0/非0を別集計する。

### 終端

TP=実終端かつ予測終端、FN=実終端かつ予測非終端、FP=実非終端かつ予測終端、TN=両方非終端。見逃し率FN/(TP+FN)、誤警報率FP/(FP+TN)。分母0ならnull（未評価）で、0%として表示しない。ここでいう終端は設定したhorizon内の判定で、数手後の危険度ではない。

### 計算時間

reference_elapsed_msは既存の診断なし予測、elapsed_msは診断付き予測。各要求で両方を計算するため、収集全体の計算コストは両者分に加えて本物プレイ/JSON/通信がある。

scene_create_ms、copy_ms、simulation_ms、cleanup_schedule_msの分布を分ける。simulation_msには診断記録も含む。elapsedはScene生成開始から解放予約までで、Predictの前後の署名検査・JSON送信・**非同期Scene解放完了**は含まない。wall_msは本物が移動/落下する実時間も含み、予測だけの計算時間ではない。

## 盤面の層別

| ラベル | 定義 |
|---|---|
| sparse | 初期盤面果物0〜1個 |
| free_fall | 初期盤面が空でなく、全果物の初期接触0 |
| fruit_contact | 初期の盤面果物同士に接触あり。名前の接頭辞ではなく相手aliasを確認 |
| dense_contact | 初期果物6個以上、接触を持つ果物3個以上という暫定的な操作定義 |
| near_game_over | 初期盤面の最大中心Yがゲームオーバー高さ−margin以上。既定margin=.5単位 |
| actual_merge / actual_no_merge | 評価期間中の実測合体有無 |
| actual_cascade | 評価期間中の実測連鎖あり |
| other | 上記の初期盤面ラベルに該当しない |

ラベルは重複する。by_stratumの件数を足して全試行数にはしない。by_board_countは0〜1、2〜5、6〜10、11個以上の互いに重ならない区分。by_episodeも返す。dense/nearは物理設定やゲームルールを変える仕組みではなく、観測後の分類。タグ不一致など既存のゲーム判定仕様も勝手に修正しない。

特定層のquotaを強制的に満たす機能はない。通常の入力列や長めのエピソードで収集し、層が0件なら未評価として追加収集する。連鎖や終端が出るまでCodexが長時間反復することは今回はしない。

## 保存物と再開

| ファイル | 内容 |
|---|---|
| experiment.json | 実験ID、設定、Unity/Python版、branch/commit、コード/Scene/Prefab/設定等のSHA-256 |
| trials.jsonl | 1行1試行の元応答とmetrics。追記・flush・fsyncし、既存行を上書きしない |
| summary.json | 全体、層別、盤面個数別、エピソード別の分布/割合/除外理由 |
| trials.csv | 試行ごとのID、条件、得点、合体数、終端、対応率、時間 |
| fruits.csv | 対応付いた果物ごとの4種類の誤差 |

新規収集は存在しない出力フォルダだけ作る。--resumeは実験設定・コード/資産ハッシュ・commit等が一致する場合のみ追記する。--samplesは追加件数ではなく保存済みを含む総試行数。再開時のゲームはresetして**新しいepisode_id**から始める。途中盤面の接触履歴を復元したことにはならない。

Ctrl+Cでは保存済み行を保持する。処理中の1手が不明なら次回resetで復旧する。OS停止などで最終行だけ壊れた場合、--summarizeは完全な前の行を読めるが、--resumeは拒否する。元データを自動修復/削除せず、新しいフォルダで収集する。

--summarizeはUnity不要で、保存stateを現在の評価関数で再集計し、JSON/CSVだけを作り直す。raw行とexperiment.jsonは変更しない。現在の集計コードのハッシュをsummaryへ記録する。

今回のsmoke実験は実装中に収集し、その後Python側の検査/CSV/ハッシュ対象を強化して保存stateで再集計した。rawの生成時コードはexperiment.jsonに残る。**現行コードでこのsmokeフォルダへresumeはできない**。ユーザーの本収集は新しいフォルダで開始する。

## ユーザーが実行する手順

1. C:\SuikaGameAIのdevelopを確認する。Unity HubからC:\SuikaGameAI\Unityを開き、2022.3.21f1でgameDisplayをPlay。main.pyや他のUnityEnvクライアントを同時に動かさない。
2. 通常のPowerShellでC:\SuikaGameAI\Pythonへ移動。新しい外部ライブラリのインストールは不要。
3. まず20試行程度の短いpilotで出力と層別件数を確認する。出力名は未使用のものにする。

```powershell
Set-Location C:\SuikaGameAI\Python
python evaluate_unity_prediction.py --samples 20 --episode-steps 40 --post-drop-steps 100 --positions 0.65 --output eval_stack_2s_01
```

同じ入力を繰り返すのは接触/合体の診断用で、最もよいXを探索しているわけではない。通常stepの仕様は変更せず、比較命令だけの落下後100更新=約2秒以上を使う。

4. 同じコード・条件のまま160件まで増やす例：

```powershell
python evaluate_unity_prediction.py --samples 160 --episode-steps 40 --post-drop-steps 100 --positions 0.65 --output eval_stack_2s_01 --resume
```

5. 別実験として入力の偏りを変える例（長時間の実行はユーザーが行う）：

```powershell
python evaluate_unity_prediction.py --samples 160 --episode-steps 80 --post-drop-steps 100 --random-x --seed 123 --output eval_random_2s_01
```

seedはPythonの入力列だけを固定する。Unityの果物乱数を固定/改変していないので同じ盤面が再現される保証はない。ゲームオーバーや指定エピソード長でresetする。ゲームルールを変えて高密度盤面を強制生成しない。

6. 0.5秒の通常区間は別フォルダ・別実験にする：

```powershell
python evaluate_unity_prediction.py --samples 20 --episode-steps 20 --post-drop-steps 25 --positions 0,0.5,1,0.65 --output eval_cycle_05s_01
```

dt=.02のとき25更新。移動中の時間と落下した更新は別に含まれるため「落下後0.5秒以上」。異なるhorizonの精度は混ぜない。

7. 中断後やUnity停止後の再集計：

```powershell
python evaluate_unity_prediction.py --summarize eval_stack_2s_01
```

8. summaryのeligible/excluded、層別n、実測合体/非0得点/実終端の分母、対応率を先に確認する。0件の層や失敗を除外した割合を見ずに一致率だけ読まない。終了後はUnityのPlayを停止する。

## 今回の短時間実測

**2秒の診断期間：7試行、2エピソード（最初6試行＋再開1試行）、比較条件一致7、除外0。x=.65のみ。**

- 実測合体あり3、なし4。進化は0→1、1→2、3→4が各1回。種類/回数/親系譜が一致3/3。
- 得点増分一致7/7。実測非0は1点・3点・10点の3試行で3/3一致。MAE0、過大/過小予測0/7。
- 最終果物の種類・個数とalias完全対応7/7。対応した延べ果物16個。
- ゲームオーバー発生0件、誤警報0件。**見逃し率は分母0で未評価**。
- sparse3試行、fruit_contact2、other2（初期条件の層）。連鎖・密集・終端近傍は0。

| 最終誤差（延べ16果物） | 平均 | 中央値 | 最大 | P95 |
|---|---:|---:|---:|---:|
| 位置 | .0137325 | .00195664 | .113766 | .0506624 |
| 速度 | .0345394 | .00053824 | .187123 | .156277 |
| 角度（度） | 1.80595 | .0234571 | 16.9596 | 8.98665 |
| 角速度（度/秒） | 7.37468 | .0948336 | 35.6236 | 30.1708 |

| 予測時間ms（7試行） | 平均 | 中央値 | 最小 | 最大 | P95 |
|---|---:|---:|---:|---:|---:|
| 診断なしreference | 10.8134 | 9.0530 | 4.5095 | 24.3194 | 20.8843 |
| 診断付き | 14.2156 | 14.4696 | 5.5244 | 19.9391 | 19.4888 |

診断付きの平均内訳：Scene生成.06179ms、コピー.94439ms、物理＋診断13.14791ms、解放予約.05371ms。非同期解放完了・JSON/通信は除外。小さな盤面・異なるhorizonなので前回13.08msとの改善比較にはしない。

**0.5秒の診断期間：別の3試行、1エピソード、x=0/.5/1、比較条件一致3、除外0。**

- 合体・得点・終端の正例は0。得点増分0が3/3一致。
- 果物の種類・個数とalias対応3/3、延べ6果物。位置平均.000687805、最大.00412659。角度最大.839166度。速度/角速度の最終差0。
- sparse2、free_fall1、other1（ラベルは重複）。診断なし平均13.2207ms、診断付き16.8391ms。3試行では時間の優劣を判断しない。

保存先：Python/evaluation_smoke_step4b/とPython/evaluation_smoke_step4b_short/。UnityでPlay/実通信/Consoleエラー0/Stopを実確認した。32件のPythonテスト、既存UDPライフサイクル/step回帰テスト成功。データ追記・新episodeへの再開・オフライン再集計を確認。

**3回の合体一致や7回の得点一致は、母集団で95%精度達成の証明ではない。** 同じエピソードの連続盤面も独立な標本ではない。

## STEP 5へ進む前の判断と必要件数

まず100〜200試行をpilotとし、複数エピソードから各層の分母を確保する。全体160件でも合体正例3件なら合体95%の検証としては不足する。合体・連鎖・終端近傍を追加収集し、入力分布とhorizonを事前に決め、調整用と評価用のエピソードを分ける。

rateはWilson95%区間も出すが、独立Bernoulli試行という仮定があり、本データでは参考値。エピソードを跨ぐ独立性も自動保証されない。正式な判定にはエピソード単位の再標本化や十分な独立盤面を別途検討する。

合体/reward95%、最適候補80%、top3包含95%は開発目標として維持できる。ただし点推定だけで合格にせず、合体正例/連鎖/危険層の件数、信頼幅、過大予測と重大な見逃しを確認する。独立な100/200件でも95%付近の割合は概算で数%の推定幅が残り、クラスタ相関があればさらに広くなる。終端見逃し0件でも、実終端0件では何も検証していない。

優先順：1)危険の見逃し、2)合体/連鎖と得点の楽観誤予測、3)ID/期間不一致の原因、4)代表的盤面での時間/メモリ。今回の少数データではSTEP 5の開始条件を満たしたとは判定しない。

### 候補順位の正解データは未取得

現在の収集は順に異なる盤面を進める。**違う盤面での実測を同じ盤面の候補順位の正解に流用しない。** summary.candidate_ranking.available=falseとしている。31候補探索、評価関数、候補選択は実装していない。

公平な候補比較には、同じ盤面と接触履歴から各候補を本物で試す検証基盤が必要。座標/速度だけの復元はcold contact cacheになる。エピソード再生は可能性があるが、RNG、生成/有効化順序、固定更新ごとの入力、描画境界のDestroy、Start、TimeScaleまで記録/再現して初期状態を照合する必要がある。計算量は候補ごとに準備履歴の物理更新数が加算され、長い履歴ほど高くなる。今回未実装で、再生すれば完全一致するという保証もない。

準備後の指標はtie/許容幅を定義したtop1一致、top3内の最適包含、Spearman/Kendall順位相関、regret。regret=実最良候補の実価値−予測選択候補の実価値。同点全候補0点で唯一の正解位置を作らない。0.5/2秒後の得点による正解は短期の測定値であり、長期高得点の保証ではない。低いregretなら多少の順位違いを許容し、終端を選ぶ誤りは別に重く評価する。

## 変更コードの詳しい説明

以下のPythonプログラムは今回新規。C#は既存処理へ情報だけを追加した。各抜粋は現在のソースの実行で生成し、行番号を照合した。

### Unityへ送る比較要求

ファイル：[evaluate_unity_prediction.py](C:/SuikaGameAI/Python/evaluate_unity_prediction.py:121)  
関数：`collect / send`、該当行：121〜127行

```python
        original_send=env._send
        def send(message):
            if message.get("command")=="step":
                message=dict(message,command="compare_step",trace_physics=True,
                             comparison_post_drop_steps=args.post_drop_steps)
            original_send(message)
        env._send=send
```

変更前：この汎用収集CLIはなかった。変更後：このインスタンス内だけstepをcompare_stepに変換し、診断とhorizonを追加する。UnityEnv自身のaction_id・再送・timeout処理を再利用する。元の送信関数を呼ぶため再送される同一要求も同じ識別子のまま送る。入力はUnityEnvの要求辞書、出力はUTF8 JSONのUDP送信。旧UnityEnvや通常stepの動作は変えない。

送信JSONの形（IDは説明用）：

```json
{"command":"compare_step","stream_id":"stream-example","episode_id":"episode-example","action_id":1,"x":0.65,"trace_physics":true,"comparison_post_drop_steps":100}
```

UnityはUDPCommunicatorUnity.Update→HandleCommand→HandleStep→Predict/実step→CompleteStep→SendPacketで返す。受信JSONにはprotocol_version、episode_id、state_id、score、fruits、step_result、predictionがあり、prediction内に計算時間・予測fruits・diagnosticsが入る。完全な実測JSONはtrials.jsonlにある。途中の数値を架空の実測として提示しない。

### 1試行の保存まで

ファイル：[evaluate_unity_prediction.py](C:/SuikaGameAI/Python/evaluate_unity_prediction.py:140)  
関数：`collect`、該当行：140〜153行

```python
                    state,reward,done,info=env.step(x,timeout=args.timeout)
                    record.update(wall_ms=(time.perf_counter()-start)*1000,state=state,action_id=info.get("action_id"))
                    record["metrics"]=evaluate(state,args.near_over_margin,args.post_drop_steps)
                    record["status"]="completed"
                    context=state;episode_steps+=1
                except (RuntimeError,TimeoutError,ValueError,KeyError,TypeError) as error:
                    record.update(status="failed",error=f"{type(error).__name__}: {error}")
                    context=None  # Never retry an unknown outcome as a new action; reset first.
                append_record(directory/"trials.jsonl",record)
                records.append(record)
                summary=export_results(directory,records)
                print(json.dumps({"attempts":len(records),"eligible":summary["eligible"],"status":record["status"],
                                  "labels":record.get("metrics",{}).get("labels",[])}),flush=True)
                if record["status"]=="failed":
```

env.stepが本物の1手完了を待つ。stateを元データとして残し、evaluateで条件と精度を計算する。エラーはfailedとして記録し、未知の結果を新actionとして再実行せず終了する。次の実行はresetから始める。入力はx/設定、出力は追記されるrecordと集計。previous_observationと正確な開始snapshotの違いに注意。

### 中断に強い追記

ファイル：[evaluate_unity_prediction.py](C:/SuikaGameAI/Python/evaluate_unity_prediction.py:37)  
関数：`append_record`、該当行：37〜42行

```python
def append_record(path, record):
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))+"\n")
        file.flush()
        os.fsync(file.fileno())

```

1行をallow_nan=FalseでJSON化し、追記モードで書く。flushでPythonのバッファを出し、fsyncで保存を要求する。入力path/record、戻り値なし。既存行は上書きしない。OS停止中の1行まで絶対に完全になる保証ではなく、壊れた最終行の扱いはload_recordsが明示する。

### 再開条件の検査

ファイル：[evaluate_unity_prediction.py](C:/SuikaGameAI/Python/evaluate_unity_prediction.py:105)  
関数：`collect`、該当行：105〜115行

```python
    if args.resume:
        metadata=json.loads((directory/"experiment.json").read_text(encoding="utf-8"))
        if metadata["config"]!=config or metadata["provenance"]!=current:
            raise ValueError("Resume requires identical config, source hashes, commit and versions; use a new output folder")
        records,partial=load_records(directory/"trials.jsonl")
        if partial:raise ValueError("Resume refused after partial final raw record; summarize existing data and use a new folder")
    else:
        directory.mkdir(parents=True,exist_ok=False)
        metadata={"schema_version":1,"experiment_id":uuid.uuid4().hex,"created_utc":datetime.now(timezone.utc).isoformat(),
                  "config":config,"provenance":current}
        (directory/"experiment.json").write_text(json.dumps(metadata,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
```

再開時はexperiment.jsonの設定とprovenanceを現在と比較。不一致なら別フォルダを要求する。読み込んだ件数から続けるが、物理世界そのものの途中再開ではない。新規時はexist_ok=Falseで既存の出力を上書きしない。入力はCLI設定、出力はmetadataと読み込んだrecords。

### 位置だけで果物を対応させない

ファイル：[prediction_evaluation.py](C:/SuikaGameAI/Python/src/suika_ai/prediction_evaluation.py:79)  
関数：`compare_fruits`、該当行：79〜94行

```python
    for alias in sorted(predicted.keys() & actual.keys()):
        p, a = predicted[alias], actual[alias]
        if p["type"] != a["type"]:
            mismatches.append(alias)
            continue
        error = {"id": alias, "type": a["type"],
                 "position": math.hypot(p["position"]["x"]-a["position"]["x"], p["position"]["y"]-a["position"]["y"]),
                 "velocity": math.hypot(p["velocity"]["x"]-a["velocity"]["x"], p["velocity"]["y"]-a["velocity"]["y"]),
                 "angle": abs((p["angle"]-a["angle"]+180) % 360-180),
                 "angular_velocity": abs(p["angular_velocity"]-a["angular_velocity"])}
        if not all(math.isfinite(error[k]) for k in ERROR_FIELDS):
            raise ValueError("Non-finite fruit error")
        pairs.append(error)
    missing, extra = sorted(actual.keys()-predicted.keys()), sorted(predicted.keys()-actual.keys())
    complete = not (missing or extra or mismatches)
    return {"mapping": "lineage_exact" if complete else "partial_lineage_only",
```

alias共通部分だけ取り、type違いなら別欄へ送る。位置/速度は2次元距離、角度は周期を考慮した差、角速度は絶対差。有限値を検査してper_fruitへ追加する。入力は最後の2Frame、出力は果物別誤差と対応不完全の一覧。説明例：位置差(.003,.004)なら誤差.005。

### 比較条件を揃える検査

ファイル：[prediction_evaluation.py](C:/SuikaGameAI/Python/src/suika_ai/prediction_evaluation.py:132)  
関数：`evaluate`、該当行：132〜146行

```python
    if not p["source_unchanged"]: reasons.append("source_changed")
    reference_matches = (p["reference_fruits"] == p["fruits"] and p["reference_score"] == p["score"]
                         and p["reference_game_over"] == p["game_over"])
    if not reference_matches: reasons.append("instrumentation_changed_prediction")
    if abs(p["fixed_delta_time"]-state["fixed_delta_time"]) > 1e-7: reasons.append("fixed_dt_mismatch")
    if p["movement_steps"] != info["movement_steps"]: reasons.append("movement_ticks_mismatch")
    if requested_post_drop_steps is not None and not state["game_over"] and p["post_drop_steps"] != requested_post_drop_steps:
        reasons.append("requested_horizon_mismatch")
    if d["truncated"]: reasons.append("trace_truncated")
    if p["physics_steps"] != state["actual_total_physics_steps"]: reasons.append("total_ticks_mismatch")
    if d["actual_ticks"] != d["predicted_ticks"]: reasons.append("trace_ticks_mismatch")
    if d["actual_ticks"] != state["actual_total_physics_steps"]: reasons.append("trace_completion_mismatch")
    if not state["game_over"] and p["post_drop_steps"] != info["physics_steps"]: reasons.append("post_drop_ticks_mismatch")
    if p["drop_success"] != info["drop_success"]: reasons.append("drop_status_mismatch")
    if info["drop_success"] and abs(p["applied_x"]-info["applied_x"]) > 1e-5: reasons.append("drop_position_mismatch")
```

公開初期状態の検査に加え、診断なし/あり予測の一致、dt、移動回数、指定horizon、記録打切り、全更新数等を検査する。違いはreasonsへ追加し、成功率の分母から除くがrawは残す。入力state/近終端margin/horizon、出力eligibleと理由等。普通の物理誤差が大きいこと自体を理由に除外して精度を水増しする処理ではない。

### 合体イベントの解析

ファイル：[prediction_evaluation.py](C:/SuikaGameAI/Python/src/suika_ai/prediction_evaluation.py:51)  
関数：`merge_events`、該当行：51〜62行

```python
    for text in history:
        match = MERGE_EVENT.fullmatch(text)
        if match:
            tick, lineage, source, target = match.groups()
            if "untracked" in lineage:
                raise ValueError("Untracked merge parent")
            result.append({"tick": int(tick), "lineage": lineage,
                           "from": int(source), "to": int(target)})
        elif ":merge:" in text:
            raise ValueError("Unknown merge event format")
    return result

```

既存診断イベントのtick、親系譜、合体前type、進化先typeを正規表現で読む。未知のmerge形式やuntracked親は黙って無合体にせずエラー。入力イベント文字列配列、出力イベント辞書配列。Collision enterだけでは合体とは数えない。

### 連鎖と得点差

ファイル：[prediction_evaluation.py](C:/SuikaGameAI/Python/src/suika_ai/prediction_evaluation.py:153)  
関数：`evaluate`、該当行：153〜163行

```python
    actual_cascade = any(e["lineage"].count("m(") > 1 for e in actual_events)
    predicted_cascade = any(e["lineage"].count("m(") > 1 for e in predicted_events)
    conditions = initial_conditions(p, d, near_margin)
    labels = conditions["labels"] + (["actual_merge"] if actual_events else ["actual_no_merge"])
    if actual_cascade: labels.append("actual_cascade")
    delta = p["reward"]-info["reward"]
    if p["score"]-conditions["score"] != p["reward"]: reasons.append("predicted_reward_inconsistent")
    if state["score"]-conditions["score"] != info["reward"]: reasons.append("actual_reward_inconsistent")
    return {"eligible": not reasons, "reference_matches_traced": reference_matches, "ineligible_reasons": reasons, "conditions": conditions, "labels": labels,
            "physical": physical,
            "trace_max": {k: max(e[k] for e in d["errors"]) for k in ERROR_FIELDS},
```

合体aliasのm(が入れ子なら、期間内の生成果物が再合体している。初期条件と事後イベントのラベルを分ける。得点差はp.reward−info.rewardで、開始scoreとの整合も検査する。出力はmerge/reward指標の元データ。説明例：予測10点、実測6点なら誤差+4の過大予測。

### 分布とP95

ファイル：[prediction_evaluation.py](C:/SuikaGameAI/Python/src/suika_ai/prediction_evaluation.py:15)  
関数：`distribution`、該当行：15〜28行

```python
    values = sorted(values)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Non-finite metric")
    def percentile(q):
        at = (len(values) - 1) * q
        lo, hi = math.floor(at), math.ceil(at)
        return values[lo] + (values[hi] - values[lo]) * (at - lo)
    if not values:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None,
                "p95": None, "p99": None, "histogram": []}
    # Same numeric bins across runs; unit depends on the named metric.
    limits = (0, 1e-6, 1e-3, 1e-2, 0.1, 1, 10, 100)
    counts = [0] * (len(limits) + 1)
    for value in values:
```

ソート後の添字(n−1)*qの両側を線形補間する。n=0はNoneとn=0を返し、0誤差とはしない。数値例[0,1,2,3,4]のP95は3.8。後半で平均・中央値・最小最大・ヒストグラムを返す。入力は指標の値配列、出力は統計辞書。

### 得点あり/なしを分ける集計

ファイル：[prediction_evaluation.py](C:/SuikaGameAI/Python/src/suika_ai/prediction_evaluation.py:182)  
関数：`_group / score_group`、該当行：182〜191行

```python
    def score_group(items):
        return {"n": len(items), "exact": rate(sum(r["reward"]["error"]==0 for r in items),len(items)),
                "absolute_error": distribution([abs(r["reward"]["error"]) for r in items]),
                "overprediction": rate(sum(r["reward"]["error"]>0 for r in items),len(items)),
                "underprediction": rate(sum(r["reward"]["error"]<0 for r in items),len(items))}
    def merge_group(items):
        return {"n": len(items), **{key: rate(sum(r["merge"][key] for r in items),len(items))
                for key in ("presence_match","types_count_match","lineage_match","count_match","cascade_match")}}
    physical = [r["physical"] for r in rows]
    events = [r["merge"] for r in rows]
```

exact/over/underを件数つきrateへ渡し、abs(error)の分布を作る。merge_groupは有無だけでなく種類・系譜・回数・連鎖を比較する。同じ関数を全体/実得点非0/0、実合体あり/なしで使い、簡単な負例に埋もれないようにする。

### 層別と失敗の集計

ファイル：[prediction_evaluation.py](C:/SuikaGameAI/Python/src/suika_ai/prediction_evaluation.py:221)  
関数：`summarize`、該当行：221〜233行

```python
def summarize(records):
    rows = [dict(r["metrics"],episode_id=r["episode_id"]) for r in records
            if r.get("status")=="completed" and r["metrics"]["eligible"]]
    invalid = [r for r in records if r.get("status")!="completed" or not r["metrics"]["eligible"]]
    labels = sorted({"sparse","free_fall","fruit_contact","dense_contact","actual_merge","actual_no_merge","actual_cascade","near_game_over","other"} | {label for r in rows for label in r["labels"]})
    return {"schema_version":1,"attempts":len(records),"eligible":len(rows),"excluded":len(invalid),
            "exclusion_counts":dict(Counter(reason for r in invalid for reason in
                (r.get("metrics",{}).get("ineligible_reasons") or [r.get("status","unknown")]))),
            "all":_group(rows),
            "game_over_all_completed_screening": {**_group([dict(r["metrics"],episode_id=r["episode_id"]) for r in records if r.get("status")=="completed"])["game_over"],
                "note":"Includes timing-mismatched trials so terminal disagreements cannot be hidden by exclusion; inspect raw records before treating as same-horizon accuracy"},
            "terminal_disagreements_for_review": [{"index":r["index"],"episode_id":r["episode_id"],"exclusions":r["metrics"]["ineligible_reasons"],"game_over":r["metrics"]["game_over"]}
                for r in records if r.get("status")=="completed" and r["metrics"]["game_over"]["actual"]!=r["metrics"]["game_over"]["predicted"]],
```

completedかつeligibleを主集計へ、残りを除外理由へ分ける。代表層は0件も出す。終端差は別のscreeningへ残す。入力は保存されたrecord配列、出力はsummary.json相当の辞書。by_episodeとby_board_countも同じ_groupを利用し、標本の偏りを見えるようにする。

### C#：最後のFrameを応答へ追加

ファイル：[PredictionDiagnostics.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/PredictionDiagnostics.cs:141)  
関数：`Compare`、該当行：141〜148行

```csharp
    public static Report Compare(Recorder predicted, Recorder actual)
    {
        if(actual==null || predicted==null)return null;
        var report=new Report { initial_actual=actual.frames[0],initial_prediction=predicted.frames[0],
            final_actual=actual.frames[actual.frames.Count-1],final_prediction=predicted.frames[predicted.frames.Count-1],
            truncated=actual.truncated||predicted.truncated,predicted_ticks=predicted.frames.Count-1,actual_ticks=actual.frames.Count-1,actual_events=actual.history.ToArray(),predicted_events=predicted.history.ToArray() };
        var errors=new List<Error>();
        for(int i=0;i<Math.Min(actual.frames.Count,predicted.frames.Count);i++)
```

変更前：初期と最初の不一致Frame、更新ごとの最大差のみ。変更後：final_actual/final_predictionも返す（Report宣言33行にも追加）。最後の各果物をaliasで対応付けるために必要。入力Recorder2つ、出力Report。物理計算や観測時刻は変えず、既存の記録済みFrameを公開するだけ。

### C#：予測開始時の条件を記録

ファイル：[SuikaPhysicsSimulator.cs](C:/SuikaGameAI/Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs:236)  
関数：`Run`、該当行：236〜242行

```csharp
    Result Run(PlayerController player, float x, PlayerController.DropRange range, float dt, int postSteps)
    {
        var copyTimer = Stopwatch.StartNew();
        var result = new Result { requested_x = x, score = score, fixed_delta_time = dt,
            initial_next_fruit_type = player.nextFruitObject.GetComponent<FruitEvolution>().fruitType, game_over_height = gameOverHeight,
            limitation = "Cold contact cache; merges retired per tick; game-over checked per tick, live per rendered Update. Not bit-exact for arbitrary active contacts or multi-tick frames." };
        var liveFruits = Object.FindObjectsOfType<FruitEvolution>();
```

変更前：Resultに可視NEXT型と終端高さがなかった。変更後：Resultの17〜18行へフィールドを追加し、Run開始時に値を記録する。入力は実player/安全範囲/時計/回数、出力は予測Resultの条件情報。可視NEXTのfruitTypeだけを読み、未知の将来の乱数を取得しない。重力/Collider/ルールは変更しない。

### テスト：終端の除外で見逃しを隠さない

ファイル：[test_prediction_evaluation.py](C:/SuikaGameAI/Python/tests/test_prediction_evaluation.py:89)  
関数：`test_terminal_tick_mismatch_remains_visible`、該当行：89〜97行

```python
    def test_terminal_tick_mismatch_remains_visible(self):
        a=state();a["game_over"]=True;a["actual_total_physics_steps"]=20
        r=record(a);self.assertFalse(r["metrics"]["eligible"])
        s=summarize([r]);self.assertEqual(s["eligible"],0)
        self.assertEqual(s["game_over_all_completed_screening"]["fn"],1)
        self.assertEqual(len(s["terminal_disagreements_for_review"]),1)
        self.assertIsNone(s["all"]["physical"]["per_fruit"]["position"]["mean"])

    def test_truncation_and_initial_mismatch_excluded(self):
```

このファイル全体が今回新規。実終端だけtrue・更新数違いの合成入力を与え、主集計は除外しつつscreeningのFNと要確認一覧に残ることを検証する。合成テストはUnity物理の実測ではない。他にID不一致、角度の折返し、連鎖/消滅、空分母、スコア誤予測、追記/再開/不一致拒否を検証する。

### その他の関数と関係

- CLI load_records：保存ファイル→record配列と末尾破損フラグ。途中の壊れた行は拒否し、最後の不完全行だけ明示して読める前の行を返す。
- CLI export_results：record配列→summary.json/trials.csv/fruits.csv。派生物だけを作り直し、rawは編集しない。
- CLI provenance：実ファイルとGit参照→版/ハッシュ。Assetsのコード・Scene・Prefab・マテリアル・meta、ProjectSettings、Packagesも対象。resumeで条件混在を防ぐ。
- CLI main：引数解析、範囲検査、収集かオフライン再集計を選ぶ。Unityへの操作はcollectだけ。
- metrics rate：成功数/分母→割合とWilson区間。分母0はnull。独立性の仮定を無視して合格証明にしない。
- metrics merge_signature：イベント→Counter。順序に依存せず進化内容/回数を比較し、親系譜を含む版も返す。
- metrics initial_conditions：正確な初期Frame→盤面個数・接触・高さ・held/NEXT等の条件とラベル。

既存APIへの影響：新規評価CLIを起動しない限りPythonの通常プレイ処理は変わらない。Unity側はcompare_stepの診断応答へ情報を追加するのみで、プロトコル番号2と通常のstep/reset/重複防止を維持した。
