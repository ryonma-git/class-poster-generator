import Foundation

// ════════════════════════════════════════════════════════════════
//  GroupConfig — 撮影対象の集団（クラス／職員室／チーム…）の定義
//
//  2つのモードをサポート：
//   - .school : 伝統的な「N年M組」。組は数字 1,2,3… か文字 A,B,C…
//   - .custom : 任意名（例「職員室」「営業部」）＋ 個人ラベル
//
//  どちらのモードでも内部的に「番号」（出席番号/管理番号）は常に
//  持つ。ファイル名やCSVのキー、ポスターの並び順に使う。
// ════════════════════════════════════════════════════════════════

enum GroupingMode: String, Codable, CaseIterable, Identifiable {
    case school   // 学年 + 組 + 番号
    case custom   // 集団名 + 個人ラベル
    var id: String { rawValue }
}

/// 組ラベル — 数字 (1組、2組…) or 文字 (A組、B組…)
enum ClassLabel: Codable, Hashable {
    case number(Int)        // 1 → "1組"
    case letter(String)     // "A" → "A組"

    /// 表示文字列（"1組" / "A組"）
    var display: String {
        switch self {
        case .number(let n): return "\(n)組"
        case .letter(let s): return "\(s)組"
        }
    }
    /// ファイル名／CSV用の正規化キー（数字ならその値、文字なら ASCII 大文字、
    /// それでも被るとファイル名で困るので頭1〜2文字を採用）
    var fileKey: String {
        switch self {
        case .number(let n): return "\(n)"
        case .letter(let s): return s.uppercased()
        }
    }

    // Codable は手動実装（associated value 付き enum）
    private enum CodingKeys: String, CodingKey { case kind, value }
    private enum Kind: String, Codable { case number, letter }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let kind = try c.decode(Kind.self, forKey: .kind)
        switch kind {
        case .number: self = .number(try c.decode(Int.self, forKey: .value))
        case .letter: self = .letter(try c.decode(String.self, forKey: .value))
        }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .number(let n):
            try c.encode(Kind.number, forKey: .kind)
            try c.encode(n, forKey: .value)
        case .letter(let s):
            try c.encode(Kind.letter, forKey: .kind)
            try c.encode(s, forKey: .value)
        }
    }
}

/// 集団の設定。AppState に1つ持つ。
struct GroupConfig: Codable, Equatable {
    var mode: GroupingMode = .school

    // school モード
    var grade: Int = 1
    var classLabel: ClassLabel = .number(1)

    // custom モード
    var groupName: String = ""        // 例「職員室」
    var groupSubtitle: String = ""    // 例「2026年度」

    /// ヘッダー等に出す集団の表示名
    var displayName: String {
        switch mode {
        case .school:
            return "\(grade)年 \(classLabel.display)"
        case .custom:
            return groupName.isEmpty ? "（集団名未設定）" : groupName
        }
    }

    /// ヘッダーの副題
    var displaySubtitle: String {
        switch mode {
        case .school: return "個人写真一覧"
        case .custom: return groupSubtitle.isEmpty ? "メンバー一覧" : groupSubtitle
        }
    }

    /// ファイル名やフォルダ名に使う安全な短い識別子
    /// - .school : "{grade}年{classKey}組"
    /// - .custom : groupName の英数字部分（なければ "group"）
    var fileSafeID: String {
        switch mode {
        case .school:
            return "\(grade)年\(classLabel.display)"
        case .custom:
            let stripped = groupName.replacingOccurrences(
                of: "[^A-Za-z0-9一-龯ぁ-んァ-ヶー]",
                with: "", options: .regularExpression)
            return stripped.isEmpty ? "group" : stripped
        }
    }

    /// 既存コード互換用：可能であれば旧 cls(Int) を返す
    /// school モード×number のときのみ妥当。他は 1 を返すフォールバック。
    var legacyClsInt: Int {
        if case .school = mode, case .number(let n) = classLabel { return n }
        return 1
    }
}
