import SwiftUI
import UniformTypeIdentifiers

// ════════════════════════════════════════════════════════════════
//  RosterImportView — CSV/TSV から名簿を取り込み
//
//  RosterEditorView の右上メニューから起動。
//  ファイル選択 → 列マッピング確認 → プレビュー → 適用 の流れ。
//
//  Excel(.xlsx) は v1 では直接読めない（zip+XML パーサが必要）。
//  CSV/TSV にエクスポートしてもらう案内を表示。
// ════════════════════════════════════════════════════════════════

struct RosterImportView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss

    @State private var showFilePicker = false
    @State private var imported: ImportedRoster? = nil
    @State private var error: String? = nil
    @State private var didApply = false
    @State private var appliedSummary: String = ""

    var body: some View {
        NavigationStack {
            Group {
                if let r = imported {
                    importContent(r)
                } else if didApply {
                    appliedScreen
                } else {
                    introScreen
                }
            }
            .navigationTitle("名簿を取り込み")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("キャンセル") { dismiss() }
                }
                if imported != nil {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("ファイルを変更") {
                            imported = nil
                            showFilePicker = true
                        }
                    }
                }
            }
            .fileImporter(
                isPresented: $showFilePicker,
                allowedContentTypes: [
                    UTType.commaSeparatedText,
                    UTType.tabSeparatedText,
                    UTType.text,
                    UTType.plainText
                ],
                allowsMultipleSelection: false
            ) { result in
                switch result {
                case .success(let urls):
                    if let url = urls.first { loadFile(url) }
                case .failure(let err):
                    error = "ファイル選択エラー: \(err.localizedDescription)"
                }
            }
            .alert("取り込みエラー", isPresented: .constant(error != nil)) {
                Button("OK") { error = nil }
            } message: {
                Text(error ?? "")
            }
        }
    }

    // MARK: - 画面

    /// 初期画面：説明＋ファイル選択ボタン
    private var introScreen: some View {
        Form {
            Section {
                Label("CSV / TSV ファイルから一括入力", systemImage: "tablecells")
                    .font(.headline)
                Text("名簿を CSV / TSV で書き出して取り込みます。番号・氏名・ふりがな（あれば学年・組）を自動でマップします。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Section("対応フォーマット") {
                Label("CSV（カンマ区切り）", systemImage: "doc.text")
                Label("TSV（タブ区切り）", systemImage: "doc.text")
                Label("文字コード: UTF-8 / Shift-JIS 自動判定", systemImage: "character")
            }
            Section("Excel(.xlsx)の場合") {
                Text("Excel から「ファイル → 名前を付けて保存 → CSV UTF-8」で書き出してから選んでください。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Section {
                Button {
                    showFilePicker = true
                } label: {
                    Label("ファイルを選択", systemImage: "folder")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
            Section("本体（PC）の名簿フォーマット") {
                Text("PC 版（make_poster.py）が使う Excel 名簿（C=学年 D=組 E=番号 R=ふりがな の慣習列）も、ヘッダー無しの CSV にして保存すれば自動でマップされます。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    /// 取り込み後画面：マッピング確認＋プレビュー
    private func importContent(_ r: ImportedRoster) -> some View {
        Form {
            Section("検出結果") {
                LabeledRow("文字コード", r.detectedEncoding)
                LabeledRow("区切り", r.detectedDelimiter == "\t" ? "タブ" : "カンマ")
                LabeledRow("行数", "\(r.rows.count) 行" + (r.hasHeader ? "（1行目はヘッダー）" : "（ヘッダーなし）"))
            }

            Section {
                ForEach(0..<r.headers.count, id: \.self) { i in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(r.headers[i])
                                .font(.subheadline.weight(.semibold))
                            if let sample = sampleCell(r, col: i) {
                                Text(sample)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                        }
                        Spacer()
                        Picker(selection: bindingForCol(i)) {
                            ForEach(ImportField.allCases) { f in
                                Text(f.rawValue).tag(f)
                            }
                        } label: { EmptyView() }
                        .pickerStyle(.menu)
                        .labelsHidden()
                    }
                }
            } header: {
                Text("列の役割（各列が何のデータか）")
            } footer: {
                Text("番号・氏名・ふりがな の3つだけマップすれば取り込めます。学年・組は学校モードで自動フィルタに使われます。")
                    .font(.caption)
            }

            Section("プレビュー（最初の5行）") {
                ScrollView(.horizontal, showsIndicators: true) {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 12) {
                            ForEach(0..<r.headers.count, id: \.self) { i in
                                Text(roleLabel(for: i))
                                    .font(.caption2.bold())
                                    .foregroundStyle(Color.accentColor)
                                    .frame(minWidth: 80, alignment: .leading)
                            }
                        }
                        ForEach(Array(r.rows.prefix(5).enumerated()), id: \.offset) { _, row in
                            HStack(spacing: 12) {
                                ForEach(0..<r.headers.count, id: \.self) { i in
                                    Text(row[safe: i] ?? "")
                                        .font(.caption)
                                        .lineLimit(1)
                                        .frame(minWidth: 80, alignment: .leading)
                                }
                            }
                        }
                    }
                    .padding(.vertical, 4)
                }
            }

            Section {
                Button {
                    apply()
                } label: {
                    Label("この内容で名簿に適用", systemImage: "checkmark.seal")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!hasRequiredMapping)

                if !hasRequiredMapping {
                    Text("「番号」列がマップされていません。最低でも番号は指定してください。")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }
        }
    }

    /// 適用完了画面
    private var appliedScreen: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 56))
                .foregroundStyle(.green)
            Text("名簿に取り込みました")
                .font(.title2.bold())
            Text(appliedSummary)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button("閉じる") { dismiss() }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
        }
        .padding()
    }

    // MARK: - 操作

    private func loadFile(_ url: URL) {
        do {
            imported = try CSVImporter.load(from: url)
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "\(error)"
        }
    }

    private func apply() {
        guard let r = imported else { return }
        let result = CSVImporter.apply(r, to: state.roster, group: state.group)
        // 児童の人数が増えていたら撮影リスト側も整える方が親切だが、Phase 1 のシム経由で
        // ensureStudentCount は呼ばれるので、SetupView/CaptureView 側との整合は次回起動時に整う。
        appliedSummary = """
            適用 \(result.applied) 件 / スキップ \(result.skipped) 件
            （学年・組がマップされている場合は、現在の \(state.group.displayName) と一致する行のみ反映されました）
            """
        didApply = true
        imported = nil
    }

    // MARK: - バインディング

    private func bindingForCol(_ i: Int) -> Binding<ImportField> {
        Binding(
            get: { imported?.mapping[i] ?? .ignore },
            set: { newValue in
                guard imported != nil else { return }
                // 他の列に同じ役割が割り当てられていたら ignore に戻す（学年/組/番号/氏名/ふりがな は1列ずつ）
                if newValue != .ignore {
                    for (k, v) in imported!.mapping where k != i && v == newValue {
                        imported!.mapping[k] = .ignore
                    }
                }
                imported!.mapping[i] = newValue
            }
        )
    }

    private var hasRequiredMapping: Bool {
        guard let r = imported else { return false }
        return r.mapping.values.contains(.number)
    }

    private func roleLabel(for i: Int) -> String {
        guard let r = imported, let f = r.mapping[i] else { return "—" }
        if f == .ignore { return "—" }
        return f.rawValue
    }

    private func sampleCell(_ r: ImportedRoster, col: Int) -> String? {
        for row in r.rows.prefix(3) {
            if let v = row[safe: col], !v.isEmpty {
                return "例: \(v)"
            }
        }
        return nil
    }
}

// MARK: - 共通の行表示

private struct LabeledRow: View {
    let label: String
    let value: String
    init(_ l: String, _ v: String) { self.label = l; self.value = v }
    var body: some View {
        HStack {
            Text(label).foregroundStyle(.secondary)
            Spacer()
            Text(value).fontWeight(.medium)
        }
    }
}

private extension Array {
    subscript(safe i: Int) -> Element? {
        indices.contains(i) ? self[i] : nil
    }
}
