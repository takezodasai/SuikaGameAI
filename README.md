# SuikaGameAI

Unityの物理シミュレーションとMCTS、学習済み方策を使って自動プレイするスイカゲームAIです。
高得点とダブルスイカ達成を目指して開発しています。

[![Python checks](https://github.com/takezodasai/SuikaGameAI/actions/workflows/python-tests.yml/badge.svg?branch=main)](https://github.com/takezodasai/SuikaGameAI/actions/workflows/python-tests.yml)

## 実行方法

**Windows 64bit対応。Unity・Pythonのインストールは不要です。**

1. [AIデモをダウンロード](https://github.com/takezodasai/SuikaGameAI/releases/download/ai-demo-v0.1.0/SuikaGameAI-AI-Demo-Windows-x64-v0.1.0.zip)します。
2. ZIPを右クリックして「すべて展開」します。
3. 展開したフォルダの **AI-Demo.exe** をダブルクリックします。

AIが自動でプレイします。**Escで停止し、結果画面でもう一度Escを押すと終了**します。
exeだけを移動せず、隣接ファイルを同じフォルダに置いてください。

- 表示：得点・落下数・思考時間・探索設定
- 設定：MCTS256回、深さ4、固定5候補、学習rollout混合率50%
- 操作：AI専用。手動プレイ不可。思考中は画面が一時停止します

非公式の実験用デモです。素材の権利確認は未完了です。[配布上の注意](docs/AI_DEMO_DISTRIBUTION.md)
[ソースからのビルド手順](docs/GUI_MODEL_PREVIEW.md#開発者向けpython不要の専用playerをビルド)

## 構成

- **Unity / C#**：ゲーム、物理予測、MCTS、自動プレイ
- **Python**：データ収集、方策学習、評価・テスト

既存のUnityゲーム基盤にAI機能を追加した個人開発です。実装・調査には生成AIも活用しています。
ダブルスイカは未達成で、学習モデルによる強さの改善は検証中です。

## 詳細

- [設計・開発範囲](docs/ENGINEERING.md)
- [実験結果](docs/RESULTS.md)
- [最新の学習・収集結果](docs/LATEST_CURRICULUM_RESULTS.md)
- [環境構築・テスト](docs/REPRODUCIBILITY.md)
- [データ収集・学習](docs/MATERIAL_PROGRESS_LEARNING_ENVIRONMENT.md)
