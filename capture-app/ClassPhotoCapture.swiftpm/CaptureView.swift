import SwiftUI

// ════════════════════════════════════════════════════════════════
//  CaptureView — 撮影画面（カメラ＋顔枠ガイド＋連続撮影）
// ════════════════════════════════════════════════════════════════

struct CaptureView: View {
    @EnvironmentObject var state: AppState
    @StateObject private var camera = CameraModel()

    // 直近に撮影して確認待ちの画像（nil なら撮影モード）
    @State private var confirmImage: UIImage? = nil
    @State private var confirmCrop: CGRect? = nil
    @State private var isCapturing = false

    // 生徒番号が変わった時に大きく表示するスプラッシュ
    @State private var splashOpacity: Double = 0
    // ピンチズーム開始時の倍率
    @State private var pinchStartZoom: CGFloat = 1.0
    // クロップ調整ビュー表示フラグ
    @State private var editingCrop = false

    private let gold = Color(red: 245/255, green: 175/255, blue: 60/255)

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.black.ignoresSafeArea()

                if camera.isConfigured {
                    CameraPreview(previewLayer: camera.previewLayer)
                        .ignoresSafeArea()
                        .gesture(pinchGesture)
                }

                // 顔枠ガイド
                let guide = guideRect(in: geo.size)
                goldFrame(rect: guide)

                // 上部: 現在の生徒・進捗
                VStack {
                    topBar
                    Spacer()
                    sizeSlider
                    bottomControls(guide: guide, previewSize: geo.size)
                }

                // 番号変更時の大きいスプラッシュ表示（デフォルト枠のちょっと上）
                Text("\(state.currentShot?.displayLabel(group: state.group) ?? "") を撮影")
                    .font(.system(size: 30, weight: .heavy))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 22).padding(.vertical, 11)
                    .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 18))
                    .opacity(splashOpacity)
                    .position(x: geo.size.width / 2, y: geo.size.height * 0.16)
                    .allowsHitTesting(false)

                // 右上: 顔ガイド ON/OFF トグル
                VStack {
                    HStack {
                        Spacer()
                        Button {
                            state.showFaceGuide.toggle()
                        } label: {
                            Label(state.showFaceGuide ? "顔ガイド ON" : "顔ガイド OFF",
                                  systemImage: state.showFaceGuide
                                      ? "person.fill.viewfinder" : "person.crop.rectangle")
                                .font(.caption)
                                .foregroundStyle(.white)
                                .padding(.horizontal, 12)
                                .padding(.vertical, 7)
                                .background(.black.opacity(0.4), in: Capsule())
                        }
                    }
                    Spacer()
                }
                .padding(.top, 14)
                .padding(.trailing, 16)

                // 確認オーバーレイ
                if let img = confirmImage {
                    confirmOverlay(image: img, crop: confirmCrop, previewSize: geo.size)
                }

                if let err = camera.errorMessage {
                    VStack {
                        Spacer()
                        Text(err)
                            .font(.callout)
                            .foregroundStyle(.white)
                            .padding()
                            .background(.red.opacity(0.85), in: RoundedRectangle(cornerRadius: 10))
                            .padding()
                    }
                }
            }
        }
        .onAppear {
            camera.requestAccess()
            showSplash()
        }
        .onDisappear { camera.stopRunning() }
        .onChange(of: state.currentIndex) { _ in
            showSplash()
        }
        .sheet(isPresented: $editingCrop) {
            if let img = confirmImage {
                CropEditorView(image: img, crop: $confirmCrop) {
                    editingCrop = false
                }
                .interactiveDismissDisabled()   // ドラッグで誤って閉じないように
            }
        }
    }

    // ── スプラッシュ表示 ──
    private func showSplash() {
        splashOpacity = 1.0
        withAnimation(.easeOut(duration: 0.35).delay(0.85)) {
            splashOpacity = 0
        }
    }

    // ── ピンチ→カメラズーム ──
    private var pinchGesture: some Gesture {
        MagnificationGesture()
            .onChanged { value in
                let newZoom = pinchStartZoom * value
                camera.setZoom(newZoom)
            }
            .onEnded { _ in
                pinchStartZoom = camera.currentZoom
            }
    }

    // ── 顔枠の矩形（プレビュー座標 px）──
    private func guideRect(in size: CGSize) -> CGRect {
        let aspect = size.width / max(1, size.height)
        let g = CropMath.defaultGuideRect(previewAspect: aspect, aspect: CELL_ASPECT,
                                          widthFrac: state.guideWidthFrac)
        return CGRect(x: g.origin.x * size.width,
                      y: g.origin.y * size.height,
                      width: g.size.width * size.width,
                      height: g.size.height * size.height)
    }

    @ViewBuilder
    private func goldFrame(rect: CGRect) -> some View {
        ZStack {
            // 顔位置ガイド（枠内に薄く・ON/OFF可）
            if state.showFaceGuide {
                FaceGuideOverlay()
                    .frame(width: rect.width, height: rect.height)
                    .position(x: rect.midX, y: rect.midY)
            }
            RoundedRectangle(cornerRadius: 6)
                .stroke(gold, lineWidth: 3)
                .frame(width: rect.width, height: rect.height)
                .position(x: rect.midX, y: rect.midY)
            // 角ハンドル風（CGPoint は iOS18 未満で Hashable 非対応のため index で回す）
            let pts = corners(of: rect)
            ForEach(pts.indices, id: \.self) { i in
                Circle().fill(.white).frame(width: 12, height: 12)
                    .overlay(Circle().stroke(gold, lineWidth: 2))
                    .position(x: pts[i].x, y: pts[i].y)
            }
        }
        .allowsHitTesting(false)
    }

    private func corners(of r: CGRect) -> [CGPoint] {
        [CGPoint(x: r.minX, y: r.minY), CGPoint(x: r.maxX, y: r.minY),
         CGPoint(x: r.minX, y: r.maxY), CGPoint(x: r.maxX, y: r.maxY)]
    }

    // ── 上部バー ──
    private var topBar: some View {
        VStack(spacing: 4) {
            Text("\(state.currentShot?.displayLabel(group: state.group) ?? "") を撮影")
                .font(.title3.bold())
                .foregroundStyle(.white)
            Text("済 \(state.capturedCount) / 欠席 \(state.absentCount) / 全 \(state.shots.count)")
                .font(.caption)
                .foregroundStyle(.white.opacity(0.85))
            Text("顔を金色の枠に合わせてください")
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.7))
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 16)
        .background(.black.opacity(0.4), in: Capsule())
        .padding(.top, 12)
    }

    // ── クロップ枠の大きさスライダー（カメラのズームには無関係）──
    // 左ほど枠が小さく、右ほど大きい。カメラ自体のズームはピンチで操作。
    private var sizeBinding: Binding<Double> {
        Binding(
            get: { Double(state.guideWidthFrac - 0.35) },     // 0(小)〜0.55(大)
            set: { state.guideWidthFrac = CGFloat($0 + 0.35) }
        )
    }

    private var sizeSlider: some View {
        VStack(spacing: 3) {
            Text("クロップ枠の大きさ（カメラのズームはピンチ操作）")
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.85))
            HStack(spacing: 12) {
                Image(systemName: "minus").foregroundStyle(.white)
                Slider(value: sizeBinding, in: 0...0.55)
                    .tint(gold)
                Image(systemName: "plus").foregroundStyle(.white)
            }
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 8)
        .background(.black.opacity(0.4), in: RoundedRectangle(cornerRadius: 14))
        .padding(.horizontal, 24)
        .padding(.bottom, 6)
    }

    // ── 下部コントロール ──
    @ViewBuilder
    private func bottomControls(guide: CGRect, previewSize: CGSize) -> some View {
        HStack(spacing: 28) {
            // 前へ
            Button {
                state.goPrev()
            } label: {
                controlIcon("chevron.left", label: "前")
            }
            .disabled(state.currentIndex == 0)

            // 欠席
            Button {
                markAbsent()
            } label: {
                controlIcon("person.slash.fill", label: "欠席")
            }

            // シャッター（カメラ未準備時はテスト用ダミー画像で撮影扱い）
            Button {
                doCapture(guide: guide, previewSize: previewSize)
            } label: {
                ZStack {
                    Circle().fill(.white).frame(width: 72, height: 72)
                    Circle().stroke(.white, lineWidth: 4).frame(width: 84, height: 84)
                }
            }
            .disabled(isCapturing)

            // 次へ
            Button {
                state.goNext()
            } label: {
                controlIcon("chevron.right", label: "次")
            }
            .disabled(state.currentIndex >= state.shots.count - 1)

            // 確認・書き出しへ
            Button {
                camera.stopRunning()
                state.screen = .review
            } label: {
                controlIcon("checklist", label: "一覧")
            }
        }
        .padding(.vertical, 16)
        .padding(.horizontal, 20)
        .background(.black.opacity(0.4), in: RoundedRectangle(cornerRadius: 20))
        .padding(.bottom, 16)
    }

    private func controlIcon(_ system: String, label: String) -> some View {
        VStack(spacing: 3) {
            Image(systemName: system).font(.title2)
            Text(label).font(.caption2)
        }
        .foregroundStyle(.white)
        .frame(width: 54)
    }

    // ── 確認オーバーレイ ──
    @ViewBuilder
    private func confirmOverlay(image: UIImage, crop: CGRect?, previewSize: CGSize) -> some View {
        ZStack {
            Color.black.opacity(0.92).ignoresSafeArea()
            VStack(spacing: 16) {
                Text("この写真でよろしいですか？")
                    .font(.headline).foregroundStyle(.white)
                Image(uiImage: image)
                    .resizable().scaledToFit()
                    .frame(maxHeight: previewSize.height * 0.6)
                    .overlay(cropOverlay(crop: crop))
                // クロップ微調整ボタン（任意・通常は使わないが必要な時に）
                Button {
                    editingCrop = true
                } label: {
                    Label("クロップを調整（拡大・上下左右）", systemImage: "crop")
                        .font(.subheadline)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered).controlSize(.regular).tint(.white)
                .padding(.horizontal, 30)

                HStack(spacing: 20) {
                    Button(role: .destructive) {
                        retake()
                    } label: {
                        Label("撮り直す", systemImage: "arrow.counterclockwise")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered).controlSize(.large).tint(.white)

                    Button {
                        confirmOK()
                    } label: {
                        Label("OK → 次へ", systemImage: "checkmark")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent).controlSize(.large)
                }
                .padding(.horizontal, 30)
            }
            .padding()
        }
    }

    @ViewBuilder
    private func cropOverlay(crop: CGRect?) -> some View {
        if let c = crop {
            GeometryReader { g in
                RoundedRectangle(cornerRadius: 4)
                    .stroke(gold, lineWidth: 2)
                    .frame(width: c.width * g.size.width, height: c.height * g.size.height)
                    .position(x: (c.midX) * g.size.width, y: (c.midY) * g.size.height)
            }
        }
    }

    // ── アクション ──
    private func doCapture(guide: CGRect, previewSize: CGSize) {
        guard !isCapturing else { return }
        isCapturing = true

        // カメラ未準備（シミュレータ等）でもフローを止めないため、
        // ダミー画像で「撮影したことにする」フォールバックを用意。
        // 実機(iPad等)ではこのパスは通らない。
        if !camera.isConfigured {
            let img = makeTestImage(number: state.currentShot?.number ?? 0)
            let nx = previewSize.width  > 0 ? guide.minX / previewSize.width  : 0
            let ny = previewSize.height > 0 ? guide.minY / previewSize.height : 0
            let nw = previewSize.width  > 0 ? guide.width / previewSize.width  : 1
            let nh = previewSize.height > 0 ? guide.height / previewSize.height : 1
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                isCapturing = false
                confirmImage = img
                confirmCrop = CGRect(x: nx, y: ny, width: nw, height: nh)
            }
            return
        }

        camera.capture(guideRectInLayer: guide, format: state.imageFormat) { img, crop in
            isCapturing = false
            guard let img else { return }
            confirmImage = img
            confirmCrop = crop
        }
    }

    /// カメラ無し時のダミー画像（番号入りグレー）。フロー確認用。
    private func makeTestImage(number: Int) -> UIImage {
        let size = CGSize(width: 1500, height: 1500 / CELL_ASPECT)  // 横長
        let renderer = UIGraphicsImageRenderer(size: size)
        return renderer.image { ctx in
            UIColor(white: 0.55, alpha: 1).setFill()
            ctx.fill(CGRect(origin: .zero, size: size))
            let text = "TEST  #\(number)"
            let attrs: [NSAttributedString.Key: Any] = [
                .font: UIFont.boldSystemFont(ofSize: size.width * 0.08),
                .foregroundColor: UIColor.white
            ]
            let ns = NSAttributedString(string: text, attributes: attrs)
            let textSize = ns.size()
            ns.draw(at: CGPoint(x: (size.width - textSize.width) / 2,
                                y: (size.height - textSize.height) / 2))
        }
    }

    private func confirmOK() {
        if let shot = state.currentShot {
            shot.image = confirmImage
            shot.cropRect = confirmCrop
            shot.status = .captured
        }
        confirmImage = nil
        confirmCrop = nil
        state.advanceToNextPending()
    }

    private func retake() {
        confirmImage = nil
        confirmCrop = nil
    }

    private func markAbsent() {
        if let shot = state.currentShot {
            shot.status = .absent
            shot.image = nil
            shot.cropRect = nil
        }
        state.advanceToNextPending()
    }
}
