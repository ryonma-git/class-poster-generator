#!/usr/bin/env python3
"""
クロップ調整GUI v5
==================
変更点:
- 自動顔検出を初期値として反映（顔検出が成功していれば、その位置でプレビュー）
- 矢印キーがListboxに取られない（フォーカス制御）
- カラーコントラスト改善（薄色背景×白文字を全面廃止）
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
    """顔検出を複数パラメータで試みて最大の顔を返す。失敗時はNone"""
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
    """
    クロップ枠のピクセル座標を計算する。
    top_pct  : 0〜100 (枠上端の位置 / 画像高さ)
    left_pct : -50〜+50 (枠中心の横位置オフセット / 画像幅)
    zoom     : 1.0〜3.0
    """
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

# ════════════════════════════════════════════════════════
#  顔検出からクロップ初期値を計算
# ════════════════════════════════════════════════════════
def auto_initial_crop_params(pil_img):
    """
    顔検出を行い、それを元に初期クロップ値 (top_pct, left_pct, zoom) を返す。
    顔検出失敗時は安全なデフォルト（top=0%, left=0%, zoom=1.0）。
    """
    w, h = pil_img.size
    face = detect_face(pil_img)
    if face is None:
        return 0.0, 0.0, 1.0

    fx, fy, fw, fh = face
    face_cx = fx + fw / 2
    face_cy = fy + fh / 2

    # 顔の高さの2.0倍をクロップ高さの目安にする → 顔がフレームの上半分に来るサイズ
    desired_crop_h = fh * 2.0

    # ベースサイズ計算（zoom=1.0時）
    if w / h < CELL_ASPECT:
        base_h = w / CELL_ASPECT
    else:
        base_h = h
    # zoomを逆算
    zoom = base_h / desired_crop_h
    zoom = max(1.0, min(3.0, zoom))

    # 実際のクロップサイズ
    crop_h = base_h / zoom
    crop_w = crop_h * CELL_ASPECT

    # 顔の上端が枠の上から15%付近にくるよう top を計算
    desired_y1 = face_cy - crop_h * 0.40
    desired_y1 = max(0, min(desired_y1, h - crop_h))
    top_pct = (desired_y1 / h) * 100

    # 顔の中心 cx を枠の中心に持ってくるよう left を計算
    desired_cx = face_cx
    left_pct = ((desired_cx - w/2) / w) * 100
    # left_pct は -50 〜 +50 にクランプ（実際にはもっと狭い範囲に）
    left_pct = max(-50, min(50, left_pct))

    return float(top_pct), float(left_pct), float(zoom)

# ════════════════════════════════════════════════════════
#  プレビュー描画（イラレ風）
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

    GOLD = (232, 156, 42)
    rd.rectangle([bx1, by1, bx2-1, by2-1], outline=GOLD, width=3)

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
    return result

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

# ── overrides CSV ──
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
#  デザイン定数（コントラスト改善版）
# ════════════════════════════════════════════════════════
PALETTE = {
    "bg":          "#1a1d29",   # 全体背景（より深い濃紺）
    "panel":       "#252938",   # パネル背景
    "panel_alt":   "#2f3447",   # 副パネル
    "panel_input": "#3a3f55",   # 入力欄背景
    "text":        "#f0f2f8",   # 明るい白
    "text_strong": "#ffffff",   # 強調
    "text_dim":    "#b8bcd0",   # 落ち着いたラベル文字（コントラスト確保）
    "text_label":  "#dfe2ee",   # 一般的なラベル
    "accent":      "#F0A028",   # アクセント（明るめのゴールド）
    "primary":     "#5BA3D8",   # プライマリ（明るめのブルー）
    "primary_dk":  "#2E6FA8",
    "success":     "#3BCC79",   # 保存
    "danger":      "#E85D5D",   # リセット
    "border":      "#454a63",
}

# ════════════════════════════════════════════════════════
#  GUI
# ════════════════════════════════════════════════════════
class CropAdjusterApp:
    PREVIEW_W = 440
    PREVIEW_H = 580
    POSTER_W  = 240

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
        self.auto_initial     = (0.0, 0.0, 1.0)  # 自動検出された初期値

        self._update_pending = False
        self._slider_user_active = False

        root.title("クロップ調整ツール")
        root.configure(bg=PALETTE["bg"])
        self._setup_ttk_style()
        self._build_ui()
        self._bind_keys()
        self._refresh_class_list()

        # 起動時にメイン領域にフォーカス
        self.root.after(100, lambda: self.root.focus_set())

    def _setup_ttk_style(self):
        style = ttk.Style()
        try: style.theme_use('clam')
        except: pass

    def _build_ui(self):
        BG     = PALETTE["bg"]
        PANEL  = PALETTE["panel"]
        TEXT   = PALETTE["text"]
        STRONG = PALETTE["text_strong"]
        DIM    = PALETTE["text_dim"]
        LABEL  = PALETTE["text_label"]

        root = self.root

        # ─── ヘッダー ───
        header = tk.Frame(root, bg=PALETTE["primary_dk"], height=52)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="●  クロップ調整ツール",
                 bg=PALETTE["primary_dk"], fg=STRONG,
                 font=("",16,"bold")).pack(side="left", padx=20, pady=10)
        tk.Label(header, text="個人写真ポスター",
                 bg=PALETTE["primary_dk"], fg=PALETTE["accent"],
                 font=("",11,"bold")).pack(side="left", pady=10)

        # ─── 上部：入力エリア ───
        topbar = tk.Frame(root, bg=PANEL, height=58)
        topbar.pack(fill="x", padx=12, pady=(10,0))
        topbar.pack_propagate(False)

        def _label(parent, t):
            return tk.Label(parent, text=t, bg=PANEL, fg=LABEL, font=("",11,"bold"))

        _label(topbar, "学年").pack(side="left", padx=(20,4), pady=16)
        self.v_grade = tk.StringVar(value="1")
        self.sb_grade = tk.Spinbox(topbar, from_=1, to=6, width=4, textvariable=self.v_grade,
                   font=("",13), bg=PALETTE["panel_input"], fg=STRONG,
                   highlightthickness=0, relief="flat",
                   buttonbackground=PALETTE["panel_alt"])
        self.sb_grade.pack(side="left", padx=4, pady=16)

        _label(topbar, "組").pack(side="left", padx=(12,4), pady=16)
        self.v_cls = tk.StringVar(value="1")
        self.sb_cls = tk.Spinbox(topbar, from_=1, to=6, width=4, textvariable=self.v_cls,
                   font=("",13), bg=PALETTE["panel_input"], fg=STRONG,
                   highlightthickness=0, relief="flat")
        self.sb_cls.pack(side="left", padx=4, pady=16)

        _label(topbar, "番号").pack(side="left", padx=(12,4), pady=16)
        self.v_num = tk.StringVar(value="1")
        self.sb_num = tk.Spinbox(topbar, from_=1, to=40, width=4, textvariable=self.v_num,
                   font=("",13), bg=PALETTE["panel_input"], fg=STRONG,
                   highlightthickness=0, relief="flat")
        self.sb_num.pack(side="left", padx=4, pady=16)

        tk.Button(topbar, text="開く", font=("",12,"bold"),
                  bg=PALETTE["primary"], fg=STRONG,
                  activebackground=PALETTE["primary_dk"], activeforeground=STRONG,
                  relief="flat", padx=18, pady=4, cursor="hand2",
                  command=self.open_photo
                 ).pack(side="left", padx=(16,12), pady=12)

        self.saved_var = tk.StringVar(value=f"調整済み {len(self.overrides)}件")
        tk.Label(topbar, textvariable=self.saved_var,
                 bg=PALETTE["panel_alt"], fg=PALETTE["accent"],
                 font=("",11,"bold"), padx=14, pady=4
                ).pack(side="right", padx=20, pady=16)

        # ─── メイン3列 ───
        main = tk.Frame(root, bg=BG)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        # ─ 左: クラス一覧 ─
        left = tk.Frame(main, bg=PANEL, width=200)
        left.pack(side="left", fill="y", padx=(0,8)); left.pack_propagate(False)

        tk.Label(left, text="CLASSES", bg=PANEL, fg=DIM,
                 font=("",10,"bold"), anchor="w"
                ).pack(fill="x", padx=14, pady=(14,4))

        lf = tk.Frame(left, bg=PANEL)
        lf.pack(fill="both", expand=True, padx=8, pady=(0,12))
        self.class_listbox = tk.Listbox(
            lf, font=("",12), height=22,
            bg=PALETTE["panel_alt"], fg=TEXT,
            selectbackground=PALETTE["primary"], selectforeground=STRONG,
            highlightthickness=0, relief="flat", borderwidth=0,
            activestyle="none", takefocus=0)  # ★ takefocus=0 で矢印キーを取られないように
        self.class_listbox.pack(fill="both", expand=True)
        self.class_listbox.bind("<<ListboxSelect>>", self._on_listbox_select)

        # ─ 中央: イラレ風プレビュー ─
        center = tk.Frame(main, bg=BG)
        center.pack(side="left", fill="both", expand=True, padx=8)

        self.name_var = tk.StringVar(value="左のクラス一覧から選んでください")
        tk.Label(center, textvariable=self.name_var,
                 bg=BG, fg=STRONG, font=("",16,"bold")
                ).pack(pady=(0,10))

        prev_panel = tk.Frame(center, bg=PANEL, padx=14, pady=14)
        prev_panel.pack()
        tk.Label(prev_panel,
                 text="クロップ範囲（ゴールドの枠の中だけがポスターに使われます）",
                 bg=PANEL, fg=PALETTE["accent"], font=("",11,"bold")
                ).pack(pady=(0,8))
        self.prev_label = tk.Label(prev_panel, bg=PALETTE["panel_alt"],
                                   width=self.PREVIEW_W, height=self.PREVIEW_H)
        self.prev_label.pack()

        # スライダー
        sl_panel = tk.Frame(center, bg=PANEL, padx=20, pady=12)
        sl_panel.pack(fill="x", pady=(12,0))

        def _slider(parent, label, var, frm, to, resolution=1):
            row = tk.Frame(parent, bg=PANEL)
            row.pack(fill="x", pady=3)
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
                             takefocus=0)  # ★
            scale.pack(side="left", fill="x", expand=True)
            return scale

        self.v_top  = tk.DoubleVar(value=0)
        self.v_left = tk.DoubleVar(value=0)
        self.v_zoom = tk.DoubleVar(value=1.0)
        _slider(sl_panel, "上下位置 (0=上端)",  self.v_top, 0, 100)
        _slider(sl_panel, "左右位置 (中央=0)",  self.v_left, -50, 50)
        _slider(sl_panel, "ズーム (1.0標準)",   self.v_zoom, 1.0, 3.0, 0.05)

        # 自動検出を再適用するボタン
        rebtn = tk.Frame(center, bg=BG)
        rebtn.pack(pady=(8,0))
        tk.Button(rebtn, text="🔍 顔検出をやり直す",
                  font=("",11), bg=PALETTE["panel_alt"], fg=STRONG,
                  activebackground=PALETTE["panel"], activeforeground=STRONG,
                  relief="flat", padx=16, pady=6, cursor="hand2",
                  command=self.reapply_auto_detect, takefocus=0
                 ).pack()

        # ボタン群
        btn_panel = tk.Frame(center, bg=BG, pady=10)
        btn_panel.pack()
        def _btn(parent, text, color, cmd, w=10, fg=STRONG):
            return tk.Button(parent, text=text, font=("",12,"bold"),
                             bg=color, fg=fg,
                             activebackground=color, activeforeground=fg,
                             relief="flat", padx=14, pady=8, width=w,
                             cursor="hand2", command=cmd, takefocus=0)

        _btn(btn_panel, "[ 前", PALETTE["panel_alt"], self.prev_photo, w=6
            ).pack(side="left", padx=4)
        _btn(btn_panel, "✓ 保存 (S)", PALETTE["success"], self.save_current, w=12,
             fg="#0a2d18").pack(side="left", padx=4)
        _btn(btn_panel, "リセット",   PALETTE["danger"],  self.reset_current, w=10
            ).pack(side="left", padx=4)
        _btn(btn_panel, "次 ]", PALETTE["panel_alt"], self.next_photo, w=6
            ).pack(side="left", padx=4)

        # ─ 右: ポスター見た目 + 一括操作 ─
        right = tk.Frame(main, bg=PANEL, width=300)
        right.pack(side="left", fill="y", padx=(8,0)); right.pack_propagate(False)

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
                  font=("",11,"bold"), bg=PALETTE["primary"], fg=STRONG,
                  activebackground=PALETTE["primary_dk"], activeforeground=STRONG,
                  relief="flat", pady=8, cursor="hand2",
                  command=self.regen_current_class, takefocus=0
                 ).pack(fill="x", padx=14, pady=4)

        tk.Button(right, text="全クラスPDF再生成",
                  font=("",11,"bold"), bg=PALETTE["accent"], fg="#1a1d29",
                  activebackground="#d68a1e", activeforeground="#1a1d29",
                  relief="flat", pady=8, cursor="hand2",
                  command=self.regen_all, takefocus=0
                 ).pack(fill="x", padx=14, pady=4)

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
                 font=("Menlo",10,"bold"), justify="left", anchor="w"
                ).pack(fill="x", padx=14)

        # ─── ステータスバー ───
        self.status_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.status_var,
                 bg=PALETTE["panel_alt"], fg=STRONG,
                 font=("",11,"bold"), anchor="w", padx=16, pady=6
                ).pack(fill="x", side="bottom")

    # ── キーボード（rootバインド + フォーカス制御）─────
    def _bind_keys(self):
        # bind_allを使うとListboxがフォーカスを持っていてもroot側で先に処理できる
        r = self.root
        r.bind_all("<Left>",         self._key_left)
        r.bind_all("<Right>",        self._key_right)
        r.bind_all("<Up>",           self._key_up)
        r.bind_all("<Down>",         self._key_down)
        r.bind_all("<Shift-Up>",     self._key_shift_up)
        r.bind_all("<Shift-Down>",   self._key_shift_down)
        r.bind_all("<bracketleft>",  lambda e: self.prev_photo() or "break")
        r.bind_all("<bracketright>", lambda e: self.next_photo() or "break")
        r.bind_all("<s>",            lambda e: (self.save_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<S>",            lambda e: (self.save_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<r>",            lambda e: (self.reset_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<R>",            lambda e: (self.reset_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<f>",            lambda e: (self.reapply_auto_detect(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<F>",            lambda e: (self.reapply_auto_detect(), "break")[1] if self._editor_focused() else None)

    def _editor_focused(self):
        """Spinboxやエントリにフォーカスがあるときはショートカットを抑制"""
        w = self.root.focus_get()
        if w in (self.sb_grade, self.sb_cls, self.sb_num):
            return False
        return True

    # 矢印キー処理 — Spinboxにフォーカスがあるときだけ通常動作
    def _key_left(self, e):
        if not self._editor_focused(): return
        self._step("left", -2)
        return "break"   # ★ Listboxへの伝播を止める

    def _key_right(self, e):
        if not self._editor_focused(): return
        self._step("left", +2)
        return "break"

    def _key_up(self, e):
        if not self._editor_focused(): return
        self._step("top", -2)
        return "break"

    def _key_down(self, e):
        if not self._editor_focused(): return
        self._step("top", +2)
        return "break"

    def _key_shift_up(self, e):
        if not self._editor_focused(): return
        self._step("zoom", +0.1)
        return "break"

    def _key_shift_down(self, e):
        if not self._editor_focused(): return
        self._step("zoom", -0.1)
        return "break"

    def _step(self, key, delta):
        if key == "top":
            self.v_top.set(max(0, min(100, self.v_top.get()+delta)))
        elif key == "left":
            self.v_left.set(max(-50, min(50, self.v_left.get()+delta)))
        elif key == "zoom":
            self.v_zoom.set(max(1.0, min(3.0, round(self.v_zoom.get()+delta, 2))))
        self._update_preview()

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
        # フォーカスをrootに戻す（矢印キー操作のため）
        self.root.focus_set()

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
        # フォーカスをrootに戻す
        self.root.focus_set()

    def _load(self, g, c, n):
        if n not in self.photos:
            self.status_var.set(f"⚠ {g}年{c}組 {n}番の写真が見つかりません")
            return
        self.current_key = (g, c, n)
        self.v_grade.set(str(g)); self.v_cls.set(str(c)); self.v_num.set(str(n))

        self.current_img = fix_exif(Image.open(self.photos[n]))

        # ★ 自動顔検出による初期値計算
        self.auto_initial = auto_initial_crop_params(self.current_img)

        # 既存の調整済み値があれば優先、なければ自動値
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

        # 名前
        name = self.roster_data.get((g,c), {}).get(n, f"{n}番")
        mark = "  ●調整済" if (g,c,n) in self.overrides else "  (自動)"
        self.name_var.set(f"{g}年 {c}組  {n:02d}番　{name}{mark}")

        self._update_preview()

        idx = self.photo_nums.index(n)+1 if n in self.photo_nums else "?"
        self.status_var.set(f"  {idx} / {len(self.photo_nums)} 人  ─  {Path(self.photos[n]).name}")

    def reapply_auto_detect(self):
        """顔検出をやり直して初期値を再適用"""
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

        prev_img = render_clipping_preview(
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
        """自動検出値に戻す"""
        if not self.current_key: return
        g, c, n = self.current_key
        if (g,c,n) in self.overrides:
            del self.overrides[(g,c,n)]
            save_overrides(self.override_path, self.overrides)
            self.saved_var.set(f"調整済み {len(self.overrides)}件")
            self._refresh_class_list()
        # 自動値に戻す
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
        # スクリプト名を make_poster.py / make_poster_v8.py の両方で探す
        candidates = [
            os.path.join(self.base, "make_poster.py"),
            os.path.join(self.base, "make_poster_v8.py"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_poster.py"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_poster_v8.py"),
        ]
        script = next((p for p in candidates if os.path.exists(p)), None)
        if not script:
            messagebox.showerror("エラー",
                "make_poster.py が見つかりません。\n"
                "写真フォルダまたはスクリプトと同じ場所に配置してください。")
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
    ap.add_argument("--overrides", default=None,
                    help="overrides CSV のパス（省略時は base/crop_check/crop_overrides.csv）")
    args = ap.parse_args()

    override_path = args.overrides or os.path.join(args.base, "crop_check", "crop_overrides.csv")

    root = tk.Tk()
    root.geometry("1280x920")
    root.minsize(1200, 880)
    app = CropAdjusterApp(root, args.base, override_path)
    root.mainloop()

if __name__ == "__main__":
    main()
