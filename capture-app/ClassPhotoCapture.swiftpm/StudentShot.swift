import SwiftUI
import CoreGraphics

// ════════════════════════════════════════════════════════════════
//  StudentShot — 生徒1人分の撮影データ
// ════════════════════════════════════════════════════════════════

enum ShotStatus {
    case pending    // 未撮影
    case captured   // 撮影済み
    case absent     // 欠席
}

/// 撮影画像フォーマット
enum ImageFormat: String, CaseIterable, Identifiable {
    case jpeg = "JPEG"
    case heic = "HEIC"
    var id: String { rawValue }
    var fileExtension: String { self == .jpeg ? "jpg" : "heic" }
}

final class StudentShot: Identifiable, ObservableObject {
    let id = UUID()
    let number: Int                 // 出席番号

    @Published var status: ShotStatus = .pending
    /// 撮影した元画像（全体・クロップ前）。表示向きに正規化済み。
    @Published var image: UIImage? = nil
    /// 撮影時の顔枠（画像座標系の正規化矩形 0–1）。クロップ情報の元。
    @Published var cropRect: CGRect? = nil

    init(number: Int) {
        self.number = number
    }

    /// crop_overrides 用のファイル名 stem を返す（例: 1年1組1番 → "1101"）
    func fileStem(grade: Int, cls: Int) -> String {
        return String(format: "%d%d%02d", grade, cls, number)
    }
}
