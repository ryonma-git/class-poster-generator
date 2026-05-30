import SwiftUI
import AVFoundation

// ════════════════════════════════════════════════════════════════
//  CameraPreview — AVCaptureVideoPreviewLayer を SwiftUI で表示
// ════════════════════════════════════════════════════════════════

struct CameraPreview: UIViewRepresentable {
    let previewLayer: AVCaptureVideoPreviewLayer

    func makeUIView(context: Context) -> PreviewUIView {
        let v = PreviewUIView()
        v.backgroundColor = .black
        v.previewLayer = previewLayer
        v.layer.addSublayer(previewLayer)
        return v
    }

    func updateUIView(_ uiView: PreviewUIView, context: Context) {
        uiView.setNeedsLayout()
    }
}

/// レイアウトに合わせてプレビュー層のフレームを追従させる UIView
final class PreviewUIView: UIView {
    weak var previewLayer: AVCaptureVideoPreviewLayer?

    override func layoutSubviews() {
        super.layoutSubviews()
        previewLayer?.frame = bounds
    }
}
