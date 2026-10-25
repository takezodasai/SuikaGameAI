# 音声制御と1ゲーム映像試作（2026-10-21）

対象：C:\SuikaGameAI / develop / Unity 2022.3.21f1。commit/pushなし。STEP7/8、4画面Viewer、AIモードは未実装。ゲームルール・GO比率.862・Collider・物理設定を変更していない。

## 評価式

`V = reward/55 - 0.2R`。H/Dは診断値のみ、両penaltyは常に0。有限非負の旧weight_height/weight_dangerは互換入力として許容するが、Python設定とUnity Freezeで0化。通常候補の同点判定からもDを外し、落下までの更新数→indexを使う。GO候補除外と全候補GO時の生存更新数→実GOライン超過量→value→indexは維持。

## 起動・停止・制御

UnityでPlay停止、未保存Sceneがない状態で **Tools → Suika → Build STEP6 Windows Player**（Ctrl+Alt+F8）を実行する。通常生成先はUnity/Builds/Step6/SuikaGameAI.exe。今回通常版と試作版Step6Previewの両方を更新済み。Scene/Prefab変更後には再ビルドする。

```powershell
cd C:\SuikaGameAI\Python
# 2ゲームを実行、映像はGame00の1つだけ。音声は00のみON。
python play_parallel_ai.py --games 2 --episodes 1 --max-steps 1000 --view-game 0 --output outputs/view_run01
# 通常headless。全音声OFF、映像機構/Viewerは起動しない。
python play_parallel_ai.py --games 4 --episodes 10 --max-steps 1000 --headless --output outputs/headless_run01
# 起動時の音声指定例（headlessはこれらの指定より全OFFを優先）
python play_parallel_ai.py --games 2 --main-audio off --others-audio on --output outputs/audio_run01
```

出力名は未作成のものを使用する。ゲーム数は従来通り1〜4。--view-gameはそのうち1つのindexだけを指定。--headlessとの併用はエラー。--no-viewerは映像転送のみでViewerを起動しない検証用。

別PowerShellから、実行中の出力フォルダを指定する：

```powershell
cd C:\SuikaGameAI\Python
python control_parallel_run.py outputs/view_run01 --others --audio on
python control_parallel_run.py outputs/view_run01 --others --audio off
python control_parallel_run.py outputs/view_run01 --game 0 --audio off
python control_parallel_run.py outputs/view_run01 --game 0 --video off
python control_parallel_run.py outputs/view_run01 --game 0 --video on
python check_parallel_data.py outputs/view_run01
```

音声は--allも使用可能。映像をON/OFFできるのは起動時に--view-gameで選んだゲームのみ。初版では起動時に未選択のゲームへ後から映像機構を追加しない。Viewerを閉じてもゲームは停止せず、映像取得も継続する。取得を止める場合はvideo offを送る。Viewer終了後の再表示はrun.jsonのvideo_mapを使い、`$env:PYTHONPATH='src'; python -m suika_ai.video_viewer --map 'run.jsonに記録された値'`。出力済みフレームしかない場合は「No fresh frame」を表示する。

収集の停止は収集器のCtrl+C。現在の操作を保存してから自分が起動したPlayerのみ終了する。Viewerは独立しており、残ったViewerはウィンドウの×で閉じる。勝手な無限Resetはしない。--episodesで指定した有限回のみResetする。

制御ツールはUDP受信ソケットを開かず、実行ID付きの原子的な制御ファイルを作る。既存収集器が要求を送信し、観測のaudio_revision/video_revisionで確認、同じrevisionで再送する。action_id/episode_idには触れずResetをまたいで設定を維持する。controls.jsonlのacknowledgedがUnity確認済み。要求をキューに入れただけでは成功扱いしない。終了済みrunへ要求を書いてもゲームは起動しない。

## 音声

プロセス単位のSuikaAudioでAudioListener.pauseと効果音生成を制御。OFF時はDrop/mergeの音源GameObject/AudioSourceを作らず、再生中の自前効果音も停止。ON時は従来PlayClipAtPoint相当の位置・音量・寿命で生成する。スコア/乱数/物理/時間には触れない。現在SceneのBGM AudioSourceは元から無効。将来BGMを有効化した場合もListener.pauseに従う。headlessでもUnity音声エンジン自体をビルドから除去したわけではない。

観測にaudio_enabled/revision/played/suppressedを追加。音声出力の聴感・機器ごとの遅延は未測定だが、OFFで生成カウンタが止まりsuppressedが増え、ONでplayedが再び増えることを実通信確認。

## 映像構造

ScreenCapture.CaptureScreenshotIntoRenderTextureで描画済みの実画面を取得し、640×360へ縮小、AsyncGPUReadback、Windows名前付き共有メモリ、独立Tkinter Viewerへ渡す。カメラのtargetTexture/viewport/Transformを変更しない。PNG/Base64/UDP画像送信は流用しない。15fpsを目標に終端フレームで取得。GPU要求は最大1つ、処理中はフレームを捨てる。メインスレッドのGPU完了待ち/Viewer待ちは行わないが、RTへのコピー・CPU転送コストはゼロではない。

共有メモリは1つの最新RGBAフレームだけ、奇数/偶数sequenceで書き込み中を判定。Viewerはコピー前後でsequenceを読み、途中のフレームを破棄する。プロセス/実行ごとに固有のマップ名。スコア/GOは撮影時の値を同じheaderへ記録。現在映像にGOラインを追加描画しておらず、Y=3.62の固定値も追加していない。

初期OFF/headlessは動画コンポーネント・RT・readback・共有メモリ・Viewerなし。実行中OFFでは進行中の非同期要求だけ安全に完了させ、RT/共有メモリを解放。OFF中にフレーム数/readback数が止まりRT数0、ONで再開することを確認した。従来観測用のTexture2Dなど既存処理は維持。

現在は描画付きWindows/DX11 Player限定。headlessの途中から映像ONには対応しない。元Playerのウィンドウも残る。最小化・描画停止・別GPU環境・リモート接続では未検証。画像上下は実機で反転バグを発見してViewerで修正済み。DX11は反転なし、他backendの調査用にViewer --flip-yを用意。追加パッケージ不要（Python標準tkinter/mmapのみ）。

## 検証結果

- Python66テスト成功。Unity評価回帰：D/旧D係数の影響なし、Dの同点判定なし、GO除外/全GOフォールバック/失敗候補の扱い成功。
- 実通信：1ゲーム35手、音声/映像切り替え14手×2、修正後目視20手。Viewer終了後も操作継続。4ゲーム×2episode×3手=24手、Reset/ID/UDP独立、混入/二重計上なし。短時間なので自然GOまでの完走は未検証。
- OFF中のRT数0、frames/readbacks一定を5連続観測で確認。音声OFFでplayed停止/suppressed増加、ONでplayed再開。新規Player例外なし。Editorログの途中保存時に一時的な未定義型compileエラー履歴は残るが、最終compile/ビルド/回帰は成功。履歴は削除していない。
- 目視：背景/籠/果物/NEXT/得点が正しい方向で表示され、移動・落下・加点の実画面を確認。

### 性能（短時間、長期統計ではない）

同じseed12345、1ゲーム、5候補、25更新、8手。以下は起動待ちを除いた収集速度。CPUは**1コア=100%**、Playerの起動後から終了前までのサンプル、メモリはworking set最大。GPUは未測定。

| 条件 | 手/秒 | Player CPU | Player最大MB |
|---|---:|---:|---:|
| 変更前headless | 1.092 | 108.5% | 119.09 |
| 変更後headless | 1.092 | 110.3% | 119.24 |
| 変更後画面付き・映像OFF | 1.082 | 36.7% | 173.37 |
| 変更後画面付き・映像ON | 1.399 | 42.4% | 179.16 |

旧/新headlessは8手すべての選択X・得点が一致。映像ONは後半2手の状態/選択が分かれたため、この値を高速化の証拠として扱わない。描画負荷・入力受付フレーム・既存のDestroy/Update境界差で盤面条件を完全固定できず、映像有無の純粋なコスト差を断定できない。候補数/予測時間/seed/ゲーム数は揃えたが、大量試行・固定入力での評価は今後。

最終14手の切替テスト：Viewer CPU5.66%（1コア比）、最大38.16MB。Player CPU43.64%、最大177.19MB。ただしON/OFF混在であり定常ON性能ではない。CPU集計範囲に起動処理を含むため、描画あり/なしのCPU単純比較にも注意。

修正後20手の目視テスト：303フレーム、更新中14.40fps。全ウィンドウ寿命32.31秒には起動待ちとゲーム終了後の無更新を含み、平均9.38fps。撮影→Tk画像設定の遅延平均44.78ms、中央値44.91ms、p95 65.68ms、最大81.27ms。画像変換+Tk設定平均7.08ms。これはモニター発光までの遅延ではなくUTC時刻差（OS時刻粒度・補正の影響あり）。

初版の共有メモリWriteArrayは約8ms/フレームで重く、一括stream転送へ修正後は切替テスト観測で約0.16〜0.28ms。CaptureScreenshot/BlitのCPU提出時間は約0.02〜0.03msだが、GPU実行時間そのものではない。15fps×640×360×4byteは1ゲーム約13.2MiB/秒の転送。4画面では単純換算約52.7MiB/秒となり、GPU/Viewer/CPU負荷の実測が必要。

生ログ：Python/outputs/preview_perf_{old,new,visible,video}_01、preview_controls_final、preview_parallel4_01、preview_visual_final。旧ビルド比較後、通常Playerも再ビルドするため、benchmark_presentation.pyのoldモードは既存の変更前exeを--baseline-exeで明示した場合のみ使用可能。記録を旧版測定値として残すため追加コピーは作っていない。

## 判断と未解決事項

**A：デバッグ用途として4画面へ段階拡張する候補として妥当**。1画面は目標に近い更新頻度で、headlessの速度低下は今回観測されなかった。ただし4画面性能やGPU負荷を保証しない。今回は1画面までで停止し、ユーザー承認後にのみ各Playerの固有マップを同じViewerの2×2に描画する。収集器とViewerの独立性を維持し、描画対象数をゲーム実行数と分ける。16ゲーム化は別途検討。

未検証：長期・自然GO完走、連続何時間ものメモリ安定性、4画面の負荷、最小化/他GPU、音声の実機聴感、GPU使用率、完全同条件の物理軌跡。現時点で学習機能や探索性能の改善を主張しない。4画面化よりSTEP7を優先する場合は、今回の映像機構をOFFにして既存headless収集を続けられる。

## 変更ファイルと関数・行番号

今回の追加・変更のみ（以前の未コミットSTEP5/6変更もGit差分には含まれる）。

| ファイル | 関数と開始行 |
|---|---|
| `Unity/Assets/Scenes/Script/StepPlanner.cs` | PlanningSettings Freeze: 17 / Breakdown Evaluate: 53 / void Choose: 173 / bool BetterNormal: 195 |
| `Unity/Assets/Scenes/Script/SuikaAudio.cs` | void Initialize: 10 / void Set(: 12 / void PlayEffect: 21 |
| `Unity/Assets/Scenes/Script/SuikaEffectSound.cs` | class SuikaEffectSound: 3 |
| `Unity/Assets/Scenes/Script/SuikaVideo.cs` | void StartIfConfigured: 25 / void Set(: 32 / IEnumerator CaptureLoop: 40 / void Capture(: 53 / void Release(: 92 / void OnDestroy: 101 |
| `Unity/Assets/Scenes/Script/SuikaWorkerOptions.cs` | void Initialize: 16 |
| `Unity/Assets/Scenes/Script/UDPStateProtocol.cs` | void HandleCommand: 23 / void SendPacket: 68 |
| `Unity/Assets/Scenes/Script/UDPCommunicatorUnity.cs` | void Start(: 30 |
| `Unity/Assets/Scenes/Script/PlayerController.cs` | void DropFruit: 131 |
| `Unity/Assets/Scenes/Script/FruitEvolution.cs` | OnCollisionEnter2D: 52 |
| `Unity/Assets/Editor/StepPlannerProbe.cs` | void Run(: 20 |
| `Unity/Assets/Editor/SuikaWorkerBuild.cs` | void BuildPreview: 13 / void BuildAt: 14 |
| `Python/src/suika_ai/unity_env.py` | def request_presentation: 369 / def validate_planning_settings: 399 |
| `Python/src/suika_ai/parallel_play.py` | def player_command: 146 / def run_parallel: 157 |
| `Python/src/suika_ai/presentation.py` | def write_control: 9 / def poll(: 32 |
| `Python/src/suika_ai/video_viewer.py` | def read_frame: 13 / def ppm(: 27 / def main(: 36 |
| `Python/play_parallel_ai.py` | def main(: 12 |
| `Python/control_parallel_run.py` | p=argparse: 8 |
| `Python/benchmark_presentation.py` | def resources: 16 / def benchmark: 26 |
| `Python/tests/test_presentation.py` | class PresentationTests: 7 |

新規Unityスクリプト3件には対応する.metaも追加。資料更新はSTEP5_DESIGN.md、STEP5_USAGE.md、STEP6_USAGE.md、DEVELOPMENT_PLAN.md、DEVELOPMENT_LOG.md、本資料。ビルドで自動更新されたTMP fallback atlasは作業開始時の内容へ復旧。今回Scene/Prefab/物理設定への編集なし。


2026-10-21追記：ユーザー承認後、Python側を最大4画面へ拡張した。本文の「1画面まで」「4画面未実装」は以前の試作時点の記録。現行の操作・測定・制約はDEBUG_VIEWER.mdを参照。
