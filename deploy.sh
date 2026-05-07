#!/bin/bash
# ════════════════════════════════════════════════════════
# クロップ調整ツール 自動デプロイ&起動 v2
# ════════════════════════════════════════════════════════
set -e

DOWNLOADS="$HOME/Downloads"
REPO_DIR="$HOME/Projects/class-poster-generator"
PHOTO_DIR="/Users/ryon/My M2/帰国後/石橋小26/【26年度】_クラス個別写真"
VENV_PATH="$PHOTO_DIR/.venv"
PYTHON_BIN="$VENV_PATH/bin/python3"
PIP_BIN="$VENV_PATH/bin/pip"

GREEN='\033[0;32m'; BLUE='\033[0;34m'
YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  クロップ調整ツール 自動デプロイ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ── 1. ダウンロードから取得 ──
echo -e "\n${YELLOW}[1/5] ダウンロードからスクリプト取得${NC}"
COPIED=0
for f in crop_adjuster.py make_poster.py; do
    if [ -f "$DOWNLOADS/$f" ]; then
        cp "$DOWNLOADS/$f" "$REPO_DIR/$f"
        echo -e "  ${GREEN}✓${NC} $f を取得"
        COPIED=$((COPIED+1))
    else
        echo -e "  ${YELLOW}-${NC} $DOWNLOADS/$f なし（スキップ）"
    fi
done
[ $COPIED -eq 0 ] && { echo -e "${RED}対象ファイルなし${NC}"; exit 1; }

# ── 2. Git ──
echo -e "\n${YELLOW}[2/5] Git コミット & プッシュ${NC}"
cd "$REPO_DIR"
if git diff --quiet && git diff --cached --quiet; then
    echo -e "  ${BLUE}変更なし${NC}"
else
    git add .
    git status --short
    read -p "  コミットメッセージ (Enter=デフォルト): " MSG
    MSG="${MSG:-改善: クロップ調整ツールの更新}"
    git commit -m "$MSG"
    git push && echo -e "  ${GREEN}✓ プッシュ完了${NC}"
fi

# ── 3. 写真フォルダにコピー ──
echo -e "\n${YELLOW}[3/5] 写真フォルダにコピー${NC}"
[ ! -d "$PHOTO_DIR" ] && { echo -e "${RED}写真フォルダなし: $PHOTO_DIR${NC}"; exit 1; }
for f in crop_adjuster.py make_poster.py; do
    [ -f "$REPO_DIR/$f" ] && cp "$REPO_DIR/$f" "$PHOTO_DIR/$f" && echo -e "  ${GREEN}✓${NC} $f"
done
cp "$REPO_DIR/make_poster.py" "$PHOTO_DIR/make_poster_v8.py" 2>/dev/null || true

# ── 4. venv確認 & ライブラリ確認 ──
echo -e "\n${YELLOW}[4/5] venv確認${NC}"
if [ ! -x "$PYTHON_BIN" ]; then
    echo -e "${RED}venvのpython3が見つかりません: $PYTHON_BIN${NC}"
    echo "venv を新規作成しますか？ (y/N)"
    read -r ANS
    if [ "$ANS" = "y" ]; then
        cd "$PHOTO_DIR"
        python3 -m venv .venv
        echo -e "  ${GREEN}✓ venv 作成${NC}"
    else
        exit 1
    fi
fi
echo -e "  ${GREEN}✓${NC} python: $PYTHON_BIN"

# ライブラリ確認
echo -e "  ライブラリ確認..."
MISSING=$("$PYTHON_BIN" -c "
import importlib
mods = ['PIL', 'cv2', 'numpy', 'pandas', 'openpyxl', 'reportlab', 'pillow_heif']
missing = []
for m in mods:
    try: importlib.import_module(m)
    except ImportError: missing.append(m)
print(' '.join(missing))
" 2>/dev/null)

if [ -n "$MISSING" ]; then
    echo -e "  ${YELLOW}不足: $MISSING${NC}"
    echo -e "  ${BLUE}インストール中...${NC}"
    "$PIP_BIN" install Pillow opencv-python numpy pandas openpyxl reportlab pillow-heif xlrd==1.2.0
fi

# ── 5. 起動 ──
echo -e "\n${YELLOW}[5/5] 起動${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
cd "$PHOTO_DIR"
exec "$PYTHON_BIN" crop_adjuster.py --base "$PHOTO_DIR"
