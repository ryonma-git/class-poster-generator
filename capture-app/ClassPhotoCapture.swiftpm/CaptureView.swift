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

    private let gold = Color(red: 245/255, green: 175/255, blue: 60/255)

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.black.ignoresSafeArea()

                if camera.isConfigured {
                    CameraPreview(previewLayer: camera.previewLayer)
                        .ignoresSafeArea()
                }

                // 顔枠ガイド
                let guide = guideRect(in: geo.size)
                goldFrame(rect: guide)

                // 上部: 現在の生徒・進捗
                VStack {
                    topBar
                    Spacer()
                    zoomSlider
                    bottomControls(guide: guide)
                }

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
        .onAppear { camera.requestAccess() }
        .onDisappear { camera.stopRunning() }
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
            Text("\(state.grade)年 \(state.cls)組  \(state.currentShot?.number ?? 0)番 を撮影")
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

    // ── ズーム（クロップ枠の大きさ）スライダー ──
    // 右へ動かすほど枠が小さく＝顔アップ（高ズーム）。場所が同じなら全員同じ枠で撮れる。
    private var zoomBinding: Binding<Double> {
        Binding(
            get: { Double(0.90 - state.guideWidthFrac) },      // 0(引き)〜0.55(アップ)
            set: { state.guideWidthFrac = CGFloat(0.90 - $0) }
        )
    }

    private var zoomSlider: some View {
        VStack(spacing: 3) {
            Text("クロップ枠のズーム（右ほど顔アップ）")
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.85))
            HStack(spacing: 12) {
                Image(systemName: "minus.magnifyingglass")
                    .foregroundStyle(.white)
                Slider(value: zoomBinding, in: 0...0.55)
                    .tint(gold)
                Image(systemName: "plus.magnifyingglass")
                    .foregroundStyle(.white)
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
    private func bottomControls(guide: CGRect) -> some View {
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

            // シャッター
            Button {
                doCapture(guide: guide)
            } label: {
                ZStack {
                    Circle().fill(.white).frame(width: 72, height: 72)
                    Circle().stroke(.white, lineWidth: 4).frame(width: 84, height: 84)
                }
            }
            .disabled(!camera.isConfigured || isCapturing)

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
    private func doCapture(guide: CGRect) {
        guard !isCapturing else { return }
        isCapturing = true
        camera.capture(guideRectInLayer: guide, format: state.imageFormat) { img, crop in
            isCapturing = false
            guard let img else { return }
            confirmImage = img
            confirmCrop = crop
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
