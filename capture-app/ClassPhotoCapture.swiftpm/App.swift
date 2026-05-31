import SwiftUI

// ポスターの写真エリア比率（cw/ph）。crop_adjuster.py の CELL_ASPECT と一致させること。
// 2026年度よりデフォルト用紙が A1 になったため A1 6×7 基準 ≒ 1.0076。
// （用紙が変わると実セル比は変わるが、PosterRenderer は実セル比で smart_crop
//  し直すので歪みは出ない。本値は撮影ガイドと crop_adjuster プレビュー用の代表値。）
let CELL_ASPECT: CGFloat = 1.0076

@main
struct ClassPhotoCaptureApp: App {
    @StateObject private var state = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(state)
        }
    }
}

/// 画面遷移を一元管理するルート
struct RootView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        switch state.screen {
        case .setup:
            SetupView()
        case .capture:
            CaptureView()
        case .review:
            ReviewView()
        case .rosterEditor, .posterDesign:
            SetupView()
                .onAppear { state.screen = .setup }
        }
    }
}
