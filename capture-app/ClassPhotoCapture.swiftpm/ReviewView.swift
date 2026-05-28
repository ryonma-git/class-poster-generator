import SwiftUI

// ════════════════════════════════════════════════════════════════
//  ReviewView — 撮影済み一覧の確認と書き出し
// ════════════════════════════════════════════════════════════════

struct ReviewView: View {
    @EnvironmentObject var state: AppState

    @State private var shareURL: URL? = nil
    @State private var showShare = false
    @State private var exportError: String? = nil
    @State private var isExporting = false

    private let cols = [GridItem(.adaptive(minimum: 96), spacing: 10)]

    var body: some View {
        NavigationStack {
            ScrollView {
                summary
                LazyVGrid(columns: cols, spacing: 12) {
                    ForEach(state.shots) { shot in
                        cell(shot)
                            .onTapGesture { jumpTo(shot) }
                    }
                }
                .padding()
            }
            .navigationTitle("確認・書き出し")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        state.screen = .capture
                    } label: { Label("撮影へ戻る", systemImage: "camera") }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        export()
                    } label: {
                        if isExporting { ProgressView() }
                        else { Label("書き出す", systemImage: "square.and.arrow.up") }
                    }
                    .disabled(isExporting || state.capturedCount == 0)
                }
            }
            .sheet(isPresented: $showShare) {
                if let url = shareURL { ShareSheet(items: [url]) }
            }
            .alert("書き出しエラー", isPresented: .constant(exportError != nil)) {
                Button("OK") { exportError = nil }
            } message: {
                Text(exportError ?? "")
            }
        }
    }

    private var summary: some View {
        VStack(spacing: 4) {
            Text("\(state.grade)年 \(state.cls)組")
                .font(.title2.bold())
            Text("撮影済 \(state.capturedCount) ／ 欠席 \(state.absentCount) ／ 未撮影 \(state.shots.count - state.doneCount)")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text("形式: \(state.imageFormat.rawValue)　タップでその番号の撮影に戻れます")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 8)
    }

    @ViewBuilder
    private func cell(_ shot: StudentShot) -> some View {
        VStack(spacing: 4) {
            ZStack {
                RoundedRectangle(cornerRadius: 8).fill(Color(.secondarySystemBackground))
                if let img = shot.image {
                    Image(uiImage: img)
                        .resizable().scaledToFill()
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                } else if shot.status == .absent {
                    VStack { Image(systemName: "person.slash"); Text("欠席").font(.caption2) }
                        .foregroundStyle(.secondary)
                } else {
                    VStack { Image(systemName: "camera"); Text("未").font(.caption2) }
                        .foregroundStyle(.tertiary)
                }
            }
            .frame(width: 96, height: 96 / CELL_ASPECT)
            .overlay(alignment: .topLeading) {
                Text("\(shot.number)")
                    .font(.caption2.bold())
                    .padding(3)
                    .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 4))
                    .foregroundStyle(.white)
                    .padding(3)
            }
        }
    }

    private func jumpTo(_ shot: StudentShot) {
        if let idx = state.shots.firstIndex(where: { $0.id == shot.id }) {
            state.currentIndex = idx
            state.screen = .capture
        }
    }

    private func export() {
        isExporting = true
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let url = try Exporter.makeZip(grade: state.grade, cls: state.cls,
                                               shots: state.shots, format: state.imageFormat)
                DispatchQueue.main.async {
                    isExporting = false
                    shareURL = url
                    showShare = true
                }
            } catch {
                DispatchQueue.main.async {
                    isExporting = false
                    exportError = "書き出しに失敗しました: \(error.localizedDescription)"
                }
            }
        }
    }
}
