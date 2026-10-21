# 描画と手前画像の配置（2026-10-21）

画像加工・取り込み・配置・微調整はユーザーが行う。既存Transformは変更しない。

## 現在の順序

Sorting Layerは全てDefault。同じLayerではOrderが大きいものが前。

|対象|Order|
|---|---:|
|BackgroundのWorld Space Canvas|−100|
|パイナップルPrefabのSpriteRenderer|−10|
|通常の果物（イチゴ・サクランボを含む）|0|
|籠の手前画像|20|
|PlayerのSpriteRenderer・NEXT表示用SpriteRenderer|30|
|保持中の果物（落下時にPrefabの値へ戻す）|31|
|得点Canvas（World Space）|40|

既存suikaBackground_lyoutはBackgroundの子のSpriteRenderer。そのOrderのみ20へ変更、Transformと画像指定は維持。Sorting Groupは現Sceneに存在しない。Canvasの子のSpriteRendererはUI Imageではないため、自身のSorting Layer/Orderで描画する。Player/NEXT/得点は操作・読み取り用として手前画像より前に置く。

InspectorでSpriteRendererまたはCanvasのSorting LayerをDefaultにする。新規Sorting LayerはEdit > Project Settings > Tags and Layers > Sorting Layersで追加できるが、今回の構成では追加不要。異なるSorting Layerを混在させるとLayerの優先順位がOrderより先に働く。親にSorting Groupを追加すると子Spriteの外部との順序が変わるため、Background・前景・果物を1つのSorting Groupでまとめない。

## 後から前景画像を配置する方法

推奨はBackground/gameDisplay（背景UI Image）の子としてBasketFrontをUI > Imageで作る。背景のTransformは変更しない。

- 元PNGと同じ1920×1080のキャンバスを保ち、手前の部分以外を透明にしたPNGを使用する。
- PNGをSprite (2D and UI)、Singleとして取り込み、BasketFrontのSource Imageへ指定。
- BasketFrontのRectTransformを親全面にStretch、Left/Right/Top/Bottom=0、Scale=1、Rotation=0にする。Preserve AspectはOFF（現在の背景Imageと合わせる）。Raycast TargetはOFF。
- BasketFrontにCanvasを追加しOverride SortingをON、Sorting Layer=Default、Order=20とする。親World Space Canvasの子として使い、別のCanvasScalerは追加しない。
- 背景と同じ座標・寸法になるため、画像の余白も含めて一致する。不要なColliderやRigidbodyは追加しない。

Hierarchy例：

```
Background (World Space Canvas, −100)
├─ gameDisplay (既存の背景Image)
│  └─ BasketFront (ユーザーが作成するImage＋子Canvas, 20)
└─ suikaBackground_lyout (現在のユーザー配置Sprite、20)
```

既存のSprite方式を使い続けても、Backgroundの子である限り画面サイズ変更時の拡縮基準は共有できる。前景を二重に表示しないよう、使う方を選ぶ。元PNGを透明余白を含めて使う場合、背景Imageのローカル寸法をW×H、Spriteの寸法をsw×shとすると、SpriteのローカルScaleはW/sw、H/sh。Pivotが中央なら親Backgroundの中心に合わせられる。現在の背景は画像の元縦横比から多少変形しているため、Sprite側で縦横同一Scaleにすると厳密には一致しない。UI Imageの全面Stretchが確実。

余白を切り詰めたPNGでは、切り取り元の左上ピクセル(x,y)、幅w、高さhを記録する。背景のRect寸法をW,Hとすると、中心Pivotの前景Imageは幅=W*w/1920、高さ=H*h/1080、中心位置X=W*((x+w/2)/1920−0.5)、Y=H*(0.5−(y+h/2)/1080)。この位置合わせはユーザーが行う。

## 画面サイズ変更

既存GameViewportが800×436.9686の構図を維持するViewportへ収める。CameraのOrthographic Sizeや物理座標は変えない。背景/得点はWorld Space、Player/果物/NEXTもworld座標で描画。前景も背景の子に置くことで同じカメラ変換を受ける。ウィンドウサイズの変更だけで各Transformを更新する別スクリプトやScreen Space Overlay Canvasを追加しない。

## 左右端の安全範囲

左右の有効なWallタグのBoxCollider2Dの内面と、操作果物の実Collider.bounds（半径・Offset・Scale・Capsuleを含む）から範囲を求める。接触余白は3×Physics2D.defaultContactOffset。固定ワープ境界では制限しない。手動FixedUpdate/AI/生成直後/落下直前が同じ範囲とCollider.Distance検査を使う。壁が不足、回転、果物が入らない等の条件は範囲を無効にして落下させない。壁は操作果物の高さをカバーし、左右2枚の直立BoxCollider構成を維持する。

保持オフセットはPlayer > Held Fruit Offsetで調整可能。現在の追従値(-0.7,-0.42,-1)を初期値にし、以前の生成時だけY=-0.39になる差を統一。初期化時の大きなNEXTの安全配置では、Playerと新しい保持果物のXのみ必要に応じてランタイムで内側へ補正する。保存されたTransformは変更しない。

ゲームオーバーの接触済み判定は無効化しない。正当に積み上がった果物がラインを超えれば従来どおり対象になる。STEP4全体の接触済み状態等の対応は環境調整完了連絡後。

参考：Unity 2022.3 2D Sorting https://docs.unity3d.com/ja/2022.3/Manual/2DSorting.html 、Sorting Group https://docs.unity3d.com/ja/2022.3/Manual/class-SortingGroup.html
