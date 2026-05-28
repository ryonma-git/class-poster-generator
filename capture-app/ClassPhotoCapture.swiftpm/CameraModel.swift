import SwiftUI
import AVFoundation

// ════════════════════════════════════════════════════════════════
//  CameraModel — AVCaptureSession のラッパ
//  プレビュー層の提供・写真撮影・撮影枠の画像座標変換を担当。
//
//  ※ 実機（iPad/iPhone の Swift Playgrounds）での動作確認・向き調整が必要。
//    README「未解決・実機調整が必要な点」を参照。
// ════════════════════════════════════════════════════════════════

final class CameraModel: NSObject, ObservableObject {
    let session = AVCaptureSession()
    let previewLayer = AVCaptureVideoPreviewLayer()

    private let photoOutput = AVCapturePhotoOutput()
    private let sessionQueue = DispatchQueue(label: "camera.session.queue")

    @Published var isAuthorized = false
    @Published var isConfigured = false
    @Published var errorMessage: String? = nil

    // 撮影完了コールバック保持用
    private var captureCompletion: ((UIImage?, CGRect?) -> Void)?
    // 撮影リクエスト時の枠情報（プレビュー座標→画像座標変換に使う）
    private var pendingGuideRectInLayer: CGRect?

    // ── 権限要求 ──
    func requestAccess() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            isAuthorized = true
            configure()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                DispatchQueue.main.async {
                    self?.isAuthorized = granted
                    if granted { self?.configure() }
                    else { self?.errorMessage = "カメラへのアクセスが許可されていません。" }
                }
            }
        default:
            isAuthorized = false
            errorMessage = "カメラへのアクセスが許可されていません。設定アプリで許可してください。"
        }
    }

    // ── セッション構成 ──
    private func configure() {
        sessionQueue.async { [weak self] in
            guard let self else { return }
            self.session.beginConfiguration()
            self.session.sessionPreset = .photo

            // 背面カメラ
            guard let device = AVCaptureDevice.default(.builtInWideAngleCamera,
                                                       for: .video, position: .back)
                    ?? AVCaptureDevice.default(for: .video),
                  let input = try? AVCaptureDeviceInput(device: device),
                  self.session.canAddInput(input) else {
                DispatchQueue.main.async { self.errorMessage = "カメラを初期化できませんでした。" }
                self.session.commitConfiguration()
                return
            }
            self.session.addInput(input)

            if self.session.canAddOutput(self.photoOutput) {
                self.session.addOutput(self.photoOutput)
            }
            self.session.commitConfiguration()

            DispatchQueue.main.async {
                self.previewLayer.session = self.session
                self.previewLayer.videoGravity = .resizeAspectFill
                self.isConfigured = true
            }
            self.startRunning()
        }
    }

    func startRunning() {
        sessionQueue.async { [weak self] in
            guard let self, !self.session.isRunning else { return }
            self.session.startRunning()
        }
    }

    func stopRunning() {
        sessionQueue.async { [weak self] in
            guard let self, self.session.isRunning else { return }
            self.session.stopRunning()
        }
    }

    // ── 撮影 ──
    /// - guideRectInLayer: プレビュー層の座標系での顔枠（px）
    /// - format: 保存フォーマット
    func capture(guideRectInLayer: CGRect,
                 format: ImageFormat,
                 completion: @escaping (UIImage?, CGRect?) -> Void) {
        self.captureCompletion = completion
        self.pendingGuideRectInLayer = guideRectInLayer

        let settings: AVCapturePhotoSettings
        if format == .heic,
           photoOutput.availablePhotoCodecTypes.contains(.hevc) {
            settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.hevc])
        } else {
            settings = AVCapturePhotoSettings()  // 既定（JPEG）
        }
        sessionQueue.async { [weak self] in
            guard let self else { return }
            self.photoOutput.capturePhoto(with: settings, delegate: self)
        }
    }
}

// ── 撮影デリゲート ──
extension CameraModel: AVCapturePhotoCaptureDelegate {
    func photoOutput(_ output: AVCapturePhotoOutput,
                     didFinishProcessingPhoto photo: AVCapturePhoto,
                     error: Error?) {
        if let error {
            DispatchQueue.main.async {
                self.errorMessage = "撮影に失敗しました: \(error.localizedDescription)"
                self.captureCompletion?(nil, nil)
            }
            return
        }
        guard let data = photo.fileDataRepresentation(),
              let uiImage = UIImage(data: data) else {
            DispatchQueue.main.async { self.captureCompletion?(nil, nil) }
            return
        }
        // 表示向きに正規化（EXIF向きを焼き込む）
        let normalized = uiImage.normalizedOrientation()

        // プレビュー枠 → 画像の正規化矩形へ変換（aspectFill のトリミングを吸収）
        var cropRect: CGRect? = nil
        if let layerRect = pendingGuideRectInLayer {
            // metadataOutputRectConverted は (0,0)左上〜(1,1)右下 の画像座標を返す
            let r = previewLayer.metadataOutputRectConverted(fromLayerRect: layerRect)
            // 念のためクランプ
            cropRect = CGRect(
                x: min(max(r.origin.x, 0), 1),
                y: min(max(r.origin.y, 0), 1),
                width: min(r.size.width, 1),
                height: min(r.size.height, 1)
            )
        }

        DispatchQueue.main.async {
            self.captureCompletion?(normalized, cropRect)
        }
    }
}

// ── UIImage 向き正規化 ──
extension UIImage {
    /// EXIF 向きを実ピクセルに焼き込み、orientation を .up にした画像を返す。
    func normalizedOrientation() -> UIImage {
        if imageOrientation == .up { return self }
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = scale
        let renderer = UIGraphicsImageRenderer(size: size, format: format)
        return renderer.image { _ in
            self.draw(in: CGRect(origin: .zero, size: size))
        }
    }
}
