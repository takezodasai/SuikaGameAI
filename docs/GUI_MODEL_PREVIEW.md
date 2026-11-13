# 最新モデルを映像付きで1ゲーム試す

Windows / Unity **2022.3.21f1**。実際の果物・得点・NEXT・進化リングが見えるUnity画面で、AIがその場で操作する。同期探索中は画面更新が一時停止する。

公開された凍結方策 `gen_d9eb9e9bef0e` を同梱。MCTS256反復・深さ4・固定5候補、rolloutの50%で学習方策を使用する。学習データセットや過去ログは不要。Python側は標準ライブラリだけで動き、学習やモデル更新は開始しない。この世代が従来方式より強いことは未確認。[モデルの出所](../Python/examples/portfolio/latest_policy_provenance.json)

## 初回：Playerをビルド

Unity Hubで2022.3.21f1とWindows Build Supportをインストールし、Editorのライセンス認証を済ませる。以下はリポジトリのルートから実行。Editorのインストール先は自分の環境に合わせる。

```powershell
git clone https://github.com/takezodasai/SuikaGameAI.git
Set-Location SuikaGameAI
$repo = (Get-Location).Path
$unity = "C:\Program Files\Unity\Hub\Editor\2022.3.21f1\Editor\Unity.exe"
$build = Start-Process -FilePath $unity -WindowStyle Hidden -Wait -PassThru -ArgumentList @(
    '-batchmode', '-nographics', '-quit',
    '-projectPath', "`"$repo\Unity`"",
    '-executeMethod', 'SuikaMaterialViewBuild.Build',
    '-logFile', "`"$repo\unity-view-build.log`""
)
if ($build.ExitCode -ne 0) { throw 'ビルド失敗。unity-view-build.log を確認してください。' }
```

成果物は `Unity/Builds/MaterialView_01/SuikaGameAI.exe`。既存フォルダがあれば保護のため再ビルドを拒否する。ビルドには時間がかかる。ビルド済みPlayerがあれば次へ進める。

## 短い確認：3落下で終了

Python 3.12の `py` コマンドを使用する。別の収集Playerが動いている間は起動を拒否する。

```powershell
py -3.12 Python/play_public_model.py --max-drops 3 --game-seconds 120
```

## 自然GOまで1ゲーム

```powershell
py -3.12 Python/play_public_model.py
```

画面付きで通常開始から1ゲームだけ実行し、終了後にPlayerを閉じる。安全上限は4時間／100,000落下で、到達したら自然GOと区別して保存する。上限は判断間で検査するため、1判断ぶん超過する可能性がある。外側の監視はさらに720秒の終了猶予を持つ。

Escでゲームを停止。Python側のCtrl+Cでも、そのコマンドが起動したPlayerだけを停止して途中ログを保持する。初回にWindowsネットワーク許可画面が出た場合は、内容を確認して手動で判断する。

保存先は `Python/outputs/public_gui_<日時>_<識別子>/`。設定・モデルSHA・各手の盤面、選択、探索統計、実ゲームイベントと終了結果を保存する。`result.json` の `natural_go=true` が自然GO。途中停止・時間上限・技術失敗を0点の自然GOとして数えない。

`--seed 123456` でゲームseedを指定可能。ただしUnity内部の完全再現は保証しない。デモseedは独立Testではなく、性能比較には別途事前登録が必要。

## 検証範囲

同じソースの表示用Playerと元の最新モデルでは、2026-11-13に3落下／5落下のGUI起動・正常終了を確認済み。公開専用ランチャーは設定・可視起動フラグ・モデル読込・自然GOと打ち切りの区別を単体検証した。
公開専用ランチャーでも、他のPlayerが存在しないことを確認して3落下の画面付き起動を実施。8.38秒、終了コード0、drop_limit、学習開始なし。全544 Pythonテスト成功（5件skip）。自然GO完走は実施していない。長時間プレイはユーザーが実行する。従来MCTS・物理・得点・GOルールは変更していない。
