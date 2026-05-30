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

/// 撮影対象の種別
enum ShotKind {
    case student    // 児童・生徒
    case teacher    // 担任（複数可）
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
    let kind: ShotKind
    let number: Int                 // 児童は出席番号、担任は担任番号(1〜)

    @Published var status: ShotStatus = .pending
    /// 撮影した元画像（全体・クロップ前）。表示向きに正規化済み。
    @Published var image: UIImage? = nil
    /// 撮影時の顔枠（画像座標系の正規化矩形 0–1）。クロップ情報の元。
    @Published var cropRect: CGRect? = nil

    init(kind: ShotKind = .student, number: Int) {
        self.kind = kind
        self.number = number
    }

    /// 画面表示用ラベル（例: "1年1組 5番" / "1年1組 担任2"）
    func displayLabel(grade: Int, cls: Int) -> String {
        switch kind {
        case .student: return "\(grade)年\(cls)組 \(number)番"
        case .teacher: return "\(grade)年\(cls)組 担任\(number)"
        }
    }

    /// ファイル名 stem を返す。
    /// - 児童: "{grade}{cls}{num:02}"（crop_adjuster 互換）
    /// - 担任: "{grade}{cls}T{num:02}"（'T' 区切りで crop_adjuster の生徒検出と衝突しない）
    func fileStem(grade: Int, cls: Int) -> String {
        switch kind {
        case .student: return String(format: "%d%d%02d", grade, cls, number)
        case .teacher: return String(format: "%d%dT%02d", grade, cls, number)
        }
    }
}
