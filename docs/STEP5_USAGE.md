# STEP 5：1手先探索の使い方

Unity 2022.3.21f1で `C:\SuikaGameAI\Unity` の gameDisplay Sceneを開いてPlayする。他のUDPクライアント（main.pyや評価プログラム）は終了しておく。

```powershell
cd C:\SuikaGameAI\Python
python play_one_step_ai.py --candidates 5 --post-drop-steps 25 --max-steps 1000 --output outputs/step5_run01.jsonl
```

開始時に一度resetする。GO・手数上限・Ctrl+Cで終了し、自動リセットし続けない。Ctrl+C時に既に予約した1手はUnity側で完了することがある。次に開始すると改めてresetする。Playを止めても終了できるが、待機中のPythonはタイムアウトまで待つ。タイムアウト後に追加操作せず、resetで復旧する。

## Python API

```python
from suika_ai.unity_env import UnityEnv
with UnityEnv() as env:
    state = env.reset()
    while not state["game_over"]:
        state, reward, done, info = env.plan_step({"candidate_count": 5, "post_drop_steps": 25})
        print(state["score"], info["planning"]["selected_x"])
```

既存の `env.step(x)` は維持。`plan_step()` は候補計算と既存step予約をUnity内の一回の受付で行う。同じaction_idの再送では再探索・再落下しない。候補計算中に実ゲームの物理更新を挟まない。各候補の初期盤面と、予測前後の実盤面・得点・乱数の不変を確認する。

## 設定変更

UnityのUDP通信オブジェクトにあるPlanning Settingsで候補数、予測更新数、係数を変更できる。Planning Floorは既存bottomのBoxCollider2Dを参照し、形状・位置は変更しない。新しいコードを読み込んだEditorで参照が空なら、保存済みgameDisplay Sceneを開き直す。未保存変更がある場合は先に確認する。

Pythonで引数を与えた場合はそのdecisionのみの設定になり、Inspector設定を書き換えない。Pythonの部分指定は文書の標準値と合成する。引数なし `env.plan_step()` はInspector値を使う。コマンドラインは既定5候補・25更新を明示する。

```json
{"weight_danger": 0.0, "weight_roughness": 0.2, "score_scale": 55.0, "danger_band_fraction": 0.15, "uncontacted_risk_weight": 0.5, "height_bins": 9}
```

上記を任意のJSON設定ファイルとして保存し、`--settings ファイル名.json`を付ける。`--candidates 9 --post-drop-steps 50`などで比較できる。候補数2〜31、予測更新1〜150、横分割2〜128、係数非負。初期設定は `V = reward/55 - 0.2R`。詳細な定義はSTEP5_DESIGN.mdに記載。

## 判断ログ

1行が1手のJSONL。`info.planning.candidates`に全候補の要求X・適用X、予測得点・加点、H/D/R、各減点・最終value、GO、除外理由、合体数、各更新数と生成/コピー/物理/解放予約のmsを記録する。`selection_score`は選択対象外ではnull。全候補GOのときだけ生存時間→ライン超過量→value→indexの順で選ぶ。失敗をGOとして扱わない。

`selected_index`と`selected_x`が採用結果。`same_source_verified`が全候補の同一初期盤面・元盤面不変の確認結果。`held_fruit_type`と`next_fruit_type`は判断開始時に見えている情報で、未表示の未来果物は取得しない。NEXTは占有高さには含めない。現評価式はまだNEXTの戦略的価値を加点しない。

`movement_reward`・`cooldown_wait_reward`・`post_drop_reward`は予測/実行で記録。実行側の物理区間外差分は`other_in_step_reward`として保存し、合計とrewardの保存則を確認する。区間は時間分類であり、合体原因の断定ではない。落下と到着が同じ物理更新の加点は落下後に分類する。

落下更新を0としてその後25更新を数える。dt=.02なら公称0.5秒、落下更新を含めて26回の物理更新。移動中・クールダウン待機中も盤面は進む。

## 制約

接触履歴やDestroyと描画境界に由来するSTEP 4の予測誤差は残る。GO予測がfalseでも安全保証ではない。短い予測では落下・連鎖が未完了の場合がある。長期得点、係数の良し悪し、候補数・予測時間の比較は今後検証する。STEP 6以降、AIモード切替、Value Network、MCTSは未実装。

2026-10-21 STEP 6移行：Hの減点を削除しHは分析用のみ。古いweight_height指定は互換入力として受け付けるが評価に影響しない。P/B/NEXT戦略等の追加評価は保留。並列収集はSTEP6_USAGE.md参照。


2026-10-21：D減点も削除。H/Dは分析用のみで旧weight_dangerは無視（0に正規化）。通常候補の同点時もDを使用しない。GO除外・全GOフォールバックは維持。音声制御と1ゲーム映像試作の操作はPRESENTATION_PROTOTYPE.md参照。新オプションには新しいPlayerが必要なため既存Playerは再ビルドする。
