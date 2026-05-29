import SwiftUI

// ════════════════════════════════════════════════════════════════
//  FaceGuide — クロップ枠内に薄く表示する「頭＋肩」のシルエット
//  左右対称。被写体の顔位置合わせの目安。薄い白半透明で表示し、
//  邪魔な場合は ON/OFF で消せる（AppState.showFaceGuide）。
// ════════════════════════════════════════════════════════════════

struct FaceGuideShape: Shape {
    func path(in rect: CGRect) -> Path {
        let w = rect.width
        let h = rect.height
        let cx = rect.midX

        var p = Path()

        // ── 頭（楕円・上部中央）──
        let headW = w * 0.34
        let headH = h * 0.40
        let headCy = rect.minY + h * 0.30
        p.addEllipse(in: CGRect(x: cx - headW / 2,
                                y: headCy - headH / 2,
                                width: headW, height: headH))

        // ── 首〜肩（左右対称のなだらかな台形）──
        let neckY      = rect.minY + h * 0.52
        let neckHalf   = w * 0.11
        let bottomY    = rect.minY + h * 0.99
        let shoulderHalf = w * 0.42

        var body = Path()
        body.move(to: CGPoint(x: cx - neckHalf, y: neckY))
        // 左肩へなだらかに
        body.addQuadCurve(
            to: CGPoint(x: cx - shoulderHalf, y: bottomY),
            control: CGPoint(x: cx - shoulderHalf * 0.78, y: neckY + h * 0.12))
        body.addLine(to: CGPoint(x: cx + shoulderHalf, y: bottomY))
        // 右肩から首へ（対称）
        body.addQuadCurve(
            to: CGPoint(x: cx + neckHalf, y: neckY),
            control: CGPoint(x: cx + shoulderHalf * 0.78, y: neckY + h * 0.12))
        body.closeSubpath()
        p.addPath(body)

        return p
    }
}

/// 枠内に重ねる顔ガイド表示（薄い白半透明＋細い輪郭）
struct FaceGuideOverlay: View {
    var body: some View {
        ZStack {
            FaceGuideShape().fill(Color.white.opacity(0.15))
            FaceGuideShape().stroke(Color.white.opacity(0.40), lineWidth: 1.5)
        }
        .allowsHitTesting(false)
    }
}
