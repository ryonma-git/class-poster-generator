#!/usr/bin/env python3
"""
クロップ調整GUI v7
==================
変更点 (v7):
- macOSのtk.Button色問題を解決（カスタムMacButton）
- スクロールイベントの完全対応（macトラックパッド対応）
- クラス全員プレビューをスクロール可能に
- ズーム上限 3.0 → 5.0
- [/] キーで前/次に移動するときに変更を自動保存
- ⌘+ / ⌘- / ⌘0 でメイン画面を拡大/縮小/リセット
- Appleライクデザイン（SF Pro Display, フラット, 余白広め）
"""

import os, glob, re, csv, argparse, subprocess, threading, sys, platform, shutil
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

# CustomTkinter（モダンスクロール対応）
try:
    import customtkinter as ctk
    HAS_CTK = True
    ctk.set_appearance_mode("light")
except ImportError:
    HAS_CTK = False
    ctk = None
    print("⚠ customtkinter が未インストールです。pip install customtkinter を実行してください")
from PIL import Image, ImageTk, ImageDraw, ImageFont
import numpy as np
import cv2

IS_MAC = platform.system() == "Darwin"

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

# システムフォント (Tk用)
def system_font_family():
    if IS_MAC:
        return "Hiragino Sans"
    return ""

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
#  プロキシ（編集用の縮小画像）
# ════════════════════════════════════════════════════════
# 元写真は4000px超で重い。クロップ値は%指定で解像度非依存なので、
# 編集・プレビュー・顔検出は縮小プロキシで行い、最終出力のみ実写真を使う。
PROXY_MAX = 1500  # 長辺の最大px

def make_proxy(img, max_dim=PROXY_MAX):
    """長辺が max_dim を超える画像を縮小して返す。小さい画像はそのまま。"""
    w, h = img.size
    long_side = max(w, h)
    if long_side <= max_dim:
        return img.convert("RGB") if img.mode != "RGB" else img
    s = max_dim / long_side
    return img.resize((max(1, int(w*s)), max(1, int(h*s))), Image.LANCZOS).convert("RGB")

# ════════════════════════════════════════════════════════
#  顔検出
# ════════════════════════════════════════════════════════
_cascade = None
_cascade_ok = None   # None=未確認 / True=正常 / False=利用不可
def detect_face(pil_img):
    """顔検出。cascade XML が見つからない場合は None を返してフォールバック。"""
    global _cascade, _cascade_ok
    if _cascade_ok is None:
        try:
            path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            clf = cv2.CascadeClassifier(path)
            if clf.empty():
                _cascade_ok = False   # XML が存在しない / 読み込み失敗
            else:
                _cascade = clf
                _cascade_ok = True
        except Exception:
            _cascade_ok = False
    if not _cascade_ok:
        return None   # 顔検出なし → auto_initial_crop_params がデフォルト値を使う
    try:
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
    except Exception:
        pass
    return None

# ════════════════════════════════════════════════════════
#  クロップ計算
# ════════════════════════════════════════════════════════
CELL_ASPECT = 1.02  # PDFの実際の写真エリア比率（A2+6×7のデフォルトケース）

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
    w, h = pil_img.size
    face = detect_face(pil_img)
    if face is None:
        return 0.0, 0.0, 1.0
    fx, fy, fw, fh = face
    face_cx = fx + fw / 2
    face_top = fy
    if w / h < CELL_ASPECT:
        base_h = w / CELL_ASPECT
    else:
        base_h = h
    head_margin = fh * 0.4  # 頭上の余白（顔の40%）
    desired_crop_h = fh * 2.2  # 顔の高さの2.2倍（アップ寄り）
    zoom = base_h / desired_crop_h
    zoom = max(1.0, min(5.0, zoom))
    crop_h_actual = base_h / zoom
    desired_y1 = max(0, face_top - head_margin)
    desired_y1 = min(desired_y1, h - crop_h_actual)
    top_pct = (desired_y1 / h) * 100
    left_pct = ((face_cx - w/2) / w) * 100
    left_pct = max(-50, min(50, left_pct))
    return float(top_pct), float(left_pct), float(zoom)

# ════════════════════════════════════════════════════════
#  プレビュー描画
# ════════════════════════════════════════════════════════
def prepare_preview_base(pil_img, max_w=420, max_h=560):
    """重いリサイズ処理。写真ロード時に1回だけ実行してキャッシュする。
    戻り値を render_clipping_overlay に渡す。"""
    iw, ih = pil_img.size
    scale = min(max_w/iw, max_h/ih)
    dw, dh = int(iw*scale), int(ih*scale)
    base_rgba = pil_img.resize((dw, dh), Image.LANCZOS).convert("RGBA")
    return {"base_rgba": base_rgba, "scale": scale,
            "iw": iw, "ih": ih, "dw": dw, "dh": dh}

def render_clipping_overlay(pb, top_pct, left_pct, zoom, px_scale=1.0):
    """キャッシュ済み基準画像(pb)にクロップ枠オーバーレイを描く軽い処理。
    スライダー操作のたびに呼ばれる。px_scale は実写真px換算用の係数。"""
    scale = pb["scale"]; iw = pb["iw"]; ih = pb["ih"]
    dw = pb["dw"]; dh = pb["dh"]
    x1, y1, x2, y2 = calc_crop_box(iw, ih, top_pct, left_pct, zoom)
    bx1, by1 = int(x1*scale), int(y1*scale)
    bx2, by2 = int(x2*scale), int(y2*scale)
    overlay = Image.new("RGBA", (dw, dh), (10, 14, 28, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0,0,dw,dh], fill=(10,14,28,150))
    od.rectangle([bx1, by1, bx2, by2], fill=(0,0,0,0))
    result = Image.alpha_composite(pb["base_rgba"], overlay).convert("RGB")
    rd = ImageDraw.Draw(result)
    GOLD = (245, 175, 60)
    rd.rectangle([bx1, by1, bx2-1, by2-1], outline=GOLD, width=3)
    # 角ハンドル（クリック可能領域として大きめに描画）
    H = 16
    for cx, cy in [(bx1, by1), (bx2-1, by1), (bx1, by2-1), (bx2-1, by2-1)]:
        rd.ellipse([cx-H//2, cy-H//2, cx+H//2, cy+H//2],
                   fill=(255,255,255), outline=GOLD, width=3)
    # クロップサイズは実写真の解像度で表示（px_scale で換算）
    real_w = int((x2-x1) * px_scale); real_h = int((y2-y1) * px_scale)
    info = f"crop: {real_w}×{real_h} px"
    f = get_pil_font(13)
    bb = rd.textbbox((0,0), info, font=f)
    rd.rectangle([6, 6, bb[2]+18, bb[3]+14], fill=(0,0,0,180))
    rd.text((12, 10), info, font=f, fill=(255,255,255))
    corners = {
        "tl": (bx1, by1), "tr": (bx2-1, by1),
        "bl": (bx1, by2-1), "br": (bx2-1, by2-1)
    }
    return result, scale, (bx1, by1, bx2, by2), corners

# 後方互換：一括描画版（バッチエディタ等から使用）
def render_clipping_preview(pil_img, top_pct, left_pct, zoom, max_w=420, max_h=560):
    pb = prepare_preview_base(pil_img, max_w, max_h)
    return render_clipping_overlay(pb, top_pct, left_pct, zoom)

# ── ポスターセル ──
C_CARD    = (0xF7, 0xF9, 0xFC)
C_LBL_BG  = (0x2B, 0x5F, 0x8E)
C_LBL_FG  = (0xFF, 0xFF, 0xFF)
C_NUM_FG  = (0xE8, 0x9C, 0x2A)
C_ACCENT  = (0xE8, 0x9C, 0x2A)

def render_poster_cell(cropped_img, num, name, cell_w=240):
    # PDFと同じ比率：写真ほぼ正方形（cw:photo_h ≈ 1.02）+ ラベル下
    photo_h = int(cell_w / 1.02)
    label_h = int(cell_w * 0.19)
    cell_h = photo_h + label_h
    R = 14
    cell = Image.new("RGBA", (cell_w, cell_h), (0,0,0,0))
    bg = Image.new("RGBA", (cell_w, cell_h), C_CARD + (255,))
    mask = Image.new("L", (cell_w, cell_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,cell_w-1,cell_h-1], radius=R, fill=255)
    cell.paste(bg, mask=mask)
    photo = cropped_img.resize((cell_w, photo_h), Image.LANCZOS).convert("RGBA")
    pmask = Image.new("L", (cell_w, photo_h), 0)
    pd_ = ImageDraw.Draw(pmask)
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
    pad = int(cell_w * 0.05); cy = label_h // 2
    num_str = f"{num:02d}"
    f_num = get_pil_font(int(label_h * 0.34))
    nb = ld.textbbox((0,0), num_str, font=f_num); nw = nb[2] - nb[0]
    ld.text((pad, cy), num_str, font=f_num, fill=C_NUM_FG+(255,), anchor="lm")
    avail = cell_w - nw - pad*3
    f_nm = get_pil_font(int(label_h * 0.55))
    while True:
        bb = ld.textbbox((0,0), name, font=f_nm)
        if bb[2]-bb[0] <= avail or f_nm.size <= 14: break
        f_nm = get_pil_font(f_nm.size - 2)
    ld.text((pad+nw+pad, cy), name, font=f_nm, fill=C_LBL_FG+(255,), anchor="lm")
    cell.paste(lbl_a, (0, photo_h), lbl_a)
    ImageDraw.Draw(cell).line([(0,photo_h),(cell_w,photo_h)], fill=C_ACCENT+(220,), width=3)
    return cell

# ── 個別IDカード画像（顔写真＋学年組番号＋漢字名＋ふりがな）──
def render_id_card(cropped_img, grade, cls, num, kanji, kana, card_w=640):
    """1人分の顔写真カードを生成。行方不明児童の捜索などに使う。
    cropped_img は実写真からクロップ済みの高解像度画像を渡す。"""
    margin = int(card_w * 0.04)
    photo_w = card_w - margin * 2
    photo_h = int(photo_w / CELL_ASPECT)
    info_h = int(card_w * 0.30)
    card_h = margin + photo_h + info_h + margin
    # 背景（白カード＋薄い枠）
    card = Image.new("RGB", (card_w, card_h), (255, 255, 255))
    cd = ImageDraw.Draw(card)
    cd.rectangle([0, 0, card_w-1, card_h-1], outline=(210, 216, 226), width=2)
    # 顔写真
    photo = cropped_img.resize((photo_w, photo_h), Image.LANCZOS).convert("RGB")
    card.paste(photo, (margin, margin))
    cd.rectangle([margin, margin, margin+photo_w-1, margin+photo_h-1],
                 outline=(180, 188, 200), width=1)
    # 情報エリア
    ix = margin
    iy = margin + photo_h + int(info_h * 0.10)
    # 学年組番号（アクセント色）
    f_meta = get_pil_font(int(info_h * 0.26))
    meta = f"{grade}年 {cls}組  {num}番"
    cd.text((ix, iy), meta, font=f_meta, fill=C_LBL_BG)
    # ふりがな（小）
    iy2 = iy + int(info_h * 0.30)
    if kana:
        f_kana = get_pil_font(int(info_h * 0.20))
        cd.text((ix, iy2), kana, font=f_kana, fill=(110, 120, 135))
    # 漢字名（大）
    iy3 = iy2 + int(info_h * 0.22)
    kanji_disp = kanji or f"{num}番"
    f_name = get_pil_font(int(info_h * 0.34))
    # はみ出すなら縮小
    avail = card_w - margin * 2
    while True:
        bb = cd.textbbox((0, 0), kanji_disp, font=f_name)
        if bb[2]-bb[0] <= avail or f_name.size <= 16:
            break
        f_name = get_pil_font(f_name.size - 2)
    cd.text((ix, iy3), kanji_disp, font=f_name, fill=(30, 36, 46))
    return card

# ── クラス全員サムネ ──
def render_class_overview(class_items, current_num=None, max_w=560, thumb_w=110):
    if not class_items:
        img = Image.new("RGB", (max_w, 100), (240, 235, 250))
        d = ImageDraw.Draw(img)
        f = get_pil_font(14)
        d.text((max_w//2, 50), "サムネ生成中...", font=f, fill=(120, 120, 140), anchor="mm")
        return img
    cols = 6
    rows = (len(class_items) + cols - 1) // cols
    pad = 10
    label_h = 26
    thumb_h = int(thumb_w / CELL_ASPECT)
    cell_w_total = thumb_w + pad
    cell_h_total = thumb_h + label_h + pad
    canvas_w = cols * cell_w_total + pad
    canvas_h = rows * cell_h_total + pad
    img = Image.new("RGB", (canvas_w, canvas_h), (250, 248, 244))
    d = ImageDraw.Draw(img)
    for idx, (num, name, cropped) in enumerate(class_items):
        col = idx % cols; row = idx // cols
        x = pad + col * cell_w_total
        y = pad + row * cell_h_total
        is_current = (num == current_num)
        bg_col = (255, 245, 215) if is_current else (255, 255, 255)
        border_col = (245, 175, 60) if is_current else (220, 215, 230)
        d.rounded_rectangle([x, y, x+thumb_w, y+thumb_h+label_h],
                           radius=8, fill=bg_col,
                           outline=border_col, width=2 if is_current else 1)
        if cropped is not None:
            try:
                t = cropped.resize((thumb_w-4, thumb_h-4), Image.LANCZOS)
                mask = Image.new("L", t.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle(
                    [0, 0, t.size[0]-1, t.size[1]-1], radius=6, fill=255)
                t.putalpha(mask)
                img.paste(t.convert("RGB"), (x+2, y+2), mask)
            except: pass
        f_num = get_pil_font(11); f_nm = get_pil_font(11)
        d.text((x+6, y+thumb_h+5), f"{num:02d}", font=f_num, fill=(232, 156, 42))
        short_name = name if len(name) <= 8 else name[:7] + "…"
        d.text((x+thumb_w-6, y+thumb_h+5), short_name,
               font=f_nm, fill=(50, 50, 70), anchor="ra")
    return img

# ── クラス顔写真一覧シート（名簿風・名前/ふりがな付き、出力用）──
def render_roster_sheet(grade, cls, items, cols=6, thumb_w=180):
    """クラス全員を1枚にまとめた一覧シートを生成。
    items: [(num, kanji, kana, cropped_img_or_None), ...]
    名簿・連絡網・行方不明時の確認などに使える高解像度シート。"""
    pad = 16
    title_h = 70
    thumb_h = int(thumb_w / CELL_ASPECT)
    name_h = 56
    cell_w = thumb_w + pad
    cell_h = thumb_h + name_h + pad
    rows = max(1, (len(items) + cols - 1) // cols)
    canvas_w = cols * cell_w + pad
    canvas_h = title_h + rows * cell_h + pad
    img = Image.new("RGB", (canvas_w, canvas_h), (248, 249, 251))
    d = ImageDraw.Draw(img)
    # タイトル帯
    d.rectangle([0, 0, canvas_w, title_h], fill=C_LBL_BG)
    f_title = get_pil_font(30)
    d.text((pad+6, title_h//2), f"{grade}年 {cls}組  顔写真一覧",
           font=f_title, fill=(255, 255, 255), anchor="lm")
    f_cnt = get_pil_font(16)
    d.text((canvas_w-pad-6, title_h//2), f"{len(items)}名",
           font=f_cnt, fill=(210, 224, 240), anchor="rm")
    for idx, (num, kanji, kana, cropped) in enumerate(items):
        col = idx % cols; row = idx // cols
        x = pad + col * cell_w
        y = title_h + pad + row * cell_h
        d.rounded_rectangle([x, y, x+thumb_w, y+thumb_h+name_h],
                            radius=10, fill=(255, 255, 255),
                            outline=(220, 226, 236), width=1)
        if cropped is not None:
            try:
                t = cropped.resize((thumb_w-6, thumb_h-6), Image.LANCZOS)
                img.paste(t.convert("RGB"), (x+3, y+3))
            except Exception:
                pass
        # 番号バッジ
        f_num = get_pil_font(18)
        d.text((x+8, y+thumb_h+6), f"{num:02d}", font=f_num, fill=C_NUM_FG)
        # 漢字名
        f_nm = get_pil_font(17)
        kanji_disp = kanji or f"{num}番"
        avail = thumb_w - 10
        while True:
            bb = d.textbbox((0,0), kanji_disp, font=f_nm)
            if bb[2]-bb[0] <= avail or f_nm.size <= 11:
                break
            f_nm = get_pil_font(f_nm.size - 1)
        d.text((x+thumb_w-8, y+thumb_h+8), kanji_disp,
               font=f_nm, fill=(30, 36, 46), anchor="ra")
        # ふりがな
        if kana:
            f_kn = get_pil_font(11)
            kana_disp = kana if len(kana) <= 14 else kana[:13]+"…"
            d.text((x+thumb_w-8, y+thumb_h+32), kana_disp,
                   font=f_kn, fill=(120, 130, 145), anchor="ra")
    return img

# ════════════════════════════════════════════════════════
#  名簿・写真関連
# ════════════════════════════════════════════════════════
def collect_photos(folder, grade, cls):
    """フォルダ内の写真を収集。JPG/JPEG/PNG を HEIC より優先する"""
    prefix = f"{grade}{cls}"
    if not folder or not os.path.isdir(folder):
        return {}
    # 拡張子の優先度（小さいほど優先）
    priority = {'.jpg': 0, '.jpeg': 0, '.png': 1, '.heic': 2}
    # num -> (priority, path)
    candidates = {}
    for fname in os.listdir(folder):
        full = os.path.join(folder, fname)
        if not os.path.isfile(full):
            continue
        stem, ext = os.path.splitext(fname)
        ext_lower = ext.lower()
        if ext_lower not in priority:
            continue
        if not stem.startswith(prefix):
            continue
        try:
            num = int(stem[len(prefix):])
        except (ValueError, TypeError):
            continue
        p = priority[ext_lower]
        # 既存より優先度の高い（数値の小さい）拡張子なら上書き
        if num not in candidates or p < candidates[num][0]:
            candidates[num] = (p, full)
    return {num: path for num, (_, path) in candidates.items()}

def find_class_folder(base, grade, cls):
    """{grade}年{cls}組のフォルダを探す。複数候補があれば写真がある方を優先"""
    candidates = []
    for root, dirs, files in os.walk(base):
        name = Path(root).name
        # 「N年M組」形式
        m = re.search(r'(\d+)\s*年\s*(\d+)\s*組', name)
        if m and int(m.group(1))==grade and int(m.group(2))==cls:
            candidates.append(root)
            continue
        # 「M組」のみ（親が「N年」）
        m2 = re.search(r'(\d+)\s*組', name)
        if m2 and int(m2.group(1))==cls:
            parent = str(Path(root).parent)
            if re.search(rf'{grade}\s*年', parent):
                candidates.append(root)
    # 写真があるフォルダを優先
    for c in candidates:
        if collect_photos(c, grade, cls):
            return c
    # なければ最初の候補
    return candidates[0] if candidates else None

def find_all_classes(base):
    results = []
    for root, dirs, files in os.walk(base):
        if not any(f.lower().endswith(('.jpg','.jpeg','.png','.heic')) for f in files):
            continue
        parts = Path(os.path.relpath(root, base)).parts
        last = parts[-1]
        m = re.search(r'(\d+)\s*年\s*(\d+)\s*組', last)
        if m:
            results.append((int(m.group(1)), int(m.group(2)), root)); continue
        m = re.search(r'(\d+)\s*組', last)
        if m:
            for part in reversed(parts[:-1]):
                m2 = re.search(r'(\d+)\s*年', part)
                if m2:
                    results.append((int(m2.group(1)), int(m.group(1)), root)); break
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
    sub["組"] = sub["組"].astype(int)
    sub["番号"] = sub["番号"].astype(int)
    sub["氏名"] = sub["氏名"].fillna("").astype(str).str.strip()
    result = {}
    for _, row in sub.iterrows():
        result.setdefault((row["学年"], row["組"]), {})[row["番号"]] = row["氏名"]
    return result

def load_full_roster(path):
    """漢字名・ふりがな両方を読み込む（検索・画像出力用）。
    戻り値: {(学年,組): {番号: {"kanji": 漢字名, "kana": ふりがな}}}
    col16=名前(漢字), col17=ふりがな"""
    import pandas as pd
    try:
        ext = Path(path).suffix.lower()
        if ext == '.xls':
            import xlrd
            wb = xlrd.open_workbook(path)
            ws = wb.sheet_by_index(0)
            rows = [ws.row_values(i) for i in range(ws.nrows)]
            df = pd.DataFrame(rows[1:], columns=rows[0])
        else:
            df = pd.read_excel(path, header=0)
        sub = df.iloc[:, [2, 3, 4, 16, 17]].copy()
        sub.columns = ["学年", "組", "番号", "漢字", "かな"]
        sub = sub.dropna(subset=["学年", "組", "番号"])
        sub["学年"] = sub["学年"].astype(int)
        sub["組"] = sub["組"].astype(int)
        sub["番号"] = sub["番号"].astype(int)
        # 全角スペースを半角に統一して見やすく
        sub["漢字"] = sub["漢字"].fillna("").astype(str).str.strip().str.replace("　", " ")
        sub["かな"] = sub["かな"].fillna("").astype(str).str.strip().str.replace("　", " ")
        result = {}
        for _, row in sub.iterrows():
            result.setdefault((row["学年"], row["組"]), {})[row["番号"]] = {
                "kanji": row["漢字"], "kana": row["かな"]}
        return result
    except Exception:
        return {}

def find_roster_file(base):
    candidates = [f for f in
        glob.glob(os.path.join(base, "*.xls")) +
        glob.glob(os.path.join(base, "*.xlsx"))
        if not Path(f).name.startswith(("~$", ".", "_"))]
    return candidates[0] if len(candidates) == 1 else None

def load_overrides(path):
    d = {}
    if not os.path.exists(path): return d
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            try:
                k = (int(row['grade']), int(row['cls']), int(row['num']))
                d[k] = {
                    'top_pct': float(row.get('top_pct', 0) or 0),
                    'left_pct': float(row.get('left_pct', 0) or 0),
                    'zoom': float(row.get('zoom', 1) or 1),
                }
            except: pass
    return d

def save_overrides(path, d):
    os.makedirs(Path(path).parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['grade','cls','num','top_pct','left_pct','zoom'])
        for (g,c,n), v in sorted(d.items()):
            w.writerow([g, c, n, v.get('top_pct', 0), v.get('left_pct', 0), v.get('zoom', 1)])

# ════════════════════════════════════════════════════════
#  デザインパレット (Apple風)
# ════════════════════════════════════════════════════════
PALETTE = {
    "bg":         "#f5f5f7",   # macOSの典型的な背景色
    "panel":      "#ffffff",   # カード（純白）
    "panel_alt":  "#fafaf7",   # 副カード
    "input_bg":   "#fafaf7",
    "text":       "#1d1d1f",   # iOS の primary text
    "text_strong":"#000000",
    "text_dim":   "#6e6e73",   # iOS の secondary
    "text_label": "#3a3a3c",
    "accent":     "#ff9500",   # iOS Orange
    "accent_bg":  "#fff4e0",
    "accent_dk":  "#cc7700",
    "primary":    "#0a84ff",   # iOS Blue
    "primary_bg": "#e6f0ff",
    "primary_dk": "#0066cc",
    "success":    "#34c759",   # iOS Green
    "success_dk": "#28a745",
    "danger":     "#ff3b30",   # iOS Red
    "danger_dk":  "#cc2922",
    "border":     "#d2d2d7",
    "border_active":"#c5c5cc",
    "neutral":    "#e5e5ea",   # 軽量グレー（ボタン背景用）
    "neutral_dk": "#d1d1d6",
}

# ════════════════════════════════════════════════════════
#  カスタムボタン（macOS対応）
# ════════════════════════════════════════════════════════
class MacButton(tk.Frame):
    """tk.Buttonの色問題を回避するLabelベースのカスタムボタン"""
    def __init__(self, parent, text, command, bg, fg, hover_bg=None,
                 font=("",12,"bold"), padx=14, pady=8, **kw):
        super().__init__(parent, bg=bg, cursor="hand2",
                        highlightthickness=0, **kw)
        self.command = command
        self.bg = bg
        self.hover_bg = hover_bg or self._lighten(bg, 0.92)
        self.label = tk.Label(self, text=text, bg=bg, fg=fg,
                              font=font, padx=padx, pady=pady,
                              cursor="hand2")
        self.label.pack()
        for w in (self, self.label):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def _lighten(self, hex_color, factor):
        h = hex_color.lstrip('#')
        r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        if factor < 1.0:
            r, g, b = int(r*factor), int(g*factor), int(b*factor)
        else:
            r = min(255, int(r + (255-r)*(factor-1)))
            g = min(255, int(g + (255-g)*(factor-1)))
            b = min(255, int(b + (255-b)*(factor-1)))
        return f'#{r:02x}{g:02x}{b:02x}'

    def _click(self, e):
        if self.command: self.command()
    def _enter(self, e):
        self.configure(bg=self.hover_bg)
        self.label.configure(bg=self.hover_bg)
    def _leave(self, e):
        self.configure(bg=self.bg)
        self.label.configure(bg=self.bg)

    def set_text(self, text):
        self.label.configure(text=text)

# ════════════════════════════════════════════════════════
#  GUI 本体
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
        self.roster_full   = load_full_roster(self.roster_path) if self.roster_path else {}

        self.current_img      = None   # 編集用プロキシ（縮小画像）
        self.current_key      = None
        self.current_orig_size = None  # 実写真の解像度 (w,h)
        self._preview_base    = None   # キャッシュ済みプレビュー基準画像
        self._px_scale        = 1.0
        self.photos           = {}
        self.photo_nums       = []
        self.auto_initial     = (0.0, 0.0, 1.0)
        # プロキシ＆顔検出結果のメモリキャッシュ（前/次ナビを高速化）
        # path -> (proxy_img, auto_initial, orig_size)
        self._proxy_cache     = {}

        self._update_pending = False
        self._dragging = False
        self._drag_start = None
        self._drag_start_left = 0
        self._drag_start_top = 0
        self._modal_count = 0  # サブウィンドウ表示中はメインのキー処理を無効化

        # 拡大率（フォントサイズ係数）
        self.scale_factor = 1.0

        # ── ウィンドウサイズと中央配置 ──
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        win_w = min(1280, int(sw * 0.85))
        win_h = min(880, int(sh * 0.82))
        x = (sw - win_w) // 2
        y = max(40, (sh - win_h) // 2 - 30)
        root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        root.minsize(1100, 700)

        self.PREVIEW_W = max(360, min(420, int(win_w * 0.30)))
        self.PREVIEW_H = max(440, min(540, int(win_h * 0.50)))
        self.POSTER_W  = 200

        root.title("クロップ調整ツール")
        root.configure(bg=PALETTE["bg"])
        self._setup_ttk_style()
        self._build_ui()
        self._bind_keys()
        self._refresh_class_list()

        # スクロール対応
        self._bind_scroll_events()

        self.root.after(100, lambda: self.root.focus_set())

    def _setup_ttk_style(self):
        style = ttk.Style()
        try: style.theme_use('clam')
        except: pass
        style.configure("Vertical.TScrollbar",
                       background=PALETTE["bg"],
                       troughcolor=PALETTE["bg"],
                       arrowcolor=PALETTE["text_dim"],
                       borderwidth=0,
                       relief="flat")

    def _font(self, size, bold=False):
        """システムフォントを取得（拡大率を反映）"""
        actual_size = int(size * self.scale_factor)
        family = system_font_family()
        weight = "bold" if bold else "normal"
        return (family, actual_size, weight) if family else ("", actual_size, weight)

    def _build_ui(self):
        BG     = PALETTE["bg"]
        PANEL  = PALETTE["panel"]
        TEXT   = PALETTE["text"]
        STRONG = PALETTE["text_strong"]
        DIM    = PALETTE["text_dim"]
        LABEL  = PALETTE["text_label"]
        root = self.root

        # ─── ヘッダー ───
        header = tk.Frame(root, bg=PALETTE["primary"], height=52)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="クロップ調整ツール",
                 bg=PALETTE["primary"], fg="#ffffff",
                 font=self._font(15, True)).pack(side="left", padx=22, pady=12)
        tk.Label(header, text="個人写真ポスター",
                 bg=PALETTE["primary"], fg="#cce4ff",
                 font=self._font(11)).pack(side="left", pady=12)

        # ─── 上部入力エリア（カード）───
        topbar_wrap = tk.Frame(root, bg=BG)
        topbar_wrap.pack(fill="x", padx=14, pady=(12, 0))
        topbar = tk.Frame(topbar_wrap, bg=PANEL,
                         highlightthickness=1, highlightbackground=PALETTE["border"])
        topbar.pack(fill="x")
        topbar_inner = tk.Frame(topbar, bg=PANEL, height=64)
        topbar_inner.pack(fill="x"); topbar_inner.pack_propagate(False)

        def _label(parent, t):
            return tk.Label(parent, text=t, bg=PANEL, fg=LABEL, font=self._font(11, True))

        _label(topbar_inner, "学年").pack(side="left", padx=(20,4), pady=20)
        self.v_grade = tk.StringVar(value="1")
        self.sb_grade = tk.Spinbox(topbar_inner, from_=1, to=6, width=4,
                   textvariable=self.v_grade, font=self._font(13),
                   bg=PALETTE["input_bg"], fg=TEXT,
                   highlightthickness=1, highlightbackground=PALETTE["border"],
                   relief="flat", buttonbackground=PALETTE["neutral"])
        self.sb_grade.pack(side="left", padx=4, pady=20)

        _label(topbar_inner, "組").pack(side="left", padx=(12,4), pady=20)
        self.v_cls = tk.StringVar(value="1")
        self.sb_cls = tk.Spinbox(topbar_inner, from_=1, to=6, width=4,
                   textvariable=self.v_cls, font=self._font(13),
                   bg=PALETTE["input_bg"], fg=TEXT,
                   highlightthickness=1, highlightbackground=PALETTE["border"],
                   relief="flat")
        self.sb_cls.pack(side="left", padx=4, pady=20)

        _label(topbar_inner, "番号").pack(side="left", padx=(12,4), pady=20)
        self.v_num = tk.StringVar(value="1")
        self.sb_num = tk.Spinbox(topbar_inner, from_=1, to=40, width=4,
                   textvariable=self.v_num, font=self._font(13),
                   bg=PALETTE["input_bg"], fg=TEXT,
                   highlightthickness=1, highlightbackground=PALETTE["border"],
                   relief="flat")
        self.sb_num.pack(side="left", padx=4, pady=20)

        # 開くボタン
        open_btn = MacButton(topbar_inner, "開く", self.open_photo,
                            bg=PALETTE["primary"], fg="#ffffff",
                            font=self._font(12, True), padx=22, pady=6)
        open_btn.pack(side="left", padx=(16,8), pady=15)

        # 名前で検索ボタン
        search_btn = MacButton(topbar_inner, "🔍 名前で検索", self.show_search,
                            bg=PALETTE["accent_bg"], fg=PALETTE["accent_dk"],
                            font=self._font(12, True), padx=16, pady=6)
        search_btn.pack(side="left", padx=(0,12), pady=15)

        # 件数バッジ
        self.saved_var = tk.StringVar(value=f"調整済み {len(self.overrides)}件")
        tk.Label(topbar_inner, textvariable=self.saved_var,
                 bg=PALETTE["accent_bg"], fg=PALETTE["accent_dk"],
                 font=self._font(11, True), padx=14, pady=6
                ).pack(side="right", padx=20, pady=18)

        # 拡大縮小ボタン
        zoom_frame = tk.Frame(topbar_inner, bg=PANEL)
        zoom_frame.pack(side="right", padx=(8,0), pady=18)
        MacButton(zoom_frame, "−", self._scale_down, bg=PALETTE["neutral"],
                 fg=TEXT, font=self._font(12, True), padx=8, pady=4).pack(side="left", padx=2)
        self.scale_label = tk.Label(zoom_frame, text="100%", bg=PANEL, fg=DIM,
                                   font=self._font(10), width=5)
        self.scale_label.pack(side="left", padx=2)
        MacButton(zoom_frame, "＋", self._scale_up, bg=PALETTE["neutral"],
                 fg=TEXT, font=self._font(12, True), padx=8, pady=4).pack(side="left", padx=2)

        # ─── メイン領域（CTkScrollableFrameで完璧なスクロール）───
        if HAS_CTK:
            self._main_scroll = ctk.CTkScrollableFrame(
                root, fg_color=BG,
                scrollbar_button_color="#a0a0a0",
                scrollbar_button_hover_color="#606060",
                scrollbar_fg_color="transparent"
            )
            self._main_scroll.pack(fill="both", expand=True, padx=14, pady=12)
            main = tk.Frame(self._main_scroll, bg=BG)
            main.pack(fill="both", expand=True)
        else:
            main = tk.Frame(root, bg=BG)
            main.pack(fill="both", expand=True, padx=14, pady=12)

        # 3列レイアウト（grid）
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=0, minsize=200)
        main.grid_columnconfigure(1, weight=1)
        main.grid_columnconfigure(2, weight=0, minsize=290)

        # ─ 左: クラス一覧 ─
        left = tk.Frame(main, bg=PANEL, width=200,
                       highlightthickness=1, highlightbackground=PALETTE["border"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0,10))
        left.grid_propagate(False)
        tk.Label(left, text="CLASSES", bg=PANEL, fg=DIM,
                 font=self._font(10, True), anchor="w"
                ).pack(fill="x", padx=14, pady=(14,4))
        lf = tk.Frame(left, bg=PANEL)
        lf.pack(fill="both", expand=True, padx=8, pady=(0,12))
        self.class_listbox = tk.Listbox(
            lf, font=self._font(12), height=22,
            bg=PALETTE["panel_alt"], fg=TEXT,
            selectbackground=PALETTE["primary"], selectforeground="#ffffff",
            highlightthickness=1, highlightbackground=PALETTE["border"],
            relief="flat", borderwidth=0,
            activestyle="none")
        self.class_listbox.pack(fill="both", expand=True)
        self.class_listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        self.class_listbox.bind("<FocusIn>", lambda e: self._set_listbox_active(True))
        self.class_listbox.bind("<FocusOut>", lambda e: self._set_listbox_active(False))
        self._listbox_active = False

        # ─ 中央 ─
        center = tk.Frame(main, bg=BG)
        center.grid(row=0, column=1, sticky="nsew", padx=10)

        self.name_var = tk.StringVar(value="左のクラス一覧から選んでください")
        tk.Label(center, textvariable=self.name_var,
                 bg=BG, fg=STRONG, font=self._font(15, True)
                ).pack(pady=(0,10))

        prev_panel = tk.Frame(center, bg=PANEL,
                             highlightthickness=1, highlightbackground=PALETTE["border"])
        prev_panel.pack()
        inner = tk.Frame(prev_panel, bg=PANEL, padx=14, pady=14)
        inner.pack()
        tk.Label(inner, text="クロップ範囲（金色の枠の中だけがポスターに使われます）",
                 bg=PANEL, fg=PALETTE["accent_dk"], font=self._font(11, True)
                ).pack(pady=(0,8))
        tk.Label(inner, text="✋ 枠の中=移動  ●角=ズーム",
                 bg=PANEL, fg=DIM, font=self._font(10)
                ).pack(pady=(0,6))
        self.prev_label = tk.Label(inner, bg=PALETTE["panel_alt"],
                                   width=self.PREVIEW_W, height=self.PREVIEW_H,
                                   cursor="fleur")
        self.prev_label.pack()
        self.prev_label.bind("<Button-1>", self._on_drag_start)
        self.prev_label.bind("<B1-Motion>", self._on_drag_motion)
        self.prev_label.bind("<ButtonRelease-1>", self._on_drag_end)
        self.prev_label.bind("<Motion>", self._on_mouse_move)

        # スライダー
        sl_panel = tk.Frame(center, bg=PANEL, padx=20, pady=14,
                           highlightthickness=1, highlightbackground=PALETTE["border"])
        sl_panel.pack(fill="x", pady=(12,0))

        def _slider(parent, label, var, frm, to, resolution=1):
            row = tk.Frame(parent, bg=PANEL)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, bg=PANEL, fg=LABEL,
                     font=self._font(11, True), width=22, anchor="w"
                    ).pack(side="left")
            scale = tk.Scale(row, from_=frm, to=to, resolution=resolution,
                             orient="horizontal", variable=var, length=380,
                             bg=PANEL, fg=STRONG,
                             troughcolor=PALETTE["panel_alt"],
                             highlightthickness=0, relief="flat",
                             activebackground=PALETTE["accent"],
                             showvalue=True, font=self._font(10, True),
                             command=self._on_slide, takefocus=0)
            scale.pack(side="left", fill="x", expand=True)
            return scale

        self.v_top  = tk.DoubleVar(value=0)
        self.v_left = tk.DoubleVar(value=0)
        self.v_zoom = tk.DoubleVar(value=1.0)
        _slider(sl_panel, "上下位置 (0=上端)",  self.v_top, 0, 100)
        _slider(sl_panel, "左右位置 (中央=0)",  self.v_left, -50, 50)
        # ★ ズーム上限を 5.0 に拡大
        _slider(sl_panel, "ズーム (1.0標準〜5.0最大)", self.v_zoom, 1.0, 5.0, 0.05)

        # 顔検出ボタン
        rebtn_row = tk.Frame(center, bg=BG)
        rebtn_row.pack(pady=(10,0))
        MacButton(rebtn_row, "🔍 顔検出をやり直す", self.reapply_auto_detect,
                 bg=PALETTE["neutral"], fg=TEXT,
                 font=self._font(11, True), padx=18, pady=8).pack()

        # 操作ボタン群
        btn_panel = tk.Frame(center, bg=BG, pady=12)
        btn_panel.pack()
        MacButton(btn_panel, "[ 前", self.prev_photo,
                 bg=PALETTE["neutral"], fg=TEXT,
                 font=self._font(12, True), padx=14, pady=8).pack(side="left", padx=4)
        MacButton(btn_panel, "✓ 保存 (S)", self.save_current,
                 bg=PALETTE["success"], fg="#ffffff",
                 font=self._font(12, True), padx=20, pady=8).pack(side="left", padx=4)
        MacButton(btn_panel, "リセット", self.reset_current,
                 bg=PALETTE["danger"], fg="#ffffff",
                 font=self._font(12, True), padx=14, pady=8).pack(side="left", padx=4)
        MacButton(btn_panel, "次 ]", self.next_photo,
                 bg=PALETTE["neutral"], fg=TEXT,
                 font=self._font(12, True), padx=14, pady=8).pack(side="left", padx=4)

        # ─ 右パネル（CTkScrollableFrameの中なので普通のFrameでOK）─
        right = tk.Frame(main, bg=PANEL, width=290,
                       highlightthickness=1, highlightbackground=PALETTE["border"])
        right.grid(row=0, column=2, sticky="nsew", padx=(10,0))

        tk.Label(right, text="ポスター上の見た目",
                 bg=PANEL, fg=PALETTE["accent_dk"], font=self._font(11, True),
                 anchor="w"
                ).pack(fill="x", padx=14, pady=(14,8))
        cell_h = int(self.POSTER_W / CELL_ASPECT) + 50
        self.poster_label = tk.Label(right, bg=PALETTE["panel_alt"],
                                     width=self.POSTER_W, height=cell_h)
        self.poster_label.pack(padx=14)

        # ─ 一括編集系UI ─
        # 注: 旧「GLOBAL ZOOM / 一括オフセット」スライダーは
        #   「個別調整値の上に重ねる」方式で混乱を招くため、コメントアウト中。
        #   将来は「クラス全員プレビュー上で個別データを直接編集できる画面」を実装予定。
        # ----------------------------------------------------------

        tk.Label(right, text="ACTIONS", bg=PANEL, fg=DIM,
                 font=self._font(10, True), anchor="w"
                ).pack(fill="x", padx=14, pady=(20,4))

        self.v_auto_pdf = tk.BooleanVar(value=False)
        tk.Checkbutton(right, text="保存時にPDF自動再生成",
                       variable=self.v_auto_pdf,
                       bg=PANEL, fg=TEXT, selectcolor=PALETTE["panel_alt"],
                       activebackground=PANEL, activeforeground=TEXT,
                       font=self._font(10, True), anchor="w",
                       highlightthickness=0, takefocus=0
                      ).pack(fill="x", padx=14, pady=2, anchor="w")

        MacButton(right, "現クラスのPDF再生成", self.regen_current_class,
                 bg=PALETTE["primary"], fg="#ffffff",
                 font=self._font(11, True), padx=10, pady=10
                ).pack(fill="x", padx=14, pady=4)

        MacButton(right, "全クラスPDF再生成", self.regen_all,
                 bg=PALETTE["accent"], fg="#ffffff",
                 font=self._font(11, True), padx=10, pady=10
                ).pack(fill="x", padx=14, pady=4)

        # ─ 顔写真の画像出力 ─
        tk.Label(right, text="顔写真の画像出力", bg=PANEL, fg=DIM,
                 font=self._font(10, True), anchor="w"
                ).pack(fill="x", padx=14, pady=(18,4))

        MacButton(right, "📸 この生徒の写真を出力", self.export_current_student,
                 bg=PALETTE["accent"], fg="#ffffff",
                 font=self._font(11, True), padx=10, pady=10
                ).pack(fill="x", padx=14, pady=4)

        MacButton(right, "📁 クラス全員を個別出力", self.export_class_all,
                 bg=PALETTE["accent_bg"], fg=PALETTE["accent_dk"],
                 font=self._font(11, True), padx=10, pady=8
                ).pack(fill="x", padx=14, pady=3)

        MacButton(right, "📋 クラス一覧シートを出力", self.export_roster_sheet,
                 bg=PALETTE["accent_bg"], fg=PALETTE["accent_dk"],
                 font=self._font(11, True), padx=10, pady=8
                ).pack(fill="x", padx=14, pady=3)

        MacButton(right, "🖼 クラス全員のプレビュー", self.show_class_overview,
                 bg=PALETTE["accent_bg"], fg=PALETTE["accent_dk"],
                 font=self._font(11, True), padx=10, pady=10
                ).pack(fill="x", padx=14, pady=(12,4))

        MacButton(right, "✏️ クラス一括調整", self.show_batch_editor,
                 bg=PALETTE["primary"], fg="#ffffff",
                 font=self._font(11, True), padx=10, pady=10
                ).pack(fill="x", padx=14, pady=4)

        MacButton(right, "🎨 デザイン設定", self.show_design_editor,
                 bg=PALETTE["accent"], fg="#ffffff",
                 font=self._font(11, True), padx=10, pady=10
                ).pack(fill="x", padx=14, pady=4)

        MacButton(right, "⚙ 出力ウィザード", self.show_wizard,
                 bg=PALETTE["primary_bg"], fg=PALETTE["primary_dk"],
                 font=self._font(11, True), padx=10, pady=10
                ).pack(fill="x", padx=14, pady=4)

        tk.Label(right, text="SHORTCUTS", bg=PANEL, fg=DIM,
                 font=self._font(10, True), anchor="w"
                ).pack(fill="x", padx=14, pady=(20,4))
        sc = ("↑↓←→        枠を移動\n"
              "Shift+↑↓     ズーム\n"
              "[  ]          前 / 次（自動保存）\n"
              "S            保存→次へ\n"
              "R            リセット\n"
              "F            顔検出やり直し\n"
              "⌘+/− (Mac)   画面拡大/縮小\n"
              "Ctrl+/− (Win)  画面拡大/縮小")
        tk.Label(right, text=sc, bg=PANEL, fg=LABEL,
                 font=("Menlo", int(10*self.scale_factor)),
                 justify="left", anchor="w"
                ).pack(fill="x", padx=14)

        tk.Label(right, text="枠の中=移動 / ●角=ズーム",
                 bg=PANEL, fg=DIM, font=self._font(9),
                 wraplength=240, justify="left"
                ).pack(fill="x", padx=14, pady=(8,4))
        # 下部に余白を追加
        tk.Frame(right, bg=PANEL, height=24).pack(fill="x")

        # ステータスバー
        self.status_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.status_var,
                 bg=PALETTE["panel"], fg=TEXT,
                 font=self._font(11), anchor="w", padx=16, pady=8,
                 highlightthickness=1, highlightbackground=PALETTE["border"]
                ).pack(fill="x", side="bottom")

        # 全子ウィジェットにホイールイベントをbind
        self.root.update_idletasks()
        self._setup_wheel_bindings()

    def _bind_scroll_events(self):
        """互換性のため残す（実体は _setup_wheel_bindings）"""
        pass

    def _setup_wheel_bindings(self):
        """全子ウィジェットにマウスホイールイベントを再帰的にbind
        CTkScrollableFrame の内部Canvas を使って確実にスクロール"""
        if not hasattr(self, "_main_scroll") or not HAS_CTK:
            return
        # CTkScrollableFrame の内部Canvas を取得
        try:
            inner_canvas = self._main_scroll._parent_canvas
        except AttributeError:
            return

        def _on_wheel(event):
            if IS_MAC:
                step = -1 * int(event.delta)
            else:
                step = -1 * int(event.delta / 120)
            if step == 0:
                step = -1 if event.delta > 0 else 1
            inner_canvas.yview_scroll(step, "units")
            return "break"

        def _bind_recursive(widget):
            try:
                widget.bind("<MouseWheel>", _on_wheel, add="+")
                widget.bind("<Button-4>",
                    lambda e: (inner_canvas.yview_scroll(-1, "units"), "break")[1], add="+")
                widget.bind("<Button-5>",
                    lambda e: (inner_canvas.yview_scroll(1, "units"), "break")[1], add="+")
            except: pass
            for child in widget.winfo_children():
                _bind_recursive(child)

        # CTkScrollableFrame全体と全子ウィジェット
        _bind_recursive(self._main_scroll)
        # 内部Canvas自体にも
        try:
            inner_canvas.bind("<MouseWheel>", _on_wheel, add="+")
            inner_canvas.bind("<Button-4>",
                lambda e: (inner_canvas.yview_scroll(-1, "units"), "break")[1], add="+")
            inner_canvas.bind("<Button-5>",
                lambda e: (inner_canvas.yview_scroll(1, "units"), "break")[1], add="+")
        except: pass

    # ── 画面拡大縮小 ──
    def _scale_up(self):
        if self.scale_factor < 1.5:
            self.scale_factor = round(self.scale_factor + 0.1, 1)
            self._apply_scale()

    def _scale_down(self):
        if self.scale_factor > 0.7:
            self.scale_factor = round(self.scale_factor - 0.1, 1)
            self._apply_scale()

    def _scale_reset(self):
        self.scale_factor = 1.0
        self._apply_scale()

    def _apply_scale(self):
        """フォントスケールを変えるためにUIを再構築"""
        self.scale_label.config(text=f"{int(self.scale_factor*100)}%")
        # シンプルな実装: 全ウィジェット破棄して再構築
        for w in self.root.winfo_children():
            w.destroy()
        self._build_ui()
        self._refresh_class_list()
        self._bind_scroll_events()
        # 状態復元
        if self.current_key:
            g, c, n = self.current_key
            self.v_grade.set(str(g)); self.v_cls.set(str(c)); self.v_num.set(str(n))
            self.open_photo()

    # ── フォーカス制御 ──
    def _set_listbox_active(self, active):
        self._listbox_active = active

    def _editor_focused(self):
        # サブウィンドウ表示中はメインのキー処理を無効化
        if self._modal_count > 0:
            return False
        w = self.root.focus_get()
        if w in (self.sb_grade, self.sb_cls, self.sb_num):
            return False
        return True

    def _modal_open(self):
        self._modal_count += 1

    def _modal_close(self):
        self._modal_count = max(0, self._modal_count - 1)

    # ── キーボード ──
    def _bind_keys(self):
        r = self.root
        r.bind_all("<Left>",         self._key_left)
        r.bind_all("<Right>",        self._key_right)
        r.bind_all("<Up>",           self._key_up)
        r.bind_all("<Down>",         self._key_down)
        r.bind_all("<Shift-Up>",     self._key_shift_up)
        r.bind_all("<Shift-Down>",   self._key_shift_down)
        # [ ] で前/次（自動保存付き）
        r.bind_all("<bracketleft>",  self._key_prev_with_save)
        r.bind_all("<bracketright>", self._key_next_with_save)
        r.bind_all("<s>",            lambda e: (self.save_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<S>",            lambda e: (self.save_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<r>",            lambda e: (self.reset_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<R>",            lambda e: (self.reset_current(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<f>",            lambda e: (self.reapply_auto_detect(), "break")[1] if self._editor_focused() else None)
        r.bind_all("<F>",            lambda e: (self.reapply_auto_detect(), "break")[1] if self._editor_focused() else None)
        # ⌘+ / ⌘− / ⌘0 で画面サイズ変更
        if IS_MAC:
            r.bind_all("<Command-plus>",  lambda e: self._scale_up())
            r.bind_all("<Command-equal>", lambda e: self._scale_up())
            r.bind_all("<Command-minus>", lambda e: self._scale_down())
            r.bind_all("<Command-0>",     lambda e: self._scale_reset())
        else:
            r.bind_all("<Control-plus>",  lambda e: self._scale_up())
            r.bind_all("<Control-equal>", lambda e: self._scale_up())
            r.bind_all("<Control-minus>", lambda e: self._scale_down())
            r.bind_all("<Control-0>",     lambda e: self._scale_reset())

    def _key_prev_with_save(self, e):
        if not self._editor_focused(): return
        # 変更があれば自動保存
        self._auto_save_if_changed()
        self.prev_photo()
        return "break"

    def _key_next_with_save(self, e):
        if not self._editor_focused(): return
        self._auto_save_if_changed()
        self.next_photo()
        return "break"

    def _auto_save_if_changed(self):
        """現在の値が初期値（自動）or 既存overrideと違えば保存"""
        if not self.current_key: return
        g, c, n = self.current_key
        cur_top  = float(self.v_top.get())
        cur_left = float(self.v_left.get())
        cur_zoom = float(self.v_zoom.get())
        # 既存overrideか自動初期値と比較
        existing = self.overrides.get((g,c,n))
        if existing:
            ref_top  = existing['top_pct']
            ref_left = existing['left_pct']
            ref_zoom = existing['zoom']
        else:
            ref_top, ref_left, ref_zoom = self.auto_initial
        # 微小差を厳しく（0.1以上で保存）
        if (abs(cur_top - ref_top) > 0.1 or
            abs(cur_left - ref_left) > 0.1 or
            abs(cur_zoom - ref_zoom) > 0.005):
            self.overrides[(g,c,n)] = {
                'top_pct': cur_top, 'left_pct': cur_left, 'zoom': cur_zoom,
            }
            save_overrides(self.override_path, self.overrides)
            self.saved_var.set(f"調整済み {len(self.overrides)}件")
            self._refresh_class_list()
            self.status_var.set(f"  ✓ {g}年{c}組{n:02d}番 自動保存")

    def _key_left(self, e):
        if not self._editor_focused() or self._listbox_active: return
        self._step("left", -2); return "break"
    def _key_right(self, e):
        if not self._editor_focused() or self._listbox_active: return
        self._step("left", +2); return "break"
    def _key_up(self, e):
        if not self._editor_focused() or self._listbox_active: return
        self._step("top", -2); return "break"
    def _key_down(self, e):
        if not self._editor_focused() or self._listbox_active: return
        self._step("top", +2); return "break"
    def _key_shift_up(self, e):
        if not self._editor_focused() or self._listbox_active: return
        self._step("zoom", +0.1); return "break"
    def _key_shift_down(self, e):
        if not self._editor_focused() or self._listbox_active: return
        self._step("zoom", -0.1); return "break"

    def _step(self, key, delta):
        if key == "top":
            self.v_top.set(max(0, min(100, self.v_top.get()+delta)))
        elif key == "left":
            self.v_left.set(max(-50, min(50, self.v_left.get()+delta)))
        elif key == "zoom":
            self.v_zoom.set(max(1.0, min(5.0, round(self.v_zoom.get()+delta, 2))))
        self._update_preview()

    # ── ドラッグ（4隅でズーム、それ以外で移動）──
    def _on_drag_start(self, event):
        if self.current_img is None: return
        # コーナーハンドル判定
        self._drag_mode = "move"  # "move" or "zoom"
        if hasattr(self, "_corners"):
            for name, (cx, cy) in self._corners.items():
                if abs(event.x - cx) < 18 and abs(event.y - cy) < 18:
                    self._drag_mode = "zoom"
                    self._drag_corner = name
                    break
        self._dragging = True
        self._drag_start = (event.x, event.y)
        self._drag_start_left = self.v_left.get()
        self._drag_start_top = self.v_top.get()
        self._drag_start_zoom = self.v_zoom.get()
        self.root.focus_set()

    def _on_drag_motion(self, event):
        if not self._dragging or self.current_img is None: return
        if self._drag_start is None: return
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]

        if self._drag_mode == "zoom":
            # コーナードラッグ：対角線方向の動きでズーム
            # 中心に近づく → ズームアップ、離れる → ズームダウン
            corner = self._drag_corner
            # 各コーナーで「内側」方向を定義
            if corner == "tl":   # 左上：右下方向にドラッグでズームアップ
                progress = (dx + dy) / 2
            elif corner == "tr": # 右上：左下方向にドラッグでズームアップ
                progress = (-dx + dy) / 2
            elif corner == "bl": # 左下：右上方向にドラッグでズームアップ
                progress = (dx - dy) / 2
            else:                # br：左上方向にドラッグでズームアップ
                progress = (-dx - dy) / 2
            # 100px の動きでズーム1.0倍変化
            zoom_delta = progress / 100
            new_zoom = max(1.0, min(5.0, self._drag_start_zoom + zoom_delta))
            self.v_zoom.set(round(new_zoom, 2))
        else:
            # 通常ドラッグ：枠を移動
            delta_left = (dx / self.PREVIEW_W) * 100
            delta_top = (dy / self.PREVIEW_H) * 100
            self.v_left.set(max(-50, min(50, self._drag_start_left + delta_left)))
            self.v_top.set(max(0, min(100, self._drag_start_top + delta_top)))

        self._update_preview()

    def _on_drag_end(self, event):
        self._dragging = False
        self._drag_start = None
        self._drag_mode = "move"

    # マウス位置に応じてカーソルを変える
    def _on_mouse_move(self, event):
        if self.current_img is None or not hasattr(self, "_corners"):
            self.prev_label.configure(cursor="fleur")
            return
        for name, (cx, cy) in self._corners.items():
            if abs(event.x - cx) < 18 and abs(event.y - cy) < 18:
                # コーナー位置に応じて拡縮カーソル
                if name in ("tl", "br"):
                    self.prev_label.configure(cursor="size_nw_se" if not IS_MAC else "crosshair")
                else:
                    self.prev_label.configure(cursor="size_ne_sw" if not IS_MAC else "crosshair")
                return
        self.prev_label.configure(cursor="fleur")

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
        self.root.focus_set()

    def _select_class_in_list(self, g, c):
        """クラス一覧(listbox)で(g,c)を選択状態にする。検索からの遷移用。"""
        for i, (cg, cc, _) in enumerate(self.classes_list):
            if cg == g and cc == c:
                try:
                    self.class_listbox.selection_clear(0, tk.END)
                    self.class_listbox.selection_set(i)
                    self.class_listbox.see(i)
                except Exception:
                    pass
                return

    # ── 写真ロード ──
    def open_photo(self):
        try:
            g = int(self.v_grade.get()); c = int(self.v_cls.get()); n = int(self.v_num.get())
        except:
            messagebox.showerror("エラー","学年・組・番号は数字で入力してください"); return
        folder = find_class_folder(self.base, g, c)
        if not folder:
            messagebox.showerror("エラー", f"{g}年{c}組のフォルダが見つかりません"); return
        new_photos = collect_photos(folder, g, c)
        # 別クラスに切り替わったらプロキシキャッシュを破棄（メモリ肥大防止）
        if set(new_photos.values()) != set(self.photos.values()):
            self._proxy_cache.clear()
        self.photos = new_photos
        self.photo_nums = sorted(self.photos.keys())
        if not self.photo_nums:
            messagebox.showwarning("写真なし", f"{g}年{c}組に写真がありません"); return
        self._load(g, c, n)
        self.root.focus_set()

    def _load(self, g, c, n):
        if n not in self.photos:
            self.status_var.set(f"⚠ {g}年{c}組 {n}番の写真が見つかりません"); return
        self.current_key = (g, c, n)
        self.v_grade.set(str(g)); self.v_cls.set(str(c)); self.v_num.set(str(n))
        # 編集用プロキシをキャッシュから取得（なければ生成）
        path = self.photos[n]
        cached = self._proxy_cache.get(path)
        if cached is not None:
            self.current_img, self.auto_initial, self.current_orig_size = cached
        else:
            full = fix_exif(Image.open(path))
            self.current_orig_size = full.size
            proxy = make_proxy(full)
            self.current_img = proxy
            self.auto_initial = auto_initial_crop_params(proxy)
            self._proxy_cache[path] = (self.current_img, self.auto_initial,
                                       self.current_orig_size)
        # プレビュー基準画像を1回だけ生成（スライダー操作を高速化）
        self._preview_base = prepare_preview_base(
            self.current_img, self.PREVIEW_W, self.PREVIEW_H)
        # 実写真px換算係数（プロキシ→実写真）
        self._px_scale = self.current_orig_size[0] / self.current_img.size[0]
        ov = self.overrides.get((g,c,n))
        if ov:
            self.v_top.set(float(ov.get('top_pct', 0)))
            self.v_left.set(float(ov.get('left_pct', 0)))
            self.v_zoom.set(float(ov.get('zoom', 1.0)))
        else:
            t, l, z = self.auto_initial
            self.v_top.set(t); self.v_left.set(l); self.v_zoom.set(z)
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
        self.v_top.set(t); self.v_left.set(l); self.v_zoom.set(z)
        self._update_preview()
        self.status_var.set("  顔検出をやり直しました")
        self.root.focus_set()

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
        # キャッシュ済み基準画像にオーバーレイだけ再描画（高速）
        prev_img, _, _, self._corners = render_clipping_overlay(
            self._preview_base, top, left, zoom,
            px_scale=getattr(self, "_px_scale", 1.0))
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

    # ── 保存 ──
    def save_current(self):
        if not self.current_key: return
        g, c, n = self.current_key
        # スライダー値を確実に取得（update_idletasks で同期）
        self.root.update_idletasks()
        cur_top = float(self.v_top.get())
        cur_left = float(self.v_left.get())
        cur_zoom = float(self.v_zoom.get())
        self.overrides[(g,c,n)] = {
            'top_pct': cur_top,
            'left_pct': cur_left,
            'zoom': cur_zoom,
        }
        save_overrides(self.override_path, self.overrides)
        self.saved_var.set(f"調整済み {len(self.overrides)}件")
        self._refresh_class_list()
        self.status_var.set(f"  ✓ {g}年{c}組{n:02d}番 保存 (top={cur_top:.1f}, left={cur_left:.1f}, zoom={cur_zoom:.2f})")
        if self.v_auto_pdf.get():
            self.regen_current_class()
        self.next_photo()

    # ── 顔写真の画像出力 ──
    def _get_full_cropped(self, g, c, n):
        """指定生徒の実写真をフル解像度で開いてクロップして返す。
        編集中の生徒は現在のスライダー値、それ以外は保存済み/自動値を使う。"""
        path = self.photos.get(n)
        if not path or not os.path.exists(path):
            return None
        full = fix_exif(Image.open(path))
        if self.current_key == (g, c, n):
            top  = float(self.v_top.get())
            left = float(self.v_left.get())
            zoom = float(self.v_zoom.get())
        else:
            ov = self.overrides.get((g, c, n))
            if ov:
                top, left, zoom = (float(ov.get('top_pct', 0)),
                                   float(ov.get('left_pct', 0)),
                                   float(ov.get('zoom', 1.0)))
            else:
                top, left, zoom = auto_initial_crop_params(make_proxy(full))
        return do_crop(full, top, left, zoom)

    def _student_info(self, g, c, n):
        info = self.roster_full.get((g, c), {}).get(n, {})
        return info.get("kanji", ""), info.get("kana", "")

    def export_current_student(self):
        if not self.current_key:
            messagebox.showinfo("写真未選択", "先にクラス一覧から生徒を選んでください")
            return
        g, c, n = self.current_key
        try:
            cropped = self._get_full_cropped(g, c, n)
        except Exception as e:
            messagebox.showerror("エラー", f"写真の読み込みに失敗しました\n{e}")
            return
        if cropped is None:
            messagebox.showerror("エラー", "写真が見つかりません")
            return
        kanji, kana = self._student_info(g, c, n)
        card = render_id_card(cropped, g, c, n, kanji, kana)
        out_dir = os.path.join(self.base, "output", "顔写真")
        os.makedirs(out_dir, exist_ok=True)
        safe = (kanji or f"{n}番").replace(" ", "").replace("/", "_").replace(os.sep, "_")
        out_path = os.path.join(out_dir, f"{g}年{c}組_{n:02d}_{safe}.png")
        card.save(out_path)
        self.status_var.set(f"  📸 保存しました: {os.path.basename(out_path)}")
        self._reveal_in_finder(out_path)

    def _reveal_in_finder(self, path):
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            elif os.name == "nt":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception:
            pass

    # ── クラス写真の参照（検索・一括出力で使用、キャッシュ付き）──
    def _class_photos(self, g, c):
        """(g,c)の写真辞書 {番号: path} を返す。フォルダ探索結果をキャッシュ。"""
        if not hasattr(self, "_class_photos_cache"):
            self._class_photos_cache = {}
        key = (g, c)
        if key not in self._class_photos_cache:
            folder = find_class_folder(self.base, g, c)
            self._class_photos_cache[key] = collect_photos(folder, g, c) if folder else {}
        return self._class_photos_cache[key]

    def _find_photo_path(self, g, c, n):
        return self._class_photos(g, c).get(n)

    def _make_face_thumb(self, g, c, n, size=120):
        """指定生徒の顔サムネイル(PIL)を生成。検索結果表示用。"""
        path = self._find_photo_path(g, c, n)
        if not path or not os.path.exists(path):
            return None
        try:
            proxy = make_proxy(fix_exif(Image.open(path)), max_dim=600)
            ov = self.overrides.get((g, c, n))
            if ov:
                t, l, z = (float(ov.get('top_pct', 0)), float(ov.get('left_pct', 0)),
                           float(ov.get('zoom', 1.0)))
            else:
                t, l, z = auto_initial_crop_params(proxy)
            cropped = do_crop(proxy, t, l, z)
            h = int(size / CELL_ASPECT)
            return cropped.resize((size, h), Image.LANCZOS)
        except Exception:
            return None

    # ── 名前・ふりがな検索 ──
    def show_search(self):
        if not self.roster_full:
            messagebox.showinfo("名簿なし",
                "名簿(xlsx)が読み込めないため検索できません。\n"
                "写真フォルダに生徒情報のExcelを置いてください。")
            return
        SearchWindow(self)

    # ── クラス全員を個別PNG出力 ──
    def export_class_all(self):
        if not self.current_key:
            messagebox.showinfo("情報", "先にクラスを選択してください")
            return
        g, c, _ = self.current_key
        photos = self._class_photos(g, c)
        nums = sorted(photos.keys())
        if not nums:
            messagebox.showwarning("写真なし", f"{g}年{c}組に写真がありません")
            return
        out_dir = os.path.join(self.base, "output", "顔写真", f"{g}年{c}組")
        os.makedirs(out_dir, exist_ok=True)

        def worker():
            done = 0
            for n in nums:
                try:
                    cropped = self._get_full_cropped(g, c, n)
                    if cropped is None:
                        continue
                    kanji, kana = self._student_info(g, c, n)
                    card = render_id_card(cropped, g, c, n, kanji, kana)
                    safe = (kanji or f"{n}番").replace(" ", "").replace("/", "_").replace(os.sep, "_")
                    card.save(os.path.join(out_dir, f"{g}年{c}組_{n:02d}_{safe}.png"))
                    done += 1
                except Exception:
                    pass
                self.root.after(0, self.status_var.set,
                                f"  📸 出力中... {done}/{len(nums)}")
            self.root.after(0, self._export_done, out_dir,
                            f"{g}年{c}組 全{done}名を出力しました")
        threading.Thread(target=worker, daemon=True).start()
        self.status_var.set(f"  📸 {g}年{c}組 の出力を開始...")

    # ── クラス一覧シートを1枚出力 ──
    def export_roster_sheet(self):
        if not self.current_key:
            messagebox.showinfo("情報", "先にクラスを選択してください")
            return
        g, c, _ = self.current_key
        photos = self._class_photos(g, c)
        nums = sorted(photos.keys())
        if not nums:
            messagebox.showwarning("写真なし", f"{g}年{c}組に写真がありません")
            return

        def worker():
            items = []
            for n in nums:
                kanji, kana = self._student_info(g, c, n)
                thumb = self._make_face_thumb(g, c, n, size=180)
                items.append((n, kanji, kana, thumb))
                self.root.after(0, self.status_var.set,
                                f"  🖼 一覧シート生成中... {len(items)}/{len(nums)}")
            sheet = render_roster_sheet(g, c, items)
            out_dir = os.path.join(self.base, "output", "顔写真")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{g}年{c}組_一覧シート.png")
            sheet.save(out_path)
            self.root.after(0, self._export_done, out_path,
                            f"{g}年{c}組 一覧シートを出力しました")
        threading.Thread(target=worker, daemon=True).start()
        self.status_var.set(f"  🖼 {g}年{c}組 一覧シート生成中...")

    def _export_done(self, reveal_path, msg):
        self.status_var.set(f"  ✅ {msg}")
        self._reveal_in_finder(reveal_path)

    def reset_current(self):
        if not self.current_key: return
        g, c, n = self.current_key
        if (g,c,n) in self.overrides:
            del self.overrides[(g,c,n)]
            save_overrides(self.override_path, self.overrides)
            self.saved_var.set(f"調整済み {len(self.overrides)}件")
            self._refresh_class_list()
        t, l, z = self.auto_initial
        self.v_top.set(t); self.v_left.set(l); self.v_zoom.set(z)
        self._update_preview()
        self.status_var.set(f"  ↺ {g}年{c}組{n:02d}番 をリセット")

    def next_photo(self):
        if not self.current_key or not self.photo_nums: return
        g, c, n = self.current_key
        if n in self.photo_nums:
            idx = self.photo_nums.index(n)
            if idx < len(self.photo_nums)-1:
                self._load(g, c, self.photo_nums[idx+1])
            else:
                # クラスの最終番号 → 次のクラスへジャンプ
                self._jump_to_class(direction=+1)

    def prev_photo(self):
        if not self.current_key or not self.photo_nums: return
        g, c, n = self.current_key
        if n in self.photo_nums:
            idx = self.photo_nums.index(n)
            if idx > 0:
                self._load(g, c, self.photo_nums[idx-1])
            else:
                # クラスの最初 → 前のクラスの最後へジャンプ
                self._jump_to_class(direction=-1)

    def _jump_to_class(self, direction=+1):
        """次（or 前）のクラスへジャンプ。学年も跨ぐ"""
        g, c, _ = self.current_key
        # 現在のクラスのインデックス
        cur_idx = -1
        for i, (g2, c2, _) in enumerate(self.classes_list):
            if g2 == g and c2 == c:
                cur_idx = i; break
        if cur_idx < 0: return

        next_idx = cur_idx + direction
        if next_idx < 0 or next_idx >= len(self.classes_list):
            # 全体の最初/最後
            if direction > 0:
                self.status_var.set("  ✅ 全クラス調整完了")
                messagebox.showinfo("完了", "全クラスの最後まで到達しました")
            else:
                self.status_var.set("  ⏪ 最初のクラスです")
            return

        ng, nc, nfolder = self.classes_list[next_idx]
        # 写真情報を更新
        self.photos = collect_photos(nfolder, ng, nc)
        self.photo_nums = sorted(self.photos.keys())
        if not self.photo_nums:
            self.status_var.set(f"  ⚠ {ng}年{nc}組に写真がありません（スキップ）")
            # さらに次へ進む
            self.current_key = (ng, nc, 0)  # ダミーキーで次へ
            self._jump_to_class(direction=direction)
            return
        # 最初の番号 (direction=+1) または最後の番号 (direction=-1)
        target_n = self.photo_nums[0] if direction > 0 else self.photo_nums[-1]
        self.v_grade.set(str(ng))
        self.v_cls.set(str(nc))
        self._load(ng, nc, target_n)
        self.status_var.set(f"  → {ng}年{nc}組 へジャンプ")

    # ── クラス全員プレビュー（スクロール対応）──
    def show_class_overview(self):
        if not self.current_key:
            messagebox.showinfo("情報", "先に学年・組を選択してください")
            return
        g, c, _ = self.current_key

        win = tk.Toplevel(self.root)
        win.title(f"{g}年{c}組 全員プレビュー")
        win.configure(bg=PALETTE["bg"])
        sw = win.winfo_screenwidth(); sh = win.winfo_screenheight()
        ww = min(900, int(sw * 0.7)); wh = min(720, int(sh * 0.78))
        win.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")

        # ヘッダー
        h = tk.Frame(win, bg=PALETTE["primary"], height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text=f"  {g}年 {c}組 全員プレビュー",
                bg=PALETTE["primary"], fg="#ffffff",
                font=self._font(14, True)).pack(side="left", padx=20, pady=10)

        # ローディング
        loading_frame = tk.Frame(win, bg=PALETTE["bg"])
        loading_frame.pack(fill="both", expand=True)
        loading = tk.Label(loading_frame,
                          text="サムネ生成中...\n（人数によっては数十秒かかります）",
                          bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                          font=self._font(13), justify="center")
        loading.pack(expand=True)
        win.update_idletasks()

        # スクロール領域を準備
        def show_image(overview):
            loading_frame.destroy()
            # Canvas + Scrollbar
            ow = tk.Frame(win, bg=PALETTE["bg"])
            ow.pack(fill="both", expand=True, padx=10, pady=10)
            cv = tk.Canvas(ow, bg=PALETTE["bg"], highlightthickness=0)
            sb = ttk.Scrollbar(ow, orient="vertical", command=cv.yview)
            cv.configure(yscrollcommand=sb.set)
            cv.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")

            self._overview_tk = ImageTk.PhotoImage(overview)
            cv.create_image(0, 0, anchor="nw", image=self._overview_tk)
            cv.configure(scrollregion=(0, 0, overview.width, overview.height))

            # ホイールスクロール
            def _wheel(e):
                step = -1 * int(e.delta) if IS_MAC else -1 * int(e.delta / 120)
                cv.yview_scroll(step, "units")
            cv.bind("<MouseWheel>", _wheel)
            win.bind("<MouseWheel>", _wheel)
            cv.bind("<Button-4>", lambda e: cv.yview_scroll(-1, "units"))
            cv.bind("<Button-5>", lambda e: cv.yview_scroll(1, "units"))

        def build():
            try:
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
                show_image(overview)
            except Exception as e:
                loading.config(text=f"エラー: {e}", fg=PALETTE["danger"])

        win.after(100, build)

    # ── PDF再生成 ──
    def regen_current_class(self):
        if not self.current_key: return
        g, c, _ = self.current_key
        self._run_poster(["--grade", str(g), "--cls", str(c)],
                         f"  ⏳ {g}年{c}組のPDF再生成中...")

    def show_design_editor(self):
        """デザイン設定画面を開く"""
        DesignEditor(self)

    def show_batch_editor(self):
        """クラス一括調整画面を開く"""
        if not self.current_key:
            messagebox.showinfo("情報", "先にクラスを選択してください")
            return
        g, c, _ = self.current_key
        ClassBatchEditor(self, g, c)

    def show_wizard(self):
        """出力ウィザードを開く"""
        PosterWizard(self)

    def regen_all(self):
        if not messagebox.askyesno("確認", "全クラスのPDFを再生成します。よろしいですか？"):
            return
        self._run_poster([], "  ⏳ 全クラスのPDF再生成中...")

    def _run_poster(self, extra_args, msg):
        self.status_var.set(msg)
        # 旧「GLOBAL ZOOM / 一括オフセット」の渡し処理はコメントアウト
        # if hasattr(self, 'v_global_zoom'): ...
        # if hasattr(self, 'v_global_top'): ...
        # if hasattr(self, 'v_global_left'): ...

        candidates = [
            os.path.join(self.base, "make_poster.py"),
            os.path.join(self.base, "make_poster_v8.py"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_poster.py"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_poster_v8.py"),
        ]
        script = next((p for p in candidates if os.path.exists(p)), None)
        if not script:
            messagebox.showerror("エラー", "make_poster.py が見つかりません。")
            return

        # 進捗ダイアログを開く
        output_dir = os.path.join(self.base, "output")
        dlg = ProgressDialog(self.root, title="ポスター生成中...",
                            output_dir=output_dir, app=self)
        self.root.update()  # ダイアログが描画されるまで待つ

        def worker():
            try:
                # -u を入れて子プロセスのstdoutバッファを無効化（リアルタイムログ取得のため）
                cmd = [sys.executable, "-u", script, "--base", self.base,
                       "--out", os.path.join(self.base, "output")] + extra_args
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT,
                                       text=True, bufsize=1, encoding='utf-8',
                                       env={**os.environ, "PYTHONUNBUFFERED": "1"})
                # 進捗推定: ▶マークを数えて分数で % を出す
                total_classes = len(self.classes_list) or 19
                done = 0
                for line in iter(proc.stdout.readline, ''):
                    line = line.rstrip()
                    if not line: continue
                    if "▶" in line:
                        done += 1
                        pct = min(99, int((done / total_classes) * 100))
                        self.root.after(0, lambda l=line, p=pct:
                            dlg.update(p, status=l, log=l))
                    else:
                        self.root.after(0, lambda l=line: dlg.update(None, log=l))
                proc.wait()
                if proc.returncode == 0:
                    self.root.after(0, lambda: dlg.finish("PDF生成完了"))
                    self.root.after(0, lambda: self.status_var.set("  ✓ PDF再生成完了"))
                else:
                    self.root.after(0, lambda: dlg.finish(
                        f"エラー終了 (code {proc.returncode})", error=True))
            except Exception as e:
                err_str = str(e)
                self.root.after(0, lambda: dlg.finish(f"例外: {err_str}", error=True))
        threading.Thread(target=worker, daemon=True).start()




# ════════════════════════════════════════════════════════
#  名前・ふりがな検索画面
# ════════════════════════════════════════════════════════
class SearchWindow:
    """漢字名・ふりがなの部分一致で全校児童を検索し、顔写真付きで一覧表示。
    結果から「開く」（編集画面に飛ぶ）や「画像出力」ができる。"""

    def __init__(self, app):
        self.app = app
        self.root = app.root
        # 全児童のフラット索引を構築: [(g, c, n, kanji, kana), ...]
        self.index = []
        for (g, c), students in sorted(app.roster_full.items()):
            for n, info in sorted(students.items()):
                self.index.append((g, c, n,
                                   info.get("kanji", ""), info.get("kana", "")))
        self._thumb_refs = {}     # サムネ参照保持（GC防止）
        self._thumb_thread = None
        self._search_seq = 0      # 検索世代（古いスレッド結果を無視）

        self.win = tk.Toplevel(self.root)
        self.win.title("名前で検索")
        self.win.configure(bg=PALETTE["bg"])
        sw = self.win.winfo_screenwidth(); sh = self.win.winfo_screenheight()
        ww = min(720, int(sw*0.6)); wh = min(760, int(sh*0.82))
        self.win.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")
        app._modal_open()
        self.win.protocol("WM_DELETE_WINDOW", self._close)

        # ヘッダー＋検索入力
        head = tk.Frame(self.win, bg=PALETTE["primary"], height=56)
        head.pack(fill="x"); head.pack_propagate(False)
        tk.Label(head, text="🔍 名前で検索", bg=PALETTE["primary"], fg="#ffffff",
                 font=app._font(15, True)).pack(side="left", padx=20)

        bar = tk.Frame(self.win, bg=PALETTE["panel"])
        bar.pack(fill="x", padx=0, pady=0)
        tk.Label(bar, text="漢字名・ふりがな・番号で部分一致検索",
                 bg=PALETTE["panel"], fg=PALETTE["text_dim"],
                 font=app._font(10)).pack(anchor="w", padx=18, pady=(10,2))
        self.q_var = tk.StringVar()
        ent = tk.Entry(bar, textvariable=self.q_var, font=app._font(15),
                       bg=PALETTE["input_bg"], fg=PALETTE["text"],
                       highlightthickness=2, highlightbackground=PALETTE["border"],
                       highlightcolor=PALETTE["primary"], relief="flat")
        ent.pack(fill="x", padx=18, pady=(0,12), ipady=6)
        # 日本語IME入力でも確実に拾えるよう StringVar の変更を監視（デバウンス付き）
        self._debounce_id = None
        self.q_var.trace_add("write", lambda *a: self._schedule_search())
        ent.bind("<Return>", lambda e: self._on_query_change())
        self.win.after(200, ent.focus_set)

        self.count_var = tk.StringVar(value=f"全 {len(self.index)} 名")
        tk.Label(bar, textvariable=self.count_var, bg=PALETTE["panel"],
                 fg=PALETTE["accent_dk"], font=app._font(10, True)
                 ).pack(anchor="w", padx=18, pady=(0,10))

        # 結果スクロール領域
        body = tk.Frame(self.win, bg=PALETTE["bg"])
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=PALETTE["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.results_frame = tk.Frame(self.canvas, bg=PALETTE["bg"])
        self._win_id = self.canvas.create_window((0,0), anchor="nw",
                                                 window=self.results_frame)
        self.results_frame.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win_id, width=e.width))
        def _wheel(e):
            step = -1*int(e.delta) if IS_MAC else -1*int(e.delta/120)
            self.canvas.yview_scroll(step, "units")
        self.canvas.bind_all("<MouseWheel>", _wheel)

        self._render_results(self.index)
        # 初回描画を確実に反映（開いた直後に空白に見える問題の対策）
        self.win.after(50, self.win.update_idletasks)

    def _schedule_search(self):
        """入力のたびに即検索すると重いので250msのデバウンスをかける。"""
        if self._debounce_id is not None:
            try:
                self.win.after_cancel(self._debounce_id)
            except Exception:
                pass
        self._debounce_id = self.win.after(250, self._on_query_change)

    def _on_query_change(self):
        self._debounce_id = None
        q = self.q_var.get().strip()
        if not q:
            matches = self.index
            self.count_var.set(f"全 {len(matches)} 名")
        else:
            ql = q.lower()
            matches = []
            for rec in self.index:
                g, c, n, kanji, kana = rec
                hay = f"{kanji} {kana} {g}年{c}組{n}番 {n}".lower()
                # スペース除去でも一致するように
                if ql in hay or ql.replace(" ", "") in hay.replace(" ", ""):
                    matches.append(rec)
            self.count_var.set(f"該当 {len(matches)} 名")
        self._render_results(matches)

    def _render_results(self, matches):
        self._search_seq += 1
        for w in self.results_frame.winfo_children():
            w.destroy()
        self._thumb_refs.clear()
        if not matches:
            tk.Label(self.results_frame, text="該当する児童がいません",
                     bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                     font=self.app._font(12)).pack(pady=40)
            return
        # 多すぎる場合はサムネ生成を上限で抑える
        THUMB_LIMIT = 60
        rows = []
        for i, rec in enumerate(matches):
            rows.append(self._make_row(rec, with_thumb=(i < THUMB_LIMIT)))
        if len(matches) > THUMB_LIMIT:
            tk.Label(self.results_frame,
                     text=f"※ 写真表示は先頭{THUMB_LIMIT}名まで（絞り込んでください）",
                     bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                     font=self.app._font(9)).pack(pady=8)
        # サムネをバックグラウンドで生成
        self._start_thumb_loading(matches[:THUMB_LIMIT], rows, self._search_seq)

    def _make_row(self, rec, with_thumb=True):
        g, c, n, kanji, kana = rec
        row = tk.Frame(self.results_frame, bg=PALETTE["panel"],
                       highlightthickness=1, highlightbackground=PALETTE["border"])
        row.pack(fill="x", padx=12, pady=5)
        # サムネ枠
        thumb_h = int(96 / CELL_ASPECT)
        thumb_lbl = tk.Label(row, bg=PALETTE["panel_alt"],
                             width=96, height=thumb_h)
        thumb_lbl.pack(side="left", padx=10, pady=8)
        # 情報
        info = tk.Frame(row, bg=PALETTE["panel"])
        info.pack(side="left", fill="both", expand=True, padx=6, pady=8)
        tk.Label(info, text=f"{g}年 {c}組  {n}番", bg=PALETTE["panel"],
                 fg=PALETTE["accent_dk"], font=self.app._font(11, True),
                 anchor="w").pack(fill="x")
        tk.Label(info, text=kanji or "（名前未登録）", bg=PALETTE["panel"],
                 fg=PALETTE["text"], font=self.app._font(15, True),
                 anchor="w").pack(fill="x")
        tk.Label(info, text=kana, bg=PALETTE["panel"],
                 fg=PALETTE["text_dim"], font=self.app._font(10),
                 anchor="w").pack(fill="x")
        # ボタン
        btns = tk.Frame(row, bg=PALETTE["panel"])
        btns.pack(side="right", padx=10)
        MacButton(btns, "開く", lambda r=rec: self._open_student(r),
                  bg=PALETTE["primary"], fg="#ffffff",
                  font=self.app._font(10, True), padx=12, pady=6
                  ).pack(side="top", pady=3)
        MacButton(btns, "画像出力", lambda r=rec: self._export_student(r),
                  bg=PALETTE["accent"], fg="#ffffff",
                  font=self.app._font(10, True), padx=12, pady=6
                  ).pack(side="top", pady=3)
        return thumb_lbl

    def _start_thumb_loading(self, matches, thumb_labels, seq):
        def worker():
            for rec, lbl in zip(matches, thumb_labels):
                if seq != self._search_seq:
                    return  # 新しい検索が始まった → 中断
                g, c, n, _, _ = rec
                thumb = self.app._make_face_thumb(g, c, n, size=96)
                if thumb is None:
                    continue
                self.win.after(0, self._set_thumb, lbl, thumb, seq)
        self._thumb_thread = threading.Thread(target=worker, daemon=True)
        self._thumb_thread.start()

    def _set_thumb(self, lbl, pil_img, seq):
        if seq != self._search_seq:
            return
        try:
            tkimg = ImageTk.PhotoImage(pil_img)
            self._thumb_refs[id(lbl)] = tkimg
            lbl.configure(image=tkimg, width=pil_img.width, height=pil_img.height)
        except Exception:
            pass

    def _open_student(self, rec):
        g, c, n, _, _ = rec
        self._close()
        self.app.v_grade.set(str(g)); self.app.v_cls.set(str(c)); self.app.v_num.set(str(n))
        self.app.open_photo()
        # クラス一覧の選択も同期
        self.app._select_class_in_list(g, c)

    def _export_student(self, rec):
        g, c, n, kanji, kana = rec
        try:
            cropped = self.app._get_full_cropped(g, c, n)
        except Exception as e:
            messagebox.showerror("エラー", f"写真の読み込みに失敗しました\n{e}")
            return
        if cropped is None:
            messagebox.showerror("エラー", "写真が見つかりません")
            return
        card = render_id_card(cropped, g, c, n, kanji, kana)
        out_dir = os.path.join(self.app.base, "output", "顔写真")
        os.makedirs(out_dir, exist_ok=True)
        safe = (kanji or f"{n}番").replace(" ", "").replace("/", "_").replace(os.sep, "_")
        out_path = os.path.join(out_dir, f"{g}年{c}組_{n:02d}_{safe}.png")
        card.save(out_path)
        self.app._reveal_in_finder(out_path)
        messagebox.showinfo("出力完了", f"保存しました:\n{os.path.basename(out_path)}")

    def _close(self):
        if self._debounce_id is not None:
            try:
                self.win.after_cancel(self._debounce_id)
            except Exception:
                pass
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        self.app._modal_close()
        self.win.destroy()


# ════════════════════════════════════════════════════════
#  クラス一括調整画面
# ════════════════════════════════════════════════════════
class ClassBatchEditor:
    """クラス全員のサムネを見ながら、一括でクロップ値を調整する"""

    def __init__(self, parent_app, grade, cls):
        self.app = parent_app
        self.grade = grade
        self.cls = cls
        self.roster = self.app.roster_data.get((grade, cls), {})
        folder = find_class_folder(self.app.base, grade, cls)
        self.photos = collect_photos(folder, grade, cls) if folder else {}
        self.nums = sorted([n for n in self.photos.keys()])

        # 元の調整値スナップショット（戻すため）
        self.original = {}
        for n in self.nums:
            ov = self.app.overrides.get((grade, cls, n))
            if ov:
                self.original[n] = dict(ov)

        # キャッシュ
        self.image_cache = {}
        self.face_cache = {}

        # 作業中の値（連続編集対応）。初期は original または face_cache の値。
        # _load_and_refresh で正式に初期化される
        self.working = {}

        # 一括調整値（現在のスライダー差分）
        self.v_zoom_mult = tk.DoubleVar(value=1.0)
        self.v_top_add = tk.DoubleVar(value=0)
        self.v_left_add = tk.DoubleVar(value=0)

        self._thumb_widgets = {}  # num -> Frame
        self.selected = set()      # 選択中の生徒番号（空なら全員対象）
        self._last_clicked = None  # Shift+クリック用

        self.app._modal_open()
        self._build_ui()
        self._bind_keys()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self.win.after(100, self._load_and_refresh)

    def _on_close(self):
        """ウィンドウクローズ（×ボタン or キャンセル）"""
        self.app._modal_close()
        self.win.destroy()

    def _build_ui(self):
        win = tk.Toplevel(self.app.root)
        self.win = win
        win.title(f"{self.grade}年{self.cls}組 一括調整")
        win.configure(bg=PALETTE["bg"])
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        ww = min(960, int(sw * 0.85))
        wh = min(820, int(sh * 0.85))
        win.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")
        win.transient(self.app.root)

        # ヘッダー
        h = tk.Frame(win, bg=PALETTE["primary"], height=46)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text=f"  {self.grade}年 {self.cls}組  クラス一括調整",
                bg=PALETTE["primary"], fg="#ffffff",
                font=(system_font_family(), 14, "bold")
                ).pack(side="left", padx=20, pady=12)
        self.status_label = tk.Label(h, text="", bg=PALETTE["primary"],
                                    fg="#cce4ff", font=(system_font_family(), 11))
        self.status_label.pack(side="right", padx=20, pady=12)

        # 一括スライダーパネル
        ctrl = tk.Frame(win, bg=PALETTE["panel"],
                       highlightthickness=1, highlightbackground=PALETTE["border"])
        ctrl.pack(fill="x", padx=14, pady=(12, 8))

        tk.Label(ctrl, text="一括調整 (現在のクロップ値に対して)",
                bg=PALETTE["panel"], fg=PALETTE["text_label"],
                font=(system_font_family(), 11, "bold")
                ).pack(anchor="w", padx=14, pady=(10, 4))

        slid = tk.Frame(ctrl, bg=PALETTE["panel"])
        slid.pack(fill="x", padx=14, pady=(0, 10))

        # ズーム倍率
        zr = tk.Frame(slid, bg=PALETTE["panel"])
        zr.pack(side="left", padx=(0, 16))
        tk.Label(zr, text="ズーム倍率", bg=PALETTE["panel"],
                fg=PALETTE["text"], font=(system_font_family(), 10, "bold")
                ).pack(anchor="w")
        tk.Scale(zr, from_=0.5, to=2.0, resolution=0.05,
                orient="horizontal", variable=self.v_zoom_mult,
                length=200, bg=PALETTE["panel"],
                troughcolor=PALETTE["panel_alt"], highlightthickness=0,
                showvalue=True, font=(system_font_family(), 9),
                command=lambda v: self._schedule_refresh()
                ).pack()

        # 上下オフセット
        tr = tk.Frame(slid, bg=PALETTE["panel"])
        tr.pack(side="left", padx=16)
        tk.Label(tr, text="上下 (+=顔を上に)", bg=PALETTE["panel"],
                fg=PALETTE["text"], font=(system_font_family(), 10, "bold")
                ).pack(anchor="w")
        tk.Scale(tr, from_=-20, to=20, resolution=1,
                orient="horizontal", variable=self.v_top_add,
                length=200, bg=PALETTE["panel"],
                troughcolor=PALETTE["panel_alt"], highlightthickness=0,
                showvalue=True, font=(system_font_family(), 9),
                command=lambda v: self._schedule_refresh()
                ).pack()

        # 左右オフセット
        lr = tk.Frame(slid, bg=PALETTE["panel"])
        lr.pack(side="left", padx=16)
        tk.Label(lr, text="左右 (+=顔を左に)", bg=PALETTE["panel"],
                fg=PALETTE["text"], font=(system_font_family(), 10, "bold")
                ).pack(anchor="w")
        tk.Scale(lr, from_=-20, to=20, resolution=1,
                orient="horizontal", variable=self.v_left_add,
                length=200, bg=PALETTE["panel"],
                troughcolor=PALETTE["panel_alt"], highlightthickness=0,
                showvalue=True, font=(system_font_family(), 9),
                command=lambda v: self._schedule_refresh()
                ).pack()

        # リセットボタン
        rr = tk.Frame(slid, bg=PALETTE["panel"])
        rr.pack(side="left", padx=16)
        MacButton(rr, "↺ 未確定をゼロに", self._reset_sliders,
                 bg=PALETTE["neutral"], fg=PALETTE["text"],
                 font=(system_font_family(), 10), padx=12, pady=6
                ).pack(pady=(20, 0))

        # サムネエリア（スクロール可能）
        thumb_outer = tk.Frame(win, bg=PALETTE["bg"])
        thumb_outer.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        self.thumb_canvas = tk.Canvas(thumb_outer, bg=PALETTE["bg"],
                                     highlightthickness=0)
        sb = ttk.Scrollbar(thumb_outer, orient="vertical",
                          command=self.thumb_canvas.yview)
        self.thumb_canvas.configure(yscrollcommand=sb.set)
        self.thumb_canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.thumb_frame = tk.Frame(self.thumb_canvas, bg=PALETTE["bg"])
        self._thumb_window = self.thumb_canvas.create_window(
            (0, 0), window=self.thumb_frame, anchor="nw")

        # 空白クリックで選択解除
        def _on_blank_click(event):
            if self.selected:
                self._commit_sliders_to_working()
                self.selected.clear()
                self._last_clicked = None
                self._update_selection_visual()
                self._update_apply_label()
                self._refresh_thumbnails()
        self.thumb_canvas.bind("<Button-1>", _on_blank_click)
        self.thumb_frame.bind("<Button-1>", _on_blank_click)

        def _on_frame_config(e):
            self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all"))
        self.thumb_frame.bind("<Configure>", _on_frame_config)

        def _on_canvas_config(e):
            self.thumb_canvas.itemconfig(self._thumb_window, width=e.width)
        self.thumb_canvas.bind("<Configure>", _on_canvas_config)

        # マウスホイール
        def _wheel(e):
            if IS_MAC: step = -1 * int(e.delta)
            else: step = -1 * int(e.delta / 120)
            if step == 0: step = -1 if e.delta > 0 else 1
            self.thumb_canvas.yview_scroll(step, "units")
            return "break"
        self.thumb_canvas.bind("<MouseWheel>", _wheel)
        win.bind("<MouseWheel>", _wheel)

        # 下部ボタン
        btnf = tk.Frame(win, bg=PALETTE["bg"])
        btnf.pack(fill="x", padx=14, pady=(0, 12))

        tk.Label(btnf, text="※ ⌘/Ctrl+クリック=個別追加 / Shift+クリック=範囲 / ⌘/Ctrl+A=全選択 / Esc=解除 / 空白=解除\n"
                     "※ ↑↓←→=顔の移動 / Shift+↑↓=ズーム / 選択を変えると値が確定",
                bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                font=(system_font_family(), 9), justify="left"
                ).pack(side="left")

        MacButton(btnf, "キャンセル", self._on_close,
                 bg=PALETTE["neutral"], fg=PALETTE["text"],
                 font=(system_font_family(), 12), padx=16, pady=8
                ).pack(side="right", padx=4)
        self._apply_btn = MacButton(btnf, "✓ 適用", self._apply,
                 bg=PALETTE["success"], fg="#ffffff",
                 font=(system_font_family(), 12, "bold"), padx=20, pady=8)
        self._apply_btn.pack(side="right", padx=4)

    def _schedule_refresh(self):
        if hasattr(self, "_refresh_after_id") and self._refresh_after_id:
            try: self.win.after_cancel(self._refresh_after_id)
            except: pass
        self._refresh_after_id = self.win.after(300, self._refresh_thumbnails)

    def _bind_keys(self):
        """キー操作: 矢印で上下/左右オフセット、Shift+矢印でズーム、A/Dで選択クラスを移動"""
        w = self.win
        def step(var, delta, lo, hi):
            new = max(lo, min(hi, var.get() + delta))
            var.set(new)
            self._schedule_refresh()
        # 一括調整画面では「顔の動かしたい方向」と矢印を一致させる
        # ↑を押す → 顔を上に動かしたい → クロップ枠を下へ → top_add += 1
        w.bind("<Up>",         lambda e: step(self.v_top_add, +1, -20, 20))
        w.bind("<Down>",       lambda e: step(self.v_top_add, -1, -20, 20))
        w.bind("<Left>",       lambda e: step(self.v_left_add, +1, -20, 20))
        w.bind("<Right>",      lambda e: step(self.v_left_add, -1, -20, 20))
        w.bind("<Shift-Up>",   lambda e: step(self.v_zoom_mult, +0.05, 0.5, 2.0))
        w.bind("<Shift-Down>", lambda e: step(self.v_zoom_mult, -0.05, 0.5, 2.0))
        # Cmd+A で全選択
        if IS_MAC:
            w.bind("<Command-a>", lambda e: self._select_all())
        else:
            w.bind("<Control-a>", lambda e: self._select_all())
        w.bind("<Escape>", lambda e: self._clear_selection())

    def _select_all(self):
        self._commit_sliders_to_working()
        self.selected = set(self.nums)
        self._update_selection_visual()
        self._update_apply_label()
        self._refresh_thumbnails()
        return "break"

    def _clear_selection(self):
        self._commit_sliders_to_working()
        self.selected.clear()
        self._last_clicked = None
        self._update_selection_visual()
        self._update_apply_label()
        self._refresh_thumbnails()
        return "break"

    def _reset_sliders(self):
        """現在の未確定スライダー値だけ捨てる（作業値は保持）"""
        self.v_zoom_mult.set(1.0)
        self.v_top_add.set(0)
        self.v_left_add.set(0)
        self._refresh_thumbnails()

    def _load_and_refresh(self):
        """画像と顔検出を全員分読み込み、サムネを表示"""
        self.status_label.config(text="読み込み中...")
        self.win.update_idletasks()

        for i, n in enumerate(self.nums):
            try:
                img = make_proxy(fix_exif(Image.open(self.photos[n])))
                self.image_cache[n] = img
                self.face_cache[n] = auto_initial_crop_params(img)
            except Exception as e:
                print(f"画像読み込みエラー {n}: {e}")
            if i % 5 == 0:
                self.status_label.config(text=f"読み込み中... {i+1}/{len(self.nums)}")
                self.win.update_idletasks()

        # 作業中の値を初期化
        for n in self.nums:
            ov = self.original.get(n)
            if ov:
                self.working[n] = dict(ov)
            elif n in self.face_cache:
                t, l, z = self.face_cache[n]
                self.working[n] = {"top_pct": t, "left_pct": l, "zoom": z}
            else:
                self.working[n] = {"top_pct": 0, "left_pct": 0, "zoom": 1.0}

        self.status_label.config(text=f"{len(self.nums)}人")
        self._refresh_thumbnails()

    def _calc_values(self, n, force_apply=False):
        """生徒nの最終クロップ値を計算
        working値（永続）+ 現在のスライダー値（一時、選択中のみ）
        """
        if n not in self.working:
            return 0, 0, 1.0
        base = self.working[n]
        top = base["top_pct"]
        left = base["left_pct"]
        zoom = base["zoom"]

        # 選択中（or 何も選択されていなければ全員）にスライダー値を一時的に加算
        is_target = force_apply or (not self.selected) or (n in self.selected)
        if is_target:
            zm = self.v_zoom_mult.get()
            ta = self.v_top_add.get()
            la = self.v_left_add.get()
            top = max(0, min(100, top + ta))
            left = max(-50, min(50, left + la))
            zoom = max(1.0, min(5.0, zoom * zm))
        return top, left, zoom

    def _commit_sliders_to_working(self):
        """現在のスライダー値を、選択中の生徒の作業値に取り込む。スライダーは0/1.0にリセット"""
        zm = self.v_zoom_mult.get()
        ta = self.v_top_add.get()
        la = self.v_left_add.get()
        # 変化なしなら何もしない
        if abs(zm - 1.0) < 0.001 and abs(ta) < 0.01 and abs(la) < 0.01:
            return
        target = self.selected if self.selected else set(self.nums)
        for n in target:
            if n not in self.working: continue
            w = self.working[n]
            w["top_pct"]  = max(0, min(100, w["top_pct"] + ta))
            w["left_pct"] = max(-50, min(50, w["left_pct"] + la))
            w["zoom"]     = max(1.0, min(5.0, w["zoom"] * zm))
        # スライダーリセット
        self.v_zoom_mult.set(1.0)
        self.v_top_add.set(0)
        self.v_left_add.set(0)

    def _refresh_thumbnails(self):
        # 既存サムネ削除
        for w in self.thumb_frame.winfo_children():
            w.destroy()
        self._thumb_widgets.clear()

        # 6列のグリッド表示
        self._cols = 6
        thumb_w = 140
        thumb_h = int(thumb_w / 1.02)
        for idx, n in enumerate(self.nums):
            if n not in self.image_cache: continue
            row, col = divmod(idx, self._cols)
            cell = tk.Frame(self.thumb_frame, bg=PALETTE["panel"],
                          highlightthickness=2,
                          highlightbackground=PALETTE["border"],
                          cursor="hand2")
            cell.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

            top, left, zoom = self._calc_values(n)
            try:
                cropped = do_crop(self.image_cache[n], top, left, zoom)
                cropped_thumb = cropped.resize((thumb_w, thumb_h), Image.LANCZOS)
                photo_tk = ImageTk.PhotoImage(cropped_thumb)
                lbl = tk.Label(cell, image=photo_tk, bg=PALETTE["panel"],
                              cursor="hand2")
                lbl.image = photo_tk
                lbl.pack()
                # クリックイベントを画像とセルに
                for w in (cell, lbl):
                    w.bind("<Button-1>",
                          lambda e, num=n: self._on_thumb_click(e, num))
            except Exception as e:
                tk.Label(cell, text=f"err", bg=PALETTE["panel"],
                        fg=PALETTE["danger"], font=(system_font_family(), 9)
                        ).pack()

            name = self.roster.get(n, f"{n}番")
            short = name if len(name) <= 8 else name[:7] + "…"
            name_lbl = tk.Label(cell, text=f"{n:02d} {short}", bg=PALETTE["panel"],
                              fg=PALETTE["text"], font=(system_font_family(), 9),
                              cursor="hand2")
            name_lbl.pack(pady=(0, 4))
            name_lbl.bind("<Button-1>",
                         lambda e, num=n: self._on_thumb_click(e, num))

            self._thumb_widgets[n] = cell

        # 選択状態を反映
        self._update_selection_visual()
        self.thumb_frame.update_idletasks()
        self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all"))

    def _on_thumb_click(self, event, num):
        """サムネクリック: 選択処理。現在の値を作業値にコミットしてから選択切替"""
        # まず現在のスライダー値を選択中の生徒に確定
        self._commit_sliders_to_working()

        # macOS: Cmd = state & 0x0010 (Mod1) もしくは 0x00100000
        # Shift = state & 0x0001
        is_shift = bool(event.state & 0x0001)
        is_cmd = bool(event.state & 0x0008) or bool(event.state & 0x00100000) or bool(event.state & 0x0010)

        if is_shift and self._last_clicked is not None:
            # Shift+クリック: 範囲選択（前回クリックから今回までを追加）
            try:
                idx_a = self.nums.index(self._last_clicked)
                idx_b = self.nums.index(num)
                lo, hi = min(idx_a, idx_b), max(idx_a, idx_b)
                for i in range(lo, hi + 1):
                    self.selected.add(self.nums[i])
            except ValueError: pass
        elif is_cmd:
            # Cmd/Ctrl+クリック: 個別追加/削除（トグル）
            if num in self.selected:
                self.selected.discard(num)
            else:
                self.selected.add(num)
            self._last_clicked = num
        else:
            # 通常クリック: 単一選択（既選択なら解除）
            if num in self.selected and len(self.selected) == 1:
                self.selected.clear()
                self._last_clicked = None
            else:
                self.selected = {num}
                self._last_clicked = num

        self._update_selection_visual()
        self._update_apply_label()
        return "break"  # 親canvasに伝播させない

    def _update_selection_visual(self):
        """選択中サムネを青枠で強調"""
        for n, w in self._thumb_widgets.items():
            if n in self.selected:
                w.configure(highlightbackground=PALETTE["primary"],
                          highlightthickness=3)
            else:
                w.configure(highlightbackground=PALETTE["border"],
                          highlightthickness=1)

    def _update_apply_label(self):
        """適用ボタンのラベルを更新（実際は変更があった全員に適用するため固定）"""
        pass

    def _apply(self):
        """working から個別overrideに書き出す。元と差分のあるものだけ保存"""
        # 最後のスライダー値もコミット
        self._commit_sliders_to_working()

        # バックアップ
        if os.path.exists(self.app.override_path):
            bak = self.app.override_path + ".bak"
            try: shutil.copy2(self.app.override_path, bak)
            except: pass

        # 対象: 選択に関わらず「working が変化のあった全員」
        # （誤動作防止：選択していなくてもスライダー差分で動かしたものは保存対象）
        target_nums = []
        for n in self.nums:
            if n not in self.working: continue
            w = self.working[n]
            orig = self.original.get(n)
            if orig:
                diff = (abs(w["top_pct"] - orig["top_pct"]) > 0.05 or
                        abs(w["left_pct"] - orig["left_pct"]) > 0.05 or
                        abs(w["zoom"] - orig["zoom"]) > 0.005)
            else:
                # 未調整 → face_cacheの値と比較
                if n in self.face_cache:
                    t, l, z = self.face_cache[n]
                    diff = (abs(w["top_pct"] - t) > 0.05 or
                            abs(w["left_pct"] - l) > 0.05 or
                            abs(w["zoom"] - z) > 0.005)
                else:
                    diff = True
            if diff:
                target_nums.append(n)

        if not target_nums:
            messagebox.showinfo("情報", "変更されたデータがありません")
            return

        count = 0
        for n in target_nums:
            if n not in self.working: continue
            w = self.working[n]
            self.app.overrides[(self.grade, self.cls, n)] = {
                "top_pct": w["top_pct"],
                "left_pct": w["left_pct"],
                "zoom": w["zoom"],
            }
            count += 1

        save_overrides(self.app.override_path, self.app.overrides)
        self.app.saved_var.set(f"調整済み {len(self.app.overrides)}件")
        self.app._refresh_class_list()
        scope = f"変更のあった{count}人"
        self.app.status_var.set(f"  ✓ {self.grade}年{self.cls}組 {scope}を保存")

        # メインアプリの現在生徒もリロード
        if self.app.current_key:
            g, c, n = self.app.current_key
            if g == self.grade and c == self.cls and n in self.app.photos:
                self.app._load(g, c, n)

        messagebox.showinfo("適用完了",
            f"{scope}のクロップ値を保存しました\n"
            f"バックアップ: crop_overrides.csv.bak")
        self.app._modal_close()
        self.win.destroy()



# ════════════════════════════════════════════════════════
#  デザイン設定エディタ（色のカスタマイズ）
# ════════════════════════════════════════════════════════
class DesignEditor:
    """ポスターのカラーをカスタマイズする画面"""

    DEFAULTS = {
        "background":  "#f0f4fa",
        "card_bg":     "#f7f9fc",
        "label_bg":    "#2b5f8e",
        "label_fg":    "#ffffff",
        "number_fg":   "#e89c2a",
        "accent":      "#e89c2a",
        "header_bg":   "#1a4d80",
        "header_sub":  "#2b5f8e",
    }

    LABELS = {
        "background":  "ポスター背景",
        "card_bg":     "カード背景（写真の枠）",
        "label_bg":    "ネームタグ背景",
        "label_fg":    "ネームタグ文字",
        "number_fg":   "番号の色",
        "accent":      "アクセント色（区切り線）",
        "header_bg":   "ヘッダー背景",
        "header_sub":  "ヘッダー左側",
    }

    def __init__(self, parent_app):
        from tkinter import colorchooser
        self.colorchooser = colorchooser
        self.app = parent_app
        self.config_path = os.path.join(self.app.base, "design_config.json")
        self.config = self._load()
        self._color_buttons = {}
        self.app._modal_open()
        self._build_ui()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self.app._modal_close()
        self.win.destroy()

    def _load(self):
        import json
        cfg = dict(self.DEFAULTS)
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, encoding="utf-8") as f:
                    cfg.update(json.load(f))
            except: pass
        return cfg

    def _save(self):
        import json
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    def _build_ui(self):
        win = tk.Toplevel(self.app.root)
        self.win = win
        win.title("デザイン設定")
        win.configure(bg=PALETTE["bg"])
        sw = win.winfo_screenwidth(); sh = win.winfo_screenheight()
        ww, wh = 720, 640
        win.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")
        win.transient(self.app.root)

        # ヘッダー
        h = tk.Frame(win, bg=PALETTE["primary"], height=46)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🎨  デザイン設定",
                bg=PALETTE["primary"], fg="#ffffff",
                font=(system_font_family(), 14, "bold")
                ).pack(side="left", padx=20, pady=12)

        body = tk.Frame(win, bg=PALETTE["bg"])
        body.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(body, text="クリックで色を変更（保存するとPDFに反映）",
                bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                font=(system_font_family(), 11)
                ).pack(anchor="w", pady=(0, 12))

        # 各色のボタン
        for key, label in self.LABELS.items():
            row = tk.Frame(body, bg=PALETTE["panel"],
                          highlightthickness=1, highlightbackground=PALETTE["border"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, bg=PALETTE["panel"],
                    fg=PALETTE["text_label"], font=(system_font_family(), 11),
                    width=24, anchor="w", padx=14, pady=10
                    ).pack(side="left")
            color_val = self.config.get(key, self.DEFAULTS[key])
            sw_btn = tk.Frame(row, bg=color_val, width=80, height=28,
                            highlightthickness=1, highlightbackground=PALETTE["border"],
                            cursor="hand2")
            sw_btn.pack(side="left", padx=8, pady=10)
            sw_btn.pack_propagate(False)
            sw_btn.bind("<Button-1>", lambda e, k=key: self._pick_color(k))
            tk.Label(row, text=color_val, bg=PALETTE["panel"],
                    fg=PALETTE["text_dim"], font=("Menlo", 10),
                    width=10, anchor="w"
                    ).pack(side="left", padx=8)
            self._color_buttons[key] = sw_btn

        # ボタン
        btnf = tk.Frame(win, bg=PALETTE["bg"])
        btnf.pack(fill="x", padx=20, pady=(0, 16))
        MacButton(btnf, "↺ デフォルトに戻す", self._reset,
                 bg=PALETTE["neutral"], fg=PALETTE["text"],
                 font=(system_font_family(), 11), padx=14, pady=8
                ).pack(side="left")
        MacButton(btnf, "キャンセル", self._on_close,
                 bg=PALETTE["neutral"], fg=PALETTE["text"],
                 font=(system_font_family(), 12), padx=16, pady=8
                ).pack(side="right", padx=4)
        MacButton(btnf, "✓ 保存", self._on_save,
                 bg=PALETTE["success"], fg="#ffffff",
                 font=(system_font_family(), 12, "bold"), padx=20, pady=8
                ).pack(side="right", padx=4)

    def _pick_color(self, key):
        current = self.config.get(key, self.DEFAULTS[key])
        result = self.colorchooser.askcolor(color=current, parent=self.win,
                                            title=self.LABELS[key])
        if result and result[1]:
            self.config[key] = result[1]
            # ボタン全体を再描画（modal stackを正しく扱う）
            self.app._modal_close()
            self.win.destroy()
            DesignEditor(self.app)

    def _reset(self):
        if messagebox.askyesno("確認", "すべての色をデフォルトに戻しますか？"):
            self.config = dict(self.DEFAULTS)
            self.app._modal_close()
            self.win.destroy()
            DesignEditor(self.app)

    def _on_save(self):
        try:
            self._save()
            messagebox.showinfo("保存完了",
                f"デザイン設定を保存しました\n"
                f"次のPDF生成から反映されます\n\n{self.config_path}")
            self.app._modal_close()
            self.win.destroy()
        except Exception as e:
            messagebox.showerror("エラー", f"保存失敗: {e}")


# ════════════════════════════════════════════════════════
#  進捗ダイアログ
# ════════════════════════════════════════════════════════
class ProgressDialog:
    def __init__(self, parent, title="生成中...", output_dir=None, app=None):
        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.transient(parent)
        self.output_dir = output_dir
        self.app = app
        if self.app and hasattr(self.app, "_modal_open"):
            self.app._modal_open()
            self.win.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if self.app and hasattr(self.app, "_modal_close"):
            self.app._modal_close()
        self.win.destroy()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        ww, wh = 640, 420
        self.win.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")
        self.win.configure(bg=PALETTE["bg"])

        # ヘッダー
        h = tk.Frame(self.win, bg=PALETTE["primary"], height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text=title, bg=PALETTE["primary"], fg="#ffffff",
                font=(system_font_family(), 13, "bold")
                ).pack(side="left", padx=16, pady=10)

        # プログレスバー
        self.pb_var = tk.DoubleVar(value=0)
        style = ttk.Style()
        try:
            style.configure("PG.Horizontal.TProgressbar",
                          background=PALETTE["primary"],
                          troughcolor=PALETTE["panel_alt"])
        except: pass
        self.pb = ttk.Progressbar(self.win, orient="horizontal",
                                  mode="determinate",
                                  variable=self.pb_var, maximum=100,
                                  style="PG.Horizontal.TProgressbar")
        self.pb.pack(fill="x", padx=20, pady=(20,4))

        # ステータス
        self.status_var = tk.StringVar(value="開始しています...")
        tk.Label(self.win, textvariable=self.status_var,
                bg=PALETTE["bg"], fg=PALETTE["text"],
                font=(system_font_family(), 11),
                anchor="w", wraplength=600
                ).pack(fill="x", padx=20, pady=4)

        # ログ
        log_frame = tk.Frame(self.win, bg=PALETTE["bg"])
        log_frame.pack(fill="both", expand=True, padx=20, pady=(8,12))
        self.log = tk.Text(log_frame, font=("Menlo", 10),
                          bg=PALETTE["panel_alt"], fg=PALETTE["text"],
                          relief="flat", height=10, wrap="word")
        sb = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # ボタンエリア
        btn_frame = tk.Frame(self.win, bg=PALETTE["bg"])
        btn_frame.pack(fill="x", padx=20, pady=(0,16))
        self.close_btn = MacButton(btn_frame, "実行中...", self._on_close,
                                  bg=PALETTE["neutral"], fg=PALETTE["text_dim"],
                                  font=(system_font_family(), 12), padx=20, pady=8)
        self.close_btn.pack(side="right")
        # フォルダを開くボタン（成功時のみ表示）
        self._open_btn_frame = btn_frame
        self.open_folder_btn = None

    def update(self, percent=None, status=None, log=None):
        if percent is not None:
            self.pb_var.set(percent)
        if status:
            self.status_var.set(status)
        if log:
            self.log.insert("end", log + "\n")
            self.log.see("end")
        self.win.update_idletasks()

    def finish(self, message="完了", error=False):
        self.pb_var.set(100)
        if error:
            self.status_var.set("✗ " + message)
            self.close_btn.bg = PALETTE["danger"]
            self.close_btn.label.configure(bg=PALETTE["danger"], fg="#ffffff",
                                          text="閉じる")
            self.close_btn.configure(bg=PALETTE["danger"])
        else:
            self.status_var.set("✓ " + message)
            self.close_btn.bg = PALETTE["success"]
            self.close_btn.label.configure(bg=PALETTE["success"], fg="#ffffff",
                                          text="閉じる")
            self.close_btn.configure(bg=PALETTE["success"])
            # 「フォルダを開く」ボタンを成功時のみ追加
            if self.output_dir and os.path.exists(self.output_dir):
                self.open_folder_btn = MacButton(self._open_btn_frame,
                    "📂 フォルダを開く", self._open_folder,
                    bg=PALETTE["primary"], fg="#ffffff",
                    font=(system_font_family(), 12, "bold"), padx=20, pady=8)
                self.open_folder_btn.pack(side="right", padx=8)
        self.win.update_idletasks()

    def _open_folder(self):
        """OSに合わせてフォルダを開く"""
        if not self.output_dir or not os.path.exists(self.output_dir):
            return
        try:
            if IS_MAC:
                subprocess.Popen(["open", self.output_dir])
            elif sys.platform.startswith("win"):
                os.startfile(self.output_dir)
            else:
                subprocess.Popen(["xdg-open", self.output_dir])
        except Exception as e:
            messagebox.showerror("エラー", f"フォルダを開けませんでした: {e}")


# ════════════════════════════════════════════════════════
#  ポスター出力ウィザード
# ════════════════════════════════════════════════════════
class PosterWizard:
    """ポスター生成の設定をウィザード形式で行う"""

    def __init__(self, parent_app):
        self.app = parent_app
        self.root = tk.Toplevel(parent_app.root)
        self.root.title("ポスター出力設定")
        self.root.configure(bg=PALETTE["bg"])

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        ww, wh = 720, 640
        self.root.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")
        self.root.transient(parent_app.root)
        self.root.grab_set()

        # 設定値
        self.v_mode  = tk.StringVar(value="class")     # class / grade-a2 / grade-a1
        self.v_paper = tk.StringVar(value="A2")        # A2 / A1
        self.v_cols  = tk.IntVar(value=6)
        self.v_rows  = tk.IntVar(value=7)
        self.v_use_teacher = tk.BooleanVar(value=False)
        self.teachers_path = None  # CSV path

        self.step = 0
        self.steps = ["mode", "layout", "teacher", "confirm"]
        self.app._modal_open()
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self.app._modal_close()
        self.root.destroy()

    def _build(self):
        # ヘッダー
        h = tk.Frame(self.root, bg=PALETTE["primary"], height=50)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="ポスター出力設定", bg=PALETTE["primary"], fg="#ffffff",
                font=(system_font_family(), 14, "bold")
                ).pack(side="left", padx=20, pady=12)
        self.step_label = tk.Label(h, text="", bg=PALETTE["primary"],
                                  fg="#cce4ff", font=(system_font_family(), 11))
        self.step_label.pack(side="right", padx=20, pady=12)

        # コンテンツ
        self.content = tk.Frame(self.root, bg=PALETTE["bg"])
        self.content.pack(fill="both", expand=True, padx=24, pady=20)

        # フッター
        footer = tk.Frame(self.root, bg=PALETTE["panel"], height=64)
        footer.pack(fill="x", side="bottom"); footer.pack_propagate(False)
        self.btn_back = MacButton(footer, "← 戻る", self._back,
                                  bg=PALETTE["neutral"], fg=PALETTE["text"],
                                  font=(system_font_family(), 12), padx=16, pady=8)
        self.btn_back.pack(side="left", padx=14, pady=12)
        self.btn_cancel = MacButton(footer, "キャンセル", self._cancel,
                                   bg=PALETTE["neutral"], fg=PALETTE["text"],
                                   font=(system_font_family(), 12), padx=16, pady=8)
        self.btn_cancel.pack(side="left", padx=4, pady=12)
        self.btn_next = MacButton(footer, "次へ →", self._next,
                                 bg=PALETTE["primary"], fg="#ffffff",
                                 font=(system_font_family(), 12, "bold"), padx=20, pady=8)
        self.btn_next.pack(side="right", padx=14, pady=12)

        self._show_step()

    def _show_step(self):
        for w in self.content.winfo_children():
            w.destroy()
        self.step_label.config(text=f"ステップ {self.step+1} / {len(self.steps)}")
        s = self.steps[self.step]
        if s == "mode":     self._step_mode()
        elif s == "layout": self._step_layout()
        elif s == "teacher":self._step_teacher()
        elif s == "confirm":self._step_confirm()
        # ボタン状態
        self.btn_back.label.configure(text="← 戻る" if self.step > 0 else "")
        if self.step == 0:
            self.btn_back.pack_forget()
        else:
            self.btn_back.pack(side="left", padx=14, pady=12)
        self.btn_next.label.configure(text="生成 ✓" if self.step == len(self.steps)-1 else "次へ →")

    def _step_mode(self):
        c = self.content
        tk.Label(c, text="出力モードを選んでください",
                bg=PALETTE["bg"], fg=PALETTE["text_strong"],
                font=(system_font_family(), 16, "bold")
                ).pack(anchor="w", pady=(0, 8))
        tk.Label(c, text="ポスターの単位（クラスごと=A2 / 学年=ロール紙）を決めます",
                bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                font=(system_font_family(), 11)
                ).pack(anchor="w", pady=(0, 20))

        options = [
            ("class",     "A2", "クラスごと（A2縦、デフォルト）",
             "1クラス1枚のA2ポスター（420×594mm 縦置き）"),
            ("grade-a2",  "A2", "学年まとめて A2幅ロール紙",
             "幅594mm（A2の長辺）のロール紙に、各クラスをA2個別と同じレイアウトで縦に連結"),
            ("grade-a1",  "A1", "学年まとめて A1幅ロール紙",
             "幅841mm（A1の長辺）のロール紙に縦に連結。より大きく掲示できる"),
        ]
        for mode, paper, title, desc in options:
            row = tk.Frame(c, bg=PALETTE["panel"],
                          highlightthickness=2,
                          highlightbackground=PALETTE["border"])
            row.pack(fill="x", pady=6)
            rb = tk.Radiobutton(row, variable=self.v_mode, value=mode,
                              bg=PALETTE["panel"],
                              activebackground=PALETTE["panel"],
                              command=lambda m=mode, p=paper: self._on_mode_select(m, p))
            rb.pack(side="left", padx=14, pady=10)
            txt = tk.Frame(row, bg=PALETTE["panel"])
            txt.pack(side="left", fill="x", expand=True, pady=10)
            tk.Label(txt, text=title, bg=PALETTE["panel"],
                    fg=PALETTE["text_strong"],
                    font=(system_font_family(), 13, "bold"),
                    anchor="w").pack(fill="x")
            tk.Label(txt, text=desc, bg=PALETTE["panel"],
                    fg=PALETTE["text_dim"],
                    font=(system_font_family(), 11),
                    anchor="w").pack(fill="x")
            tk.Label(row, text=paper,
                    bg=PALETTE["accent_bg"], fg=PALETTE["accent_dk"],
                    font=(system_font_family(), 11, "bold"),
                    padx=10, pady=4).pack(side="right", padx=14, pady=14)

    def _on_mode_select(self, mode, paper):
        self.v_paper.set(paper)

    def _step_layout(self):
        c = self.content
        tk.Label(c, text="レイアウトを設定",
                bg=PALETTE["bg"], fg=PALETTE["text_strong"],
                font=(system_font_family(), 16, "bold")
                ).pack(anchor="w", pady=(0, 8))
        tk.Label(c, text="コマ数（行×列）を設定します。学年モードでは行数は人数に応じて自動調整されます",
                bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                font=(system_font_family(), 11)
                ).pack(anchor="w", pady=(0, 20))

        # プリセット
        preset_frame = tk.Frame(c, bg=PALETTE["bg"])
        preset_frame.pack(fill="x", pady=(0, 16))
        tk.Label(preset_frame, text="プリセット:", bg=PALETTE["bg"],
                fg=PALETTE["text_label"], font=(system_font_family(), 11, "bold")
                ).pack(side="left", padx=(0,12))
        for label, cols, rows in [("6×7 (42枠)", 6, 7),
                                   ("5×7 (35枠)", 5, 7),
                                   ("6×6 (36枠)", 6, 6),
                                   ("7×7 (49枠)", 7, 7)]:
            MacButton(preset_frame, label,
                     command=lambda c2=cols, r2=rows: self._set_layout(c2, r2),
                     bg=PALETTE["neutral"], fg=PALETTE["text"],
                     font=(system_font_family(), 11), padx=12, pady=6
                    ).pack(side="left", padx=4)

        # 詳細設定
        det = tk.Frame(c, bg=PALETTE["panel"],
                      highlightthickness=1,
                      highlightbackground=PALETTE["border"])
        det.pack(fill="x", pady=10, padx=2)
        det_inner = tk.Frame(det, bg=PALETTE["panel"], padx=20, pady=20)
        det_inner.pack(fill="x")

        for label, var, frm, to in [("列数", self.v_cols, 3, 10),
                                     ("行数", self.v_rows, 3, 12)]:
            row = tk.Frame(det_inner, bg=PALETTE["panel"])
            row.pack(fill="x", pady=8)
            tk.Label(row, text=label, bg=PALETTE["panel"],
                    fg=PALETTE["text_label"], font=(system_font_family(), 12, "bold"),
                    width=10, anchor="w").pack(side="left")
            tk.Spinbox(row, from_=frm, to=to, textvariable=var,
                      width=6, font=(system_font_family(), 13),
                      bg=PALETTE["input_bg"], fg=PALETTE["text"],
                      relief="flat", highlightthickness=1,
                      highlightbackground=PALETTE["border"]
                     ).pack(side="left", padx=8)

        # 説明
        tk.Label(c,
                text="※ 学年モードでは、行数は1学年の人数によって自動的に拡張されます\n"
                     "※ 紙サイズは前のステップで決まりました（{}）".format(self.v_paper.get()),
                bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                font=(system_font_family(), 10), justify="left"
                ).pack(anchor="w", pady=(20, 0))

    def _set_layout(self, cols, rows):
        self.v_cols.set(cols)
        self.v_rows.set(rows)

    def _step_teacher(self):
        c = self.content
        tk.Label(c, text="担任情報",
                bg=PALETTE["bg"], fg=PALETTE["text_strong"],
                font=(system_font_family(), 16, "bold")
                ).pack(anchor="w", pady=(0, 8))
        tk.Label(c, text="担任の情報をポスターに含めるかどうか選択します（オプション）",
                bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                font=(system_font_family(), 11)
                ).pack(anchor="w", pady=(0, 20))

        # 含めるかチェック
        cb_frame = tk.Frame(c, bg=PALETTE["panel"],
                           highlightthickness=1,
                           highlightbackground=PALETTE["border"])
        cb_frame.pack(fill="x", pady=8, padx=2)
        tk.Checkbutton(cb_frame, text="担任情報をポスターに含める",
                      variable=self.v_use_teacher,
                      bg=PALETTE["panel"], fg=PALETTE["text"],
                      activebackground=PALETTE["panel"],
                      selectcolor=PALETTE["accent_bg"],
                      font=(system_font_family(), 13, "bold"),
                      padx=20, pady=14
                     ).pack(anchor="w")

        # 説明
        info = tk.Frame(c, bg=PALETTE["accent_bg"])
        info.pack(fill="x", pady=20)
        tk.Label(info, text="📝 担任情報の準備方法",
                bg=PALETTE["accent_bg"], fg=PALETTE["accent_dk"],
                font=(system_font_family(), 12, "bold"),
                padx=14, pady=(10, 4), anchor="w"
                ).pack(fill="x")
        info_text = (
            "担任情報を使う場合、写真フォルダに teachers.csv ファイルを作成してください。\n"
            "形式（1行目はヘッダー）:\n"
            "  grade,cls,name,photo\n"
            "  1,1,山田太郎,teacher_photos/1-1.jpg\n"
            "  1,2,佐藤花子,teacher_photos/1-2.jpg\n"
            "  ...\n"
            "photo列はオプション（写真がない場合は名前のみ表示）"
        )
        tk.Label(info, text=info_text,
                bg=PALETTE["accent_bg"], fg=PALETTE["text"],
                font=("Menlo", 10),
                padx=14, pady=(0, 12), anchor="w", justify="left"
                ).pack(fill="x")

        # CSVファイル選択
        path_frame = tk.Frame(c, bg=PALETTE["bg"])
        path_frame.pack(fill="x", pady=8)
        tk.Label(path_frame, text="teachers.csv のパス:",
                bg=PALETTE["bg"], fg=PALETTE["text_label"],
                font=(system_font_family(), 11)
                ).pack(anchor="w")
        # 自動検出
        auto_path = os.path.join(self.app.base, "teachers.csv")
        if os.path.exists(auto_path):
            self.teachers_path = auto_path
            tk.Label(path_frame, text=f"✓ 自動検出: {auto_path}",
                    bg=PALETTE["bg"], fg=PALETTE["success_dk"],
                    font=(system_font_family(), 10), anchor="w"
                    ).pack(fill="x", pady=4)
        else:
            tk.Label(path_frame, text=f"（teachers.csv は写真フォルダ直下に配置してください）",
                    bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                    font=(system_font_family(), 10), anchor="w"
                    ).pack(fill="x", pady=4)

    def _step_confirm(self):
        c = self.content
        tk.Label(c, text="設定の確認",
                bg=PALETTE["bg"], fg=PALETTE["text_strong"],
                font=(system_font_family(), 16, "bold")
                ).pack(anchor="w", pady=(0, 8))
        tk.Label(c, text="以下の設定でポスターを生成します",
                bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                font=(system_font_family(), 11)
                ).pack(anchor="w", pady=(0, 20))

        mode_label = {
            "class": "クラスごと（A2縦）",
            "grade-a2": "学年ロール紙（A2幅594mm）",
            "grade-a1": "学年ロール紙（A1幅841mm）",
        }[self.v_mode.get()]

        items = [
            ("出力モード", mode_label),
            ("紙サイズ",   self.v_paper.get()),
            ("レイアウト", f"{self.v_cols.get()}列 × {self.v_rows.get()}行"),
            ("担任情報",   "含める" if self.v_use_teacher.get() else "含めない"),
        ]
        if self.v_use_teacher.get() and self.teachers_path:
            items.append(("teachers.csv", Path(self.teachers_path).name))

        for label, value in items:
            row = tk.Frame(c, bg=PALETTE["panel"],
                          highlightthickness=1,
                          highlightbackground=PALETTE["border"])
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, bg=PALETTE["panel"],
                    fg=PALETTE["text_dim"],
                    font=(system_font_family(), 11),
                    width=14, anchor="w", padx=14, pady=10
                    ).pack(side="left")
            tk.Label(row, text=value, bg=PALETTE["panel"],
                    fg=PALETTE["text_strong"],
                    font=(system_font_family(), 12, "bold"),
                    anchor="w", padx=14, pady=10
                    ).pack(side="left", fill="x", expand=True)

    def _back(self):
        if self.step > 0:
            self.step -= 1
            self._show_step()

    def _next(self):
        if self.step < len(self.steps)-1:
            self.step += 1
            self._show_step()
        else:
            self._execute()

    def _cancel(self):
        self._on_close()

    def _execute(self):
        """設定でポスター生成スクリプトを呼ぶ"""
        args = ["--mode", self.v_mode.get(), "--paper", self.v_paper.get()]
        if self.v_mode.get() == "class":
            args += ["--cols", str(self.v_cols.get()), "--rows", str(self.v_rows.get())]
        if self.v_use_teacher.get() and self.teachers_path:
            args += ["--teachers", self.teachers_path]
        # ウィザードを閉じてからPDF生成（進捗ダイアログが新たにmodalを取る）
        self.app._modal_close()
        self.root.destroy()
        self.app._run_poster(args, "  ⏳ ウィザードの設定でポスター生成中...")

# ════════════════════════════════════════════════════════
def _last_base_path():
    """last_base.txt のパスを返す（.app と スクリプト起動で別々に保存）"""
    if getattr(sys, 'frozen', False):
        d = os.path.expanduser("~/.crop_adjuster")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "last_base.txt")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_base.txt")

def _load_last_base():
    p = _last_base_path()
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            val = f.read().strip()
            if os.path.isdir(val):
                return val
    return None

def _save_last_base(base):
    with open(_last_base_path(), "w", encoding="utf-8") as f:
        f.write(base)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None,
                    help="写真フォルダのパス（省略時はダイアログで選択）")
    ap.add_argument("--overrides", default=None)
    # macOS が -psn_X_XXXXX を渡す場合があるので known_args で受け取る
    args, _ = ap.parse_known_args()

    base = args.base

    # --base 未指定（.appダブルクリック起動など）→ フォルダ選択ダイアログ
    if not base or not os.path.isdir(base):
        # 小さなダミーウィンドウを出してからダイアログを開く（macOS対策）
        tmp = tk.Tk()
        tmp.withdraw()
        last = _load_last_base()
        from tkinter import filedialog
        base = filedialog.askdirectory(
            title="クラス個人写真フォルダを選択してください",
            initialdir=last or os.path.expanduser("~")
        )
        tmp.destroy()
        if not base:
            return   # キャンセルされたら終了

    _save_last_base(base)
    override_path = args.overrides or os.path.join(base, "crop_check", "crop_overrides.csv")
    root = tk.Tk()
    app = CropAdjusterApp(root, base, override_path)
    root.mainloop()

if __name__ == "__main__":
    main()
