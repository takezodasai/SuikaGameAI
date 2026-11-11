# 大幅時短の再調査（2026-10-28）

今回は調査・設計のみ。ソース/Player/設定/既存ログ/学習モデルは変更しない。新しいゲーム・学習・環境導入は実行しない。

## 測定事実
現PCはi7-8700K（6core/12thread）、GTX1070 8GiB、driver581.57。現在学習用requirementsはtorch2.6.0+cpu。これを勝手にGPU版へ変更しない。

overnight_20261027_021652_2927e1e1の完了4ゲームで、transitionごとのMCTS elapsed_msとstep_wall_secondsを合計した割合：job0 99.551%、job1 98.515%、job2 98.738%、job3 99.679%。起動/終了まで含む全wallではなく各手のwall時間に対する割合。通信や描画だけを最適化して大幅短縮する余地は乏しい。

sync_opt_01/profile_finalの中盤32回/深さ16（最適化ON・非warmup）では、全2684.160msのうちrollout_advance inclusive2440.323ms＝90.916%。プロファイラ負荷を含む1盤面の計測であり、全ゲームへ割合を一般化しない。native_physics約8割は、このrollout時間と重なるので加算しない。

物理マルチスレッド+整列ONはphysics_threads_01で密集32/d4の中央値716→1410ms、状態差/深さ16で選択差。採用しない。深いランダムsuffixが多いことから、prefix共有だけで深さ16全体を大幅短縮できる根拠もない。

## 方法の整理

|案|大幅短縮の可能性|従来判断の完全一致|実装/検証上の主要問題|
|---|---|---|---|
|GO終端/完全一致経路キャッシュ|局面依存|条件を厳密にすれば目標にできる|序盤重複0.36%の例、GO近傍59%tickの例。時間換算は未検証|
|不要trace生成削減/IL2CPP|主に周辺費用|A/Bが必要|native物理の支配部分を直接減らせない|
|複数UnityによるMCTS反復並列|CPUを活用する余地|通常のroot/tree parallelは一致しない|UCTは直前の結果に依存。Virtual Loss等で方策も変化、IPC/rootコピー費用|
|予測エンジンをnative CPUへ分離|根本的な改善候補|Unity標準との一致を保証できない|Collider/摩擦/睡眠/接触/合体順/GOの移植と誤差監査|
|完全物理snapshotで途中から分岐|prefix再生の削減候補|snapshotエンジン内で検証が必要|Unity2022 PathSessionには接触cache込みの復元APIがない。独立エンジンが必要|
|GPUで多数worldをまとめて計算|大量収集/バッチで有力な研究方向|現Unityと一致する保証なし|CPU-GPU往復、可変果物数、合体/GOの分岐、MCTS逐次依存、GPU互換性|
|MCTSの方策蒸留＋少数探索|物理呼出しを大きく減らす目標を立てられる|判断は変化する|自然GOの得点非劣性/GO精度を確認しなければ採用不可|
|価値モデルで長いrandom rolloutを置換|支配的なsuffixを削減する候補|判断は変化する|旧ValueNetの未達問題、GO付近過大評価、学習/予測状態分布の差|

## GPUの現実的な位置付け
Unity2022の2DはBox2D、3DはPhysX。PhysXのCUDA剛体機能は現在のPhysicsScene2Dへ設定追加で適用できるものではない。
https://docs.unity3d.com/ja/2022.3/Manual/PhysicsSection.html
https://nvidia-omniverse.github.io/PhysX/physx/5.1.0/docs/GPURigidBodies.html

GPUバッチsimulationは実在する。Madronaは多数の環境をまとめてGPU実行する設計。紹介される性能は別環境/RTX4090等であり、このゲームやGTX1070の速度見積もりへ流用しない。
https://madrona-engine.github.io/

GPUは小さい盤面を1tickずつCPUから転送する設計では転送/起動費用が問題。世界状態・接触/合体/GO・複数tickをGPU上へ保持し、多数の枝または独立ゲームをバッチ処理する設計が必要になるとの判断。これは当プロジェクトへの推論であり実測ではない。
https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html

GTX1070はCC6.1。調査時のWarp標準wheelはCUDA13.4/Turing sm75以降を要件としている。GTX1070へ最新版pip installで解決とは扱えない。CUDA12向けwheel/ソースbuildの選択肢はあるが、Pascal対応は選択版ごとに別確認する必要がある。
https://developer.nvidia.com/cuda/gpus/legacy
https://github.com/NVIDIA/warp/blob/main/docs/user_guide/faq.rst

ニューラルネットの学習/大量候補のバッチ評価はGPUの現実的な用途。ただし小さいネットを1盤面だけ評価する場合はCPUの方が低遅延な可能性もある。現在の物理計算が自動的にGPUへ移るわけではない。

## native engine/snapshotという根本案
Box2D3.2の公式ドキュメントに全world snapshot APIがある（experimental）。位置/速度だけでなくfull simulation stateを保存/復元する設計。これが信頼できればrootから同じprefixを何度も物理再生する構造を変更できる。ただしcallbacks/user dataは別管理が必要で、ゲーム側の得点・保持/NEXT・接触済み/合体中・cooldown・公開果物sample・生成IDも合わせて保存する必要がある。snapshotサイズ/コピー費用/メモリ上限も測る。これはUnity2022に同APIが存在する意味ではない。
https://box2d.org/documentation/group__snapshot.html

Unity6の新PhysicsCore2Dは従来Rigidbody2Dとは独立したBox2D3系APIであり、Unity更新だけで現在のゲームが同一挙動のまま高速化するものではない。
https://docs.unity.com/en-us/engine/6000.6/manual/unity2d/2d-physics-api/get-started/introduction

別エンジンを予測専用に使えばUnity実ゲームとの差が生じる。両方移植すれば新しい物理環境となる。現環境を残し、別環境IDで比較しなければならない。CircleCollider化/solver削減/大きいdt化を同等の内部最適化として扱わない。

## 推奨する次の試作：方策蒸留のオフライン診断
目標は現在のMCTSを先生として、探索で学んだ有望な行動を次の局面でも利用し、毎回ゼロから長いランダム探索を繰り返さないこと。将来得点だけを予測した旧ValueNetとは教師信号が異なる。計画結果をネットへ一般化し再び探索を補助するExpert Iterationに対応した方向性。
https://papers.neurips.cc/paper_files/paper/2017/hash/d8e1344e27a5b08cdfd5d027d9b8d6de-Abstract.html
https://github.com/google-deepmind/open_spiel/blob/master/docs/alpha_zero.md

1. 既存ログのdecision_sourceまたは対応する落下前盤面と、同じ判断のroot候補/訪問数/評価値を監査。操作後盤面に操作前の教師を付けない。未来NEXT、探索中のchance結果、最終得点は入力へ入れない。
2. 小型DeepSetsに盤面と合法候補Xの候補特徴を与え、root訪問分布/選択行動を学習。候補数可変に対応。先生の回数/深さ/時間打切り/予測GO情報を品質管理に保持し、すべて同質と見なさない。高得点ゲームだけ選別しない。
3. game/seed group splitを固定。既存ACのTestを再調整へ流用しない。教師の再現は高得点化保証ではない。上位候補再現率、確信度と実際の誤り、GO候補を強く推す頻度を評価。
4. 当初は新モデルで行動を直接確定せず、小予算MCTSの候補優先順位/rollout補助に使う比較モード。候補を切り捨てず一定の探索機会を残す。従来GO除外/全GOfallbackを維持。不確実時は従来MCTSに戻す。
5. 固定盤面を通過後、ユーザーが自然GOの対応比較。最終得点/GO失敗/スイカ/ダブル/実wall時間を評価し、劣化許容幅は比較前に決める。数値のspeedupや得点維持は未検証なので約束しない。

既存AC：110ゲーム/23,089状態/39seed群で、新価値MAE265.45に対し単純ridge272.84、旧構造再学習276.30。seed単位の差区間は0を含み、ダブル教師0件。価値モデルを単にGPUへ乗せてもこの精度問題は解消しない。まず方策を分離して学習できるかを調べる理由となるが、方策の成功を保証するものではない。

## 判断
「現MCTSと完全に同じ判断」が絶対条件ならGO終端cache等の小規模削減へ限定し、大幅短縮を約束しない。「実ゲームの得点を保つ」が条件なら、方策蒸留/短期物理探索/長期価値という別AIを従来MCTSと比較するのが大幅短縮と高得点化を同時に狙う第一候補。GPU用ゲームエンジンを全面実装するより、小さく失敗を判定できるため優先する。必要ならその後native snapshot simulatorを独立研究。現在のPlayer/収集は維持。
