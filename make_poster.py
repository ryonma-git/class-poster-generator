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
from reportlab.lib.pagesizes import A2
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# ════════════════════════════════════════════
#  レイアウト
# ════════════════════════════════════════════
A2_W, A2_H = A2
MM         = 72 / 25.4
MARGIN_X   = 15 * MM
MARGIN_TOP = 18 * MM
MARGIN_BOT = 12 * MM
HEADER_H   = 25 * MM
GAP_COL    =  5 * MM
GAP_ROW    =  6 * MM
LABEL_H    = 18 * MM
COLS       = 6
ROWS_FIXED = 7    # 全クラス共通の行数（6×7=42枠）

# ════════════════════════════════════════════
#  カラー
# ════════════════════════════════════════════
C_HDR_BG  = (0x2B,0x5F,0x8E)
C_HDR_SUB = (0x4A,0x90,0xC4)
C_ACCENT  = (0xE8,0x9C,0x2A)
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

def smart_crop(pil_img, target_w, target_h, override=None):
    """
    学校個人写真向けクロップ。crop_adjuster.py と同じロジック。
    重要: 頭の上を確実に枠内に収める（顔の高さ × 0.5 の余白）
    override: {top_pct, left_pct, zoom} を渡すと手動クロップを優先。
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
    else:
        # 自動：顔検出
        face = detect_face(pil_img)
        if face is not None:
            fx, fy, fw, fh = face
            face_cx = fx + fw / 2
            face_top = fy
            # 頭の上に余白（顔高さの50%）
            head_margin = fh * 0.5
            # クロップ高さは顔の高さ × 2.8倍（頭・余白を含むサイズ）
            desired_crop_h = fh * 2.8
            zoom = base_h / desired_crop_h
            zoom = max(1.0, min(2.5, zoom))
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
def make_student_cell(img_path, cw, ch, lh, num, name, override=None):
    R  = 18
    ph = ch - lh

    cell = Image.new("RGBA", (cw, ch), (0,0,0,0))
    cell.paste(Image.new("RGBA",(cw,ch), C_CARD+(255,)),
               mask=rmask((cw,ch), R))

    # ── 写真 ──
    if img_path and os.path.exists(img_path):
        try:
            pil   = fix_exif_rotation(Image.open(img_path))
            photo = smart_crop(pil, cw, ph, override=override)
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
def make_teacher_cell(cw, ch, lh, name):
    R    = 18
    cell = Image.new("RGBA", (cw,ch), (0,0,0,0))
    cell.paste(Image.new("RGBA",(cw,ch), C_TCH_BG+(255,)), mask=rmask((cw,ch),R))
    d = ImageDraw.Draw(cell)
    d.text((cw//2, int(ch*0.35)), "担　任",
           font=get_font(int(ch*0.11)), fill=C_ACCENT+(220,), anchor="mm")
    _, fn = fit_font(d, name, int(cw*0.84), int(ch*0.12))
    d.text((cw//2, int(ch*0.56)), name, font=fn, fill=(255,255,255,255), anchor="mm")
    d.rectangle([int(cw*0.2),ch-7,int(cw*0.8),ch-3], fill=C_ACCENT+(200,))
    return cell

# ════════════════════════════════════════════
#  ポスター生成（1クラス）
# ════════════════════════════════════════════
def generate_poster(grade, cls, folder, out_dir, roster, teacher=None, overrides=None):
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
    rows        = ROWS_FIXED  # 全クラス42枠で統一（空き枠は描画せず余白）

    # ── ピクセル計算（150dpi）──
    DPI=150; P=DPI/72.0
    pw,ph = int(A2_W*P), int(A2_H*P)
    mx = int(MARGIN_X*P);   mt = int(MARGIN_TOP*P)
    mb = int(MARGIN_BOT*P); hh = int(HEADER_H*P)
    gc = int(GAP_COL*P);    gr = int(GAP_ROW*P)
    lh = int(LABEL_H*P)

    cw = (pw - 2*mx - (COLS-1)*gc) // COLS
    ch = ((ph - mt - hh - mb) - (rows-1)*gr) // rows

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

    # グリッド
    gt    = mt + hh + int(4*P)
    cells = ([("t", teacher)] if teacher else []) + [("s", n) for n in nums]

    for idx, (kind, val) in enumerate(cells):
        col = idx % COLS; row = idx // COLS
        x   = mx + col*(cw+gc)
        y   = gt + row*(ch+gr)
        if kind == "t":
            ci = make_teacher_cell(cw, ch, lh, val)
        else:
            ov = (overrides or {}).get((grade, cls, val))
            ci = make_student_cell(photos.get(val), cw, ch, lh, val,
                                   roster.get(val, f"{val:02d}番"),
                                   override=ov)
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
    c = canvas.Canvas(out, pagesize=A2)
    c.drawImage(ImageReader(buf), 0, 0, width=A2_W, height=A2_H)
    c.save()
    print(f"  ✅ {total}名 → {Path(out).name}")

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

    if args.grade and args.cls:
        folder = find_class_folder(args.base, args.grade, args.cls)
        roster = master.get((args.grade, args.cls), {})
        if not roster:
            print(f"⚠ {args.grade}年{args.cls}組: 名簿なし"); return
        generate_poster(args.grade, args.cls, folder, args.out,
                        roster, args.teacher, overrides=overrides)
    else:
        classes = find_all_classes(args.base)
        print(f"写真フォルダ検出: {len(classes)}クラス")
        for g, c, folder in classes:
            roster = master.get((g, c), {})
            if not roster:
                print(f"\n⚠ {g}年{c}組: 名簿なし（スキップ）"); continue
            generate_poster(g, c, folder, args.out, roster, args.teacher, overrides=overrides)

    print("\n完了 ✅")

if __name__ == "__main__":
    main()
