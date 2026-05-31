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
    case home           // 表紙（新規／保存済みから選ぶ）
    case projectList    // 保存した撮影の一覧
    case setup
    case capture
    case review
    case rosterEditor   // 名簿入力（Phase 2）
    case posterDesign   // ポスター生成設定（Phase 3+）
}

final class AppState: ObservableObject {
    @Published var screen: Screen = .home

    // ── プロジェクト（複数クラス対応） ──
    /// 現在編集中のプロジェクトID。新規作成時に採番。
    @Published var currentProjectID: String = ProjectStore.newID()
    /// 現在プロジェクトの作成日時（保存時に維持）
    private var currentCreatedAt: Double = Date().timeIntervalSince1970

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
    /// 既に撮影済みのデータがあれば kind+number で引き継ぐ（設定画面に戻って
    /// 戻ってきても写真が消えないように）。
    func startCapture() {
        // 既存ショットを (kind, number) で引けるよう退避
        var existing: [String: StudentShot] = [:]
        for s in shots { existing["\(s.kind)-\(s.number)"] = s }

        func makeOrReuse(kind: ShotKind, number: Int) -> StudentShot {
            if let prev = existing["\(kind)-\(number)"] { return prev }
            return StudentShot(kind: kind, number: number)
        }

        var arr: [StudentShot] = (1...max(1, studentCount))
            .map { makeOrReuse(kind: .student, number: $0) }
        if teacherCount > 0 {
            arr += (1...teacherCount).map { makeOrReuse(kind: .teacher, number: $0) }
        }
        shots = arr
        // 最初の未撮影へ。全部撮影済みなら先頭。
        currentIndex = shots.firstIndex(where: { $0.status == .pending }) ?? 0
        // 名簿の枠も人数に合わせて伸縮（既存入力は保持）
        roster.ensureStudentCount(studentCount)
        roster.ensureTeacherCount(teacherCount)
        screen = .capture
    }

    /// 撮影画面へ戻る（リストは作り直さず、撮影済みデータを維持）。
    func resumeCapture() {
        if shots.isEmpty {
            startCapture()
        } else {
            screen = .capture
        }
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

    /// 設定画面へ戻る（撮影データは保持）。撮影途中に設定を見直したいとき用。
    func backToSetup() {
        screen = .setup
    }

    /// 撮影データを全消去して最初からやり直す（名簿は保持するか選べる）。
    /// - keepRoster: true なら名簿（名前・ふりがな）は残す。
    func resetCapture(keepRoster: Bool) {
        for shot in shots {
            shot.image = nil
            shot.cropRect = nil
            shot.status = .pending
        }
        // 撮影リスト自体も作り直す（人数変更にも追従）
        shots = []
        currentIndex = 0
        if !keepRoster {
            roster = Roster()
        }
        screen = .setup
    }

    // MARK: - プロジェクト（複数クラス）

    /// 新規プロジェクトを作って設定画面へ。
    func newProject() {
        currentProjectID = ProjectStore.newID()
        currentCreatedAt = Date().timeIntervalSince1970
        group = GroupConfig()
        studentCount = 35
        teacherCount = 1
        imageFormat = .jpeg
        roster = Roster()
        shots = []
        currentIndex = 0
        screen = .setup
    }

    /// 保存済みプロジェクトを開く。撮影済みがあれば確認画面、無ければ設定へ。
    func openProject(id: String) {
        guard let loaded = ProjectStore.load(id: id) else { return }
        let f = loaded.file
        currentProjectID = f.id
        currentCreatedAt = f.createdAt
        group = f.group
        studentCount = f.studentCount
        teacherCount = f.teacherCount
        imageFormat = ImageFormat(rawValue: f.imageFormat) ?? .jpeg
        roster = f.roster
        shots = loaded.shots
        currentIndex = shots.firstIndex(where: { $0.status == .pending }) ?? 0
        // 撮影が1枚でもあれば確認画面、無ければ設定画面
        let hasAny = shots.contains { $0.status != .pending }
        screen = hasAny ? .review : .setup
    }

    /// 現在の状態をディスクへ保存（撮影リストが空なら保存しない）。
    func saveCurrentProject() {
        guard !shots.isEmpty else { return }
        ProjectStore.save(
            id: currentProjectID,
            group: group,
            roster: roster,
            studentCount: studentCount,
            teacherCount: teacherCount,
            imageFormat: imageFormat,
            shots: shots,
            createdAt: currentCreatedAt
        )
    }

    /// ホームへ戻る（自動保存してから）。
    func goHome() {
        saveCurrentProject()
        screen = .home
    }

    func deleteProject(id: String) {
        ProjectStore.delete(id: id)
    }
}
