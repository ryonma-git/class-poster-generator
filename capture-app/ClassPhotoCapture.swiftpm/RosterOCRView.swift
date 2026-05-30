import SwiftUI
import PhotosUI

// ════════════════════════════════════════════════════════════════
//  RosterOCRView — 写真から名簿を取り込み（Vision OCR）
//
//  PhotosPicker で名簿の写真を選び、VisionOCRImporter で
//  番号・漢字・ふりがな に分解して表形式で表示。
//  ユーザが各セルを手直ししたあと「適用」で AppState.roster に反映。
//
//  認識精度の限界があるので、UI は「OCR結果はあくまで叩き台」と
//  明示しつつ、編集の自由度を最優先する。
// ════════════════════════════════════════════════════════════════

struct RosterOCRView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss

    @State private var pickerItem: PhotosPickerItem? = nil
    @State private var image: UIImage? = nil
    @State private var rows: [OCRRow] = []
    @State private var isProcessing = false
    @State private var error: String? = nil
    @State private var didApply = false
    @State private var appliedSummary: String = ""

    var body: some View {
        NavigationStack {
            Group {
                if didApply {
                    appliedScreen
                } else if !rows.isEmpty {
                    resultScreen
                } else {
                    introScreen
                }
            }
            .navigationTitle("写真から取り込み")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("キャンセル") { dismiss() }
                }
                if !rows.isEmpty {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("やり直す") { reset() }
                    }
                }
            }
            .onChange(of: pickerItem) { newItem in
                guard let newItem else { return }
                loadPickerItem(newItem)
            }
            .alert("認識エラー", isPresented: .constant(error != nil)) {
                Button("OK") { error = nil }
            } message: { Text(error ?? "") }
        }
    }

    // MARK: - 画面

    /// 初期画面
    private var introScreen: some View {
        Form {
            Section {
                Label("名簿の写真からテキストを抽出", systemImage: "doc.text.viewfinder")
                    .font(.headline)
                Text("プリントの名簿を撮影またはスキャンした画像から、Vision Framework で番号・漢字・ふりがなを自動抽出します。抽出後に表形式で確認・編集できます。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Section("対応する画像") {
                Label("印刷された名簿のスキャン・撮影", systemImage: "printer")
                Label("活字（フォント）で書かれた名前一覧", systemImage: "textformat")
            }
            Section("注意") {
                Text("手書き・斜め・暗い・小さい字は誤認識しやすいので、結果は必ず確認して手直ししてください。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Section {
                PhotosPicker(selection: $pickerItem,
                             matching: .images,
                             photoLibrary: .shared()) {
                    Label("写真を選ぶ", systemImage: "photo.on.rectangle.angled")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(isProcessing)
            }
            if isProcessing {
                Section {
                    HStack {
                        ProgressView()
                        Text("認識中…")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    /// OCR結果画面
    private var resultScreen: some View {
        Form {
            if let img = image {
                Section {
                    Image(uiImage: img)
                        .resizable()
                        .scaledToFit()
                        .frame(maxHeight: 200)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                } header: {
                    Text("元画像")
                }
            }
            Section {
                LabeledContent("検出行数", value: "\(rows.count) 行")
                LabeledContent("有効行（番号あり）",
                               value: "\(rows.filter { !$0.number.isEmpty }.count) 行")
            } header: { Text("結果サマリ") } footer: {
                Text("番号が空欄の行はスキップされます。必要なら手入力で埋めてください。")
                    .font(.caption)
            }

            Section("行データ（手直し可）") {
                ForEach($rows) { $row in
                    rowEditor($row)
                }
                .onDelete { rows.remove(atOffsets: $0) }

                Button {
                    rows.append(OCRRow())
                } label: {
                    Label("行を追加", systemImage: "plus.circle")
                }
                .font(.subheadline)
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
                .disabled(applicableRowCount == 0)
                if applicableRowCount == 0 {
                    Text("適用できる行がありません（番号入りの行が必要です）。")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }
        }
    }

    /// 適用完了
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

    // MARK: - 行エディタ

    private func rowEditor(_ row: Binding<OCRRow>) -> some View {
        HStack(spacing: 8) {
            TextField("番号", text: row.number)
                .keyboardType(.numberPad)
                .frame(width: 56)
                .textFieldStyle(.roundedBorder)
            VStack(alignment: .leading, spacing: 4) {
                TextField("漢字", text: row.kanji)
                    .textFieldStyle(.roundedBorder)
                TextField("ふりがな", text: row.furigana)
                    .textFieldStyle(.roundedBorder)
            }
        }
        .padding(.vertical, 2)
    }

    // MARK: - 操作

    private func loadPickerItem(_ item: PhotosPickerItem) {
        Task {
            do {
                guard let data = try await item.loadTransferable(type: Data.self),
                      let img = UIImage(data: data) else {
                    self.error = "画像を読み込めませんでした。"
                    return
                }
                await MainActor.run {
                    self.image = img
                    self.isProcessing = true
                }
                let result = try await VisionOCRImporter.recognize(img)
                await MainActor.run {
                    self.rows = result
                    self.isProcessing = false
                }
            } catch let e as OCRError {
                await MainActor.run {
                    self.error = e.errorDescription
                    self.isProcessing = false
                }
            } catch {
                await MainActor.run {
                    self.error = "\(error.localizedDescription)"
                    self.isProcessing = false
                }
            }
        }
    }

    private func apply() {
        var applied = 0
        var skipped = 0
        for row in rows {
            let numStr = row.number.trimmingCharacters(in: .whitespaces)
            guard let n = Int(numStr.trimmedAsciiDigits()), n > 0 else {
                skipped += 1; continue
            }
            // 該当 Member が無ければ追加
            if state.roster.studentByNumber(n) == nil {
                state.roster.students.append(Member(role: .student, number: n))
            }
            guard let m = state.roster.studentByNumber(n) else { skipped += 1; continue }
            let kanji = row.kanji.trimmingCharacters(in: .whitespaces)
            let furi = row.furigana.trimmingCharacters(in: .whitespaces)
            if !kanji.isEmpty { m.name = kanji }
            if !furi.isEmpty  { m.furigana = furi }
            applied += 1
        }
        // 番号順
        state.roster.students.sort { $0.number < $1.number }
        appliedSummary = "適用 \(applied) 件 / スキップ \(skipped) 件"
        didApply = true
    }

    private func reset() {
        pickerItem = nil
        image = nil
        rows = []
        isProcessing = false
    }

    private var applicableRowCount: Int {
        rows.filter { Int($0.number.trimmingCharacters(in: .whitespaces).trimmedAsciiDigits()) != nil }
            .count
    }
}
