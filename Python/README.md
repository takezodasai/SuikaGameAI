# Python tools

公開デモ・最短手順は[プロジェクトREADME](../README.md)、テストは[再現手順](../docs/REPRODUCIBILITY.md)を参照。

- `examples/portfolio/demo.py`：同梱公開盤面・小型方策の推論。NumPyのみ、Unity不要。
- `double_watermelon_learning.py`：研究用の収集・監査・学習。ローカルデータセットとPlayerが必要。
- `material_progress.py`：中間成果・初期条件・既知/不明の処理。
- `tests/`：合成fixtureを使う回帰テスト。長時間ゲームは実行しない。

Unity/C#がゲームとMCTS、Pythonが実験管理・データ検証・オフライン学習を担当する。
