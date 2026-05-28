# クラス写真キャプチャ（ClassPhotoCapture）

担任教師が撮影時にポスターと同じ比率の顔枠で連続撮影し、**元の全体写真＋枠情報**を
書き出して、既存の `crop_adjuster`（Python / Mac・Win）でそのまま読み込めるようにする
Swift Playgrounds アプリ。

> ステータス: **開発中（v0 / スキャフォールド段階）**。
> 実機（iPad/iPhone/Mac の Swift Playgrounds）での動作確認・調整はこれから。

---

## 目的・背景

現行ワークフロー:
1. 先生がスマホ等で個人写真を撮影（バラバラの構図）
2. Mac/Win の `crop_adjuster` で1枚ずつ顔位置をクロップ調整（617件）
3. `make_poster` でクラスポスターPDFを生成

課題: **2 のクロップ調整が重労働**。撮影時点で構図（顔位置）が決まっていれば、
この作業がほぼ不要になる。

本アプリの狙い: **撮影時に顔枠ガイドを出し、枠に合わせて撮るだけ**で、
クロップ情報込みのデータを書き出す。→ crop_adjuster 側は微調整のみ。

---

## 要件定義（確定事項）

ユーザー（現役教師・情報担当）との合意:

| 項目 | 決定 |
|------|------|
| 生徒情報の入力 | **人数のみ**（番号で撮影。名前は入力しない） |
| 端末の向き | **縦・横どちらでも対応**できること |
| 書き出し形式 | **独自パッケージ（中身ZIP）**。画像は **JPEG または HEIC** を選択可 |
| エクスポートに含めるもの | **元の全体写真（クロップで外れた部分も含む）＋枠情報**（再クロップできるように） |
| 提出経路 | **AirDrop で情報担当へ** / または **Google Drive 経由** → まとめてDL → 学校Windowsの crop_adjuster で編集 |
| 顔枠の比率 | ポスターと同じ **CELL_ASPECT = 1.1289**（crop_adjuster と一致） |
| プラットフォーム | **Swift Playgrounds（.swiftpm App）**。将来 App Store 配布も視野 |

### 撮影フロー
1. **設定画面**: 学年・組・人数を入力（＋画像形式 JPEG/HEIC、向きの選択）
2. **撮影画面**:
   - カメラプレビューに金色の顔枠（CELL_ASPECT）
   - 撮影注意（顔を枠に／明るさ／背景 等）
   - 「○年○組 ○番を撮影してください」表示
   - 撮影 → 確認（撮り直し / OK）→ 自動で次の番号へ
   - **欠席ボタン**で番号をスキップ
3. **確認・書き出し画面**: 撮影済み一覧（撮り直し可）→ エクスポート

---

## crop_adjuster との連携仕様（重要・ここを壊さない）

crop_adjuster（`../crop_adjuster.py`）が読み込む形式に厳密に合わせる。

### フォルダ・ファイル命名
```
<出力ルート>/
  ○年/○年○組/                         例: 1年/1年1組/
    {学年}{組}{番号2桁}.jpg(またはheic)  例: 1101.jpg, 1102.jpg …（元の全体写真）
  crop_check/
    crop_overrides.csv
```
- ファイル名: `f"{grade}{cls}{num:02d}"`（学年1桁・組1桁・番号2桁＝4桁）。
  - 例: 1年1組1番 → `1101` 、3年2組15番 → `3215`
- crop_adjuster の `collect_photos()`: prefix=`f"{grade}{cls}"`、残りを番号として解釈。
- crop_adjuster の `find_class_folder()`: フォルダ名 `○年○組` または 親`○年`＋`○組` を正規表現で探索。

### crop_overrides.csv 形式（BOM付きUTF-8）
```
grade,cls,num,top_pct,left_pct,zoom
1,1,1,25.59,-1.53,2.57
...
```
- 1行＝1人。撮影時の顔枠位置から算出（下記）。

### 枠位置 → crop_overrides 変換（CropMath）
crop_adjuster の `calc_crop_box(W,H,top_pct,left_pct,zoom)` の**逆算**。
撮影画像の正規化枠 `(nx, ny, nw, nh)`（0–1、画像座標系）から:

```
aspect = CELL_ASPECT
if W/H < aspect:  base_h = W/aspect      # 縦長画像
else:             base_h = H             # 横長画像
top_pct  = ny * 100                       # 枠上端
left_pct = (nx + nw/2 - 0.5) * 100        # 枠の横中心
zoom     = base_h / (nh * H)              # 枠の高さから（1.0〜5.0でクランプ）
```
- top_pct: 0–100、left_pct: -50–50、zoom: 1.0–5.0 にクランプ。
- これで crop_adjuster 側で「撮影時の枠」が初期クロップとして再現される。
- **元画像はクロップせず全体を保存**するので、crop_adjuster で枠を再調整可能。

> 注: 端末の向き（縦/横）で W,H と正規化枠の取り方が変わる。撮影画像は
> 表示向きに正規化（EXIF/orientation を焼き込み）してから保存する想定。

---

## ファイル構成（.swiftpm）

```
capture-app/
  README.md                         ← 本ドキュメント
  ClassPhotoCapture.swiftpm/
    Package.swift                   ← App Playground 定義（カメラ権限 purposeString 含む）
    App.swift                       ← @main、CELL_ASPECT 定数、画面ルーティング
    AppState.swift                  ← 状態モデル（学年/組/人数/形式/撮影配列/画面） ※未
    StudentShot.swift               ← 1人分のデータ（番号/状態/画像/枠/寸法） ※未
    CropMath.swift                  ← 枠→crop_overrides 逆算 ※未
    CameraModel.swift               ← AVCaptureSession ラッパ（撮影/プレビュー層） ※未
    CameraPreview.swift             ← AVCaptureVideoPreviewLayer の SwiftUI ラッパ ※未
    SetupView.swift                 ← 設定画面 ※未
    CaptureView.swift               ← 撮影画面（顔枠ガイド＋連続撮影） ※未
    ReviewView.swift                ← 確認・書き出し ※未
    Exporter.swift                  ← フォルダ構成＋CSV生成＋ZIP化＋共有 ※未
```
（※未 = これから実装。App.swift / Package.swift は作成済み）

---

## 実装メモ / 技術方針

- **カメラ**: `AVCaptureSession` + `AVCapturePhotoOutput`。プレビューは
  `AVCaptureVideoPreviewLayer`（`UIViewRepresentable`）。
- **枠→画像座標**: 撮影時に `previewLayer.metadataOutputRectConverted(fromLayerRect:)`
  でプレビュー上の枠を画像の正規化矩形に変換 → CropMath へ。
  - aspectFill によるプレビューのトリミングを正しく吸収するため、この変換を使う。
- **HEIC/JPEG**: `AVCapturePhotoSettings`。HEIC 非対応端末は JPEG にフォールバック。
- **向き対応**: `AVCaptureConnection.videoRotationAngle`（iOS17+）/ `videoOrientation`
  で撮影向きを合わせ、保存画像は表示向きへ正規化。
- **エクスポート**: 一時ディレクトリに上記フォルダ構成を作成 → `Foundation` で
  ZIP（`NSFileCoordinator` の `.forUploading` で .zip 生成）→ `UIActivityViewController`
  で AirDrop / Files / Google Drive へ共有。
- **権限**: `Package.swift` の `.camera(purposeString:)` で NSCameraUsageDescription を付与。

### 未解決・実機調整が必要な点（次エージェントへの申し送り）
1. プレビュー枠→撮影画像の座標変換は端末向き・aspectFill 設定で要検証。
2. 縦持ち撮影時の W/H とポスター比率(横長1.13)の整合（縦写真をどう扱うか）。
   - 案: 縦持ちでも顔枠は 1.13（横長寄り）で出し、保存は全体。crop_adjuster 側で吸収。
3. HEIC の crop_adjuster 取り込み: Python 側は `.heic` も収集対象だが、
   pillow-heif 依存。JPEG をデフォルト推奨にするのが無難。
4. Swift Playgrounds 上でのカメラ動作（iPad 実機推奨。Mac版は Mac カメラ）。

---

## 既存プロジェクトとの関係

- 本アプリは **撮影〜データ書き出し**専用。クロップ微調整・ポスター生成は
  既存の `crop_adjuster.py` / `make_poster.py`（リポジトリ直下）が担う。
- 連携は上記「フォルダ命名 + crop_overrides.csv」のファイル受け渡しのみ。疎結合。
- 既存 Python アプリ・安定版には一切影響しない（別ディレクトリ `capture-app/`）。

---

## 開発の再開方法

1. `capture-app/ClassPhotoCapture.swiftpm` を Swift Playgrounds（iPad/Mac）で開く
   （または Xcode で開く）。
2. 未実装ファイル（上記 ※未）を順に実装。CropMath → CameraModel/Preview →
   各 View → Exporter の順が依存的に進めやすい。
3. crop_adjuster 連携は本READMEの「連携仕様」を厳守（命名・CSV・CropMath）。
</content>
