# 実行と再現性

## 公開サンプル（Unity不要）

リポジトリルートでPython 3.12を使用する。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install numpy==2.2.3
.\.venv\Scripts\python.exe Python\examples\portfolio\demo.py --json
.\.venv\Scripts\python.exe Python\examples\portfolio\render_overview.py --check
```

213係数の方策と実ログの公開観測を同梱している。入力は盤面・保持果物・公開NEXT・現在得点。
未公開の未来や最終得点は含まない。候補確率のデモであり、物理探索・ゲーム性能の再現ではない。
サンプルは開発データ由来で、独立した評価データではない。

## Pythonテスト（Windows）

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r Python\requirements-test.txt
$env:PYTHONPATH = "Python;Python/src"
.\.venv\Scripts\python.exe -m unittest discover -s Python\tests -v
```

GPU不要。Windows固有のプロセス・ロック処理を含むため、CIはWindows/Python 3.12を対象にする。
Unityや長時間シミュレーションはCIに含めず、ライブ試験は必要条件がそろわなければskipされる。
テスト用の予約seedは合成fixtureを注入し、ローカル実験ログに依存させない。
実験本体では予約情報がなければ失敗する動作を維持し、架空のTest予約ファイルは作らない。

2026-11-13、ステージ済みソースだけを展開した一時チェックアウトで、公開デモ・図の検査・全539テストを確認した。
534件成功、既存のUnity診断ファイルが必要な5件skip。ローカルの実験ログを参照せずに通ることを確認している。

## Unityプロジェクト

Unity Hubで`Unity/`を **2022.3.21f1** で開き、`Assets/Scenes/gameDisplay.unity`を選ぶ。
標準ゲームと、明示的なフラグで起動する研究用Labを区別する。

新Playerのビルド例（既存フォルダがあれば上書きを拒否）：

```powershell
$repo = (Get-Location).Path
& "C:\Program Files\Unity 2022.3.21f1\Editor\Unity.exe" `
    -batchmode -nographics -quit `
    -projectPath "$repo\Unity" `
    -executeMethod SuikaMaterialCurriculumBuild.Build `
    -logFile "$env:TEMP\suika-build.log"
```

成果物は`Unity/Builds/MaterialCurriculum_01/`。Unityライセンス・Editor環境が必要。
公開サンプルとPython CIはビルドを必要としない。

## 公開範囲

| 対象 | Gitに含める | 再現範囲 |
|---|---|---|
| ソース・テスト | はい | 実装と合成fixtureの回帰試験 |
| 小型方策・観測サンプル | はい | 固定5候補の推論 |
| 集計JSON・図の生成コード | はい | 公開集計と図の検査 |
| 全ゲームの生ログ | いいえ | 集計から生ゲームを再生成できるとは主張しない |
| 全データセット・旧Player | いいえ | 研究スクリプトの一部はローカル資産が必要 |
| 内部solver状態 | いいえ | 途中盤面の厳密復元は保証しない |

[長時間収集手順](MATERIAL_PROGRESS_LEARNING_ENVIRONMENT.md)はローカルデータセットが必要で、fresh cloneの最短デモとは別。

## CI

[workflow](../.github/workflows/python-tests.yml)は読取権限のみで、固定SHAの公式checkout/setup-pythonを使う。
推論デモ、図の出所検査、Python回帰試験を実行する。
参考：[GitHub公式 Python CI](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)、[setup-python](https://github.com/actions/setup-python)。
