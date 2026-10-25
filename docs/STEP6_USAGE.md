# STEP 6：独立した複数ゲームの実行

## 採用方式

1ゲームを1つのUnity Windows Playerプロセスとして実行する。Pythonの各スレッドは専用UnityEnvを1つ所有する。候補予測は従来どおり各ゲーム内で逐次実行し、異なるゲームを同時進行させる。

| 方式 | 既存構造との整合性 | 速度・再現性・実装コスト |
|---|---|---|
| 独立Playerプロセス（採用） | GameManager/ScoreManager/EvolutionDatabaseのstatic、Unity Random、Time.timeScale、GO/ResetをOSプロセスで分離 | メモリ・起動費用は増えるが既存実ゲームを再利用できる。CPU競合と描画の更新境界による差は残る。まず2〜4ゲーム向け |
| 1プロセスで複数PhysicsScene2D | 物理世界だけを分離しても上記staticや乱数、時間・UIは分離されない | 将来的に軽量化できる可能性はあるがゲーム本体のcontext化・手動tick/イベント順の設計が必要。今回の小規模対応を超えるため見送る |

通常描画と`-batchmode -nographics`を同じPlayerで使える。描画なしでグラフィックス初期化を省くUnityの仕組みを利用する（[Unity 2022.3コマンドライン資料](https://docs.unity3d.com/2022.3/Documentation/Manual/PlayerCommandLineArguments.html)）。fixedDeltaTime・timeScale・物理設定は変更しない。描画の有無やPC負荷で1描画フレーム内のFixedUpdate数が変わり、既知のGO/Destroy境界誤差が変化する可能性はある。完全同一軌跡や高速学習の完成を主張しない。

## 1. 一度Playerをビルドする

Unity 2022.3.21f1でC:\SuikaGameAI\Unityを開き、Playを停止する。未保存Scene変更は自身で確認・保存する。

メニュー：**Tools → Suika → Build STEP6 Windows Player**（Ctrl+Alt+F8）

生成先：`C:\SuikaGameAI\Unity\Builds\Step6\SuikaGameAI.exe`

ビルド時だけgameDisplay Sceneを指定する。ユーザーのBuild SettingsはSampleSceneのままでもよく、登録先を勝手に変更しない。Scene・Prefabを更新した場合は再ビルドが必要。exeだけでなく隣の_Data、UnityPlayer.dll、MonoBleedingEdge等も実行に必要。ビルド生成物はGit対象外。ビルド中はPlayerを終了しておく。

## 2. 起動

```powershell
cd C:\SuikaGameAI\Python
# まず2ゲーム、各1エピソード・最大1000手
python play_parallel_ai.py --games 2 --episodes 1 --max-steps 1000 --output outputs/parallel_run01
# 4ゲーム、明示的に各10エピソードを収集
python play_parallel_ai.py --games 4 --episodes 10 --max-steps 1000 --output outputs/parallel_run02
# 描画なし（初版の検証済み入口。長期の精度比較は今後）
python play_parallel_ai.py --games 4 --episodes 10 --max-steps 1000 --headless --output outputs/parallel_headless01
```

既存フォルダへの上書きは拒否する。--outputを省くと日時とランダムIDによる新しいフォルダを作る。自動プレイの開始時に各ゲームをResetする。--episodesで指定した有限回数だけ実行し、GOまたは手数上限で1エピソードを閉じる。手数上限で終わったものは未完了として記録し、最終得点ラベルにしない。既定は各1エピソードであり、無限Resetループはない。

停止は実行中のターミナルで**Ctrl+C**。受付済みstepの完了とログ書き込みを待ち、新しいstep/Resetは送らない。起動したPlayerだけを終了し、既存Editorや別のPlayerには触らない。緊急終了では最後の命令が結果不明になる可能性があるため、そのエピソードを成功扱いしない。新しい実行は別出力フォルダ・新しいResetで開始する。途中のUnity物理世界の復元/再開機能はまだない。

各ゲームの画面を個別に閉じると、その実行は異常終了として扱う。通常はCtrl+Cを使う。GUI表示位置の整列・YouTube用表示はSTEP 9の対象。

## 3. ポートとゲームID

既定--base-port 18000では、game_00=Unity18000/Python18001、game_01=18002/18003、game_02=18004/18005、game_03=18006/18007。localhostのみ使用する。起動前に全ポートの使用状況を検査し、使用中なら起動しない。同時に別の収集をする場合は例えば`--base-port 19000`を指定する。

ゲームごとに独立したseed（既定12345+i）を起動前に設定する。Resetは各プロセスの乱数系列をそのまま進める。エピソードごとに同じ乱数へ戻さない。状態にgame_id/process_id/stream_id/episode_id/state_id、行動にaction_idがあり、Pythonは期待するgame_id以外の観測を拒否する。action_idは各エピソード内で独立管理。ファイルはゲーム別、データキーはgame_id+stream_id+episode_id+action_id。

`--seed`、`--candidates`（既定5）、`--post-drop-steps`（既定25）、`--settings 設定.json`、`--exe 別のPlayer.exe`を指定できる。通常の1ゲームは従来のEditor+play_one_step_ai.pyを維持。Player経由の比較は`--games 1`を使う。

## 4. データ形式

出力にはrun.json（設定・PID・ポート・seed）、game_XX.jsonl、game_XX_player.log、summary.jsonを保存する。JSONLは排他的に新規作成し、1イベントごとにflush+fsyncする。処理停止で完了済みのレコードを上書きしない。強制終了時には最後の行だけ不完全な場合があり、検査コマンドはその行をデータとして数えず報告する。

- episode_start：ゲーム/stream/episode ID、seed、初期state。
- transition：action_id、観測前状態observed_before、Unity内受付時のdecision_source、操作後state、現在果物、公開NEXT、selected_x、score、reward、between_steps_reward、GO、評価候補内訳info。
- terminal_observation：step間にGOになった場合の終端観測と加点。新しい落下行動や重複actionとしては記録しない。
- episode_end：GO/打切り理由、最終観測、step_reward_total、between_steps_reward_total、末尾のtail_between_steps_reward、保存則conserved。自然GOならfinal_score、打切りならfinal_score=nullとlast_observed_score。
- worker_error：例外、最後の既知状態、結果不明の命令、完了済み手数。勝手にResetして続行しない。

observed_beforeは直前に受信したスナップショットなので、実際の受付盤面と時間差がある。学習用の行動前盤面はdecision_source（候補共通のsource_fruits/現在果物/表示NEXT/score_before）を優先する。未表示の未来果物は含めない。terminal_observationの終端通知は落下行動として学習しない。

得点を二重計上しない：`操作後score = 前観測score + between_steps_reward + reward`。episode終了時は`初期score + Σreward + Σbetween_steps_reward + tail_between_steps_reward = 最終観測score`。既存reward_accountingも状態に残す。between_steps_rewardをstep rewardへ足して別名保存しない。

最終得点はepisode_endからepisode IDで各transitionへ結び付ける。STEP 7でValue target・残り得点・割引・正規化・打切りのbootstrap等を設計する。今回はモデル学習を行わない。

## 5. 保存データの検査と速度

```powershell
python check_parallel_data.py outputs/parallel_run01
```

重複action、ゲーム混入、得点/報酬保存、終端ラベルを検査する。summary.jsonのcollection_steps_per_secondは起動待ちを除いた全ゲーム合計、startup_included_steps_per_secondは起動を含む。メモリやログのfsyncも含めて実測し、候補予測速度と混同しない。

## 6. 評価関数と今後

新式は`V = 得点増分/55 - 0.2R`。Hは診断用のみ、height_penaltyは互換のため0として保持。古いweight_heightがJSONに残っていても減点は復活しない。evaluation_version=step5-v3-score-roughness。GO候補除外と全GOフォールバックは維持。

P（合体しやすさ）、B（小果物の埋もれ）、NEXT戦略、進化順配置は将来の上級者戦略AI構想として保留。STEP 6でこれらやモード切替は実装しない。

STEP 7へ進む前に、自然GOを含む長期収集、画面有無での精度/GO率、データ保存量とディスク使用量、異常終了データの除外、エピソード単位の学習/検証分割、Value targetとモデル保存/再開の方針を確認する。


## 今回の短時間検証結果（2026-10-21）

Python61テスト成功。Unity評価テストで、高さHの分析値は残るが高さ減点は0、古いweight_height=100でも減点しないこととGO選別を確認。

| 実行 | 完了手数 | 起動除外の合計手/秒 | 起動込み手/秒 |
|---|---:|---:|---:|
| 画面付き1ゲーム | 5 | 1.55 | 0.53 |
| 画面付き2ゲーム | 合計10 | 3.30 | 1.51 |
| 描画なし4ゲーム | 合計20 | 6.04 | 4.85 |

各ゲーム5手の小さい測定で、初回ロードのキャッシュ、果物系列、OS負荷が異なる。画面付き2ゲームは約2.13倍の合計手/秒だが、長期の速度保証ではない。4ゲームは描画条件も異なり、描画省略だけの効果とは分離できない。物理更新間隔は全ゲーム約0.02秒、timeScale=1。

1/2/4ゲームの全保存transitionでゲーム混入・重複なし、報酬保存を確認。各ゲームで異なるstream/episode/PID/seedと果物系列を確認。2ゲーム各2エピソード（各5手、合計20手）でも指定回数だけのResetと保存を確認。

実Player2個で、一方のReset後ももう一方のエピソードと果物が残ることを確認。自然GOを待つ短時間テスト（中央35手/左端70手）ではGOが発生せず、その条件の個別GOは未確認。別途、既存EditorのGO fixtureと独立Playerを併走させ、EditorだけGO→停止→Resetしても他PlayerのGO/エピソード/盤面が変わらないことを確認。収集器のGO終端・step間GO・最終得点保存は自動テストで確認している。自然GOエピソードを含む長期データ収集はユーザー側で追加検証する。

Playerスモークログに新規例外なし。Editor側の従来plan_stepも確認。STEP 4の予測誤差、描画有無による長期挙動差、強制終了/電源断とディスク満杯、長期メモリ使用量は未解決/未検証。

停止経路も実2Playerで確認：Ctrl+Cと同じKeyboardInterrupt処理で各4手を保存し、stoppedの打切り記録・保存則・子Player解放を確認。Editorは既存のPlay状態に戻している。seed/PID/各種IDは再現・管理メタデータであり、将来のValue Network入力には未公開未来を推測する目的でseedを含めない方針とする。


2026-10-21：D減点も削除。H/Dは分析用のみで旧weight_dangerは無視（0に正規化）。通常候補の同点時もDを使用しない。GO除外・全GOフォールバックは維持。音声制御と1ゲーム映像試作の操作はPRESENTATION_PROTOTYPE.md参照。新オプションには新しいPlayerが必要なため既存Playerは再ビルドする。


## 4画面デバッグViewer
--gamesと独立した--view-games 0〜gamesを追加。例：`python play_parallel_ai.py --games 4 --view-games 4 --output outputs/view4_run01`。1枚/2枚/3〜4枚は1画面/横2分割/2×2。--view-game単一indexも互換維持。音声ボタンと負荷・停止・再接続はDEBUG_VIEWER.md参照。headlessでは映像なし。


STEP7-A追加：--seed autoで実行ごとのseedを自動選択、--independent-episode-seedsでViewerなしの独立episode収集（Player再起動）を選べる。従来の整数seed・連続Reset/RNG方式は維持。例と変換/学習手順はSTEP7A_USAGE.md。
