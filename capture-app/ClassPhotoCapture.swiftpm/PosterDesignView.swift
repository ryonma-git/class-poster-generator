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
    @State private var showDetailColors = false      // 詳細カラー編集を開いているか
    @State private var designConfigURL: URL? = nil   // 配色 JSON 書き出し
    @State private var showDesignShare = false       // 配色 JSON 用共有シート

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
                if showDetailColors {
                    detailColorsSection
                }
                designExportSection
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
            .sheet(isPresented: $showDesignShare) {
                if let url = designConfigURL { ShareSheet(items: [url]) }
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

            Toggle("詳細にカスタマイズ", isOn: $showDetailColors.animation())
                .font(.subheadline)
        }
    }

    /// 9項目を個別に編集できる詳細パネル
    private var detailColorsSection: some View {
        Section {
            colorEditorRow(label: "ヘッダー帯（主）",
                           subtitle: "ページ上部の濃い帯",
                           keyPath: \.headerBgHex)
            colorEditorRow(label: "ヘッダー帯（左サブ）",
                           subtitle: "左側の少し明るい帯",
                           keyPath: \.headerSubHex)
            colorEditorRow(label: "アクセント",
                           subtitle: "ヘッダー下線・番号・装飾線",
                           keyPath: \.accentHex)
            colorEditorRow(label: "背景",
                           subtitle: "ページ全体の地",
                           keyPath: \.backgroundHex)
            colorEditorRow(label: "カード背景",
                           subtitle: "児童セルの背景（写真の周囲）",
                           keyPath: \.cardBgHex)
            colorEditorRow(label: "ラベル背景",
                           subtitle: "氏名表示帯の地",
                           keyPath: \.labelBgHex)
            colorEditorRow(label: "ラベル文字",
                           subtitle: "氏名の文字色（通常は白）",
                           keyPath: \.labelFgHex)
            colorEditorRow(label: "番号",
                           subtitle: "出席番号の文字色",
                           keyPath: \.numberFgHex)
            colorEditorRow(label: "担任セル背景",
                           subtitle: "担任の地",
                           keyPath: \.teacherBgHex)

            Button {
                config.design = .default
                presetIndex = 0
                clearGenerated()
            } label: {
                Label("「標準」プリセットに戻す", systemImage: "arrow.uturn.backward")
                    .font(.subheadline)
            }
        } header: {
            Text("詳細カラー")
        } footer: {
            Text("変更は次回の生成時に反映されます。本体の make_poster.py と同じ design_config.json を作って共有できます（下のセクション）。")
                .font(.caption)
        }
    }

    /// 1行分の編集UI（ColorPicker＋hex表示）
    private func colorEditorRow(label: String,
                                subtitle: String,
                                keyPath: WritableKeyPath<PosterDesign, UInt32>) -> some View {
        let binding = Binding<Color>(
            get: { Color(hex: config.design[keyPath: keyPath]) },
            set: { newColor in
                config.design[keyPath: keyPath] = newColor.hexUInt32()
                clearGenerated()
            }
        )
        return HStack(spacing: 12) {
            ColorPicker(selection: binding, supportsOpacity: false) {
                EmptyView()
            }
            .labelsHidden()
            .frame(width: 44)

            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(.subheadline)
                Text(subtitle)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text(Color.hexString(config.design[keyPath: keyPath]))
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 2)
    }

    /// 配色を本体互換 JSON で書き出し
    private var designExportSection: some View {
        Section {
            Button {
                exportDesignConfig()
            } label: {
                Label("配色を本体（PC）に書き出す（design_config.json）",
                      systemImage: "arrow.up.doc")
            }
        } footer: {
            Text("書き出した design_config.json を crop_adjuster の作業フォルダに置くと、本体側のポスター出力もこの配色になります。")
                .font(.caption)
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
            Toggle("担任の写真を入れる", isOn: $config.useTeacherPhoto)
                .disabled(!config.includeTeacher || !hasAnyTeacherPhoto)
            if config.useTeacherPhoto && !hasAnyTeacherPhoto {
                Text("担任の写真が撮影されていません。撮影画面で担任を撮影してください。")
                    .font(.caption)
                    .foregroundStyle(.orange)
            } else if config.useTeacherPhoto {
                Text("担任セルが児童セルと同じ写真＋ラベル形式になります。地の色は担任色（青系）のまま。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    /// 担任 shot のいずれかに画像があるか
    private var hasAnyTeacherPhoto: Bool {
        state.shots.contains { $0.kind == .teacher && $0.image != nil }
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

    private func exportDesignConfig() {
        let json = config.design.designConfigJSON
        do {
            let data = try JSONSerialization.data(
                withJSONObject: json,
                options: [.prettyPrinted, .sortedKeys])
            let url = FileManager.default.temporaryDirectory
                .appendingPathComponent("design_config.json")
            try? FileManager.default.removeItem(at: url)
            try data.write(to: url)
            designConfigURL = url
            showDesignShare = true
        } catch {
            self.error = "配色の書き出しに失敗: \(error)"
        }
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
