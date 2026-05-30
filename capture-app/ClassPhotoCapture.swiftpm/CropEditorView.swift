import SwiftUI

// ════════════════════════════════════════════════════════════════
//  CropEditorView — 撮影後のクロップ枠を細かく調整するビュー
//  確認画面の「クロップを調整」ボタンから開く。
//  - 1本指ドラッグ: クロップ枠を上下左右に移動
//  - ピンチ: クロップ枠を拡大/縮小（アスペクト比は維持）
//  「適用」で結果を反映、「キャンセル/閉じる」で元のままに戻す。
// ════════════════════════════════════════════════════════════════

struct CropEditorView: View {
    let image: UIImage
    @Binding var crop: CGRect?
    let onClose: () -> Void

    @State private var workCrop: CGRect
    @State private var dragBase: CGRect? = nil
    @State private var pinchBase: CGRect? = nil

    private let gold = Color(red: 245/255, green: 175/255, blue: 60/255)

    init(image: UIImage, crop: Binding<CGRect?>, onClose: @escaping () -> Void) {
        self.image = image
        self._crop = crop
        self.onClose = onClose
        // 既に枠があればそれを引き継ぐ。無ければ画像中央に CELL_ASPECT のデフォルト枠を作る。
        let initial = crop.wrappedValue ?? Self.defaultCrop(imageSize: image.size)
        self._workCrop = State(initialValue: initial)
    }

    /// 画像中央に、ピクセル比が CELL_ASPECT になるデフォルト枠を作る
    static func defaultCrop(imageSize: CGSize) -> CGRect {
        let aspectImg = Double(imageSize.width / max(1, imageSize.height))
        let cropWoverH = Double(CELL_ASPECT) / aspectImg
        var w = 0.7
        var h = w / cropWoverH
        if h > 0.9 { h = 0.9; w = h * cropWoverH }
        return CGRect(x: (1 - w) / 2, y: (1 - h) * 0.30, width: w, height: h)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 10) {
                Text("ドラッグで上下左右に移動／ピンチで拡大・縮小")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.top, 6)

                GeometryReader { g in
                    let layout = fitLayout(image: image.size, in: g.size)
                    let rx = layout.origin.x + workCrop.minX * layout.size.width
                    let ry = layout.origin.y + workCrop.minY * layout.size.height
                    let rw = workCrop.width * layout.size.width
                    let rh = workCrop.height * layout.size.height
                    ZStack {
                        Color.black
                        Image(uiImage: image)
                            .resizable().scaledToFit()
                            .frame(width: g.size.width, height: g.size.height)
                        // クロップ枠
                        Rectangle()
                            .stroke(gold, lineWidth: 3)
                            .frame(width: rw, height: rh)
                            .position(x: rx + rw/2, y: ry + rh/2)
                        // 角ハンドル
                        ForEach(0..<4, id: \.self) { i in
                            let p = corner(index: i, x: rx, y: ry, w: rw, h: rh)
                            Circle()
                                .fill(.white)
                                .frame(width: 12, height: 12)
                                .overlay(Circle().stroke(gold, lineWidth: 2))
                                .position(x: p.x, y: p.y)
                        }
                    }
                    .contentShape(Rectangle())
                    .gesture(dragGesture(layout: layout))
                    .simultaneousGesture(magnifyGesture())
                }
                .frame(maxHeight: .infinity)

                HStack(spacing: 14) {
                    Button { onClose() } label: {
                        Text("キャンセル").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered).controlSize(.large)

                    Button {
                        crop = workCrop
                        onClose()
                    } label: {
                        Label("適用", systemImage: "checkmark")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent).controlSize(.large)
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 14)
            }
            .navigationTitle("クロップを調整")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("閉じる") { onClose() }
                }
            }
        }
    }

    private func corner(index: Int, x: CGFloat, y: CGFloat, w: CGFloat, h: CGFloat) -> CGPoint {
        switch index {
        case 0: return CGPoint(x: x,       y: y)
        case 1: return CGPoint(x: x + w,   y: y)
        case 2: return CGPoint(x: x,       y: y + h)
        default: return CGPoint(x: x + w,  y: y + h)
        }
    }

    // ── ドラッグで移動 ──
    private func dragGesture(layout: CGRect) -> some Gesture {
        DragGesture()
            .onChanged { value in
                if dragBase == nil { dragBase = workCrop }
                guard let base = dragBase, layout.size.width > 0, layout.size.height > 0
                else { return }
                let dx = value.translation.width / layout.size.width
                let dy = value.translation.height / layout.size.height
                var nx = base.minX + dx
                var ny = base.minY + dy
                nx = min(1 - base.width,  max(0, nx))
                ny = min(1 - base.height, max(0, ny))
                workCrop = CGRect(x: nx, y: ny, width: base.width, height: base.height)
            }
            .onEnded { _ in dragBase = nil }
    }

    // ── ピンチで拡大/縮小（アスペクト比は維持）──
    private func magnifyGesture() -> some Gesture {
        MagnificationGesture()
            .onChanged { value in
                if pinchBase == nil { pinchBase = workCrop }
                guard let base = pinchBase else { return }
                let cx = base.midX
                let cy = base.midY
                var newW = base.width  * value
                var newH = base.height * value
                // 最小サイズ（短辺で 0.18 を下回らない）
                let minSide: CGFloat = 0.18
                if min(newW, newH) < minSide {
                    let s = minSide / min(newW, newH)
                    newW *= s; newH *= s
                }
                // 画像内に収まる最大サイズ
                if newW > 1.0 { let s = 1.0 / newW; newW *= s; newH *= s }
                if newH > 1.0 { let s = 1.0 / newH; newW *= s; newH *= s }
                var nx = cx - newW/2
                var ny = cy - newH/2
                nx = min(1 - newW, max(0, nx))
                ny = min(1 - newH, max(0, ny))
                workCrop = CGRect(x: nx, y: ny, width: newW, height: newH)
            }
            .onEnded { _ in pinchBase = nil }
    }

    private func fitLayout(image: CGSize, in container: CGSize) -> CGRect {
        let imgAR = image.width / max(1, image.height)
        let conAR = container.width / max(1, container.height)
        if imgAR > conAR {
            let w = container.width
            let h = w / imgAR
            return CGRect(x: 0, y: (container.height - h) / 2, width: w, height: h)
        } else {
            let h = container.height
            let w = h * imgAR
            return CGRect(x: (container.width - w) / 2, y: 0, width: w, height: h)
        }
    }
}
