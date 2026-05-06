# クラス個人写真 A2ポスター生成ツール

小学校・中学校で配布する**クラス個人写真ポスター（A2サイズ）**を、
名簿Excelとフォルダ整理された写真ファイルから一括生成するPythonツール。

## 特徴

- 全校名簿Excel + 写真フォルダから全クラスのA2ポスターを自動生成
- 顔検出による自動センタリング
- 撮影できなかった生徒は「写真なし」プレースホルダーで枠だけ確保
- HEIC/JPG混在対応（自動変換）
- GUIによるクロップ位置の手動微調整(イラレ風プレビュー)
- 全クラス共通レイアウト(6×7=42枠で統一)

## 必要な環境

- macOS / Linux
- Python 3.9 以上
- 名簿が `.xls` 形式の場合は `xlrd==1.2.0` または `.xlsx` への変換

## セットアップ

```bash
# リポジトリを取得
git clone https://github.com/ryonma-git/class-poster-generator.git
cd class-poster-generator

# 仮想環境の作成
python3 -m venv .venv
source .venv/bin/activate

# ライブラリのインストール
pip install -r requirements.txt
```

## データの準備

スクリプトと**別の場所**に、写真フォルダを以下の構造で用意してください。
個人情報を含むため、Gitには絶対に上げないでください(`.gitignore`で防いでいます)。

```
/path/to/写真フォルダ/
  ├── 名簿.xlsx              ← 全校名簿
  ├── 1年/
  │   ├── 1年1組/
  │   │   ├── 1101.jpg      ← {学年}{クラス}{出席番号2桁}
  │   │   ├── 1102.jpg
  │   │   └── ...
  │   ├── 1年2組/
  │   └── ...
  ├── 2年/
  └── ...
```

### 名簿Excelのフォーマット

学校システム標準フォーマットを想定:
- C列(3列目): 学年
- D列(4列目): 組
- E列(5列目): 番号
- R列(18列目): ふりがな(姓名)

## 使い方

### ① ポスター生成

```bash
# 全クラス一括
python make_poster.py --base /path/to/写真フォルダ --out ./output

# 特定クラスのみ
python make_poster.py --base /path/to/写真フォルダ --grade 1 --cls 1 --out ./output
```

### ② クロップ位置の手動調整(GUI)

```bash
python crop_adjuster.py --base /path/to/写真フォルダ
```

調整後、再度ポスター生成を実行すると反映されます。

#### キーボードショートカット

| キー | 動作 |
|---|---|
| `↑` `↓` `←` `→` | クロップ枠を移動 |
| `Shift + ↑` `↓` | ズーム |
| `[` `]` | 前 / 次の生徒 |
| `S` | 保存→次へ |
| `R` | リセット |

## ライセンス

[MIT License](LICENSE) © ryonma-git
