import UIKit
import Photos

// ════════════════════════════════════════════════════════════════
//  PhotoExporter — 撮影した写真を iOS「写真」アプリへ書き出す
//  - オリジナル: クロップ前の元の全体写真を保存
//  - クロップ済み: 撮影時の枠でクロップした写真を保存
// ════════════════════════════════════════════════════════════════

enum PhotoExportMode {
    case original   // クロップ前
    case cropped    // クロップ済み
}

enum PhotoExporter {
    /// 写真ライブラリへの追加権限を要求し、完了したら handler に結果を渡す。
    static func requestAddPermission(_ handler: @escaping (Bool) -> Void) {
        let status = PHPhotoLibrary.authorizationStatus(for: .addOnly)
        switch status {
        case .authorized, .limited:
            DispatchQueue.main.async { handler(true) }
        case .notDetermined:
            PHPhotoLibrary.requestAuthorization(for: .addOnly) { newStatus in
                DispatchQueue.main.async {
                    handler(newStatus == .authorized || newStatus == .limited)
                }
            }
        default:
            DispatchQueue.main.async { handler(false) }
        }
    }

    /// shots を「写真」アプリへ順次保存。完了時に成功・失敗件数を返す。
    /// - mode: .original or .cropped
    static func saveAll(shots: [StudentShot], mode: PhotoExportMode,
                        progress: @escaping (Int, Int) -> Void,
                        completion: @escaping (Int, Int) -> Void) {
        let captured = shots.filter { $0.status == .captured && $0.image != nil }
        let total = captured.count
        guard total > 0 else { completion(0, 0); return }

        var ok = 0
        var ng = 0
        let group = DispatchGroup()

        for (idx, shot) in captured.enumerated() {
            guard let original = shot.image else { ng += 1; continue }
            let img: UIImage? = (mode == .cropped)
                ? croppedImage(original, normalized: shot.cropRect) ?? original
                : original
            guard let saving = img else { ng += 1; continue }

            group.enter()
            PHPhotoLibrary.shared().performChanges {
                _ = PHAssetCreationRequest.creationRequestForAsset(from: saving)
            } completionHandler: { success, _ in
                DispatchQueue.main.async {
                    if success { ok += 1 } else { ng += 1 }
                    progress(idx + 1, total)
                    group.leave()
                }
            }
        }

        group.notify(queue: .main) {
            completion(ok, ng)
        }
    }

    /// 正規化矩形（0〜1, 画像座標）で UIImage をクロップ
    static func croppedImage(_ image: UIImage, normalized crop: CGRect?) -> UIImage? {
        guard let crop = crop, let cg = image.cgImage else { return nil }
        let cgW = CGFloat(cg.width)
        let cgH = CGFloat(cg.height)
        let rect = CGRect(
            x: max(0, crop.minX) * cgW,
            y: max(0, crop.minY) * cgH,
            width: min(1, crop.width) * cgW,
            height: min(1, crop.height) * cgH
        ).integral
        guard let cropped = cg.cropping(to: rect) else { return nil }
        return UIImage(cgImage: cropped, scale: image.scale, orientation: .up)
    }
}
