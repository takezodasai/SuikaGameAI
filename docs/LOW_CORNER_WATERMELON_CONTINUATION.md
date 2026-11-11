# 左下の低いスイカ盤面からの続行実験

2026-11-05。今回だけの盤面選別条件として実施。学習報酬、通常AIの選択規則、MCTS・物理・GOルールは変更していない。夜間収集はユーザーが停止し、4台の終了を確認してから実験を開始した。実験後も夜間収集は自動再開していない。

## 選定

完了済み155ゲームのうち、実ゲームでスイカ生成した43ゲームの保存盤面を調査した。非GOのaction境界で、実測Collider境界から床の距離<=0.15、近い壁の距離<=0.20、めり込み>=−0.05、スイカ速度<=0.25、接触済み果物のGOラインまでの余裕>=0.10という条件で選定。該当した独立元ゲームは3件。

該当盤面を現在のGOラインまでの余裕、果物数、床・壁の距離で順位付けした。候補の将来得点や元ゲームの最終得点は選定に使用していない。比較実験の結果を見て選び直していない。

選択盤面は前回20時間セッションのJob 14、元seed1597884696、244落下後、2,528点、15果物。スイカ中心は約(−1.3252,−2.5001)、左壁まで0.00367、床まで0.00420 Unity単位。接触済み果物のGOラインまでの余裕は約1.425。最初からスイカが1個存在する。

元ログ：`Python/outputs/rollout_selfplay_20261103_183911_bb3d49e4/jobs/job_000014/attempt_000/trace.jsonl`。

## 復元・実行

既存Watermelon Labと同じ近似cold再構成を使用。専用Playerは既存のPolicySelfPlay_01で、ビルドし直していない。3落下のsmoke確認後、事前固定した2つの未来seedで順番に続行した。

開始時の比較項目（果物の種類・数・位置・速度・回転・接触済みフラグ、保持果物種類、NEXT、得点）は保存値と一致し、位置・速度・回転の比較差は0。接触solver cacheやsleep timerを復元したわけではなく、元ゲームの厳密な反実仮想ではない。元RNG JSONは出所情報として保存し、続行では新しい未来seedを使用する。

条件：MCTS256反復、深さ4、固定5候補、同期、学習rollout50%混合。使用モデルは従来の`learned_rollout_01/training/model.json`（SHA81d9f3b5…）。ルート最終選択は従来MCTS。各試行最大600秒、総予算1,200秒、実際の2試行合計は約313.5秒。

## 結果

|未来seed|終了|追加得点|実験開始後の落下|最終得点|新規スイカ|2個共存|ダブル|
|---|---|---:|---:|---:|---:|---|---:|
|1043115001|自然GO|253|26|2,781|0|なし|0|
|1043115002|自然GO|310|36|2,838|0|なし|0|

両試行とも技術エラーなし、指定256探索と元状態不変を確認。最初からあるスイカを新規成功に数えていない。終了時にもスイカは1個残り、中心はそれぞれ約(−1.3288,−2.4993)、(−1.3303,−2.4978)で、低い左下位置を保っていた。

現在のAIはこの2試行で2個目を作れなかった。ただし到達不可能とは判定できない。この盤面での他の行動方針や未来系列は未検証であり、角配置の一般的な優位性を調べる対照比較でもない。

通常ゲームの学習セットには自動追加していない。近似盤面からの条件付き実験として出所・元seed群・未来seed・モデルSHA・復元限界を保存した。

## 保存先と再利用

`Python/outputs/low_corner_watermelon_01/`：selection.json（他2候補含む）、fixture.json、plan.json、selected_board.png、smoke、future_1043115001、future_1043115002、summary.json。

追加した`Python/play_fixture_rollout.py`で同じ方式を再実行可能。出力は新しいフォルダを必須とし、既存Playerが稼働していたら拒否する。

```powershell
Set-Location C:\SuikaGameAI\Python
.\.venv\Scripts\python.exe .\play_fixture_rollout.py `
    --fixture .\outputs\low_corner_watermelon_01\fixture.json `
    --output ("outputs\corner_trial_" + (Get-Date -Format "yyyyMMdd_HHmmss")) `
    --future-seed 1043115003 --seconds 600
```

一時停止した20時間収集に戻す場合（今回はこちらから実行していない）：

```powershell
.\.venv\Scripts\python.exe .\selfplay_rollout.py collect `
    --output .\outputs\rollout_selfplay_20261105_010701_cb9e6983 --resume
```

元の完了ログのSHA一致、保護対象398既存ソースに変更なしを確認。新規学習・commit・pushなし。
