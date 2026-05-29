import CoreGraphics

// ════════════════════════════════════════════════════════════════
//  CropMath — 撮影時の顔枠を crop_adjuster の overrides 値へ逆算する
//
//  crop_adjuster.py の calc_crop_box(W,H,top_pct,left_pct,zoom) の逆算。
//  撮影画像内の正規化枠 (0–1, 画像座標系) から top_pct/left_pct/zoom を求め、
//  crop_overrides.csv にそのまま書き出せるようにする。
//  ※ README.md「枠位置 → crop_overrides 変換」と一致させること。
// ════════════════════════════════════════════════════════════════

struct CropParams {
    var topPct: Double
    var leftPct: Double
    var zoom: Double
}

enum CropMath {
    /// 撮影画像の正規化枠から crop_adjuster の (top_pct, left_pct, zoom) を算出。
    /// - rect:   画像座標系での枠 (origin 左上、x/y/width/height はすべて 0–1)
    /// - imageW/imageH: 撮影画像の実ピクセル寸法（表示向きに正規化済みの値）
    /// - aspect: CELL_ASPECT（crop_adjuster と一致）
    static func params(forNormalizedRect rect: CGRect,
                       imageW: Double, imageH: Double,
                       aspect: Double) -> CropParams {
        let W = max(1.0, imageW)
        let H = max(1.0, imageH)

        // calc_crop_box と同じベースサイズ計算
        let baseH: Double
        if W / H < aspect {
            baseH = W / aspect          // 縦長画像
        } else {
            baseH = H                   // 横長画像
        }

        let nx = Double(rect.origin.x)
        let ny = Double(rect.origin.y)
        let nw = Double(rect.size.width)
        let nh = Double(rect.size.height)

        // 枠上端 → top_pct
        var topPct = ny * 100.0
        // 枠の横中心 → left_pct
        var leftPct = (nx + nw / 2.0 - 0.5) * 100.0
        // 枠の高さ → zoom（crop_h = baseH/zoom = nh*H）
        let cropHpx = max(1.0, nh * H)
        var zoom = baseH / cropHpx

        // crop_adjuster と同じクランプ範囲
        topPct = min(100.0, max(0.0, topPct))
        leftPct = min(50.0, max(-50.0, leftPct))
        zoom = min(5.0, max(1.0, zoom))

        return CropParams(topPct: topPct, leftPct: leftPct, zoom: zoom)
    }

    /// 顔枠（プレビュー上の正規化矩形）。横中心・やや上寄り。
    /// 見た目の縦横比は常に aspect を保つ（はみ出す場合は幅を縮めて維持）。
    /// - previewAspect: プレビュー領域の縦横比 (w/h)
    /// - widthFrac: 枠の幅（プレビュー幅に対する割合）。小さいほど顔がアップ＝高ズーム。
    static func defaultGuideRect(previewAspect: CGFloat, aspect: CGFloat,
                                 widthFrac: CGFloat = 0.62) -> CGRect {
        var wFrac = min(0.95, max(0.30, widthFrac))
        // 見た目を aspect(=w/h) にする高さ割合: hFrac = wFrac * previewAspect / aspect
        var hFrac = wFrac * previewAspect / aspect
        // 縦にはみ出す場合は、アスペクト比を保ったまま幅を縮める
        let maxH: CGFloat = 0.82
        if hFrac > maxH {
            hFrac = maxH
            wFrac = hFrac * aspect / previewAspect
        }
        let x = (1.0 - wFrac) / 2.0
        // やや上寄り（顔が枠の中心〜上に来る想定）。枠が大きいほど上に詰める。
        let y: CGFloat = max(0.04, (1.0 - hFrac) * 0.40)
        return CGRect(x: x, y: y, width: wFrac, height: hFrac)
    }
}
