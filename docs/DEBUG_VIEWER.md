# 4画面デバッグViewer（2026-10-21）

C:\SuikaGameAI / develop。既存の独立Unity Player、数値UDP、音声制御、JSONL保存を維持。今回の実装はPythonのみ。Unity本体・Scene・Prefab・物理設定・GO比率.862・評価式 `V=reward/55-.2R` は変更していない。Player再ビルドは不要（前回の映像対応Playerを使用）。commit/push/追加バックアップなし。STEP7/8未実装。

## 起動

```powershell
cd C:\SuikaGameAI\Python
# 4ゲーム、4画面、1つのViewerに2×2表示
python play_parallel_ai.py --games 4 --view-games 4 --episodes 1 --max-steps 1000 --output outputs/view4_run01
# 4ゲームを実行、表示は最初の2ゲームだけ（横2分割）
python play_parallel_ai.py --games 4 --view-games 2 --episodes 1 --max-steps 1000 --output outputs/view2_run01
# 3ゲーム表示は2×2の1枠が空く
python play_parallel_ai.py --games 4 --view-games 3 --output outputs/view3_run01
# 1画面は従来指定も使用可能。例：Game02だけ表示
python play_parallel_ai.py --games 4 --view-game 2 --output outputs/view_single_run01
# 全headless、音声OFF、映像機構・Viewerなし
python play_parallel_ai.py --games 4 --headless --episodes 10 --output outputs/headless4_run01
```

出力フォルダは未作成の名前を使う。--gamesは1〜4、--view-gamesは0〜games（先頭Nゲーム）。未指定なら0。--view-gameは従来互換の単一indexで、--view-gamesと同時指定不可。--headlessと1枚以上の映像は同時指定不可。--no-viewerで転送のみ有効化できる。表示対象以外には新規映像処理を起動しないが、描画付きモードでは元のUnityウィンドウも残り、非表示対象Playerも通常描画する。最小化時の取得は保証しない。

Viewer再接続（実行中run）：

```powershell
$env:PYTHONPATH='src'
python -m suika_ai.video_viewer --run outputs/view4_run01 --metrics outputs/view4_run01/reopened_metrics.json
```

1枚は1画面、2枚は横2分割、3〜4枚は2×2。各タイルにGame ID・撮影時点の得点・GO・画像遅延を表示。手数は画像headerに含まれないため今回は未表示、ゲーム別JSONLのtransitionに記録済み。古い--mapによるViewer単体起動も維持。

## 音声と停止

基本はGame00のみON、他はOFF。headlessは全OFF。起動時--main-audio on/off、--others-audio on/offも維持。

Viewer右上 **Others audio ON / OFF** で、表示されていないゲームも含むGame00以外をまとめて制御。ボタンは要求投入のみを表示し、確認済みであるかはcontrols.jsonlのacknowledgedを見る。GO後や収集終了後にもViewerが残ることがあり、終了済みゲームへの要求は処理されない。

既存コマンドも使用可能：

```powershell
cd C:\SuikaGameAI\Python
python control_parallel_run.py outputs/view4_run01 --others --audio on
python control_parallel_run.py outputs/view4_run01 --others --audio off
python control_parallel_run.py outputs/view4_run01 --game 0 --audio off
python control_parallel_run.py outputs/view4_run01 --game 2 --video off
python control_parallel_run.py outputs/view4_run01 --game 2 --video on
python check_parallel_data.py outputs/view4_run01
```

映像ON/OFFできるのは起動時に選択したゲームのみ。Viewerを閉じても各Player・収集・保存は継続する。映像取得自体を止めるにはvideo offを送る。全ゲームの停止は収集器のCtrl+Cで、現在の操作の保存後に自分が起動した子Playerだけ終了する。Viewerは独立なので残った場合は×で閉じる。

## 構造とheadless

run.jsonにゲームごとの固有video_mapsを記録。表示選択されたPlayerだけ従来の15fps/640x360/非同期GPUreadback→共有メモリを起動。Python Viewerが各マップの最新フレームを読み、1つのウィンドウに配置。読込中のフレームはsequenceで排除し、遅れた古いフレームを追いかけない。Viewerからゲームを待たせる要求・ロック・UDP受信は追加していない。ただしCPU/GPUを共有するため処理負荷による間接的影響はある。

音声UIは既存の原子的な制御ファイルを使用し、既存の収集器が要求を送る。action_id・物理演算・Reset経路は変更していない。不正な複合要求は全項目を検証してから反映する。

headless/表示0では動画Player引数なし、RT/readback/転送/Viewerなし。空の表示対象リスト生成は起動時のみ。従来の制御pollは維持。Unityコードは今回未変更。headless実通信では全ゲームのvideo_frames/readbacks/render_texturesが0、音声生成も0だった。

Viewerの各フレーム測定値は直近4096件のみ保持し、総表示数・欠落数は累計。長時間で測定配列が増え続けない。active_display_fpsは最初〜最後の表示間隔で、映像OFFを挟むとその期間も含む。更新停止時はno fresh frameを表示し、古い画像を現状態と保証しない。

## 短時間検証

- Python71テスト成功。1/2/3/4枚の配置、表示数/範囲/互換指定/headless、固有ソース、制御独立性、不正要求の部分適用防止、測定配列上限を検査。
- 実機4画面をComputer Useで確認。異なる盤面のGame ID・得点・GO更新を確認。Viewerの音声ON/OFFボタンに対しGame01〜03すべてのacknowledgedを確認、Game00を対象にしないことも確認。
- 4ゲーム×16手×3条件=192手と目視4ゲーム×30手=120手。全ログで報酬保存・混入/重複なし。Playerログに新規例外なし。映像1枚では非表示3ゲームのRT/readbacks=0。
- 計測用Viewerは先に自動終了し、その後も各Playerの完了と保存が継続。1枚テストは終了後約7.4〜8.8秒、4枚テストは約2.4〜5.2秒後にゲーム別ログ保存が完了。目視試験も終了時に全データを検査。自然GOまでの完走は未実施。
- 1/2/3枚の配置は自動テスト、4枚は実画像で確認。画面を手動で自由配置する機能や画面サイズへの自動縮小は今回追加していない。

## 性能測定

同じ4ゲーム、seed12345〜12348、5候補、落下後25更新、各16手。1枚/4枚は4つとも描画付きPlayerで、表示対象だけ動画転送。headlessは4つとも描画なし。各条件1回の短時間測定で、以下は起動待ちを除く合計64手/最遅worker収集時間。

| 条件 | 合計手/秒 | 起動込み手/秒 | CPU概算合計 | 最大working set合算 |
|---|---:|---:|---:|---:|
| headless4 | 3.638 | 3.448 | 432.2% | 482.7 MB |
| 4ゲーム・1枚表示 | 3.660 | 2.955 | 162.6% | 732.2 MB |
| 4ゲーム・4枚表示 | 3.549 | 2.924 | 158.4% | 756.4 MB |

CPUは1コア=100%、各PlayerとViewerの個別平均を合算（起動を含みサンプル期間が異なる）。メモリは各プロセス最大値の和で同時ピークではない。収集Python/Editor/OSは含まない。GPU使用率・GPU実行時間は未測定。headlessのCPUが高い原因は今回切り分けておらず、映像が処理を軽くしたとは解釈しない。

1枚Viewer単体：CPU11.03%、最大41.65MB。4枚Viewer単体：CPU33.92%、最大54.26MB。

| 表示 | 映像更新中fps | 平均遅延 | p95遅延 |
|---|---:|---:|---:|
| 1枚 Game00 | 14.31 | 44.35ms | 64.38ms |
| 4枚 Game00 | 14.13 | 45.89ms | 66.10ms |
| 4枚 Game01 | 14.31 | 45.06ms | 64.26ms |
| 4枚 Game02 | 14.28 | 40.62ms | 59.88ms |
| 4枚 Game03 | 13.92 | 45.44ms | 84.49ms |

遅延はUnity撮影UTC→Tk画像設定まででモニター発光遅延ではない。UTC粒度/補正とOS負荷の影響を含む。更新中fpsは起動待ち除外。全Viewer寿命平均fpsは起動待ちを含むため約10〜11fps。

headlessを基準とした選択X/得点の初回分岐は、1枚表示ではGame00/01/02/03が8/9/8/11手目、4枚では8/10/15/11手目。盤面進行や受信描画境界の差で後半条件は一致していない。4枚表示の約3%の速度差を純粋な表示負荷とも統計的劣化とも断定しない。旧版headlessの同一16手条件での再測定はしていないが、今回はUnity側のheadless経路自体を変えていない。

生ログ：Python/outputs/debug_headless4_01、debug_viewer1of4_01、debug_viewer4_01、debug_viewer_ui_01。summary.json、debug_viewer_test.json、viewer_metrics.json、各JSONL、controls.jsonlで確認できる。

再測定（既存フォルダ名と重複させない）：

```powershell
python benchmark_debug_viewer.py --views 0 --steps 16 --port 23000 --output outputs/bench_headless02
python benchmark_debug_viewer.py --views 1 --steps 16 --port 23200 --output outputs/bench_view1_02
python benchmark_debug_viewer.py --views 4 --steps 16 --port 23400 --output outputs/bench_view4_02
```

この計測は独立した4ゲームを起動し、Viewerは指定時間で先に終了する。新しい計測コードは終了時の完了手数と終了後に進んだゲームも記録する。短時間の少数比較にとどめ、性能の結論には長時間・複数seedで再測定する。

## 残りとSTEP7

4画面デバッグ表示の初版として使用可能。元のPlayerウィンドウも残る、最小化/他GPU/長時間安定性は未検証。1280×720相当＋ラベルの固定サイズで、小さい画面向けの自動縮小は未実装。手数のViewer表示・音声確認状態のUI反映・GPU計測も未実装。

次にSTEP7へ進める基盤は維持している。ただし学習前には自然GOを含む長時間データ、打切りと終端ラベル、Value Networkの入力/教師ラベル/分割/保存再開の設計を確認する。今回はValue Network/MCTSを実装していない。

## 今回の変更関数

| ファイル | 関数・開始行 |
|---|---|
| `Python/src/suika_ai/parallel_play.py` | def selected_video_games L157 / def run_parallel L174 |
| `Python/src/suika_ai/video_viewer.py` | def viewer_sources L41 / def tile_positions L36 / class FrameMetrics L51 / def main L71 |
| `Python/src/suika_ai/presentation.py` | def configured_video_maps L9 / def write_control L16 / def poll L39 |
| `Python/play_parallel_ai.py` | def main L12 |
| `Python/benchmark_debug_viewer.py` | def benchmark L8 |
| `Python/tests/test_presentation.py` | class MultiViewerTests L35 |

資料更新：本資料、STEP6_USAGE.md、PRESENTATION_PROTOTYPE.md、DEVELOPMENT_PLAN.md、DEVELOPMENT_LOG.md。Unityファイルへの今回の編集なし。


## プレイ中の表示切り替え（2026-10-21）

```powershell
cd C:\SuikaGameAI\Python
python play_parallel_ai.py --games 4 --view-games 4 --episodes 10 --seed auto
```

- Viewer上部の「一覧」で全映像、「game_00」〜「game_03」で選択したゲームだけを表示。
- 映像をダブルクリックすると、そのゲームの1画面表示と一覧を切り替える。
- 「全画面 (F11)」またはF11で全画面を切り替え、Escで通常ウィンドウへ戻す。画像は縦横比を維持して領域へ拡大縮小（Tkの1/8刻み）。
- ゲームのReset/再起動や行動命令は送らず、ゲーム・保存を継続する。切り替えられるのは起動時に映像を設定したゲームだけ。--view-games 1で起動した場合、他ゲームは選択できない。
- 1画面表示中は隠れた映像の読み取り/変換/描画を省略する。Unity側の撮影・共有メモリ転送は起動時の設定どおり継続し、音声設定も切り替えない。
- Python全80テスト成功。実Tkウィンドウで4枚→各1枚→4枚、F11/Esc、画像の範囲内拡縮を検証。今回、Unity Playerを使ったプレイ中の再検証・性能測定は未実施。Unityコード・ゲームルール・物理・評価式は未変更。
