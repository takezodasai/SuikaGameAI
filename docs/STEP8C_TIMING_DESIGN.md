# STEP 8-C 落下タイミングの設計案（未実装）

## 現在の合法な間隔

PlayerController.dropCooldownSecondsは0.4f（実測metadata 0.40000000596秒）。CanDropFruitは保持果物あり、Time.timeScale>0、Time.timeAsDouble>=nextDropAllowedAtを要求。DropFruitはさらに実Collider/壁によるEnsureHeldWithinRangeを通す。成功した時刻+.4を次の許可時刻にする。
今回、既存のlegacy action=2を約5ms間隔で0.65秒だけ送った。プローブが許可時刻から復元した成功落下の間隔は0.404123秒。0.4秒未満では受け付けず、Update/入力到達の刻み分だけ遅れる。数学上の下限は設定0.4秒であり、0.404123秒を新しい仕様値にはしない。AIはFixedUpdateの約0.02秒刻みなので、端数・浮動小数点・次のtick待ちも入る。条件だけから常に正確な20tickとは保証しない。

現在のAI移動速度はspeed7.5×NormalMoveInput0.5=3.75ワールド単位/ゲーム秒（matchKeyboardMoveSpeed=true）。移動中も実ゲームの物理/合体/得点/GOは進む。目標に先に着いてもcooldownが残れば待ち、cooldownが先に終わっても目標未到着なら落下しない。移動とcooldownは並行であり、単純に「移動時間+0.4秒」と足さない。

## post_drop_steps=25との違い

実行側UDPStepProtocolは、落下tickの次から25回以上のFixedUpdateを数え、LateUpdateで完了する。dt=.02なら落下後約0.5秒分。これは法的な最短落下間隔0.4秒とは別の、観測を返す窓。
現在はStepControlLocked/activeStepによってその窓が終わるまで次のstepを受けないため、同じ位置でも通常のenv.step連続入力は0.4秒より遅い。UDP/次のtick/移動/思考時間も加わる。catch-upで1renderに複数FixedUpdateがあれば、LateUpdateで判定するため25を超過し得る。
予測はdrop tick自体とその後25tickを進める。25tickは静止の保証でも次の合法入力時刻の保証でもない。今回25の設定は変更していない。

## 時間の定義

t0=コマンド受理時の現在ゲーム時刻。tauは「t0から実際に落下するまでの要求時間」であり、エピソード通算時刻や壁時計ではない。
落下位置xを現在と同じ安全範囲でワールド座標へ変換し、現在保持X/速度/固定刻み/残りcooldownから最短合法tickを求める。概算はmax(移動所要時間,残りcooldown)だが、実装は既存のMoveTowardsとNextDropAllowedAtを共有してtick単位で判定する。距離0でも受理後の最初のFixedUpdateを考慮する。
`追加0.25秒`を提供するなら、tau=最短合法時間+追加待機、とUI/ログで明示。0.25秒は.02刻みの整数でないため「少なくとも0.25秒」の場合13tick=.26秒に切り上げる等、丸め方を明示する。指定tauと適用tauを別々に保存する。

## 行動と実行

- drop(x,tau): すぐに目標へ移動を開始し、目標到着・cooldown終了・予約tick到達の全条件を満たして一度だけDropFruitを呼ぶ。移動中も世界を止めない。
- wait(k_ticks): 現在位置を維持し、落下せず物理だけ進める。NEXTは更新しない。自然合体/得点/GOは通常どおり。GOなら早期に終了する。
- 不合法なtauは候補生成で除外し、外部入力なら明確にエラー。密かに違うタイミングに変更して成功とは扱わない。
- 「WaitTicks(tau)してから現在のAdvance(x)」は、移動時間を追加で足してしまうため同じ仕様にならない。dropにnot-before tickを持たせ、移動と待機を同じ固定更新ループで管理する必要がある。
- Reset/GO/episode変更は予約を取り消す。action_idで再送の二重実行を防ぎ、drop/waitの種類と受理/完了/中止を区別。現在のPythonは非GOでdrop_success=falseの完了を拒否するため、wait用の明示的な応答種別が必要。

## 観測境界と探索

予測horizon25と実行の次意思決定境界を分離する設計が先。早期落下を可能にするためだけに世界を0.5秒進めてから時間を巻き戻すことはしない。
最短入力可能時刻を実行境界とするなら、予測の枝も同じ境界で接続する。長い評価用lookaheadで使った状態から、より早い時刻の次行動を重ねない。実行後状態/長期評価用状態/境界時刻を混同しない。
現PathSessionはネイティブ世界を保持し、WaitTicksで物理・合体・score・GO・clockを進められる。ただし予測のGOはtick後、実ゲームはUpdateで、Destroyタイミングやcontact cacheの制約も残る。任意時刻分岐でその差を消したと主張しない。

## 候補数・重複防止

例として5位置×追加待機3種=15drop候補。wait-onlyはxに関係ないので1種類ずつにまとめる。同じ落下tickになるtau候補は統合し、tau=0で状態を進めないwaitは禁止する。
MCTS反復数が同じなら全枝展開量は限定されるが、15候補では初回のroot網羅だけでも15反復必要。各候補に渡る訪問が減る。待機k追加は各rolloutでk回のSimulateコストを増やすため、単純に3倍とも一定時間とも言えない。35果物の現測定では32回/深さ4だけで約1秒の停止があり、時間候補を増やす前に計算とライブ進行の分離を優先する。
連続waitには1判断/rolloutあたりの累積時間上限と連続回数上限を設ける。隣接waitをまとめても、中間の意思決定機会/GO早期終了/NEXT非更新を維持する。接触cacheを捨てるJSONハッシュだけで別のnative状態を同一視しない。

waitでは未知NEXTを新しく抽選しない。保持/公開NEXTは同じままで、未知出現のchance nodeは実際のdropでだけ進める。探索深さはwaitも含めた意思決定回数で制限し、別に累積物理時間/落下数も記録して比較する。

ログ候補:accept_state_id/accept_game_tick、action_kind、requested_tau、applied_drop_tick/applied_tau、movement_ticks/cooldown_wait_ticks/extra_wait_ticks、思考のwall時間、drop_success、GOが発生したphase、各phaseのscore差。wall時間とgame時間は混ぜない。

## 報酬とValue

各行動のscore_after-score_at_acceptを一度だけ加算。移動/予約待機/落下後/操作間を分け、wait中の自然加点を次のdropでも加算しない。非同期化するなら思考中の加点も別の時刻境界として扱う。
Value入力にはcooldown/移動速度/dtが既に含まれるが、現モデルは主に25post tickのデータで学習した。早い境界・待機中・長い待機による分布変化は別途評価が必要。現在のモデルを変更/再学習しない。

## 次の実装に進む前の確認

1. ライブ進行と探索を分離する場合のrootの基準時刻、予約入力の期限と失効条件。
2. tauが最短時間からの追加か、現在からの総時間かをAPI上で固定。
3. 次の意思決定境界と評価horizon25の分離。
4. 同位置でcooldown直前/直後、移動時間との重なり、wait中合体/GO、再送/Reset中断を少数固定盤面で検証。
5. その後に5位置×少数tauを試し、Value/MCTSへの効果を比較する。今回、時間行動や非同期化は実装していない。
