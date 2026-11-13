# AIのプレイを見る

Windows / Unity **2022.3.21f1**。実際の果物・得点・NEXT・進化リングが見えるUnity画面で、AIがその場で操作する。同期探索中は画面更新が一時停止する。

## 見る人向け

ビルド済みの専用デモは、フォルダ内の **AI-Demo.exeをダブルクリック**するだけで自動プレイを開始する。PythonやUnity Editorは不要。
exeだけを取り出さず、`AI-Demo_Data`、DLL、モデルなどを同じフォルダに置く。

**現在、exeの一般公開は保留中。** 画像・背景・音・元コードの入手元が分からず、再配布条件を確認できていない。
ダウンロードリンクはまだ設けていない。[配布前の確認事項](AI_DEMO_DISTRIBUTION.md)

- 画面上部：得点、落下数、思考時間、探索設定。
- 画面下部：非公式のAI研究デモであること、手動操作不可、停止方法。
- 停止：Esc。終了結果の画面からもう一度Escで閉じる。
- 思考中は画面が一時停止する。同期MCTSの制約であり、リアルタイム表示は行わない。

公開された凍結方策 `gen_d9eb9e9bef0e` を同梱。MCTS256反復・深さ4・固定5候補、rolloutの50%で学習方策を使用する。
新しい学習やモデル更新は開始しない。この世代が従来方式より強いことは未確認。[モデルの出所](../Python/examples/portfolio/latest_policy_provenance.json)

## 開発者向け：Python不要の専用Playerをビルド

Unity Editorが必要なのは、ソースからビルドする開発者側だけ。
Unity 2022.3.21f1とWindows Build Supportを用意し、リポジトリのルートで実行する。Editorのパスは環境に合わせる。

```powershell
$repo = (Get-Location).Path
$unity = "C:\Program Files\Unity\Hub\Editor\2022.3.21f1\Editor\Unity.exe"
$build = Start-Process -FilePath $unity -WindowStyle Hidden -Wait -PassThru -ArgumentList @(
    '-batchmode', '-nographics', '-quit',
    '-projectPath', "`"$repo\Unity`"",
    '-executeMethod', 'SuikaStandaloneDemoBuild.BuildReadable',
    '-logFile', "`"$repo\unity-standalone-build.log`""
)
if ($build.ExitCode -ne 0) { throw 'ビルド失敗。unity-standalone-build.log を確認してください。' }
```

成果物：`Unity/Builds/StandaloneAiDemo_02/AI-Demo.exe` と隣接ファイル。
`SUIKA_STANDALONE_DEMO` をこのビルドだけに指定し、標準Playerは従来の起動方法を維持する。既存のビルドフォルダは上書きしない。
専用Playerは起動時にモデルのSHA256と形式を検査し、読み込めなければ手動ゲームへ切り替えずエラー画面で停止する。
手動の移動・落下・リセットとUI操作を無効化し、UDPの操作受付・送信も開始しない。
4時間／100,000落下は安全上限で、自然GOとは区別する。検査は判断の間なので、上限を1判断ぶん超過する可能性がある。

短い確認：

```powershell
& .\Unity\Builds\StandaloneAiDemo_02\AI-Demo.exe -aiDemoMaxDrops 3
```

通常は引数なしで自然GOまで1ゲーム。終了後は結果画面を保持する。
ログは `%USERPROFILE%\AppData\LocalLow\DefaultCompany\suikaGAME\ai-demo\<日時>_<識別子>\` に保存する（CompanyName/ProductNameを変更した場合はその設定に従う）。
設定・ゲームseed・モデルSHA・各手の盤面／探索／選択・実ゲームイベントと終了理由が対象。`trace.jsonl` の `evt="end"` を確認し、`natural_go=true` と打ち切りを区別する。
seedの完全な物理再現や独立Test性能を保証するデモではない。

## 研究用の既存Pythonランチャー

以下は開発用の別経路。一般のデモ閲覧者には不要。

### 初回：研究用Playerをビルド

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

### 短い確認：3落下で終了

Python 3.12の `py` コマンドを使用する。別の収集Playerが動いている間は起動を拒否する。

```powershell
py -3.12 Python/play_public_model.py --max-drops 3 --game-seconds 120
```

### 自然GOまで1ゲーム

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


### 専用exeの追加確認（2026-11-13）

`StandaloneAiDemo_02` をPythonなしで直接起動し、3落下・各256反復で正常停止。6.63秒、`drop_limit`、自然GOではない。実盤面不変監査が全判断true、予測Scene残留0、UDPエンドポイントなし。
日本語の情報表示と結果画面を目視確認。停止後のEnter入力で再開せず、Escで終了することを確認した。
Python回帰テスト543件中538件成功・5件skip。新ビルドでの自然GO完走・長時間安定性は今回未検証。
