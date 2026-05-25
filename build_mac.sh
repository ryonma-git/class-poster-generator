#!/bin/bash
# ══════════════════════════════════════════════════════════
#  Mac .app ローカルビルドスクリプト
#  使い方: bash ~/Projects/class-poster-generator/build_mac.sh
# ══════════════════════════════════════════════════════════
set -e

REPO_DIR="$HOME/Projects/class-poster-generator"
BUILD_VENV="$REPO_DIR/.venv_build"

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Mac .app ビルド${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

cd "$REPO_DIR"

# ── 1. ビルド専用 venv を準備（初回のみ時間がかかる）──
echo -e "\n${YELLOW}[1/5] ビルド環境の準備${NC}"
if [ ! -x "$BUILD_VENV/bin/python3" ]; then
    echo "  初回セットアップ中（数分かかります）..."
    python3 -m venv "$BUILD_VENV"
fi
PY="$BUILD_VENV/bin/python3"
echo -e "  ${GREEN}✓${NC} Python: $($PY --version)"

# ── 2. ライブラリ確認・インストール ──
echo -e "\n${YELLOW}[2/5] ライブラリのインストール確認${NC}"
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q \
    Pillow opencv-python numpy pandas openpyxl \
    reportlab pillow-heif "xlrd==1.2.0" customtkinter \
    pyinstaller
echo -e "  ${GREEN}✓${NC} 完了"

# ── 3. 古いビルドを削除 ──
echo -e "\n${YELLOW}[3/5] 古いビルドを削除${NC}"
rm -rf dist build __pycache__ *.spec
echo -e "  ${GREEN}✓${NC} クリーン完了"

# ── 4. PyInstaller でビルド ──
echo -e "\n${YELLOW}[4/5] ビルド実行${NC}"

echo "  make_poster をビルド中..."
"$PY" -m PyInstaller \
    --onefile \
    --name make_poster \
    --hidden-import cv2 \
    --hidden-import pillow_heif \
    --hidden-import pandas \
    --hidden-import openpyxl \
    --hidden-import xlrd \
    make_poster.py

echo "  crop_adjuster をビルド中（時間がかかります）..."
# cv2 の Haar cascade XML（顔検出用）のパスを取得してバンドルに含める
HAARCASCADE_XML=$("$PY" -c "import cv2, os; print(os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml'))")
echo "  Haar cascade XML: $HAARCASCADE_XML"
"$PY" -m PyInstaller \
    --windowed \
    --name "CropAdjuster" \
    --collect-all customtkinter \
    --hidden-import PIL._tkinter_finder \
    --hidden-import cv2 \
    --collect-data cv2 \
    --hidden-import pillow_heif \
    --hidden-import pandas \
    --hidden-import openpyxl \
    --hidden-import xlrd \
    --add-data "${HAARCASCADE_XML}:cv2/data" \
    crop_adjuster.py

# make_poster を .app に同梱
cp dist/make_poster "dist/CropAdjuster.app/Contents/MacOS/make_poster"
echo -e "  ${GREEN}✓${NC} make_poster を .app に同梱しました"

# ── 5. zip にまとめる ──
echo -e "\n${YELLOW}[5/5] zip を作成${NC}"
cd dist
zip -r "クロップ調整ツール-Mac.zip" "CropAdjuster.app"
cd ..

echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ 完成！${NC}"
echo -e "  .app  → $REPO_DIR/dist/CropAdjuster.app"
echo -e "  zip   → $REPO_DIR/dist/クロップ調整ツール-Mac.zip"
echo -e ""
echo -e "  まず動作確認:"
echo -e "  ${BLUE}open dist/CropAdjuster.app${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
