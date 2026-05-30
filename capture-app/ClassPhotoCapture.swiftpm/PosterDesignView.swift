import SwiftUI
import PDFKit

// ════════════════════════════════════════════════════════════════
//  PosterDesignView — ポスター生成画面
//
//  ReviewView から「ポスターを作成」で起動。
//  紙サイズ・配色プリセット・列数行数を選んで PDF を生成し、
//  画面下にプレビュー、共有シートで書き出し。
//
//  Phase 3 は最小機能。色詳細カスタマイズは Phase 4 で実装。
// ════════════════════════════════════════════════════════════════

struct PosterDesignView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss

    @State private var config = PosterConfig()
    @State private var generatedURL: URL? = nil
    @State private var isGenerating = false
    @State private var error: String? = nil
    @State private var showShare = false
    @State private var presetIndex: Int = 0

    /// 紙サイズに応じた推奨レイアウトを最初に当てておく
    init() {
        var c = PosterConfig()
        c.paper = .A1
        c.cols = c.paper.suggestedCols
        c.rows = c.paper.suggestedRows
        _config = State(initialValue: c)
    }

    var body: some View {
        NavigationStack {
            Form {
                paperSection
                designSection
                layoutSection
                teacherSection
                generateSection
                if let url = generatedURL {
                    previewSection(url)
                }
            }
            .navigationTitle("ポスターを作成")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("閉じる") { dismiss() }
                }
            }
            .alert("生成エラー",
                   isPresented: .constant(error != nil)) {
                Button("OK") { error = nil }
            } message: { Text(error ?? "") }
            .sheet(isPresented: $showShare) {
                if let url = generatedURL { ShareSheet(items: [url]) }
            }
            .onChange(of: config.paper) { new in
                // 紙サイズを変えたら推奨レイアウトに揃える
                config.cols = new.suggestedCols
                config.rows = new.suggestedRows
                clearGenerated()
            }
            .onChange(of: presetIndex) { idx in
                config.design = PosterDesign.presets[safe: idx]?.value ?? .default
                clearGenerated()
            }
        }
    }

    // MARK: - セクション

    private var paperSection: some View {
        Section("用紙サイズ") {
            Picker("シリーズ", selection: $config.paper) {
                ForEach(PaperSize.allCases) { p in
                    Text(p.displayName).tag(p)
                }
            }
            .pickerStyle(.menu)
            Text("印刷時はプリンターで「実寸（100%）」を指定してください。\n2026年度の標準は **A1（594×841mm）** です。")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var designSection: some View {
        Section("配色プリセット") {
            Picker("プリセット", selection: $presetIndex) {
                ForEach(Array(PosterDesign.presets.enumerated()), id: \.offset) { idx, item in
                    Text(item.name).tag(idx)
                }
            }
            .pickerStyle(.segmented)
            // 色のサムネ
            HStack(spacing: 6) {
                colorChip(config.design.headerBg, label: "ヘッダー")
                colorChip(config.design.labelBg,  label: "ラベル")
                colorChip(config.design.numberFg, label: "番号")
                colorChip(config.design.teacherBg, label: "担任")
                colorChip(config.design.background, label: "背景", border: true)
            }
            .padding(.top, 4)
            Text("詳細な色のカスタマイズは Phase 4 で実装します。")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
    }

    private var layoutSection: some View {
        Section("レイアウト") {
            Stepper("列数: \(config.cols) 列", value: $config.cols, in: 3...8)
            Stepper("行数: \(config.rows) 行（最低）", value: $config.rows, in: 3...12)
            Text("行数は人数に合わせて自動で増えます。ここで設定するのは最低行数です。")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var teacherSection: some View {
        Section("担任") {
            Toggle("担任を含める", isOn: $config.includeTeacher)
                .disabled(state.roster.teachers.isEmpty)
            if state.roster.teachers.isEmpty {
                Text("担任の名簿が未設定です。「名簿」で担任名を入力してください。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var generateSection: some View {
        Section {
            Button {
                generate()
            } label: {
                HStack {
                    if isGenerating { ProgressView() }
                    else { Image(systemName: "doc.text.image") }
                    Text(isGenerating ? "生成中…" : "ポスターを生成")
                        .fontWeight(.semibold)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 4)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(isGenerating || state.capturedCount == 0)

            if state.capturedCount == 0 {
                Text("撮影済みが1人もありません。")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
            if !rosterReady {
                Text("名簿が一部未入力です（名前の無い人は空欄で表示されます）。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func previewSection(_ url: URL) -> some View {
        Section("プレビュー") {
            PDFKitPreview(url: url)
                .frame(height: 380)
                .background(Color.black.opacity(0.05))
            Button {
                showShare = true
            } label: {
                Label("PDF を書き出す（共有）", systemImage: "square.and.arrow.up")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            Text(url.lastPathComponent)
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
    }

    // MARK: - ヘルパ

    private func colorChip(_ color: Color, label: String, border: Bool = false) -> some View {
        VStack(spacing: 3) {
            RoundedRectangle(cornerRadius: 6)
                .fill(color)
                .frame(width: 36, height: 28)
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.secondary.opacity(border ? 0.3 : 0), lineWidth: 1)
                )
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    private var rosterReady: Bool {
        let entered = state.roster.students.filter { !$0.furigana.isEmpty || !$0.name.isEmpty }.count
        return entered >= state.roster.students.count
    }

    private func clearGenerated() {
        if let url = generatedURL {
            try? FileManager.default.removeItem(at: url)
        }
        generatedURL = nil
    }

    private func generate() {
        clearGenerated()
        isGenerating = true
        let group = state.group
        let roster = state.roster
        let shots = state.shots
        let cfg = config
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let url = try PosterRenderer.renderPDF(group: group,
                                                       roster: roster,
                                                       shots: shots,
                                                       config: cfg)
                DispatchQueue.main.async {
                    isGenerating = false
                    generatedURL = url
                }
            } catch {
                DispatchQueue.main.async {
                    isGenerating = false
                    self.error = "\(error)"
                }
            }
        }
    }
}

// MARK: - PDF プレビュー（PDFKit ラッパ）

private struct PDFKitPreview: UIViewRepresentable {
    let url: URL
    func makeUIView(context: Context) -> PDFView {
        let v = PDFView()
        v.autoScales = true
        v.displayMode = .singlePageContinuous
        v.backgroundColor = UIColor.systemGray6
        v.document = PDFDocument(url: url)
        return v
    }
    func updateUIView(_ uiView: PDFView, context: Context) {
        if uiView.document?.documentURL != url {
            uiView.document = PDFDocument(url: url)
        }
    }
}

// ヘルパ
private extension Array {
    subscript(safe i: Int) -> Element? {
        indices.contains(i) ? self[i] : nil
    }
}
