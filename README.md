# SuikaGameAI

Suika Game AI using Unity and Python

## 構成

- `Unity/`: Unity 2022.3.21f1プロジェクト。Assets、Packages、ProjectSettings、Toolsを保持。
- `Python/`: Python 3.12以上。ソース、UDPクライアント、テスト、pyproject.toml、poetry.lockを保持。
- `docs/`: 開発計画、開発記録、UDPプロトコル。

STEP 3.5の滑らかな移動まで検証済み。STEP 4は独立物理シミュレーターと比較基盤を実装済みだが、接触時の予測誤差が残り未完了。STEP 5は未着手。

## 開発を開始する

1. Codexでこのリポジトリのルートを開く。
2. Unity Hubで`Unity/`を追加し、2022.3.21f1で開く。対象Sceneは`Assets/Scenes/gameDisplay.unity`。
3. Python環境は`Python/`で`poetry install`などにより依存関係を復元する。
4. 自動テストは`Python/`でPowerShellの`$env:PYTHONPATH="src"; python -B -m unittest discover -s tests -v`。Unity Play不要のテストにもローカルUDP通信を使用する。
5. Unity実通信テストはPlay中に実行し、UDPクライアントを複数同時起動しない。

元のOneDriveプロジェクトから必要ファイルをコピーした新規統合リポジトリ。元データと旧Git履歴は変更していない。Library、仮想環境、ログ、ビルド・学習生成物はGit管理対象外。
資料内の旧フォルダ名・絶対パスは過去の検証記録として保持している。現在の構成は上記を参照。
