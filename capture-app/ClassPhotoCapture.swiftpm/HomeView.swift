import SwiftUI

// ════════════════════════════════════════════════════════════════
//  HomeView — 表紙
//
//  - 新しく撮影する → 設定画面へ（新規プロジェクト）
//  - 保存した撮影を開く → プロジェクト一覧へ
//
//  複数クラスを順に撮れるよう、保存済みプロジェクトの件数も表示。
// ════════════════════════════════════════════════════════════════

struct HomeView: View {
    @EnvironmentObject var state: AppState
    @State private var summaries: [ProjectSummary] = []

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 28) {
                    header

                    VStack(spacing: 14) {
                        // 新しく撮影する
                        Button {
                            state.newProject()
                        } label: {
                            actionLabel(icon: "camera.fill",
                                        title: "新しく撮影する",
                                        subtitle: "クラスを選んで撮影をはじめる")
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .tint(brandColor)

                        // 保存した撮影を開く
                        Button {
                            state.screen = .projectList
                        } label: {
                            actionLabel(icon: "folder.fill",
                                        title: "保存した撮影を開く",
                                        subtitle: summaries.isEmpty
                                            ? "まだ保存された撮影はありません"
                                            : "\(summaries.count) 件の撮影データ（作業途中も含む）")
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.large)
                        .disabled(summaries.isEmpty)
                    }
                    .padding(.horizontal)

                    // 直近の撮影をいくつか表示（あれば）
                    if !summaries.isEmpty {
                        recentSection
                    }
                }
                .padding(.vertical, 32)
                .frame(maxWidth: 560)
                .frame(maxWidth: .infinity)
            }
            .navigationTitle("")
            .onAppear { summaries = ProjectStore.loadSummaries() }
        }
    }

    private var header: some View {
        VStack(spacing: 10) {
            Image(systemName: "camera.aperture")
                .font(.system(size: 52))
                .foregroundStyle(brandColor)
            Text("クラス写真キャプチャ")
                .font(.largeTitle.bold())
            Text("撮影 → 名簿 → ポスターまで、この端末で。")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 12)
    }

    private func actionLabel(icon: String, title: String, subtitle: String) -> some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.title2)
                .frame(width: 32)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(subtitle)
                    .font(.caption)
                    .opacity(0.85)
            }
            Spacer()
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 6)
        .frame(maxWidth: .infinity)
    }

    private var recentSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("最近の撮影")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .padding(.horizontal)
            ForEach(summaries.prefix(3)) { s in
                Button {
                    state.openProject(id: s.id)
                } label: {
                    ProjectRow(summary: s)
                }
                .buttonStyle(.plain)
                .padding(.horizontal)
            }
            if summaries.count > 3 {
                Button("すべて見る（\(summaries.count) 件）") {
                    state.screen = .projectList
                }
                .font(.caption)
                .padding(.horizontal)
            }
        }
    }
}

// MARK: - プロジェクト一覧

struct ProjectListView: View {
    @EnvironmentObject var state: AppState
    @State private var summaries: [ProjectSummary] = []
    @State private var pendingDelete: ProjectSummary? = nil

    var body: some View {
        NavigationStack {
            Group {
                if summaries.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "tray")
                            .font(.system(size: 48))
                            .foregroundStyle(.secondary)
                        Text("保存された撮影はありません")
                            .font(.headline)
                        Text("ホームの「新しく撮影する」から始めてください。")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    .padding()
                } else {
                    List {
                        ForEach(summaries) { s in
                            Button {
                                state.openProject(id: s.id)
                            } label: {
                                ProjectRow(summary: s)
                            }
                            .buttonStyle(.plain)
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    pendingDelete = s
                                } label: {
                                    Label("削除", systemImage: "trash")
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("保存した撮影")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        state.screen = .home
                    } label: { Label("ホーム", systemImage: "house") }
                }
            }
            .onAppear { summaries = ProjectStore.loadSummaries() }
            .alert("この撮影を削除しますか？",
                   isPresented: .constant(pendingDelete != nil),
                   presenting: pendingDelete) { s in
                Button("削除", role: .destructive) {
                    state.deleteProject(id: s.id)
                    summaries = ProjectStore.loadSummaries()
                    pendingDelete = nil
                }
                Button("キャンセル", role: .cancel) { pendingDelete = nil }
            } message: { s in
                Text("「\(s.displayName)」の撮影データと写真がすべて削除されます。取り消せません。")
            }
        }
    }
}

// MARK: - 1行表示

struct ProjectRow: View {
    let summary: ProjectSummary

    var body: some View {
        HStack(spacing: 12) {
            thumbnail
            VStack(alignment: .leading, spacing: 3) {
                Text(summary.displayName)
                    .font(.headline)
                Text("撮影済 \(summary.capturedCount) / \(summary.totalCount) 名")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(Self.dateText(summary.updatedAt))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Spacer()
            // 進捗バッジ
            if summary.capturedCount >= summary.totalCount && summary.totalCount > 0 {
                Label("完了", systemImage: "checkmark.circle.fill")
                    .font(.caption2)
                    .foregroundStyle(.green)
            } else {
                Label("作業中", systemImage: "ellipsis.circle")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 6)
        .padding(.horizontal, 10)
        .background(Color(.secondarySystemBackground),
                    in: RoundedRectangle(cornerRadius: 12))
    }

    private var thumbnail: some View {
        Group {
            if let path = summary.thumbnailPath, let img = UIImage(contentsOfFile: path) {
                Image(uiImage: img)
                    .resizable()
                    .scaledToFill()
            } else {
                ZStack {
                    Color(.tertiarySystemBackground)
                    Image(systemName: "person.crop.rectangle")
                        .foregroundStyle(.secondary)
                }
            }
        }
        .frame(width: 48, height: 48)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private static func dateText(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "ja_JP")
        f.dateFormat = "M月d日(E) HH:mm"
        return f.string(from: d)
    }
}
