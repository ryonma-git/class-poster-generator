#!/usr/bin/env python3
"""
クラス個人写真 A2ポスター生成スクリプト v8
使い方:
  python make_poster_v8.py --base . --out ./output
  python make_poster_v8.py --base . --grade 1 --cls 1 --out ./output
"""

import os, glob, math, io, argparse, re, subprocess
from pathlib import Path
import pandas as pd
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A0, A1, A2, A3, A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# ════════════════════════════════════════════
#  レイアウト
# ════════════════════════════════════════════
A0_W, A0_H = A0
A1_W, A1_H = A1
A2_W, A2_H = A2
A3_W, A3_H = A3
A4_W, A4_H = A4

# 用紙サイズ辞書（pt単位、縦置き）— A0〜A4 を一元管理
PAPER_SIZES = {
    "A0": A0,
    "A1": A1,
    "A2": A2,
    "A3": A3,
    "A4": A4,
}
MM         = 72 / 25.4
MARGIN_X   = 15 * MM
MARGIN_TOP = 18 * MM
MARGIN_BOT = 12 * MM
HEADER_H   = 25 * MM
GAP_COL    =  5 * MM
GAP_ROW    =  6 * MM
LABEL_H    = 18 * MM
DEFAULT_COLS = 6
DEFAULT_ROWS = 7    # クラス単位ポスターのデフォルト行数

# ════════════════════════════════════════════
#  カラー
# ════════════════════════════════════════════
C_HDR_BG  = (0x2B,0x5F,0x8E)
C_HDR_SUB = (0x4A,0x90,0xC4)
C_ACCENT  = (0xE8,0x9C,0x2A)
def load_design_config(base):
    """design_config.json を読み込み、なければデフォルト"""
    import json
    defaults = {
        "background":  "#f0f4fa",
        "card_bg":     "#f7f9fc",
        "label_bg":    "#2b5f8e",
        "label_fg":    "#ffffff",
        "number_fg":   "#e89c2a",
        "accent":      "#e89c2a",
        "header_bg":   "#1a4d80",
        "header_sub":  "#2b5f8e",
    }
    cfg_path = os.path.join(base, "design_config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                user_cfg = json.load(f)
                defaults.update(user_cfg)
        except: pass
    return defaults


def hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


C_CARD    = (0xF7,0xF9,0xFC)
C_LBL_BG  = (0x2B,0x5F,0x8E)
C_LBL_FG  = (0xFF,0xFF,0xFF)
C_NUM_FG  = (0xE8,0x9C,0x2A)
C_BG      = (0xEE,0xF3,0xF8)
C_TCH_BG  = (0x4A,0x90,0xC4)

# ════════════════════════════════════════════
#  名簿列（C=学年 D=組 E=番号 R=ふりがな）
# ════════════════════════════════════════════
COL_GRADE=2; COL_CLS=3; COL_NUM=4; COL_NAME=17

# ════════════════════════════════════════════
#  フォント（macOS・Linux 両対応）
# ════════════════════════════════════════════
FONT_CANDIDATES = [
    # macOS ヒラギノ（丸ゴシック系 → 教育現場向け）
    "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
    "/System/Library/Fonts/Hiragino Sans W3.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/Library/Fonts/ヒラギノ角ゴ Pro W3.otf",
    # UDデジタル教科書体（お持ちの場合は優先）
    "/Library/Fonts/UDDigiKyokashoProN-Regular.otf",
    "C:/Windows/Fonts/UDDigiKyokashoN-R.ttc",
    # Linux フォールバック
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
]

_font_path = None
def get_font_path():
    global _font_path
    if _font_path is None:
        for p in FONT_CANDIDATES:
            if p and os.path.exists(p):
                _font_path = p
                print(f"  フォント: {Path(p).name}")
                break
    return _font_path

def get_font(size):
    p = get_font_path()
    if p:
        try:
            return ImageFont.truetype(p, max(10, int(size)))
        except:
            pass
    return ImageFont.load_default()

def fit_font(draw, text, max_w, max_size, min_size=12):
    """テキストが max_w に収まる最大フォントサイズを返す"""
    for size in range(int(max_size), min_size - 1, -1):
        f = get_font(size)
        b = draw.textbbox((0, 0), text, font=f)
        if (b[2] - b[0]) <= max_w:
            return size, f
    return min_size, get_font(min_size)

# ════════════════════════════════════════════
#  名簿ファイル自動検出
# ════════════════════════════════════════════
def find_roster_file(base):
    candidates = [
        f for f in
        glob.glob(os.path.join(base, "*.xls")) +
        glob.glob(os.path.join(base, "*.xlsx"))
        if not Path(f).name.startswith(("~$", ".", "_"))
        and "__MACOSX" not in f
    ]
    if len(candidates) == 1:
        print(f"  名簿自動検出: {Path(candidates[0]).name}")
        return candidates[0]
    if len(candidates) > 1:
        names = "\n    ".join(Path(f).name for f in candidates)
        raise RuntimeError(f"名簿Excelが複数あります。--roster で指定してください:\n    {names}")
    return None

# ════════════════════════════════════════════
#  名簿読み込み
# ════════════════════════════════════════════
def load_master_roster(path):
    ext = Path(path).suffix.lower()
    if ext == '.xls':
        try:
            import xlrd
            wb = xlrd.open_workbook(path)
            ws = wb.sheet_by_index(0)
            rows = [ws.row_values(i) for i in range(ws.nrows)]
            df = pd.DataFrame(rows[1:], columns=rows[0])
        except Exception as e:
            raise RuntimeError(f"xls読み込み失敗: {e}\n  ファイルを.xlsxで保存し直してください")
    else:
        df = pd.read_excel(path, header=0)

    # 列確認
    print(f"  列確認: 学年={df.columns[COL_GRADE]} | 組={df.columns[COL_CLS]} | "
          f"番号={df.columns[COL_NUM]} | 名前={df.columns[COL_NAME]}")
    print(f"  サンプル: {df.iloc[0,COL_GRADE]}年{df.iloc[0,COL_CLS]}組"
          f"{df.iloc[0,COL_NUM]}番 {df.iloc[0,COL_NAME]}")

    sub = df.iloc[:, [COL_GRADE, COL_CLS, COL_NUM, COL_NAME]].copy()
    sub.columns = ["学年","組","番号","氏名"]
    sub = sub.dropna(subset=["学年","組","番号"])
    sub["学年"] = sub["学年"].astype(int)
    sub["組"]   = sub["組"].astype(int)
    sub["番号"] = sub["番号"].astype(int)
    sub["氏名"] = sub["氏名"].fillna("").astype(str).str.strip()

    result = {}
    for _, row in sub.iterrows():
        result.setdefault((row["学年"], row["組"]), {})[row["番号"]] = row["氏名"]

    total = sum(len(v) for v in result.values())
    print(f"  読込完了: {len(result)}クラス / {total}人")
    return result


# ════════════════════════════════════════════
#  overrides 読み込み
# ════════════════════════════════════════════
def load_overrides_csv(path):
    """crop_overrides.csv を読み込んで {(g,c,n): {top_pct, left_pct, zoom}} を返す"""
    import csv as _csv
    d = {}
    if not path or not os.path.exists(path):
        return d
    with open(path, encoding='utf-8-sig') as f:
        for row in _csv.DictReader(f):
            try:
                k = (int(row['grade']), int(row['cls']), int(row['num']))
                d[k] = {
                    'top_pct':  float(row.get('top_pct',  0) or 0),
                    'left_pct': float(row.get('left_pct', 0) or 0),
                    'zoom':     float(row.get('zoom',     1) or 1),
                }
            except: pass
    return d


def load_teachers_csv(path):
    """teachers.csv を {(grade,cls): {name, photo}} で返す"""
    import csv as _csv
    d = {}
    if not path or not os.path.exists(path):
        return d
    with open(path, encoding='utf-8-sig') as f:
        for row in _csv.DictReader(f):
            try:
                k = (int(row['grade']), int(row['cls']))
                d[k] = {
                    'name':  row.get('name', '').strip(),
                    'photo': row.get('photo', '').strip(),
                }
            except: pass
    return d

# ════════════════════════════════════════════
#  フォルダ走査
# ════════════════════════════════════════════
def _parse_folder(name):
    m = re.search(r'(\d+)\s*年\s*(\d+)\s*組', name)
    if m: return m.group(1), m.group(2)
    m = re.search(r'(\d+)\s*組', name)
    if m: return None, m.group(1)
    return None, None

def find_all_classes(base):
    results = []
    for root, dirs, files in os.walk(base):
        if not any(f.lower().endswith(('.jpg','.jpeg','.png','.heic')) for f in files):
            continue
        parts = Path(os.path.relpath(root, base)).parts
        g, c = _parse_folder(parts[-1])
        if not g:
            for part in reversed(parts[:-1]):
                m = re.search(r'(\d+)\s*年', part)
                if m: g = m.group(1); break
        if g and c:
            results.append((int(g), int(c), root))
    return sorted(results)

def find_class_folder(base, grade, cls):
    for g, c, folder in find_all_classes(base):
        if g == grade and c == cls:
            return folder
    return os.path.join(base, f"{grade}年", f"{grade}年{cls}組")

# ════════════════════════════════════════════
#  HEIC変換
# ════════════════════════════════════════════
def convert_heic_in_folder(folder):
    heics = (glob.glob(os.path.join(folder, "*.heic")) +
             glob.glob(os.path.join(folder, "*.HEIC")))
    n = 0
    for src in heics:
        dst = os.path.splitext(src)[0] + ".jpg"
        if os.path.exists(dst): continue
        ok = False
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            Image.open(src).convert("RGB").save(dst, "JPEG", quality=92)
            ok = True
        except: pass
        if not ok:
            try:
                r = subprocess.run(
                    ["sips","-s","format","jpeg",src,"--out",dst],
                    capture_output=True, timeout=30)
                ok = r.returncode == 0 and os.path.exists(dst)
            except: pass
        if ok: n += 1
        else: print(f"    ⚠ HEIC変換失敗: {Path(src).name}")
    return n

def collect_photos(folder, grade, cls):
    n = convert_heic_in_folder(folder)
    if n: print(f"    HEIC→JPG変換: {n}件")
    prefix = f"{grade}{cls}"
    photos = {}
    for ext in ['.jpg','.jpeg','.JPG','.JPEG','.png','.PNG']:
        for f in glob.glob(os.path.join(folder, f"{prefix}*{ext}")):
            stem = Path(f).stem
            if not stem.startswith(prefix): continue
            try:
                num = int(stem[len(prefix):])
                if num not in photos:
                    photos[num] = f
            except: pass
    return photos

# ════════════════════════════════════════════
#  顔検出・クロップ
# ════════════════════════════════════════════
_cascade = None
def get_cascade():
    global _cascade
    if _cascade is None:
        _cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    return _cascade

def fix_exif_rotation(pil_img):
    """EXIF情報に基づいて回転補正"""
    try:
        from PIL import ExifTags
        exif = pil_img._getexif()
        if exif:
            for tag, val in exif.items():
                if ExifTags.TAGS.get(tag) == 'Orientation':
                    rotations = {3: 180, 6: 270, 8: 90}
                    if val in rotations:
                        return pil_img.rotate(rotations[val], expand=True)
    except: pass
    return pil_img

def detect_face(pil_img):
    """
    顔検出。複数パラメータで試みて最大の顔を返す。
    Returns: (fx, fy, fw, fh) or None
    """
    w, h = pil_img.size
    rgb  = np.array(pil_img.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # コントラスト均一化で暗い写真にも対応
    gray_eq = cv2.equalizeHist(gray)

    min_face = max(20, int(min(w, h) * 0.05))

    for img_g in [gray, gray_eq]:
        for scale in [1.05, 1.08, 1.12, 1.15]:
            for neighbors in [3, 4, 5]:
                faces = get_cascade().detectMultiScale(
                    img_g, scaleFactor=scale,
                    minNeighbors=neighbors,
                    minSize=(min_face, min_face))
                if len(faces) > 0:
                    # 最大の顔
                    return sorted(faces, key=lambda f: f[2]*f[3], reverse=True)[0]
    return None

def smart_crop(pil_img, target_w, target_h, override=None, zoom_multiplier=1.0, top_offset=0, left_offset=0):
    """
    学校個人写真向けクロップ。
    aspect は target_w/target_h（PDF実際の写真エリア比率）で動的計算
    """
    w, h = pil_img.size
    aspect = target_w / target_h

    # ── ベースサイズ計算（zoom=1.0時の最大枠） ──
    if w / h < aspect:
        base_w = w
        base_h = base_w / aspect
    else:
        base_h = h
        base_w = base_h * aspect

    # ── パラメータ決定 ──
    if override is not None:
        top_pct  = override.get('top_pct',  0)
        left_pct = override.get('left_pct', 0)
        zoom     = override.get('zoom',     1.0)
        zoom = max(1.0, min(5.0, zoom * zoom_multiplier))
    else:
        # 自動：顔検出
        face = detect_face(pil_img)
        if face is not None:
            fx, fy, fw, fh = face
            face_cx = fx + fw / 2
            face_top = fy
            # 頭の上に余白（顔高さの50%）
            head_margin = fh * 0.4  # 頭上の余白（顔の40%）
            # クロップ高さは顔の高さ × 2.8倍（頭・余白を含むサイズ）
            desired_crop_h = fh * 2.2  # 顔の高さの2.2倍（アップ寄り）
            zoom = base_h / desired_crop_h
            zoom = max(1.0, min(5.0, zoom))
            # 全体ズーム倍率を適用
            zoom = max(1.0, min(5.0, zoom * zoom_multiplier))
            crop_h_actual = base_h / zoom
            # クロップ枠の上端を「顔上端 - 余白」に設定
            desired_y1 = max(0, face_top - head_margin)
            desired_y1 = min(desired_y1, h - crop_h_actual)
            top_pct = (desired_y1 / h) * 100
            # 左右は顔の中心
            left_pct = ((face_cx - w/2) / w) * 100
            left_pct = max(-50, min(50, left_pct))
        else:
            top_pct, left_pct, zoom = 0.0, 0.0, 1.0
            zoom = max(1.0, min(5.0, zoom * zoom_multiplier))

    # 全体オフセット適用
    top_pct = max(0, min(100, top_pct + top_offset))
    left_pct = max(-50, min(50, left_pct + left_offset))

    # ── 実クロップ範囲計算 ──
    crop_w = base_w / zoom
    crop_h = base_h / zoom
    cx = w/2 + w * left_pct/100
    cy = h * top_pct/100 + crop_h/2
    x1 = cx - crop_w/2
    y1 = cy - crop_h/2
    x1 = max(0, min(x1, w - crop_w))
    y1 = max(0, min(y1, h - crop_h))

    return pil_img.crop((int(x1), int(y1),
                         int(x1+crop_w), int(y1+crop_h))).resize(
        (target_w, target_h), Image.LANCZOS)


# ════════════════════════════════════════════
#  写真なしプレースホルダー
# ════════════════════════════════════════════
def make_placeholder(w, h):
    img = Image.new("RGB", (w, h), (230, 234, 244))
    d   = ImageDraw.Draw(img)
    for x in range(0, w, 16): d.line([(x,0),(x,h)], fill=(220,224,236), width=1)
    for y in range(0, h, 16): d.line([(0,y),(w,y)], fill=(220,224,236), width=1)
    cx = w//2; ir = int(min(w,h)*0.20); icy = int(h*0.36); bc = (172,180,200)
    d.ellipse([cx-ir, icy-ir, cx+ir, icy+ir], fill=bc)
    bt = icy+int(ir*0.85)
    d.polygon([(cx-int(ir*1.1),bt),(cx+int(ir*1.1),bt),
               (cx+int(ir*1.85),int(h*0.92)),(cx-int(ir*1.85),int(h*0.92))], fill=bc)
    f  = get_font(int(min(w,h)*0.09))
    tb = d.textbbox((0,0), "写真なし", font=f)
    d.text((cx-(tb[2]-tb[0])//2, int(h*0.72)), "写真なし", font=f, fill=(125,133,155))
    return img

# ════════════════════════════════════════════
#  角丸マスク
# ════════════════════════════════════════════
def rmask(size, r, top=True, bot=True):
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0,0,size[0]-1,size[1]-1], radius=r, fill=255)
    if not top: d.rectangle([0, 0, size[0]-1, r], fill=255)
    if not bot: d.rectangle([0, size[1]-1-r, size[0]-1, size[1]-1], fill=255)
    return m

# ════════════════════════════════════════════
#  生徒セル描画
# ════════════════════════════════════════════
def make_student_cell(img_path, cw, ch, lh, num, name, override=None, zoom_multiplier=1.0, top_offset=0, left_offset=0):
    R  = 18
    ph = ch - lh

    cell = Image.new("RGBA", (cw, ch), (0,0,0,0))
    cell.paste(Image.new("RGBA",(cw,ch), C_CARD+(255,)),
               mask=rmask((cw,ch), R))

    # ── 写真 ──
    if img_path and os.path.exists(img_path):
        try:
            pil   = fix_exif_rotation(Image.open(img_path))
            photo = smart_crop(pil, cw, ph, override=override, zoom_multiplier=zoom_multiplier, top_offset=top_offset, left_offset=left_offset)
        except:
            photo = make_placeholder(cw, ph)
    else:
        photo = make_placeholder(cw, ph)

    pa = photo.convert("RGBA")
    pa.putalpha(rmask((cw,ph), R, top=True, bot=False))
    cell.paste(pa, (0,0), pa)

    # ── ラベル ──
    lbl = Image.new("RGBA", (cw, lh), (0,0,0,0))
    lbl.paste(Image.new("RGBA",(cw,lh), C_LBL_BG+(255,)),
              mask=rmask((cw,lh), R, top=False, bot=True))
    ld  = ImageDraw.Draw(lbl)
    pad = int(cw * 0.05)
    cy  = lh // 2

    # 番号（ゴールド・小さめ）
    num_str = f"{num:02d}"
    f_num   = get_font(int(lh * 0.32))
    nb      = ld.textbbox((0,0), num_str, font=f_num)
    nw      = nb[2] - nb[0]
    ld.text((pad, cy), num_str, font=f_num, fill=C_NUM_FG+(255,), anchor="lm")

    # 名前（残り幅に収まるよう自動縮小）
    avail   = cw - nw - pad * 3
    _, f_nm = fit_font(ld, name, min(avail, int(cw*0.80)), int(lh*0.55))
    ld.text((pad+nw+pad, cy), name, font=f_nm, fill=C_LBL_FG+(255,), anchor="lm")

    cell.paste(lbl, (0, ph), lbl)
    ImageDraw.Draw(cell).line([(0,ph),(cw,ph)], fill=C_ACCENT+(200,), width=2)
    return cell

# ════════════════════════════════════════════
#  担任セル描画
# ════════════════════════════════════════════
def make_teacher_cell(cw, ch, lh, name, img_path=None, override=None,
                      zoom_multiplier=1.0, top_offset=0, left_offset=0):
    """担任セル。
    - img_path 未指定: 旧来の文字のみ（青地＋「担任」＋名前＋下バー）
    - img_path 指定: 児童セルと同形（写真上＋ラベル下）、ただし全体は teacherBg 色。
      Phase 6a で固めた iOS のレイアウトを移植。
    """
    R = 18
    cell = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

    # 写真あり分岐
    if img_path and os.path.exists(img_path):
        ph = ch - lh
        # ── 全体カード（担任色） ──
        cell.paste(Image.new("RGBA", (cw, ch), C_TCH_BG + (255,)),
                   mask=rmask((cw, ch), R))

        # ── 写真 ──
        try:
            pil = fix_exif_rotation(Image.open(img_path))
            photo = smart_crop(pil, cw, ph, override=override,
                               zoom_multiplier=zoom_multiplier,
                               top_offset=top_offset, left_offset=left_offset)
        except Exception:
            photo = make_placeholder(cw, ph)

        pa = photo.convert("RGBA")
        pa.putalpha(rmask((cw, ph), R, top=True, bot=False))
        cell.paste(pa, (0, 0), pa)

        # ── ラベル（teacherBg のまま） ──
        lbl = Image.new("RGBA", (cw, lh), (0, 0, 0, 0))
        lbl.paste(Image.new("RGBA", (cw, lh), C_TCH_BG + (255,)),
                  mask=rmask((cw, lh), R, top=False, bot=True))
        ld = ImageDraw.Draw(lbl)
        pad = int(cw * 0.05)
        cy = lh // 2

        # 「担」マーク（アクセント色、左）
        mark = "担"
        f_mark = get_font(int(lh * 0.32))
        mb = ld.textbbox((0, 0), mark, font=f_mark)
        mw = mb[2] - mb[0]
        ld.text((pad, cy), mark, font=f_mark, fill=C_ACCENT + (255,), anchor="lm")

        # 名前（右、白）
        avail = cw - mw - pad * 3
        _, f_nm = fit_font(ld, name, min(avail, int(cw * 0.80)), int(lh * 0.55))
        ld.text((pad + mw + pad, cy), name, font=f_nm,
                fill=(255, 255, 255, 255), anchor="lm")

        cell.paste(lbl, (0, ph), lbl)
        # ラベル上端のアクセント線（少し太め）
        ImageDraw.Draw(cell).line([(0, ph), (cw, ph)], fill=C_ACCENT + (220,), width=3)
        return cell

    # 写真なし — 旧来のレイアウト
    cell.paste(Image.new("RGBA", (cw, ch), C_TCH_BG + (255,)), mask=rmask((cw, ch), R))
    d = ImageDraw.Draw(cell)
    d.text((cw // 2, int(ch * 0.35)), "担　任",
           font=get_font(int(ch * 0.11)), fill=C_ACCENT + (220,), anchor="mm")
    _, fn = fit_font(d, name, int(cw * 0.84), int(ch * 0.12))
    d.text((cw // 2, int(ch * 0.56)), name, font=fn,
           fill=(255, 255, 255, 255), anchor="mm")
    d.rectangle([int(cw * 0.2), ch - 7, int(cw * 0.8), ch - 3],
                fill=C_ACCENT + (200,))
    return cell

# ════════════════════════════════════════════
#  ポスター生成（1クラス）
# ════════════════════════════════════════════
def _resolve_teacher_photo(folder, grade, cls, photo_hint=None):
    """担任写真のフルパスを返す。
    - photo_hint がフルパス相当なら最優先で利用
    - そうでなければ {folder}/担任/{g}{c}T01.{jpg,heic,JPG,HEIC} を順にトライ
      （iOS の撮影アプリが書き出すファイル名規約）
    """
    if photo_hint:
        if os.path.isabs(photo_hint) and os.path.exists(photo_hint):
            return photo_hint
        # folder からの相対も試す
        cand = os.path.join(folder, photo_hint)
        if os.path.exists(cand):
            return cand
        cand = os.path.join(folder, '担任', os.path.basename(photo_hint))
        if os.path.exists(cand):
            return cand
    # フォールバック自動検出
    teacher_dir = os.path.join(folder, '担任')
    if not os.path.isdir(teacher_dir):
        return None
    stem = f"{grade}{cls}T01"
    for ext in ('jpg', 'jpeg', 'heic', 'JPG', 'JPEG', 'HEIC'):
        p = os.path.join(teacher_dir, f"{stem}.{ext}")
        if os.path.exists(p):
            return p
    # T01 が無ければ 担任/ 内の最初の画像
    for name in sorted(os.listdir(teacher_dir)):
        if name.lower().endswith(('.jpg', '.jpeg', '.heic', '.png')):
            return os.path.join(teacher_dir, name)
    return None


def generate_poster(grade, cls, folder, out_dir, roster, teacher=None, overrides=None, cols=None, rows=None, paper='A1', zoom_multiplier=1.0, top_offset=0, left_offset=0, teacher_photo=None, use_teacher_photo=False):
    print(f"\n▶ {grade}年{cls}組  [{Path(folder).name}]")
    nums  = sorted(roster.keys())
    total = len(nums)
    if not total:
        print("  ⚠ 名簿データなし"); return

    photos      = collect_photos(folder, grade, cls)
    no_photo    = [n for n in nums if n not in photos]
    if no_photo:
        print(f"  写真なし: {no_photo}")

    cells_total = total + (1 if teacher else 0)
    use_cols = cols if cols else DEFAULT_COLS
    use_rows = rows if rows else DEFAULT_ROWS
    # 自動行数: 人数からの計算と固定値の最大
    auto_rows = math.ceil(cells_total / use_cols)
    final_rows = max(auto_rows, use_rows)

    # ── ピクセル計算（150dpi）──
    # 大判（A0/A1）は150dpi、小判（A3/A4）はファイルサイズ抑制のため200dpi相当に。
    # 用紙が小さいほど絶対ピクセルは小さくなるので印刷品質は維持できる。
    DPI = 150 if paper in ("A0", "A1", "A2") else 200
    P = DPI / 72.0
    page_w_pt, page_h_pt = PAPER_SIZES.get(paper, A1)
    pw, ph = int(page_w_pt * P), int(page_h_pt * P)
    mx = int(MARGIN_X*P);   mt = int(MARGIN_TOP*P)
    mb = int(MARGIN_BOT*P); hh = int(HEADER_H*P)
    gc = int(GAP_COL*P);    gr = int(GAP_ROW*P)
    lh = int(LABEL_H*P)

    cw = (pw - 2*mx - (use_cols-1)*gc) // use_cols
    # 紙面いっぱい：cw, ch をそれぞれ独立に計算
    available_h = (ph - mt - hh - mb) - (final_rows - 1) * gr
    ch = available_h // final_rows

    # ── ページ描画 ──
    page = Image.new("RGB", (pw,ph), C_BG)
    d    = ImageDraw.Draw(page)
    for xi in range(0,pw,40): d.line([(xi,0),(xi,ph)], fill=(220,228,238), width=1)
    for yi in range(0,ph,40): d.line([(0,yi),(pw,yi)], fill=(220,228,238), width=1)

    # ヘッダー
    ht = mt - int(4*P); ah = max(5, hh//14)
    d.rectangle([0,ht,pw,ht+hh], fill=C_HDR_BG)
    d.rectangle([0,ht+hh-ah,pw,ht+hh], fill=C_ACCENT)
    d.rectangle([0,ht,int(pw*0.28),ht+hh-ah], fill=C_HDR_SUB)
    cy_ = ht + (hh-ah)//2
    d.text((int(pw*0.32), cy_),
           f"{grade}年　{cls}組　個人写真一覧",
           font=get_font(int(hh*0.38)), fill=(255,255,255), anchor="lm")
    d.text((pw-mx, cy_), f"全{total}名",
           font=get_font(int(hh*0.24)), fill=C_ACCENT, anchor="rm")

    # 担任写真の解決（use_teacher_photo=True かつ photo が見つかれば写真ありセル）
    resolved_teacher_photo = None
    if use_teacher_photo and teacher:
        resolved_teacher_photo = _resolve_teacher_photo(folder, grade, cls, teacher_photo)
        if resolved_teacher_photo:
            print(f"  担任写真: {Path(resolved_teacher_photo).name}")
        else:
            print(f"  担任写真: 見つからず（文字のみセルにフォールバック）")

    # グリッド
    gt    = mt + hh + int(4*P)
    cells = ([("t", teacher)] if teacher else []) + [("s", n) for n in nums]

    # 担任写真の override は overrides[(grade, cls, 'T01')] で持つ（Phase 6b 拡張）
    teacher_override = (overrides or {}).get((grade, cls, 'T01'))

    for idx, (kind, val) in enumerate(cells):
        col = idx % use_cols; row = idx // use_cols
        x   = mx + col*(cw+gc)
        y   = gt + row*(ch+gr)
        if kind == "t":
            ci = make_teacher_cell(cw, ch, lh, val,
                                   img_path=resolved_teacher_photo,
                                   override=teacher_override,
                                   zoom_multiplier=zoom_multiplier,
                                   top_offset=top_offset, left_offset=left_offset)
        else:
            ov = (overrides or {}).get((grade, cls, val))
            ci = make_student_cell(photos.get(val), cw, ch, lh, val,
                                   roster.get(val, f"{val:02d}番"),
                                   override=ov, zoom_multiplier=zoom_multiplier,
                                   top_offset=top_offset, left_offset=left_offset)
        page.paste(ci.convert("RGB"), (x,y), ci)

    # フッター
    d.text((pw//2, ph-int(4*P)),
           f"{grade}年{cls}組　個人写真一覧",
           font=get_font(int(8*P)), fill=(160,170,185), anchor="mb")

    os.makedirs(out_dir, exist_ok=True)
    out  = os.path.join(out_dir, f"{grade}年{cls}組_クラスポスター.pdf")
    buf  = io.BytesIO()
    page.save(buf, format="PNG", dpi=(DPI,DPI))
    buf.seek(0)
    c = canvas.Canvas(out, pagesize=(page_w_pt, page_h_pt))
    c.drawImage(ImageReader(buf), 0, 0, width=page_w_pt, height=page_h_pt)
    c.save()
    print(f"  ✅ {total}名 → {Path(out).name}")


# ════════════════════════════════════════════
#  学年全クラス ロール紙ポスター
#  （A2/A1個別と同じレイアウト・セルサイズを保ったまま縦に連結）
# ════════════════════════════════════════════
def generate_grade_poster(grade, classes_data, out_dir, roster_master,
                          paper="A2", overrides=None, zoom_multiplier=1.0, top_offset=0, left_offset=0):
    """
    学年単位ポスター（ロール紙縦長出力）。
    paper="A2" → 幅594mm（A2の長辺）のロール
    paper="A1" → 幅841mm（A1の長辺）のロール
    各クラスのレイアウトは A2個別ポスター（420×594mm）と完全に同じ。
    そのレイアウトを上下に並べて、ロール紙幅に中央配置する。
    """
    print(f"\n▶ {grade}年生 ロール紙ポスター (幅{paper}＝", end="")
    if paper == "A1":
        roll_width_mm = 841   # A1の長辺
    else:
        roll_width_mm = 594   # A2の長辺
    print(f"{roll_width_mm}mm)")

    if not classes_data:
        print("  ⚠ クラスデータなし"); return

    # ── 1クラス分のサイズ ──
    # 縦横比はA2個別（420:594）を維持しつつ、ロール紙幅ギリギリまで拡大
    SIDE_MARGIN_MM = 10  # 片側余白
    class_w_mm = roll_width_mm - SIDE_MARGIN_MM * 2
    class_h_mm = class_w_mm * (594 / 420)  # A2比率を維持

    DPI = 150; P = DPI / 72.0

    # クラスデータ準備
    class_blocks = []
    total_students = 0
    for cls, folder in sorted(classes_data):
        roster = roster_master.get((grade, cls), {})
        if not roster: continue
        nums = sorted(roster.keys())
        photos = collect_photos(folder, grade, cls)
        class_blocks.append({
            "cls": cls, "folder": folder, "roster": roster,
            "nums": nums, "photos": photos
        })
        total_students += len(nums)

    if not class_blocks:
        print("  ⚠ 名簿データのあるクラスがありません"); return

    # ── ロール紙のサイズ（mm単位 → ポイント）──
    GAP_BETWEEN_CLASSES_MM = 30
    HEADER_TOP_MM = 0   # 全体ヘッダーは省略（各クラスにヘッダーがあるため）

    pw_mm = roll_width_mm
    ph_mm = (class_h_mm * len(class_blocks)
             + GAP_BETWEEN_CLASSES_MM * (len(class_blocks) - 1)
             + HEADER_TOP_MM)

    # ピクセルサイズ（150dpi）
    pw = int(pw_mm * MM * P)
    ph = int(ph_mm * MM * P)
    page_w_pt = pw_mm * MM
    page_h_pt = ph_mm * MM

    # 1クラスエリアのピクセルサイズ
    class_w_px = int(class_w_mm * MM * P)
    class_h_px = int(class_h_mm * MM * P)
    gap_px = int(GAP_BETWEEN_CLASSES_MM * MM * P)

    # クラスは中央寄せ → 左右に余白
    class_x_offset = (pw - class_w_px) // 2

    # ── ページキャンバス ──
    page = Image.new("RGB", (pw, ph), C_BG)
    d = ImageDraw.Draw(page)

    # 背景グリッド
    for xi in range(0, pw, 40): d.line([(xi,0),(xi,ph)], fill=(220,228,238), width=1)
    for yi in range(0, ph, 40): d.line([(0,yi),(pw,yi)], fill=(220,228,238), width=1)

    # 各クラスを縦に並べる（個別A2ポスターを再利用）
    for idx, blk in enumerate(class_blocks):
        cls = blk["cls"]
        # 個別A2ポスターを生成（同じロジック）
        class_img = _render_single_class_image(
            grade, cls, blk["folder"], blk["roster"], blk["photos"],
            None, overrides, zoom_multiplier,
            target_w=class_w_px, target_h=class_h_px,
            top_offset=top_offset, left_offset=left_offset)

        # 縦位置
        y_pos = idx * (class_h_px + gap_px)
        page.paste(class_img, (class_x_offset, y_pos))

        # クラス間の区切り線（最後以外）
        if idx < len(class_blocks) - 1:
            sep_y = y_pos + class_h_px + gap_px // 2
            d.line([(int(pw*0.1), sep_y), (int(pw*0.9), sep_y)],
                   fill=C_ACCENT, width=4)

    # 出力
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{grade}年生_ロール紙_{paper}幅{roll_width_mm}mm.pdf")
    buf = io.BytesIO()
    page.save(buf, format="PNG", dpi=(DPI, DPI))
    buf.seek(0)
    c = canvas.Canvas(out, pagesize=(page_w_pt, page_h_pt))
    c.drawImage(ImageReader(buf), 0, 0, width=page_w_pt, height=page_h_pt)
    c.save()
    print(f"  ✅ {len(class_blocks)}クラス {total_students}名 → {Path(out).name}")
    print(f"     仕上がりサイズ: {pw_mm}mm × {ph_mm}mm")


def _render_single_class_image(grade, cls, folder, roster, photos,
                                teacher, overrides, zoom_multiplier,
                                target_w, target_h, top_offset=0, left_offset=0):
    """
    1クラス分のポスターをPIL Imageとして返す（PDF化はしない）。
    個別A2ポスター generate_poster と同じレイアウトロジック。
    """
    nums = sorted(roster.keys())
    total = len(nums)

    cells_total = total + (1 if teacher else 0)
    use_cols = DEFAULT_COLS
    use_rows = DEFAULT_ROWS
    auto_rows = math.ceil(cells_total / use_cols)
    final_rows = max(auto_rows, use_rows)

    # 各値はターゲットサイズに合わせて再スケール（A2基準のまま）
    DPI = 150; P = DPI / 72.0
    pw, ph = target_w, target_h
    mx = int(MARGIN_X * P)
    mt = int(MARGIN_TOP * P)
    mb = int(MARGIN_BOT * P)
    hh = int(HEADER_H * P)
    gc = int(GAP_COL * P)
    gr = int(GAP_ROW * P)
    lh = int(LABEL_H * P)

    cw = (pw - 2*mx - (use_cols-1)*gc) // use_cols
    # 紙面いっぱい：cw, ch をそれぞれ独立に計算
    available_h = (ph - mt - hh - mb) - (final_rows - 1) * gr
    ch = available_h // final_rows

    # 1クラス分のキャンバス
    page = Image.new("RGB", (pw, ph), C_BG)
    d = ImageDraw.Draw(page)
    for xi in range(0, pw, 40): d.line([(xi,0),(xi,ph)], fill=(220,228,238), width=1)
    for yi in range(0, ph, 40): d.line([(0,yi),(pw,yi)], fill=(220,228,238), width=1)

    # ヘッダー
    ht = mt - int(4*P); ah = max(5, hh//14)
    d.rectangle([0,ht,pw,ht+hh], fill=C_HDR_BG)
    d.rectangle([0,ht+hh-ah,pw,ht+hh], fill=C_ACCENT)
    d.rectangle([0,ht,int(pw*0.28),ht+hh-ah], fill=C_HDR_SUB)
    cy_ = ht + (hh-ah)//2
    d.text((int(pw*0.32), cy_),
           f"{grade}年　{cls}組　個人写真一覧",
           font=get_font(int(hh*0.38)), fill=(255,255,255), anchor="lm")
    d.text((pw-mx, cy_), f"全{total}名",
           font=get_font(int(hh*0.24)), fill=C_ACCENT, anchor="rm")

    # グリッド
    gt = mt + hh + int(4*P)
    cells = ([("t", teacher)] if teacher else []) + [("s", n) for n in nums]
    for idx, (kind, val) in enumerate(cells):
        col = idx % use_cols; row = idx // use_cols
        x = mx + col*(cw+gc); y = gt + row*(ch+gr)
        if kind == "t":
            ci = make_teacher_cell(cw, ch, lh, val)
        else:
            ov = (overrides or {}).get((grade, cls, val))
            ci = make_student_cell(photos.get(val), cw, ch, lh, val,
                                   roster.get(val, f"{val:02d}番"),
                                   override=ov, zoom_multiplier=zoom_multiplier,
                                   top_offset=top_offset, left_offset=left_offset)
        page.paste(ci.convert("RGB"), (x, y), ci)

    return page


# ════════════════════════════════════════════
#  メイン
# ════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="クラス個人写真 A2ポスター生成 v8")
    ap.add_argument("--base",    required=True)
    ap.add_argument("--roster",  default=None,
                    help="名簿Excel（省略時はbaseフォルダから自動検出）")
    ap.add_argument("--out",     default="./output")
    ap.add_argument("--grade",   default=None, type=int)
    ap.add_argument("--cls",     default=None, type=int)
    ap.add_argument("--teacher", default=None)
    ap.add_argument("--overrides", default=None,
                    help="crop_overrides.csvのパス（省略時はcrop_check/crop_overrides.csvを自動検出）")
    ap.add_argument("--cols", type=int, default=None,
                    help="列数（クラス単位は6、学年単位は省略でクラス数になります）")
    ap.add_argument("--rows", type=int, default=None,
                    help="行数（省略時は人数に応じて自動）")
    ap.add_argument("--mode", choices=["class", "grade-a2", "grade-a1"], default="class",
                    help="出力モード: class=クラスごと（紙サイズは --paper で指定）、grade-a2/a1=学年ロール紙")
    ap.add_argument("--paper", choices=["A0", "A1", "A2", "A3", "A4"], default=None,
                    help="紙サイズ。class モード時のデフォルトは A1。grade モードはモード名側で決まる")
    ap.add_argument("--teachers", default=None,
                    help="担任情報CSV（grade,cls,name,photo の4列）")
    ap.add_argument("--teacher-photo", action="store_true",
                    help="担任セルに写真を入れる（Phase 6b）。{folder}/担任/{g}{c}T01.* を自動検出。")
    ap.add_argument("--zoom-multiplier", type=float, default=1.0,
                    help="全体ズーム倍率（1.0=標準、1.3=30%%アップ、0.8=20%%引き）")
    ap.add_argument("--top-offset", type=float, default=0,
                    help="全体の上下オフセット（%%、+で下に、-で上に）")
    ap.add_argument("--left-offset", type=float, default=0,
                    help="全体の左右オフセット（%%、+で右に、-で左に）")
    args = ap.parse_args()

    # 名簿特定
    rpath = args.roster or find_roster_file(args.base)
    if not rpath:
        print("⚠ 名簿Excelが見つかりません。--roster で指定してください")
        return

    print(f"\n名簿読み込み: {Path(rpath).name}")
    master = load_master_roster(rpath)

    # overrides 自動検出
    overrides_path = args.overrides
    if not overrides_path:
        default = os.path.join(args.base, "crop_check", "crop_overrides.csv")
        if os.path.exists(default):
            overrides_path = default
    overrides = load_overrides_csv(overrides_path) if overrides_path else {}
    if overrides:
        print(f"  手動調整: {len(overrides)}件読み込み（{Path(overrides_path).name}）")

    # 担任CSV
    teachers_path = args.teachers
    if not teachers_path:
        default_t = os.path.join(args.base, "teachers.csv")
        if os.path.exists(default_t):
            teachers_path = default_t
    teachers_data = load_teachers_csv(teachers_path) if teachers_path else {}
    if teachers_data:
        print(f"  担任情報: {len(teachers_data)}クラス分")

    # ★ デザイン設定を読み込む
    global C_CARD, C_LBL_BG, C_LBL_FG, C_NUM_FG, C_ACCENT, C_BG, C_HDR_BG, C_HDR_SUB
    design = load_design_config(args.base)
    try:
        C_CARD   = hex_to_rgb(design["card_bg"])
        C_LBL_BG = hex_to_rgb(design["label_bg"])
        C_LBL_FG = hex_to_rgb(design["label_fg"])
        C_NUM_FG = hex_to_rgb(design["number_fg"])
        C_ACCENT = hex_to_rgb(design["accent"])
        C_BG     = hex_to_rgb(design["background"])
        C_HDR_BG = hex_to_rgb(design["header_bg"])
        C_HDR_SUB= hex_to_rgb(design["header_sub"])
        print(f"  デザイン設定: design_config.json から読込")
    except Exception as e:
        print(f"  デザイン設定: デフォルト使用 ({e})")

    # 紙サイズ判定
    # class モードのデフォルトは A1（2026年度より変更）。
    # grade モードはモード名から決まる（grade-a1 → A1幅、grade-a2 → A2幅）。
    paper = args.paper
    if paper is None:
        if args.mode == "grade-a1":
            paper = "A1"
        elif args.mode == "grade-a2":
            paper = "A2"
        else:
            paper = "A1"  # class モードのデフォルト

    if args.mode in ("grade-a2", "grade-a1"):
        # 学年単位
        classes = find_all_classes(args.base)
        # 学年別にグループ化
        by_grade = {}
        for g, c, folder in classes:
            by_grade.setdefault(g, []).append((c, folder))
        if args.grade:
            grades_to_process = [args.grade] if args.grade in by_grade else []
        else:
            grades_to_process = sorted(by_grade.keys())
        print(f"学年単位ポスター生成: {len(grades_to_process)}学年（{paper}縦長）")
        for g in grades_to_process:
            generate_grade_poster(g, by_grade[g], args.out, master,
                                  paper=paper, overrides=overrides,
                                  zoom_multiplier=args.zoom_multiplier, top_offset=args.top_offset, left_offset=args.left_offset)
    elif args.grade and args.cls:
        # 単一クラス
        folder = find_class_folder(args.base, args.grade, args.cls)
        roster = master.get((args.grade, args.cls), {})
        if not roster:
            print(f"⚠ {args.grade}年{args.cls}組: 名簿なし"); return
        teacher_info = teachers_data.get((args.grade, args.cls), {})
        teacher = teacher_info.get('name') or args.teacher
        generate_poster(args.grade, args.cls, folder, args.out,
                        roster, teacher, overrides=overrides,
                        cols=args.cols, rows=args.rows, paper=paper,
                        zoom_multiplier=args.zoom_multiplier, top_offset=args.top_offset, left_offset=args.left_offset,
                        teacher_photo=teacher_info.get('photo'),
                        use_teacher_photo=args.teacher_photo)
    else:
        # 全クラス（クラス単位）
        classes = find_all_classes(args.base)
        print(f"写真フォルダ検出: {len(classes)}クラス（{paper}）")
        for g, c, folder in classes:
            roster = master.get((g, c), {})
            if not roster:
                print(f"\n⚠ {g}年{c}組: 名簿なし（スキップ）"); continue
            teacher_info = teachers_data.get((g, c), {})
            teacher = teacher_info.get('name') or args.teacher
            generate_poster(g, c, folder, args.out, roster, teacher,
                          overrides=overrides, cols=args.cols, rows=args.rows,
                          paper=paper, zoom_multiplier=args.zoom_multiplier, top_offset=args.top_offset, left_offset=args.left_offset,
                          teacher_photo=teacher_info.get('photo'),
                          use_teacher_photo=args.teacher_photo)

    print("\n完了 ✅")

if __name__ == "__main__":
    main()
