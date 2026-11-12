# 設計と追加開発の範囲

## 課題

落下直後の得点だけでなく、接触・合体・盤面の余裕が将来に影響するゲームを対象にする。
連続座標と確率的な果物出現を扱いながら、実際の得点で改善を評価できるAI開発環境を作る。

| 領域 | 実装 | 設計上の理由 |
|---|---|---|
| C#の探索 | action/chanceを扱うMCTS、公開NEXTと未知果物の分岐 | 未公開の未来を参照しない |
| 独立物理予測 | PhysicsScene2Dで落下後を計算 | 実ゲームを変更せず候補を調べる |
| 長時間実行 | Scene解放監査、メモリ計測、通信処理の修正 | 蓄積・応答停止の原因を追える |
| Python実験 | 設定・モデルSHA固定、並列ジョブ、試行単位保存 | 途中停止で完了データを失わない |
| 学習 | 小型方策、結果重み付き模倣、世代別保存 | 基準MCTSを残して実験する |
| 観測 | 原子的合体イベントとknown mask | 一瞬の共存とログ欠損を区別する |

既存Unityゲーム基盤・素材を全て独自に作ったという意味ではない。AI・通信・実験・学習の追加部分が本ポートフォリオの中心。
生成AI支援を用いた開発として、ソースとテストに加え、採用しなかった方式と未検証事項も示す。

## 判断したことと学んだこと

**物理予測を正解とみなさない。** 位置・速度・回転だけでは内部の接触キャッシュ等を再現できない。
予測Scene、近似盤面の続行、通常開始からの自然GO得点を分ける。

**探索量やモデルの複雑さだけで成功としない。** widening、探索予算配分、Q/V、MC/TDなどを試したが、
一貫した実ゲーム改善を確認していない方式は標準採用していない。深さを増やすだけで長期戦略が改善するとは考えていない。

**実験単位を間違えない。** 同じrootの未来系列・反復を独立群として水増ししない。
入れ子フォルダの検出漏れで96試行が6独立rootの反復になった際には、元データを保持して再集計し、登録・dry-run・回帰テストを追加した。
[監査記録](BRANCH96_REPETITION_AUDIT_REPORT.md)

**終端と欠損を学習前に確認する。** 操作間の追加得点、実測GO、打ち切り、欠損終端を区別する。
追加得点は実際の続行方針の下でのreturnであり、達成可能な最高得点ではない。未観測イベントを負例化しない。

## コード入口

- [MctsPlanner.cs](../Unity/Assets/Scenes/Script/MctsPlanner.cs)：探索と最終候補選択。
- [SuikaPhysicsSimulator.cs](../Unity/Assets/Scenes/Script/SuikaPhysicsSimulator.cs)：独立予測と状態の扱い。
- [LearnedRolloutPolicy.cs](../Unity/Assets/Scenes/Script/LearnedRolloutPolicy.cs)：213係数、ランダム混合、fallback。
- [SuikaMaterialProgress.cs](../Unity/Assets/Scenes/Script/SuikaMaterialProgress.cs)：初期値・原子的更新・初回到達。
- [double_watermelon_learning.py](../Python/double_watermelon_learning.py)：収集から学習・モデル保存。
- [material_progress.py](../Python/material_progress.py)：既知/不明、実ゲーム成果、未来教師の区別。

次は通常開始の得点を維持しながら、生成後の材料育成を改善できるかを評価する。
成功経験がない段階で、報酬設定だけでダブルスイカの成功方法を学べたとは主張しない。
