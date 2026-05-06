#!/usr/bin/env python3
"""
クロップ調整GUI v6
==================
変更点:
- 初期クロップ: 頭の上を確実に枠内に収める（顔上部に余白を取る）
- ウィンドウサイズを画面に応じて最適化＋中央配置
- スクロール可能なメインキャンバス
- 全体プレビュー（クラス全員のサムネ一覧）パネル
- マウスドラッグでクロップ枠を移動
- カラーパレット刷新（白文字×薄背景を全面排除）
- フォーカス制御の改善（リスト選択中はリスト操作、それ以外は枠操作）
- 柔らかい角・余白・パステルアクセント
"""

import os, glob, re, csv, argparse, subprocess, threading, sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFont
import numpy as np
import cv2

# ════════════════════════════════════════════════════════
#  共通: フォント・EXIF・顔検出
# ════════════════════════════════════════════════════════
FONT_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
    "/System/Library/Fonts/Hiragino Sans W3.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/Library/Fonts/UDDigiKyokashoProN-Regular.otf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
]
_fp = None
def get_pil_font(size):
    global _fp
    if _fp is None:
        _fp = next((p for p in FONT_CANDIDATES if p and os.path.exists(p)), None)
    if _fp:
        try: return ImageFont.truetype(_fp, size)
        except: pass
    return ImageFont.load_default()

def fix_exif(img):
    try:
        from PIL import ExifTags
        exif = img._getexif()
        if exif:
            for tag, val in exif.items():
                if ExifTags.TAGS.get(tag) == 'Orientation':
                    r = {3:180, 6:270, 8:90}.get(val, 0)
                    if r: return img.rotate(r, expand=True)
    except: pass
    return img

# ════════════════════════════════════════════════════════
#  顔検出
# ════════════════════════════════════════════════════════
_cascade = None
def detect_face(pil_img):
    global _cascade
    if _cascade is None:
        _cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    w, h = pil_img.size
    rgb  = np.array(pil_img.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    min_f = max(20, int(min(w, h) * 0.05))
    for g in [gray, cv2.equalizeHist(gray)]:
        for scale in [1.05, 1.08, 1.12, 1.15]:
            for nb in [3, 4, 5]:
                faces = _cascade.detectMultiScale(
                    g, scaleFactor=scale, minNeighbors=nb,
                    minSize=(min_f, min_f))
                if len(faces) > 0:
                    return sorted(faces, key=lambda f:f[2]*f[3], reverse=True)[0]
    return None

# ════════════════════════════════════════════════════════
#  クロップ計算
# ════════════════════════════════════════════════════════
CELL_ASPECT = 3 / 4

def calc_crop_box(img_w, img_h, top_pct, left_pct, zoom):
    if img_w / img_h < CELL_ASPECT:
        base_w = img_w
        base_h = base_w / CELL_ASPECT
    else:
        base_h = img_h
        base_w = base_h * CELL_ASPECT
    crop_w = base_w / zoom
    crop_h = base_h / zoom
    cx = img_w/2 + img_w * left_pct/100
    cy = img_h * top_pct/100 + crop_h/2
    x1 = cx - crop_w/2
    y1 = cy - crop_h/2
    x1 = max(0, min(x1, img_w - crop_w))
    y1 = max(0, min(y1, img_h - crop_h))
    return (int(x1), int(y1), int(x1+crop_w), int(y1+crop_h))

def do_crop(pil_img, top_pct, left_pct, zoom):
    w, h = pil_img.size
    box  = calc_crop_box(w, h, top_pct, left_pct, zoom)
    return pil_img.crop(box)

def auto_initial_crop_params(pil_img):
    """
    顔検出から初期クロップ値を計算。
    重要: 頭の上を必ず枠内に収める（頭頂部にも余白を確保）
    """
    w, h = pil_img.size
    face = detect_face(pil_img)
    if face is None:
        return 0.0, 0.0, 1.0

    fx, fy, fw, fh = face
    face_cx = fx + fw / 2
    face_cy = fy + fh / 2
    face_top = fy

    # ── ベースサイズ（zoom=1.0時の最大枠）──
    if w / h < CELL_ASPECT:
        base_h = w / CELL_ASPECT
    else:
        base_h = h

    # ── 頭の上に確保したい余白（顔の高さの50%）──
    # 顔の上端から頭頂部まで、髪の毛分のスペース
    head_margin = fh * 0.5

    # 顔の高さ × 2.5倍をクロップ高さの基本値にする
    # （以前は2.0倍だったが、頭が見切れるため大きめに）
    desired_crop_h = fh * 2.8

    # ズーム計算（より大きい枠が必要なら zoom を下げる）
    zoom = base_h / desired_crop_h
    zoom = max(1.0, min(2.5, zoom))

    crop_h_actual = base_h / zoom

    # ── top_pct 計算 ──
    # 顔の上端 - head_margin の位置にクロップ枠の上端を持ってくる
    desired_y1 = face_top - head_margin
    # ただし画像の上端を超えない
    desired_y1 = max(0, desired_y1)
    # クロップ枠が画像下端を超えないよう調整
    desired_y1 = min(desired_y1, h - crop_h_actual)
    top_pct = (desired_y1 / h) * 100

    # ── left_pct 計算（顔を中央に）──
    left_pct = ((face_cx - w/2) / w) * 100
    left_pct = max(-50, min(50, left_pct))

    return float(top_pct), float(left_pct), float(zoom)

# ════════════════════════════════════════════════════════
#  プレビュー描画
# ════════════════════════════════════════════════════════
def render_clipping_preview(pil_img, top_pct, left_pct, zoom, max_w=420, max_h=560):
    iw, ih = pil_img.size
    scale = min(max_w/iw, max_h/ih)
    dw, dh = int(iw*scale), int(ih*scale)
    base = pil_img.resize((dw, dh), Image.LANCZOS).convert("RGB")

    x1, y1, x2, y2 = calc_crop_box(iw, ih, top_pct, left_pct, zoom)
    bx1, by1 = int(x1*scale), int(y1*scale)
    bx2, by2 = int(x2*scale), int(y2*scale)

    overlay = Image.new("RGBA", (dw, dh), (10, 14, 28, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0,0,dw,dh], fill=(10,14,28,150))
    od.rectangle([bx1, by1, bx2, by2], fill=(0,0,0,0))

    result = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    rd = ImageDraw.Draw(result)

    # 柔らかいゴールド枠
    GOLD = (245, 175, 60)
    rd.rectangle([bx1, by1, bx2-1, by2-1], outline=GOLD, width=3)
    # 角の小さなマーカー
    L = 14
    for cx, cy in [(bx1, by1), (bx2-1, by1), (bx1, by2-1), (bx2-1, by2-1)]:
        rd.line([(cx-L if cx>bx1 else cx, cy), (cx+L if cx<bx2-1 else cx, cy)],
                fill=GOLD, width=4)
        rd.line([(cx, cy-L if cy>by1 else cy), (cx, cy+L if cy<by2-1 else cy)],
                fill=GOLD, width=4)

    info = f"crop: {x2-x1}×{y2-y1} px"
    f = get_pil_font(13)
    bb = rd.textbbox((0,0), info, font=f)
    rd.rectangle([6, 6, bb[2]+18, bb[3]+14], fill=(0,0,0,180))
    rd.text((12, 10), info, font=f, fill=(255,255,255))
    return result, scale, (bx1, by1, bx2, by2)

# ════════════════════════════════════════════════════════
#  ポスター上の見た目
# ════════════════════════════════════════════════════════
C_CARD    = (0xF7, 0xF9, 0xFC)
C_LBL_BG  = (0x2B, 0x5F, 0x8E)
C_LBL_FG  = (0xFF, 0xFF, 0xFF)
C_NUM_FG  = (0xE8, 0x9C, 0x2A)
C_ACCENT  = (0xE8, 0x9C, 0x2A)

def render_poster_cell(cropped_img, num, name, cell_w=240):
    label_h = 50
    photo_h = int(cell_w / CELL_ASPECT)
    cell_h  = photo_h + label_h
    R       = 14

    cell = Image.new("RGBA", (cell_w, cell_h), (0,0,0,0))
    bg   = Image.new("RGBA", (cell_w, cell_h), C_CARD + (255,))
    mask = Image.new("L", (cell_w, cell_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,cell_w-1,cell_h-1], radius=R, fill=255)
    cell.paste(bg, mask=mask)

    photo = cropped_img.resize((cell_w, photo_h), Image.LANCZOS).convert("RGBA")
    pmask = Image.new("L", (cell_w, photo_h), 0)
    pd_   = ImageDraw.Draw(pmask)
    pd_.rounded_rectangle([0,0,cell_w-1,photo_h-1], radius=R, fill=255)
    pd_.rectangle([0, photo_h//2, cell_w-1, photo_h-1], fill=255)
    photo.putalpha(pmask)
    cell.paste(photo, (0,0), photo)

    lbl = Image.new("RGBA", (cell_w, label_h), C_LBL_BG + (255,))
    lmask = Image.new("L", (cell_w, label_h), 0)
    ld_ = ImageDraw.Draw(lmask)
    ld_.rounded_rectangle([0,0,cell_w-1,label_h-1], radius=R, fill=255)
    ld_.rectangle([0, 0, cell_w-1, label_h//2], fill=255)
    lbl_a = Image.new("RGBA", (cell_w, label_h), (0,0,0,0))
    lbl_a.paste(lbl, mask=lmask)

    ld = ImageDraw.Draw(lbl_a)
    pad = int(cell_w * 0.05)
    cy  = label_h // 2
    num_str = f"{num:02d}"
    f_num   = get_pil_font(int(label_h * 0.34))
    nb      = ld.textbbox((0,0), num_str, font=f_num)
    nw      = nb[2] - nb[0]
    ld.text((pad, cy), num_str, font=f_num, fill=C_NUM_FG+(255,), anchor="lm")

    avail = cell_w - nw - pad*3
    f_nm  = get_pil_font(int(label_h * 0.55))
    while True:
        bb = ld.textbbox((0,0), name, font=f_nm)
        if bb[2]-bb[0] <= avail or f_nm.size <= 14:
            break
        f_nm = get_pil_font(f_nm.size - 2)
    ld.text((pad+nw+pad, cy), name, font=f_nm, fill=C_LBL_FG+(255,), anchor="lm")

    cell.paste(lbl_a, (0, photo_h), lbl_a)
    ImageDraw.Draw(cell).line([(0,photo_h),(cell_w,photo_h)],
                              fill=C_ACCENT+(220,), width=3)
    return cell

# ════════════════════════════════════════════════════════
#  クラス全員のサムネ一覧（プレビュー）
# ════════════════════════════════════════════════════════
def render_class_overview(class_items, current_num=None, max_w=560, thumb_w=110):
    """
    class_items: [(num, name, cropped_img), ...]
    現在編集中の生徒は強調表示
    """
    if not class_items:
        img = Image.new("RGB", (max_w, 100), (240, 235, 250))
        d = ImageDraw.Draw(img)
        f = get_pil_font(14)
        d.text((max_w//2, 50), "クラスの写真を読み込み中...",
               font=f, fill=(120, 120, 140), anchor="mm")
        return img

    cols   = 6
    rows   = (len(class_items) + cols - 1) // cols
    pad    = 8
    label_h = 24
    thumb_h = int(thumb_w / CELL_ASPECT)
    cell_w_total = thumb_w + pad
    cell_h_total = thumb_h + label_h + pad

    canvas_w = cols * cell_w_total + pad
    canvas_h = rows * cell_h_total + pad

    img = Image.new("RGB", (canvas_w, canvas_h), (245, 240, 252))
    d = ImageDraw.Draw(img)

    for idx, (num, name, cropped) in enumerate(class_items):
        col = idx % cols
        row = idx // cols
        x = pad + col * cell_w_total
        y = pad + row * cell_h_total

        is_current = (num == current_num)

        # 背景（現在編集中は明るいゴールド）
        bg_col = (255, 245, 215) if is_current else (255, 255, 255)
        border_col = (245, 175, 60) if is_current else (220, 215, 230)
        d.rounded_rectangle([x, y, x+thumb_w, y+thumb_h+label_h],
                           radius=8, fill=bg_col,
                           outline=border_col, width=2 if is_current else 1)

        # 写真サムネ
        if cropped is not None:
            try:
                t = cropped.resize((thumb_w-4, thumb_h-4), Image.LANCZOS)
                # 角丸マスク
                mask = Image.new("L", t.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle(
                    [0, 0, t.size[0]-1, t.size[1]-1], radius=6, fill=255)
                t.putalpha(mask)
                img.paste(t.convert("RGB"), (x+2, y+2), mask)
            except:
                pass

        # 番号・名前
        f_num = get_pil_font(11)
        f_nm  = get_pil_font(11)
        num_text = f"{num:02d}"
        d.text((x+6, y+thumb_h+4), num_text, font=f_num, fill=(232, 156, 42))
        # 名前は短縮
        short_name = name if len(name) <= 8 else name[:7] + "…"
        d.text((x+thumb_w-6, y+thumb_h+4), short_name,
               font=f_nm, fill=(70, 70, 95), anchor="ra")

    return img

# ════════════════════════════════════════════════════════
#  名簿・写真関連
# ════════════════════════════════════════════════════════
def collect_photos(folder, grade, cls):
    prefix = f"{grade}{cls}"
    photos = {}
    for ext in ['.jpg','.jpeg','.JPG','.JPEG','.png','.PNG']:
        for f in glob.glob(os.path.join(folder, f"{prefix}*{ext}")):
            stem = Path(f).stem
            if not stem.startswith(prefix): continue
            try:
                num = int(stem[len(prefix):])
                if num not in photos: photos[num] = f
            except: pass
    return photos

def find_class_folder(base, grade, cls):
    for root, dirs, files in os.walk(base):
        if not any(f.lower().endswith(('.jpg','.jpeg','.png','.heic')) for f in files):
            continue
        name = Path(root).name
        m = re.search(r'(\d+)\s*年\s*(\d+)\s*組', name)
        if m and int(m.group(1))==grade and int(m.group(2))==cls:
            return root
        m2 = re.search(r'(\d+)\s*組', name)
        if m2 and int(m2.group(1))==cls:
            parent = str(Path(root).parent)
            if re.search(rf'{grade}\s*年', parent):
                return root
    return None

def find_all_classes(base):
    results = []
    for root, dirs, files in os.walk(base):
        if not any(f.lower().endswith(('.jpg','.jpeg','.png','.heic')) for f in files):
            continue
        parts = Path(os.path.relpath(root, base)).parts
        last = parts[-1]
        m = re.search(r'(\d+)\s*年\s*(\d+)\s*組', last)
        if m:
            results.append((int(m.group(1)), int(m.group(2)), root))
            continue
        m = re.search(r'(\d+)\s*組', last)
        if m:
            for part in reversed(parts[:-1]):
                m2 = re.search(r'(\d+)\s*年', part)
                if m2:
                    results.append((int(m2.group(1)), int(m.group(1)), root))
                    break
    return sorted(set(results))

def load_master_roster(path):
    import pandas as pd
    ext = Path(path).suffix.lower()
    if ext == '.xls':
        try:
            import xlrd
            wb = xlrd.open_workbook(path)
            ws = wb.sheet_by_index(0)
            rows = [ws.row_values(i) for i in range(ws.nrows)]
            df = pd.DataFrame(rows[1:], columns=rows[0])
        except: return {}
    else:
        df = pd.read_excel(path, header=0)
    sub = df.iloc[:, [2,3,4,17]].copy()
    sub.columns = ["学年","組","番号","氏名"]
    sub = sub.dropna(subset=["学年","組","番号"])
    sub["学年"] = sub["学年"].astype(int)
    sub["組"]   = sub["組"].astype(int)
    sub["番号"] = sub["番号"].astype(int)
    sub["氏名"] = sub["氏名"].fillna("").astype(str).str.strip()
    result = {}
    for _, row in sub.iterrows():
        result.setdefault((row["学年"], row["組"]), {})[row["番号"]] = row["氏名"]
    return result

def find_roster_file(base):
    candidates = [
        f for f in
        glob.glob(os.path.join(base, "*.xls")) +
        glob.glob(os.path.join(base, "*.xlsx"))
        if not Path(f).name.startswith(("~$", ".", "_"))
    ]
    return candidates[0] if len(candidates) == 1 else None

def load_overrides(path):
    d = {}
    if not os.path.exists(path): return d
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            try:
                k = (int(row['grade']), int(row['cls']), int(row['num']))
                d[k] = {
                    'top_pct':  float(row.get('top_pct',  0) or 0),
                    'left_pct': float(row.get('left_pct', 0) or 0),
                    'zoom':     float(row.get('zoom',     1) or 1),
                }
            except: pass
    return d

def save_overrides(path, d):
    os.makedirs(Path(path).parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['grade','cls','num','top_pct','left_pct','zoom'])
        for (g,c,n), v in sorted(d.items()):
            w.writerow([g, c, n,
                        v.get('top_pct', 0),
                        v.get('left_pct', 0),
                        v.get('zoom', 1)])

# ════════════════════════════════════════════════════════
#  デザインパレット（柔らかく・コントラスト高く）
# ════════════════════════════════════════════════════════
PALETTE = {
    # ベース：明るめのグレージュ
    "bg":          "#f5f3ee",   # 全体背景（暖かみのあるオフホワイト）
    "panel":       "#ffffff",   # カード背景
    "panel_alt":   "#f7f4ee",   # 副カード
    "panel_input": "#fbf8f1",   # 入力欄背景
    # テキスト：濃いめでコントラスト確保
    "text":        "#2a2a2a",   # メインテキスト
    "text_strong": "#1a1a1a",   # 強調
    "text_dim":    "#7a7a82",   # 弱め（コントラスト4.5:1以上）
    "text_label":  "#3d3d4a",   # ラベル
    # アクセントカラー：パステル基調
    "accent":      "#d4942e",   # ゴールド
    "accent_bg":   "#fff4dd",   # ゴールド背景
    "primary":     "#3a7ab8",   # ブルー
    "primary_bg":  "#e3eef9",   # ブルー背景
    "primary_dk":  "#27598c",
    "success":     "#2d9b5c",   # グリーン
    "success_bg":  "#e3f5e8",
    "danger":      "#c44545",   # レッド
    "danger_bg":   "#fae5e5",
    "border":      "#dfd9cf",
    "border_active": "#c9bea8",
}

# ════════════════════════════════════════════════════════
#  GUI
# ════════════════════════════════════════════════════════
class CropAdjusterApp:

    def __init__(self, root, base, override_path):
        self.root          = root
        self.base          = base
        self.override_path = override_path
        self.overrides     = load_overrides(override_path)

        self.classes_list  = find_all_classes(base)
        self.roster_path   = find_roster_file(base)
        self.roster_data   = load_master_roster(self.roster_path) if self.roster_path else {}

        self.current_img      = None
        self.current_key      = None
        self.photos           = {}
        self.photo_nums       = []
        self.auto_initial     = (0.0, 0.0, 1.0)
        self.class_thumbnails = {}  # (g,c,n) -> cropped PIL image

        self._update_pending = False
        self._dragging = False
        self._drag_start = None
        self._drag_start_left = 0
        self._drag_start_top = 0

        # ── ウィンドウサイズを画面に合わせて最適化 ──
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        # macOSのDockやメニューバーを考慮してマージン
        win_w = min(1280, int(sw * 0.85))
        win_h = min(900, int(sh * 0.82))
        # 中央配置
        x = (sw - win_w) // 2
        y = max(40, (sh - win_h) // 2 - 20)  # メニューバー分少し上
        root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        root.minsize(1100, 700)

        # プレビューサイズを画面サイズから動的に決定
        self.PREVIEW_W = max(360, min(440, int(win_w * 0.32)))
        self.PREVIEW_H = max(440, min(560, int(win_h * 0.55)))
        self.POSTER_W  = 200

        root.title("クロップ調整ツール")
        root.configure(bg=PALETTE["bg"])
        self._setup_ttk_style()
        self._build_ui()
        self._bind_keys()
        self._refresh_class_list()

        self.root.after(100, lambda: self.root.focus_set())

    def _setup_ttk_style(self):
        style = ttk.Style()
        try: style.theme_use('clam')
        except: pass
        # スクロールバー
        style.configure("Vertical.TScrollbar",
                       background=PALETTE["panel_alt"],
                       troughcolor=PALETTE["bg"],
                       arrowcolor=PALETTE["text_dim"],
                       borderwidth=0)

    def _build_ui(self):
        BG     = PALETTE["bg"]
        PANEL  = PALETTE["panel"]
        TEXT   = PALETTE["text"]
        STRONG = PALETTE["text_strong"]
        DIM    = PALETTE["text_dim"]
        LABEL  = PALETTE["text_label"]

        root = self.root

        # ─── ヘッダー ───
        header = tk.Frame(root, bg=PALETTE["primary"], height=50)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="✦  クロップ調整ツール",
                 bg=PALETTE["primary"], fg="#ffffff",
                 font=("",16,"bold")).pack(side="left", padx=22, pady=10)
        tk.Label(header, text="個人写真ポスター",
                 bg=PALETTE["primary"], fg="#fff5e0",
                 font=("",11)).pack(side="left", pady=10)

        # ─── 上部入力エリア ───
        topbar = tk.Frame(root, bg=PANEL, height=58, highlightthickness=0)
        topbar.pack(fill="x", padx=14, pady=(12,0))
        topbar.pack_propagate(False)

        def _label(parent, t):
            return tk.Label(parent, text=t, bg=PANEL, fg=LABEL, font=("",11,"bold"))

        _label(topbar, "学年").pack(side="left", padx=(20,4), pady=16)
        self.v_grade = tk.StringVar(value="1")
        self.sb_grade = tk.Spinbox(topbar, from_=1, to=6, width=4, textvariable=self.v_grade,
                   font=("",13), bg=PALETTE["panel_input"], fg=TEXT,
                   highlightthickness=1, highlightbackground=PALETTE["border"],
                   relief="flat",
                   buttonbackground=PALETTE["panel_alt"])
        self.sb_grade.pack(side="left", padx=4, pady=16)

        _label(topbar, "組").pack(side="left", padx=(12,4), pady=16)
        self.v_cls = tk.StringVar(value="1")
        self.sb_cls = tk.Spinbox(topbar, from_=1, to=6, width=4, textvariable=self.v_cls,
                   font=("",13), bg=PALETTE["panel_input"], fg=TEXT,
                   highlightthickness=1, highlightbackground=PALETTE["border"],
                   relief="flat")
        self.sb_cls.pack(side="left", padx=4, pady=16)

        _label(topbar, "番号").pack(side="left", padx=(12,4), pady=16)
        self.v_num = tk.StringVar(value="1")
        self.sb_num = tk.Spinbox(topbar, from_=1, to=40, width=4, textvariable=self.v_num,
                   font=("",13), bg=PALETTE["panel_input"], fg=TEXT,
                   highlightthickness=1, highlightbackground=PALETTE["border"],
                   relief="flat")
        self.sb_num.pack(side="left", padx=4, pady=16)

        tk.Button(topbar, text="開く", font=("",12,"bold"),
                  bg=PALETTE["primary"], fg="#ffffff",
                  activebackground=PALETTE["primary_dk"], activeforeground="#ffffff",
                  relief="flat", padx=20, pady=4, cursor="hand2",
                  command=self.open_photo, takefocus=0
                 ).pack(side="left", padx=(16,12), pady=12)

        self.saved_var = tk.StringVar(value=f"調整済み {len(self.overrides)}件")
        tk.Label(topbar, textvariable=self.saved_var,
                 bg=PALETTE["accent_bg"], fg=PALETTE["accent"],
                 font=("",11,"bold"), padx=14, pady=4
                ).pack(side="right", padx=20, pady=16)

        # ─── スクロール可能なメインエリア ───
        # Canvas + Scrollbar の構造
        outer = tk.Frame(root, bg=BG)
        outer.pack(fill="both", expand=True, padx=14, pady=12)

        self.main_canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical",
                                 command=self.main_canvas.yview,
                                 style="Vertical.TScrollbar")
        self.scrollable_frame = tk.Frame(self.main_canvas, bg=BG)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))
        )

        self.main_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.main_canvas.configure(yscrollcommand=scrollbar.set)
        self.main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # マウスホイールで Canvas をスクロール
        def _on_mousewheel(event):
            self.main_canvas.yview_scroll(int(-1*(event.delta/3)), "units")
        self.main_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        # macOSのトラックパッド用
        self.main_canvas.bind_all("<Button-4>", lambda e: self.main_canvas.yview_scroll(-1, "units"))
        self.main_canvas.bind_all("<Button-5>", lambda e: self.main_canvas.yview_scroll(1, "units"))

        # main は scrollable_frame の中
        main = tk.Frame(self.scrollable_frame, bg=BG)
        main.pack(fill="both", expand=True)

        # ─ 左: クラス一覧 ─
        left = tk.Frame(main, bg=PANEL, width=200,
                       highlightthickness=1, highlightbackground=PALETTE["border"])
        left.pack(side="left", fill="y", padx=(0,10))
        left.pack_propagate(False)

        tk.Label(left, text="CLASSES", bg=PANEL, fg=DIM,
                 font=("",10,"bold"), anchor="w"
                ).pack(fill="x", padx=14, pady=(14,4))

        lf = tk.Frame(left, bg=PANEL)
        lf.pack(fill="both", expand=True, padx=8, pady=(0,12))
        self.class_listbox = tk.Listbox(
            lf, font=("",12), height=22,
            bg=PALETTE["panel_alt"], fg=TEXT,
            selectbackground=PALETTE["primary"], selectforeground="#ffffff",
            highlightthickness=1, highlightbackground=PALETTE["border"],
            relief="flat", borderwidth=0,
            activestyle="none")
        self.class_listbox.pack(fill="both", expand=True)
        self.class_listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        # Listbox にフォーカスがあるかどうかを追跡
        self.class_listbox.bind("<FocusIn>", lambda e: self._set_listbox_active(True))
        self.class_listbox.bind("<FocusOut>", lambda e: self._set_listbox_active(False))
        self._listbox_active = False

        # ─ 中央 ─
        center = tk.Frame(main, bg=BG)
        center.pack(side="left", fill="both", expand=True, padx=10)

        self.name_var = tk.StringVar(value="左のクラス一覧から選んでください")
        tk.Label(center, textvariable=self.name_var,
                 bg=BG, fg=STRONG, font=("",16,"bold")
                ).pack(pady=(0,10))

        prev_panel = tk.Frame(center, bg=PANEL,
                             highlightthickness=1, highlightbackground=PALETTE["border"])
        prev_panel.pack()
        inner = tk.Frame(prev_panel, bg=PANEL, padx=14, pady=14)
        inner.pack()
        tk.Label(inner,
                 text="クロップ範囲（ゴールドの枠の中だけがポスターに使われます）",
                 bg=PANEL, fg=PALETTE["accent"], font=("",11,"bold")
                ).pack(pady=(0,8))
        tk.Label(inner,
                 text="✋ 枠をドラッグして移動できます",
                 bg=PANEL, fg=DIM, font=("",10)
                ).pack(pady=(0,6))
        self.prev_label = tk.Label(inner, bg=PALETTE["panel_alt"],
                                   width=self.PREVIEW_W, height=self.PREVIEW_H,
                                   cursor="hand2")
        self.prev_label.pack()
        # ドラッグイベント
        self.prev_label.bind("<Button-1>", self._on_drag_start)
        self.prev_label.bind("<B1-Motion>", self._on_drag_motion)
        self.prev_label.bind("<ButtonRelease-1>", self._on_drag_end)

        # スライダー
        sl_panel = tk.Frame(center, bg=PANEL, padx=20, pady=14,
                           highlightthickness=1, highlightbackground=PALETTE["border"])
        sl_panel.pack(fill="x", pady=(12,0))

        def _slider(parent, label, var, frm, to, resolution=1):
            row = tk.Frame(parent, bg=PANEL)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, bg=PANEL, fg=LABEL,
                     font=("",11,"bold"), width=22, anchor="w"
                    ).pack(side="left")
            scale = tk.Scale(row, from_=frm, to=to, resolution=resolution,
                             orient="horizontal", variable=var, length=380,
                             bg=PANEL, fg=STRONG,
                             troughcolor=PALETTE["panel_alt"],
                             highlightthickness=0, relief="flat",
                             activebackground=PALETTE["accent"],
                             showvalue=True, font=("",10,"bold"),
                             command=self._on_slide,
                             takefocus=0)
            scale.pack(side="left", fill="x", expand=True)
            return scale

        self.v_top  = tk.DoubleVar(value=0)
        self.v_left = tk.DoubleVar(value=0)
        self.v_zoom = tk.DoubleVar(value=1.0)
        _slider(sl_panel, "上下位置 (0=上端)",  self.v_top, 0, 100)
        _slider(sl_panel, "左右位置 (中央=0)",  self.v_left, -50, 50)
        _slider(sl_panel, "ズーム (1.0標準)",   self.v_zoom, 1.0, 3.0, 0.05)

        # 顔検出やり直しボタン
        rebtn = tk.Frame(center, bg=BG)
        rebtn.pack(pady=(10,0))
        tk.Button(rebtn, text="🔍 顔検出をやり直す",
                  font=("",11), bg=PALETTE["panel_alt"], fg=TEXT,
                  activebackground=PALETTE["accent_bg"], activeforeground=TEXT,
                  relief="flat", padx=16, pady=6, cursor="hand2",
                  command=self.reapply_auto_detect, takefocus=0,
                  highlightthickness=1, highlightbackground=PALETTE["border"]
                 ).pack()

        # 操作ボタン
        btn_panel = tk.Frame(center, bg=BG, pady=10)
        btn_panel.pack()
        def _btn(parent, text, color, cmd, w=10, fg="#ffffff"):
            return tk.Button(parent, text=text, font=("",12,"bold"),
                             bg=color, fg=fg,
                             activebackground=color, activeforeground=fg,
                             relief="flat", padx=14, pady=8, width=w,
                             cursor="hand2", command=cmd, takefocus=0)

        _btn(btn_panel, "[ 前", PALETTE["panel_alt"], self.prev_photo, w=6, fg=TEXT
            ).pack(side="left", padx=4)
        _btn(btn_panel, "✓ 保存 (S)", PALETTE["success"], self.save_current, w=12
            ).pack(side="left", padx=4)
        _btn(btn_panel, "リセット",   PALETTE["danger"],  self.reset_current, w=10
            ).pack(side="left", padx=4)
        _btn(btn_panel, "次 ]", PALETTE["panel_alt"], self.next_photo, w=6, fg=TEXT
            ).pack(side="left", padx=4)

        # ─ 右: ポスター見た目 + アクション ─
        right = tk.Frame(main, bg=PANEL, width=270,
                        highlightthickness=1, highlightbackground=PALETTE["border"])
        right.pack(side="left", fill="y", padx=(10,0))
        right.pack_propagate(False)

        tk.Label(right, text="ポスター上の見た目",
                 bg=PANEL, fg=PALETTE["accent"], font=("",11,"bold"),
                 anchor="w"
                ).pack(fill="x", padx=14, pady=(14,8))

        cell_h = int(self.POSTER_W / CELL_ASPECT) + 50
        self.poster_label = tk.Label(right, bg=PALETTE["panel_alt"],
                                     width=self.POSTER_W, height=cell_h)
        self.poster_label.pack(padx=14)

        tk.Label(right, text="ACTIONS", bg=PANEL, fg=DIM,
                 font=("",10,"bold"), anchor="w"
                ).pack(fill="x", padx=14, pady=(20,4))

        self.v_auto_pdf = tk.BooleanVar(value=False)
        tk.Checkbutton(right, text="保存時にPDF自動再生成",
                       variable=self.v_auto_pdf,
                       bg=PANEL, fg=TEXT, selectcolor=PALETTE["panel_alt"],
                       activebackground=PANEL, activeforeground=TEXT,
                       font=("",10,"bold"), anchor="w", highlightthickness=0,
                       takefocus=0
                      ).pack(fill="x", padx=14, pady=2, anchor="w")

        tk.Button(right, text="現クラスのPDF再生成",
                  font=("",11,"bold"), bg=PALETTE["primary"], fg="#ffffff",
                  activebackground=PALETTE["primary_dk"], activeforeground="#ffffff",
                  relief="flat", pady=8, cursor="hand2",
                  command=self.regen_current_class, takefocus=0
                 ).pack(fill="x", padx=14, pady=4)

        tk.Button(right, text="全クラスPDF再生成",
                  font=("",11,"bold"), bg=PALETTE["accent"], fg="#ffffff",
                  activebackground="#b87a1e", activeforeground="#ffffff",
                  relief="flat", pady=8, cursor="hand2",
                  command=self.regen_all, takefocus=0
                 ).pack(fill="x", padx=14, pady=4)

        # クラス全体プレビューを開くボタン
        tk.Button(right, text="🖼 クラス全員のプレビュー",
                  font=("",11,"bold"), bg=PALETTE["accent_bg"], fg=PALETTE["accent"],
                  activebackground=PALETTE["accent"], activeforeground="#ffffff",
                  relief="flat", pady=8, cursor="hand2",
                  command=self.show_class_overview, takefocus=0,
                  highlightthickness=1, highlightbackground=PALETTE["accent"]
                 ).pack(fill="x", padx=14, pady=(12,4))

        tk.Label(right, text="SHORTCUTS", bg=PANEL, fg=DIM,
                 font=("",10,"bold"), anchor="w"
                ).pack(fill="x", padx=14, pady=(20,4))
        sc = ("↑↓←→        枠を移動\n"
              "Shift+↑↓     ズーム\n"
              "[  ]          前 / 次の生徒\n"
              "S            保存→次へ\n"
              "R            リセット\n"
              "F            顔検出やり直し")
        tk.Label(right, text=sc, bg=PANEL, fg=LABEL,
                 font=("Menlo",10), justify="left", anchor="w"
                ).pack(fill="x", padx=14)

        tk.Label(right, text="クロップ枠を直接ドラッグでも移動可能",
                 bg=PANEL, fg=DIM, font=("",9), wraplength=240, justify="left"
                ).pack(fill="x", padx=14, pady=(8,14))

        # ステータスバー
        self.status_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.status_var,
                 bg=PALETTE["panel_alt"], fg=TEXT,
                 font=("",11,"bold"), anchor="w", padx=16, pady=6
                ).pack(fill="x", side="bottom")

    # ── フォーカス制御 ──
    def _set_listbox_active(self, active):
        self._listbox_active = active

    def _editor_focused(self):
        """Spinboxにフォーカスがあるときはショートカット抑制"""
        w = self.root.focus_get()
        if w in (self.sb_grade, self.sb_cls, self.sb_num):
            return False
        return True

    # ── キーボード ──
    def _bind_keys(self):
        r = self.root
        r.bind_all("<Left>",         self._key_left)
        r.bind_all("<Right>",        self._key_right)
        r.bind_all("<Up>",           self._key_up)
        r.bind_all("<Down>",         self._key_down)
        r.bind_all("<Shift-Up>",     self._key_shift_up)
        r.bind_all("<Shift-Down>",   self._key_shift_down)
        r.bind_all("<bracketleft>",  lambda e: (self.prev_photo(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<bracketright>", lambda e: (self.next_photo(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<s>",            lambda e: (self.save_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<S>",            lambda e: (self.save_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<r>",            lambda e: (self.reset_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<R>",            lambda e: (self.reset_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<f>",            lambda e: (self.reapply_auto_detect(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<F>",            lambda e: (self.reapply_auto_detect(), "break")[1] if self._editor_focused() else None)

    # 矢印キー：Listboxアクティブなら何もしない（Listboxの標準動作に任せる）
    def _key_left(self, e):
        if not self._editor_focused(): return
        if self._listbox_active: return
        self._step("left", -2); return "break"

    def _key_right(self, e):
        if not self._editor_focused(): return
        if self._listbox_active: return
        self._step("left", +2); return "break"

    def _key_up(self, e):
        if not self._editor_focused(): return
        if self._listbox_active: return
        self._step("top", -2); return "break"

    def _key_down(self, e):
        if not self._editor_focused(): return
        if self._listbox_active: return
        self._step("top", +2); return "break"

    def _key_shift_up(self, e):
        if not self._editor_focused(): return
        if self._listbox_active: return
        self._step("zoom", +0.1); return "break"

    def _key_shift_down(self, e):
        if not self._editor_focused(): return
        if self._listbox_active: return
        self._step("zoom", -0.1); return "break"

    def _step(self, key, delta):
        if key == "top":
            self.v_top.set(max(0, min(100, self.v_top.get()+delta)))
        elif key == "left":
            self.v_left.set(max(-50, min(50, self.v_left.get()+delta)))
        elif key == "zoom":
            self.v_zoom.set(max(1.0, min(3.0, round(self.v_zoom.get()+delta, 2))))
        self._update_preview()

    # ── マウスドラッグ ──
    def _on_drag_start(self, event):
        if self.current_img is None: return
        self._dragging = True
        self._drag_start = (event.x, event.y)
        self._drag_start_left = self.v_left.get()
        self._drag_start_top  = self.v_top.get()
        self.root.focus_set()  # Listboxフォーカスを外す

    def _on_drag_motion(self, event):
        if not self._dragging or self.current_img is None: return
        if self._drag_start is None: return
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        # プレビューサイズに対する移動量を、画像座標系の%に変換
        # PREVIEW幅に対する%が1単位（左右±50%）に相当
        delta_left = (dx / self.PREVIEW_W) * 100
        delta_top  = (dy / self.PREVIEW_H) * 100
        new_left = max(-50, min(50, self._drag_start_left + delta_left))
        new_top  = max(0, min(100, self._drag_start_top + delta_top))
        self.v_left.set(new_left)
        self.v_top.set(new_top)
        self._update_preview()

    def _on_drag_end(self, event):
        self._dragging = False
        self._drag_start = None

    # ── クラス一覧 ──
    def _refresh_class_list(self):
        self.class_listbox.delete(0, tk.END)
        counts = {}
        for (g,c,n) in self.overrides:
            counts[(g,c)] = counts.get((g,c), 0) + 1
        for g, c, _ in self.classes_list:
            n_done = counts.get((g,c), 0)
            mark = f"  ●{n_done}" if n_done else ""
            self.class_listbox.insert(tk.END, f"  {g}年 {c}組{mark}")

    def _on_listbox_select(self, event):
        sel = self.class_listbox.curselection()
        if not sel: return
        idx = sel[0]
        if idx >= len(self.classes_list): return
        g, c, _ = self.classes_list[idx]
        self.v_grade.set(str(g))
        self.v_cls.set(str(c))
        self.v_num.set("1")
        self.open_photo()
        self.root.focus_set()  # ★ フォーカスをrootに戻す

    # ── 写真ロード ──
    def open_photo(self):
        try:
            g = int(self.v_grade.get())
            c = int(self.v_cls.get())
            n = int(self.v_num.get())
        except:
            messagebox.showerror("エラー","学年・組・番号は数字で入力してください")
            return
        folder = find_class_folder(self.base, g, c)
        if not folder:
            messagebox.showerror("エラー", f"{g}年{c}組のフォルダが見つかりません")
            return
        self.photos     = collect_photos(folder, g, c)
        self.photo_nums = sorted(self.photos.keys())
        if not self.photo_nums:
            messagebox.showwarning("写真なし", f"{g}年{c}組に写真がありません")
            return
        self._load(g, c, n)
        self.root.focus_set()

    def _load(self, g, c, n):
        if n not in self.photos:
            self.status_var.set(f"⚠ {g}年{c}組 {n}番の写真が見つかりません")
            return
        self.current_key = (g, c, n)
        self.v_grade.set(str(g)); self.v_cls.set(str(c)); self.v_num.set(str(n))

        self.current_img = fix_exif(Image.open(self.photos[n]))
        self.auto_initial = auto_initial_crop_params(self.current_img)

        ov = self.overrides.get((g,c,n))
        if ov:
            self.v_top.set(float(ov.get('top_pct',  0)))
            self.v_left.set(float(ov.get('left_pct', 0)))
            self.v_zoom.set(float(ov.get('zoom',   1.0)))
        else:
            t, l, z = self.auto_initial
            self.v_top.set(t)
            self.v_left.set(l)
            self.v_zoom.set(z)

        name = self.roster_data.get((g,c), {}).get(n, f"{n}番")
        mark = "  ●調整済" if (g,c,n) in self.overrides else "  (自動)"
        self.name_var.set(f"{g}年 {c}組  {n:02d}番　{name}{mark}")

        self._update_preview()

        idx = self.photo_nums.index(n)+1 if n in self.photo_nums else "?"
        self.status_var.set(f"  {idx} / {len(self.photo_nums)} 人  ─  {Path(self.photos[n]).name}")

    def reapply_auto_detect(self):
        if self.current_img is None: return
        self.auto_initial = auto_initial_crop_params(self.current_img)
        t, l, z = self.auto_initial
        self.v_top.set(t)
        self.v_left.set(l)
        self.v_zoom.set(z)
        self._update_preview()
        self.status_var.set("  顔検出をやり直しました")
        self.root.focus_set()

    # ── スライダー連動 ──
    def _on_slide(self, val):
        if not self._update_pending:
            self._update_pending = True
            self.root.after_idle(self._do_update)

    def _do_update(self):
        self._update_pending = False
        self._update_preview()

    def _update_preview(self):
        if self.current_img is None: return
        top  = self.v_top.get()
        left = self.v_left.get()
        zoom = float(self.v_zoom.get())

        prev_img, _, _ = render_clipping_preview(
            self.current_img, top, left, zoom,
            max_w=self.PREVIEW_W, max_h=self.PREVIEW_H)
        self._prev_tk = ImageTk.PhotoImage(prev_img)
        self.prev_label.configure(image=self._prev_tk,
                                  width=prev_img.width, height=prev_img.height)

        if self.current_key:
            cropped = do_crop(self.current_img, top, left, zoom)
            g, c, n = self.current_key
            name = self.roster_data.get((g,c), {}).get(n, f"{n}番")
            cell = render_poster_cell(cropped, n, name, cell_w=self.POSTER_W)
            self._cell_tk = ImageTk.PhotoImage(cell)
            self.poster_label.configure(image=self._cell_tk,
                                        width=cell.width, height=cell.height)
            # サムネキャッシュ更新
            self.class_thumbnails[(g,c,n)] = cropped

    # ── 保存・リセット・移動 ──
    def save_current(self):
        if not self.current_key: return
        g, c, n = self.current_key
        self.overrides[(g,c,n)] = {
            'top_pct':  float(self.v_top.get()),
            'left_pct': float(self.v_left.get()),
            'zoom':     float(self.v_zoom.get()),
        }
        save_overrides(self.override_path, self.overrides)
        self.saved_var.set(f"調整済み {len(self.overrides)}件")
        self._refresh_class_list()
        self.status_var.set(f"  ✓ {g}年{c}組{n:02d}番 を保存しました")
        if self.v_auto_pdf.get():
            self.regen_current_class()
        self.next_photo()

    def reset_current(self):
        if not self.current_key: return
        g, c, n = self.current_key
        if (g,c,n) in self.overrides:
            del self.overrides[(g,c,n)]
            save_overrides(self.override_path, self.overrides)
            self.saved_var.set(f"調整済み {len(self.overrides)}件")
            self._refresh_class_list()
        t, l, z = self.auto_initial
        self.v_top.set(t)
        self.v_left.set(l)
        self.v_zoom.set(z)
        self._update_preview()
        self.status_var.set(f"  ↺ {g}年{c}組{n:02d}番 をリセット（自動検出値に戻しました）")

    def next_photo(self):
        if not self.current_key or not self.photo_nums: return
        g, c, n = self.current_key
        if n in self.photo_nums:
            idx = self.photo_nums.index(n)
            if idx < len(self.photo_nums)-1:
                self._load(g, c, self.photo_nums[idx+1])

    def prev_photo(self):
        if not self.current_key or not self.photo_nums: return
        g, c, n = self.current_key
        if n in self.photo_nums:
            idx = self.photo_nums.index(n)
            if idx > 0:
                self._load(g, c, self.photo_nums[idx-1])

    # ── クラス全体プレビュー ──
    def show_class_overview(self):
        """クラス全員のサムネ一覧を別ウィンドウで表示"""
        if not self.current_key:
            messagebox.showinfo("情報", "先に学年・組を選択してください")
            return
        g, c, _ = self.current_key

        # サブウィンドウ
        win = tk.Toplevel(self.root)
        win.title(f"{g}年{c}組 全員プレビュー")
        win.configure(bg=PALETTE["bg"])
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        ww = min(900, int(sw * 0.7))
        wh = min(700, int(sh * 0.7))
        win.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")

        # ヘッダー
        h = tk.Frame(win, bg=PALETTE["primary"], height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text=f"  {g}年 {c}組 全員プレビュー",
                bg=PALETTE["primary"], fg="#ffffff",
                font=("",14,"bold")).pack(side="left", padx=20, pady=10)

        loading = tk.Label(win, text="サムネ生成中... しばらくお待ちください",
                          bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                          font=("",13))
        loading.pack(pady=20)
        win.update_idletasks()

        def build():
            try:
                # 全員分のクロップ画像を生成
                items = []
                roster = self.roster_data.get((g,c), {})
                photos = collect_photos(find_class_folder(self.base, g, c), g, c)
                for num in sorted(photos.keys()):
                    name = roster.get(num, f"{num}番")
                    try:
                        pil = fix_exif(Image.open(photos[num]))
                        ov = self.overrides.get((g,c,num))
                        if ov:
                            t, l, z = ov['top_pct'], ov['left_pct'], ov['zoom']
                        else:
                            t, l, z = auto_initial_crop_params(pil)
                        cropped = do_crop(pil, t, l, z)
                        items.append((num, name, cropped))
                    except:
                        items.append((num, name, None))

                overview = render_class_overview(items, current_num=self.current_key[2],
                                                 max_w=ww-40, thumb_w=120)
                # 表示
                loading.destroy()
                self._overview_tk = ImageTk.PhotoImage(overview)
                lbl = tk.Label(win, image=self._overview_tk, bg=PALETTE["bg"])
                lbl.pack(padx=20, pady=10)
            except Exception as e:
                loading.config(text=f"エラー: {e}", fg=PALETTE["danger"])

        win.after(100, build)

    # ── PDF再生成 ──
    def regen_current_class(self):
        if not self.current_key: return
        g, c, _ = self.current_key
        self._run_poster(["--grade", str(g), "--cls", str(c)],
                         f"  ⏳ {g}年{c}組のPDF再生成中...")

    def regen_all(self):
        if not messagebox.askyesno("確認", "全クラスのPDFを再生成します。よろしいですか？"):
            return
        self._run_poster([], "  ⏳ 全クラスのPDF再生成中...")

    def _run_poster(self, extra_args, msg):
        self.status_var.set(msg)
        candidates = [
            os.path.join(self.base, "make_poster.py"),
            os.path.join(self.base, "make_poster_v8.py"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_poster.py"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_poster_v8.py"),
        ]
        script = next((p for p in candidates if os.path.exists(p)), None)
        if not script:
            messagebox.showerror("エラー",
                "make_poster.py が見つかりません。")
            return
        def worker():
            try:
                cmd = [sys.executable, script, "--base", self.base,
                       "--out", os.path.join(self.base, "output")] + extra_args
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if r.returncode == 0:
                    self.root.after(0, lambda: self.status_var.set("  ✓ PDF再生成完了"))
                else:
                    err = (r.stderr or r.stdout)[-400:]
                    self.root.after(0, lambda: messagebox.showerror(
                        "PDF生成エラー", f"エラー:\n{err}"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("実行エラー", str(e)))
        threading.Thread(target=worker, daemon=True).start()

# ════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base",      required=True)
    ap.add_argument("--overrides", default=None)
    args = ap.parse_args()

    override_path = args.overrides or os.path.join(args.base, "crop_check", "crop_overrides.csv")

    root = tk.Tk()
    app = CropAdjusterApp(root, args.base, override_path)
    root.mainloop()

if __name__ == "__main__":
    main()
