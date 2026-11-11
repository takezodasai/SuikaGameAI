# 2D物理マルチスレッドの隔離比較（2026-10-28）

## 判定
標準採用しない。単一スレッドの既存Player・設定・MCTSを維持。新Playerは `Unity/Builds/PhysicsThreads_01/SuikaGameAI.exe`。通常起動では物理設定を変更しない。`-suikaPhysicsThreadProbe` 指定の診断中だけPhysics2D.jobOptionsのuseMultithreading/useConsistencySortingを同時ONにし、探索ごとにfinallyで復元する。ProjectSettingsを書き換えない。UCT/rollout/乱数/更新幅/探索回数/GO比率0.83/環境IDを変更しない。

## 方法と結果
CPU i7-8700K、6core/12thread。既存時短版の内部最適化は両条件ともON。固定rootから各試行を再構築。固定5候補・seed8191・32回、通常深さ4。初回warmupを除外し、順序を交互にする。検証では候補・全ノード・各反復の行動/果物系列/得点/合体/GO/tick/最終状態ハッシュを比較。`exact_valid/summary.json` は4盤面×warmup/本測定＝8対応。完全一致2/8（GO近傍のみ）。最初の落下位置とroot訪問数は全盤面一致していても、他の3盤面では物理状態が一致しないため結果維持とは認めない。

|盤面|単一ms|並列ms|選択X（両条件）|完全一致|
|---|---:|---:|---:|---|
|序盤0果物|165.0|641.7|0|不可|
|中盤14果物|528.1|1154.3|0|不可|
|密集35果物|919.3|1738.6|1|不可|
|GO近傍38果物|320.9|537.3|0.5|一致|

上表は状態ハッシュ検証込みの各1測定。速度判定には別のハッシュ/詳細profiler無し測定 `timing/summary.json` を使用。密集35果物・32回/深さ4、warmup除外3回の中央値：単一716.085ms（707.500〜734.722）、並列1409.718ms（1356.482〜1419.908）。約1.97倍の所要時間で高速化なし。少数の固定盤面であり全局面への一般化や自然GO得点比較はしない。既存収集プロセスを操作せず測定したため、背景負荷の影響は除外できない。

追加の深さ16診断でも、序盤は選択Xが0.25→0.75へ変化、中盤は初回反復から予測得点/合体が変化した。単なる表示差ではない。初期 `exact/` 実行は最後のGO近傍fixtureパスを誤指定し、最初の3盤面の対応測定後に診断Playerだけを終了した。原ログは保持し、正しいパスで `near_go/` と4盤面の `exact_valid/` を正常終了。Pythonドライバに起動前のファイル存在確認を追加。初期実行を全完了として扱わない。

## 考察
ジョブ投入/同期/整列の費用が小規模シミュレーションで上回った可能性はあるが、今回ジョブ内部の時間までは計測しておらず確定原因とはしない。Unity公式でも並列化で処理順序の決定性が下がり、Consistency Sortingには整列コストがあると説明される。整列ONは従来の単一スレッドとのビット一致保証ではない。ジョブ閾値を変更すれば改善する可能性は未検証であり、この試作の成功として扱わない。
https://docs.unity3d.com/cn/2022.3/Manual/class-Physics2DManager.html
https://docs.unity3d.com/2022.3/Documentation/ScriptReference/PhysicsJobOptions2D-useConsistencySorting.html

## 互換性と回帰
Python305テスト成功（新規6）。Unity rules122/MCTS861/path26/frame58、合計1067チェック成功。新Playerの単一スレッド側は既存SyncOptimized_03の保存済み4盤面・32回/深さ4の選択位置、全ノード、反復状態ハッシュ/得点/合体/GO/tickと一致。Physics2DSettings、Scene、MctsPlanner、PredictionLifecycle、旧3Playerのexe/DLL、計10ファイルのSHA256不変を確認。通常のプレイ手順は旧Playerのまま。自然GOゲームや長時間収集、GUI長時間操作は実施しない。commit/pushなし。

## 変更箇所
- Unity/Assets/Scenes/Script/SuikaPhysicsThreadProbe.cs（新規）：専用フラグ起動、設定の適用/復元、固定rootのA/Bと品質比較。meta追加。
- Unity/Assets/Editor/SuikaWorkerBuild.cs:38 BuildPhysicsThreadValidation（追加）：既存ビルドを上書きしない別出力。
- Python/benchmark_physics_threads.py（新規）：短時間専用ドライバ、設定反映/完了回数/root不変/Scene解放/品質/時間の監査。
- Python/tests/test_physics_threads.py（新規）：速くても品質不一致を同等扱いしない等6テスト。
- docs/DEVELOPMENT_LOG.md、DEVELOPMENT_PLAN.md：本診断を追記。

## 再測定
PowerShellでC:\SuikaGameAI\Pythonから：
```powershell
$out = "outputs\physics_thread_check_" + (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8)
.\.venv\Scripts\python.exe .\benchmark_physics_threads.py --exe ..\Unity\Builds\PhysicsThreads_01\SuikaGameAI.exe --output $out --fixtures .\outputs\step8c_01\dense_safe_fixture.json --specs 32:4 --repeats 3 --timing
```
これは診断専用。通常プレイへ並列物理を適用するコマンドではない。

次の候補は物理設定を変えないGO終端キャッシュ。GO近傍での重複を削減する見込みはあるが、全ゲームの短縮率は未検証。今回まとめて実装せず、別のA/Bで品質と速度を測る。
