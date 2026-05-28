import SwiftUI

// ════════════════════════════════════════════════════════════════
//  SetupView — 設定画面（学年・組・人数・画像形式）
// ════════════════════════════════════════════════════════════════

struct SetupView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        NavigationStack {
            Form {
                Section("クラス") {
                    Stepper("学年: \(state.grade) 年", value: $state.grade,
                            in: state.gradeRange)
                    Stepper("組: \(state.cls) 組", value: $state.cls,
                            in: state.clsRange)
                    Stepper("人数: \(state.studentCount) 人", value: $state.studentCount,
                            in: state.countRange)
                }

                Section("画像形式") {
                    Picker("保存形式", selection: $state.imageFormat) {
                        ForEach(ImageFormat.allCases) { f in
                            Text(f.rawValue).tag(f)
                        }
                    }
                    .pickerStyle(.segmented)
                    Text("JPEG は互換性が高くおすすめです。HEIC は容量が小さくなります。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("撮影の進め方") {
                    Label("顔を金色の枠に合わせて撮影します", systemImage: "viewfinder")
                    Label("撮影 → 確認 → 自動で次の番号へ", systemImage: "arrow.right.circle")
                    Label("欠席は「欠席」ボタンでスキップ", systemImage: "person.slash")
                }

                Section {
                    Button {
                        state.startCapture()
                    } label: {
                        HStack {
                            Spacer()
                            Label("撮影をはじめる（全 \(state.studentCount) 人）",
                                  systemImage: "camera.fill")
                                .font(.headline)
                            Spacer()
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                }
            }
            .navigationTitle("クラス写真キャプチャ")
        }
    }
}
