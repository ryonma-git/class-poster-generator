import SwiftUI

// ポスターの写真エリア比率（cw/ph）。crop_adjuster.py の CELL_ASPECT と一致させること。
// A2 6×7 レイアウトでの実測値 ≒ 1.1289。
let CELL_ASPECT: CGFloat = 1.1289

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
        }
    }
}
