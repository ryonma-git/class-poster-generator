#!/bin/bash
# ══════════════════════════════════════════════════════════
#  顔写真ツール 最新開発版 ランチャー
#  （feature/photo-manager ブランチの最新コードで起動）
#
#  使い方: このファイルをダブルクリックするだけ
#
#  ※ 既存の deploy.sh・安定版には一切影響しません。
#    最新コードは毎回 git から取り出すので、開発が進めば
#    このファイルを開き直すだけで常に最新版が起動します。
# ══════════════════════════════════════════════════════════
set -e

REPO="$HOME/Projects/class-poster-generator"
PHOTO_DIR="/Users/ryon/My M2/帰国後/石橋小26/【26年度】_クラス個別写真"
PY="$PHOTO_DIR/.venv/bin/python3"
BRANCH="feature/ios-poster-generator"
DEV="$HOME/.crop_adjuster_dev"   # 安定版と混ざらない独立フォルダ

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  顔写真ツール 最新開発版 起動${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ── 1. リポジトリ・venv の存在確認 ──
if [ ! -d "$REPO/.git" ]; then
    echo -e "${RED}✗ リポジトリが見つかりません: $REPO${NC}"
    echo "  何かキーを押すと閉じます..."; read -r -n 1; exit 1
fi
if [ ! -x "$PY" ]; then
    echo -e "${RED}✗ Python(venv)が見つかりません: $PY${NC}"
    echo "  先に従来の deploy.sh を一度実行して venv を作ってください。"
    echo "  何かキーを押すと閉じます..."; read -r -n 1; exit 1
fi

# ── 2. 最新の feature 版コードを取り出す（現在のブランチに依存しない）──
echo -e "\n${YELLOW}[1/2] 最新コードを取得${NC}"
mkdir -p "$DEV"
cd "$REPO"
# リモートに新しい版があれば取り込む（失敗してもローカル版で続行）
git fetch origin "$BRANCH" --quiet 2>/dev/null || true
REF="$BRANCH"
git rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1 && REF="origin/$BRANCH"
git show "$REF:crop_adjuster.py" > "$DEV/crop_adjuster.py"
echo -e "  ${GREEN}✓${NC} $REF の crop_adjuster.py を取得"
# make_poster.py も最新を取得（$DEV と写真フォルダの両方に反映）。
# crop_adjuster は写真フォルダの make_poster.py を優先して探すため、ここで上書きしないと
# A1デフォルト等の最新変更が反映されない。
git show "$REF:make_poster.py" > "$DEV/make_poster.py" 2>/dev/null \
    && cp "$DEV/make_poster.py" "$PHOTO_DIR/make_poster.py" 2>/dev/null \
    && echo -e "  ${GREEN}✓${NC} $REF の make_poster.py を取得（写真フォルダにも反映）"

# ── 3. 起動 ──
echo -e "\n${YELLOW}[2/2] 起動${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
cd "$DEV"
exec "$PY" "$DEV/crop_adjuster.py" --base "$PHOTO_DIR"
