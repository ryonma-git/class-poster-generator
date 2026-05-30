import Foundation
import SwiftUI

// ════════════════════════════════════════════════════════════════
//  Roster — 名簿モデル
//
//  Member 1人 = 1セル分のメタデータ（氏名・ふりがな・番号・役職など）
//  ポスター生成に必須。撮影だけなら空でも動く（旧来通り番号だけで進行）。
// ════════════════════════════════════════════════════════════════

enum MemberRole: String, Codable, CaseIterable, Identifiable {
    case student   // 児童・生徒・メンバー
    case teacher   // 担任・リーダー
    var id: String { rawValue }
}

final class Member: Identifiable, ObservableObject, Codable {
    let id: UUID
    let role: MemberRole

    /// 並び順を決める番号。学校モードでは出席番号。
    /// 集団モードでも内部的に必ず持つ（CSV列やファイル名のキー）。
    @Published var number: Int

    /// 氏名（漢字 or そのまま表示用）
    @Published var name: String = ""
    /// ふりがな（ポスターのデフォルト表記）
    @Published var furigana: String = ""

    /// 集団モード時の個人ラベル（例「校長」「教頭」）。
    /// 学校モードでは未使用（nil）。
    @Published var customLabel: String? = nil

    init(id: UUID = UUID(), role: MemberRole, number: Int,
         name: String = "", furigana: String = "",
         customLabel: String? = nil) {
        self.id = id
        self.role = role
        self.number = number
        self.name = name
        self.furigana = furigana
        self.customLabel = customLabel
    }

    // ── Codable（@Published は手動で取り回す） ──
    private enum CodingKeys: String, CodingKey {
        case id, role, number, name, furigana, customLabel
    }
    convenience init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(
            id: try c.decode(UUID.self, forKey: .id),
            role: try c.decode(MemberRole.self, forKey: .role),
            number: try c.decode(Int.self, forKey: .number),
            name: try c.decodeIfPresent(String.self, forKey: .name) ?? "",
            furigana: try c.decodeIfPresent(String.self, forKey: .furigana) ?? "",
            customLabel: try c.decodeIfPresent(String.self, forKey: .customLabel)
        )
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(role, forKey: .role)
        try c.encode(number, forKey: .number)
        try c.encode(name, forKey: .name)
        try c.encode(furigana, forKey: .furigana)
        try c.encodeIfPresent(customLabel, forKey: .customLabel)
    }
}

/// ポスターでの名前表記モード
enum NameStyle: String, Codable, CaseIterable, Identifiable {
    case furigana   // ふりがな優先（本体準拠／デフォルト）
    case kanji      // 漢字
    var id: String { rawValue }
    var label: String { self == .furigana ? "ふりがな" : "漢字" }
}

/// 名簿全体
final class Roster: ObservableObject, Codable {
    /// 児童・メンバー（番号順）
    @Published var students: [Member] = []
    /// 担任・リーダー（番号順）
    @Published var teachers: [Member] = []
    /// ポスターでの名前表記
    @Published var nameStyle: NameStyle = .furigana

    init() {}

    /// 出席番号 → Member 引き当て
    func studentByNumber(_ n: Int) -> Member? {
        students.first { $0.number == n }
    }
    func teacherByNumber(_ n: Int) -> Member? {
        teachers.first { $0.number == n }
    }

    /// 学生数に合わせて students を伸縮（足りなければ追加、余れば末尾を削除）
    func ensureStudentCount(_ count: Int) {
        if students.count < count {
            for n in (students.count + 1)...count {
                students.append(Member(role: .student, number: n))
            }
        } else if students.count > count {
            students = Array(students.prefix(count))
        }
        renumberStudents()
    }
    func ensureTeacherCount(_ count: Int) {
        if teachers.count < count {
            for n in (teachers.count + 1)...max(1, count) {
                teachers.append(Member(role: .teacher, number: n))
            }
            if count == 0 { teachers.removeAll() }
        } else if teachers.count > count {
            teachers = Array(teachers.prefix(count))
        }
        renumberTeachers()
    }
    func renumberStudents() {
        for (i, m) in students.enumerated() { m.number = i + 1 }
    }
    func renumberTeachers() {
        for (i, m) in teachers.enumerated() { m.number = i + 1 }
    }

    /// ポスター表記に出す名前（ふりがな or 漢字、どちらか欠ければ他方を返す）
    func displayName(for member: Member) -> String {
        switch nameStyle {
        case .furigana:
            return member.furigana.isEmpty ? member.name : member.furigana
        case .kanji:
            return member.name.isEmpty ? member.furigana : member.name
        }
    }

    // ── Codable ──
    private enum CodingKeys: String, CodingKey {
        case students, teachers, nameStyle
    }
    convenience init(from decoder: Decoder) throws {
        self.init()
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.students = try c.decodeIfPresent([Member].self, forKey: .students) ?? []
        self.teachers = try c.decodeIfPresent([Member].self, forKey: .teachers) ?? []
        self.nameStyle = try c.decodeIfPresent(NameStyle.self, forKey: .nameStyle) ?? .furigana
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(students, forKey: .students)
        try c.encode(teachers, forKey: .teachers)
        try c.encode(nameStyle, forKey: .nameStyle)
    }
}
