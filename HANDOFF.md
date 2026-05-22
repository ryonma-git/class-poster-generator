# クラス個人写真ポスター生成ツール — 引き継ぎ資料

> このドキュメントは Claude Code 等の別セッションでの開発継続用です。
> 現在の機能・実装状況・既知の課題・将来計画をまとめています。

## プロジェクト概要

小学校のクラス個人写真をA2/A1ポスターに一括生成するツール。
ユーザーは現役の小学校教師（情報部長、今年度退職予定）。来年度以降は他の教師が運用予定。
**最終目標**: 素人でも使える完全自動化アプリ。

## 動作環境

- **OS**: macOS（MacBook Air、Python 3.14 + Homebrew）
- **将来**: Windows でも動作する必要あり
- **写真フォルダ**: `~/My M2/帰国後/石橋小26/【26年度】_クラス個別写真/`
- **venv**: フォルダ内 `.venv/`

## ファイル構成

```
~/Projects/class-poster-generator/           # Gitリポジトリ
├── crop_adjuster.py        # GUI（CustomTkinter + tkinter）
├── make_poster.py          # PDF生成バックエンド
├── deploy.sh               # 自動デプロイ
├── requirements.txt
├── teachers_template.csv   # 担任情報テンプレート
├── README.md
├── HANDOFF.md              # 本ドキュメント
└── .git/
                                               
【26年度】_クラス個別写真/                   # 実運用フォルダ
├── 1年/1年1組/1101.JPG …            # 写真（学年×組×番号）
├── 2026年度4月_生徒情報.xlsx        # 名簿
├── crop_check/crop_overrides.csv    # クロップ調整値
├── output/*.pdf                     # 生成PDF
├── teachers.csv                     # 担任情報（任意）
├── teacher_photos/{学年}-{組}.jpg   # 担任写真（任意）
├── design_config.json               # デザイン色（任意）
└── .venv/
```

## 名簿・写真の規約

- **名簿** `2026年度4月_生徒情報.xlsx`:
  - C列=学年, D列=組, E列=番号, R列=ふりがな(姓名)
- **写真ファイル名**: `{学年}{組}{番号2桁}.{ext}` (例: `2304.jpg`)
- **拡張子混在対応**: JPG/JPEG/HEIC/PNG（JPG優先）
- **データ規模**: 6学年19クラス、約620名

## 現在の機能（完成度: 概ね完成）

### crop_adjuster.py (GUI)

#### メイン画面
- 写真フォルダ自動検出、名簿読み込み
- OpenCV顔検出による自動クロップ（`desired_crop_h = fh * 2.2`, `head_margin = fh * 0.4`）
- 手動微調整（top_pct, left_pct, zoom）
- マウスドラッグで枠移動
- キー操作: ↑↓←→=枠移動、Shift+↑↓=ズーム、[]=前/次（自動保存）、S=保存、R=リセット、F=顔検出やり直し
- マウスホイール・トラックパッドスクロール対応

#### サブ画面
1. **🖼 クラス全員のプレビュー**: 静的サムネ一覧
2. **✏️ クラス一括調整**: 重要機能
   - サムネをクリックで複数選択
   - ⌘/Ctrl+クリック=個別追加、Shift+クリック=範囲、⌘A=全選択、Esc/空白=解除
   - 上下/左右/ズーム スライダー（顔の動かしたい方向と矢印が一致）
   - **3層構造の値管理**:
     - `original` (開いた時のスナップ／キャンセルで戻る)
     - `working` (生徒ごとの作業値、選択切替で蓄積)
     - スライダー値 (現在の差分、選択中のみ表示反映)
   - キー操作: ↑↓←→=顔移動、Shift+↑↓=ズーム
   - 「✓ 適用」: working が元と違う全員に保存（バックアップ自動取得）
3. **🎨 デザイン設定**: 8項目の色カスタマイズ（design_config.json）
4. **🚀 ポスター出力ウィザード**: 4ステップ（モード/レイアウト/担任/確認）

#### 進捗ダイアログ
- PDF生成中のリアルタイムログとプログレスバー
- 完了時に「📂 フォルダを開く」ボタン
- subprocess は `-u` + `PYTHONUNBUFFERED=1` でunbuffered

#### モーダル管理
- `_modal_count` でサブウィンドウ表示中はメインのキー処理を無効化
- 対応済み: ClassBatchEditor, DesignEditor, PosterWizard, ProgressDialog

### make_poster.py (PDF生成)

- 出力モード: `class` (A2個別) / `grade-a2` (A2幅594mmロール) / `grade-a1` (A1幅841mmロール)
- ロール紙はA2個別と同じレイアウト・セルサイズを縦に連結（中央寄せ、片側余白10mm）
- セル全体は紙面いっぱい（cw, ch を独立計算、縦横比強制なし）
- 写真エリア比率は `target_w / target_h` で動的計算
- プレビュー側 `CELL_ASPECT = 1.02` で一致

### deploy.sh
- 自己更新機能（Downloads/deploy.sh が新しければ自動取得して再実行）
- Downloads → リポジトリ → 写真フォルダ の順にコピー
- git add/commit/push（コミットメッセージプロンプト）
- venv 確認、python -m pip でライブラリインストール

## 重要な実装ポリシー

1. **データ破壊的操作には自動バックアップ** (`crop_overrides.csv.bak`)
2. **モーダル管理は `_modal_count` で一元化**
3. **PDFとプレビューの完全一致**（CELL_ASPECTの動的計算）
4. **個別調整値は絶対値で保存**（top_pct/left_pct/zoom）
5. **Apple/iOSライクなデザイン**（macOSのtk.Button色問題はMacButtonクラスで回避）

## 既知の制約・未対応事項

| 項目 | 状態 | 優先度 |
|---|---|---|
| PyInstallerでの.app/.exe化 | 未対応 | 高（来年度引継ぎ向け） |
| Googleドライブ連携（フォルダ自動構築） | 未対応 | 高 |
| 写真名前順→出席番号自動変換 | 未対応 | 高 |
| 担任写真の自動取り込みUI | 未対応 | 中 |
| クラス全員プレビューの動的更新 | 未対応 | 低 |
| ウィザードレイアウトのプレビュー | 未対応 | 低 |
| 比率動的計算（コマ数→比率） | 見送り | — |

## デフォルト調整値（重要）

```python
# 顔検出（make_poster.py & crop_adjuster.py）
desired_crop_h = fh * 2.2   # 顔の高さの2.2倍（アップ寄り）
head_margin = fh * 0.4      # 頭上の余白（顔の40%）

# プレビュー側
CELL_ASPECT = 1.02          # PDFの実比率（A2+6×7時）
```

> 注: 過去に 2.8/0.5/0.75 だった時期があるが、2.2/0.4/1.02 が現状の最適値。

## ライブラリ依存

```
Pillow, opencv-python, numpy, pandas, openpyxl,
reportlab, pillow-heif, xlrd==1.2.0, customtkinter
```

## GitHubリポジトリ

- **URL**: https://github.com/ryonma-git/class-poster-generator
- **匿名メール**: 263776487+ryonma-git@users.noreply.github.com
- ライセンス: MIT

## 次セッションでの取り組み候補

1. **PyInstallerでのアプリ化** (`.app`/`.exe` 化)
2. **新年度セットアップウィザード**（フォルダ構造自動構築）
3. **写真リネームツール**（iPhone撮影順→出席番号順）
4. **Google Drive連携**（写真アップロード→処理→ダウンロード）

これらを実装すれば「素人でもクリックだけでポスター生成」が実現できる。

## 開発者へのメモ

- ユーザーは詳細な手順書を好む（コマンド全部書く）
- エラーログは必ず提示
- 「漏れなく対応」を強調
- スクリーンショットの個人情報は学習・保存しない
