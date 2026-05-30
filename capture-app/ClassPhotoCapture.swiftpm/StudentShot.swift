import SwiftUI
import CoreGraphics

// ════════════════════════════════════════════════════════════════
//  StudentShot — 撮影対象1人分のデータ（児童・メンバー・担任など）
//
//  学校モード／集団モード両対応。ファイル名・表示ラベルは GroupConfig
//  から引いて生成するため、本ファイルにモードごとの分岐は持たない。
// ════════════════════════════════════════════════════════════════

enum ShotStatus {
    case pending    // 未撮影
    case captured   // 撮影済み
    case absent     // 欠席／不在
}

/// 撮影対象の種別
enum ShotKind {
    case student    // 児童・生徒・メンバー
    case teacher    // 担任・リーダー
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

    /// 画面表示用ラベル — GroupConfig から生成
    /// 学校モード: "1年1組 5番" / "1年1組 担任2"
    /// 集団モード: "職員室 5番" / "職員室 リーダー2"（個人ラベルがあればそれを優先）
    func displayLabel(group: GroupConfig, customLabel: String? = nil) -> String {
        let groupName = group.displayName
        if let label = customLabel, !label.isEmpty {
            return "\(groupName) \(label)"
        }
        switch kind {
        case .student: return "\(groupName) \(number)番"
        case .teacher:
            switch group.mode {
            case .school: return "\(groupName) 担任\(number)"
            case .custom: return "\(groupName) リーダー\(number)"
            }
        }
    }

    /// ファイル名 stem を返す（GroupConfig から派生）
    /// 学校モード（数字組）:
    ///   児童: "{grade}{cls}{num:02}" 例 4年2組5番 → "4205"
    ///   担任: "{grade}{cls}T{num:02}" 例 4年2組担任1 → "42T01"
    /// 学校モード（ABC組）:
    ///   児童: "{grade}{ClsKey}{num:02}" 例 4年A組5番 → "4A05"
    ///   担任: "{grade}{ClsKey}T{num:02}" 例 4年A組担任1 → "4AT01"
    /// 集団モード:
    ///   児童: "{groupID}_{num:02}"
    ///   担任: "{groupID}_T{num:02}"
    func fileStem(group: GroupConfig) -> String {
        switch group.mode {
        case .school:
            let g = group.grade
            let ck = group.classLabel.fileKey
            switch kind {
            case .student: return String(format: "%d%@%02d", g, ck, number)
            case .teacher: return String(format: "%d%@T%02d", g, ck, number)
            }
        case .custom:
            let id = group.fileSafeID
            switch kind {
            case .student: return String(format: "%@_%02d", id, number)
            case .teacher: return String(format: "%@_T%02d", id, number)
            }
        }
    }

    // MARK: - 旧APIの後方互換シム（既存呼び出し箇所の段階移行用）

    /// 旧 API: 数字組前提の表示ラベル
    func displayLabel(grade: Int, cls: Int) -> String {
        var g = GroupConfig()
        g.mode = .school
        g.grade = grade
        g.classLabel = .number(cls)
        return displayLabel(group: g)
    }
    /// 旧 API: 数字組前提のファイル名 stem
    func fileStem(grade: Int, cls: Int) -> String {
        var g = GroupConfig()
        g.mode = .school
        g.grade = grade
        g.classLabel = .number(cls)
        return fileStem(group: g)
    }
}
