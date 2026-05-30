import SwiftUI

// ════════════════════════════════════════════════════════════════
//  AppState — アプリ全体の状態（画面遷移・設定・撮影データ）
// ════════════════════════════════════════════════════════════════

enum Screen {
    case setup
    case capture
    case review
}

final class AppState: ObservableObject {
    @Published var screen: Screen = .setup

    // ── 設定 ──
    @Published var grade: Int = 1            // 学年
    @Published var cls: Int = 1              // 組
    @Published var studentCount: Int = 35    // 人数
    @Published var teacherCount: Int = 1     // 担任の人数（0で担任なし）
    @Published var imageFormat: ImageFormat = .jpeg

    // 顔枠の幅（プレビュー幅に対する割合）。小さいほど顔アップ＝高ズーム。
    // 撮影場所が変わらなければ全員同じ枠で撮れるよう、セッションを通して保持する。
    @Published var guideWidthFrac: CGFloat = 0.62

    // 顔位置ガイド（枠内に薄く表示する頭・肩のシルエット）の表示ON/OFF
    @Published var showFaceGuide: Bool = true

    // ── 撮影データ ──
    @Published var shots: [StudentShot] = []
    @Published var currentIndex: Int = 0     // いま撮影中のインデックス

    // 設定値の範囲
    let gradeRange = 1...6
    let clsRange = 1...12
    let countRange = 1...45
    let teacherRange = 0...5

    /// 設定をもとに撮影リストを生成して撮影画面へ。
    /// 児童（番号順）の後に担任（1〜teacherCount）を続ける。
    func startCapture() {
        var arr: [StudentShot] = (1...max(1, studentCount))
            .map { StudentShot(kind: .student, number: $0) }
        if teacherCount > 0 {
            arr += (1...teacherCount).map { StudentShot(kind: .teacher, number: $0) }
        }
        shots = arr
        currentIndex = 0
        screen = .capture
    }

    var currentShot: StudentShot? {
        guard shots.indices.contains(currentIndex) else { return nil }
        return shots[currentIndex]
    }

    var capturedCount: Int {
        shots.filter { $0.status == .captured }.count
    }
    var absentCount: Int {
        shots.filter { $0.status == .absent }.count
    }
    var doneCount: Int {
        shots.filter { $0.status != .pending }.count
    }

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
