import SwiftUI

// ════════════════════════════════════════════════════════════════
//  AppState — アプリ全体の状態
//
//  保持するもの:
//   - 画面遷移 (screen)
//   - 集団設定 (group): 学校モード or 集団モード
//   - 名簿     (roster): ポスター生成に使う氏名・ふりがな
//   - 撮影リスト (shots)
//   - 撮影オプション（画像形式・人数・担任人数・顔枠サイズ・ガイド表示）
// ════════════════════════════════════════════════════════════════

enum Screen {
    case setup
    case capture
    case review
    case rosterEditor   // 名簿入力（Phase 2）
    case posterDesign   // ポスター生成設定（Phase 3+）
}

final class AppState: ObservableObject {
    @Published var screen: Screen = .setup

    // ── 集団設定（旧 grade/cls/teacherCount を内包） ──
    @Published var group: GroupConfig = GroupConfig()

    // ── 撮影オプション ──
    @Published var studentCount: Int = 35
    @Published var teacherCount: Int = 1
    @Published var imageFormat: ImageFormat = .jpeg

    // 顔枠の幅（プレビュー幅に対する割合）。小さいほど顔アップ＝高ズーム。
    @Published var guideWidthFrac: CGFloat = 0.62
    // 顔位置ガイド（枠内に薄く表示する頭・肩のシルエット）の表示ON/OFF
    @Published var showFaceGuide: Bool = true

    // ── 撮影データ ──
    @Published var shots: [StudentShot] = []
    @Published var currentIndex: Int = 0

    // ── 名簿（ポスター生成に使用、撮影だけなら空でOK） ──
    @Published var roster: Roster = Roster()

    // 設定値の範囲
    let gradeRange = 1...6
    let countRange = 1...45
    let teacherRange = 0...5
    /// 数字組モード時の組番号レンジ
    let clsNumberRange = 1...12
    /// 文字組モード時の選択肢（A〜J）
    let clsLetterChoices = ["A","B","C","D","E","F","G","H","I","J"]

    // ── 旧APIの後方互換シム（既存ファイル段階移行用） ──
    var grade: Int {
        get { group.grade }
        set { group.grade = newValue }
    }
    /// 学校×数字組モード時のみ妥当。それ以外は legacyClsInt（=1）を返す。
    var cls: Int {
        get { group.legacyClsInt }
        set {
            if case .school = group.mode { group.classLabel = .number(newValue) }
        }
    }

    /// 設定をもとに撮影リスト＋名簿の枠を生成して撮影画面へ。
    func startCapture() {
        // 撮影リスト
        var arr: [StudentShot] = (1...max(1, studentCount))
            .map { StudentShot(kind: .student, number: $0) }
        if teacherCount > 0 {
            arr += (1...teacherCount).map { StudentShot(kind: .teacher, number: $0) }
        }
        shots = arr
        currentIndex = 0
        // 名簿の枠も人数に合わせて伸縮（既存入力は保持）
        roster.ensureStudentCount(studentCount)
        roster.ensureTeacherCount(teacherCount)
        screen = .capture
    }

    var currentShot: StudentShot? {
        guard shots.indices.contains(currentIndex) else { return nil }
        return shots[currentIndex]
    }

    var capturedCount: Int { shots.filter { $0.status == .captured }.count }
    var absentCount: Int { shots.filter { $0.status == .absent }.count }
    var doneCount: Int { shots.filter { $0.status != .pending }.count }

    /// 次の未処理（pending）へ移動。全て処理済みなら確認画面へ。
    func advanceToNextPending() {
        if let next = shots.indices.first(where: { $0 > currentIndex && shots[$0].status == .pending }) {
            currentIndex = next
        } else if let firstPending = shots.indices.first(where: { shots[$0].status == .pending }) {
            currentIndex = firstPending
        } else {
            screen = .review
        }
    }

    func goPrev() {
        if currentIndex > 0 { currentIndex -= 1 }
    }
    func goNext() {
        if currentIndex < shots.count - 1 { currentIndex += 1 }
    }
}
