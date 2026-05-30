import SwiftUI

// ════════════════════════════════════════════════════════════════
//  RosterEditorView — 名簿手入力
//
//  ReviewView から「名簿を編集」で起動。出席番号順に
//  ふりがな（ポスター掲載用）／漢字／担任名 を入力。
//
//  AppState.roster を直接編集するので、戻った瞬間に反映される。
//  追加機能（CSV取り込み・OCR）は別シートとして上部に並べる予定。
// ════════════════════════════════════════════════════════════════

struct RosterEditorView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss

    /// 入力フォーカスを enum で一元管理（タップで該当フィールドへフォーカスを送れる）
    enum Field: Hashable {
        case studentFurigana(Int)   // 出席番号
        case studentKanji(Int)
        case teacherFurigana(Int)
        case teacherKanji(Int)
    }
    @FocusState private var focused: Field?
    @State private var showImporter = false

    var body: some View {
        NavigationStack {
            Form {
                styleSection
                studentSection
                if !state.roster.teachers.isEmpty {
                    teacherSection
                }
                hintSection
            }
            .navigationTitle("名簿")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完了") { dismiss() }
                        .fontWeight(.semibold)
                }
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        Button {
                            showImporter = true
                        } label: {
                            Label("CSV / TSV から取り込み", systemImage: "tablecells.badge.ellipsis")
                        }
                        Divider()
                        Button(role: .destructive) {
                            clearAllNames()
                        } label: {
                            Label("すべて消去", systemImage: "eraser")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
                // キーボード上の「次へ」ボタン
                ToolbarItemGroup(placement: .keyboard) {
                    Button {
                        focusPrevious()
                    } label: { Image(systemName: "chevron.up") }
                    Button {
                        focusNext()
                    } label: { Image(systemName: "chevron.down") }
                    Spacer()
                    Button("閉じる") { focused = nil }
                }
            }
            .onAppear {
                // 撮影リストと名簿の人数を必ず揃える（後から人数変更しても破綻しないよう）
                state.roster.ensureStudentCount(state.studentCount)
                state.roster.ensureTeacherCount(state.teacherCount)
            }
            .sheet(isPresented: $showImporter) {
                RosterImportView().environmentObject(state)
            }
        }
    }

    // MARK: - セクション

    private var styleSection: some View {
        Section {
            Picker("ポスター表記", selection: $state.roster.nameStyle) {
                ForEach(NameStyle.allCases) { s in
                    Text(s.label).tag(s)
                }
            }
            .pickerStyle(.segmented)
        } header: {
            Text("ポスターに載せる名前")
        } footer: {
            Text(state.roster.nameStyle == .furigana
                 ? "ふりがな欄を優先表示します。空ならば漢字を使います。"
                 : "漢字欄を優先表示します。空ならばふりがなを使います。")
                .font(.caption)
        }
    }

    private var studentSection: some View {
        Section {
            ForEach(state.roster.students) { member in
                MemberRow(member: member,
                          numberLabel: "\(member.number)番",
                          focusedFurigana: $focused,
                          furiganaField: .studentFurigana(member.number),
                          kanjiField: .studentKanji(member.number))
            }
        } header: {
            Text("児童・生徒  \(state.roster.students.count)名")
        }
    }

    private var teacherSection: some View {
        Section {
            ForEach(state.roster.teachers) { member in
                MemberRow(member: member,
                          numberLabel: state.roster.teachers.count > 1
                            ? "担任\(member.number)"
                            : "担任",
                          focusedFurigana: $focused,
                          furiganaField: .teacherFurigana(member.number),
                          kanjiField: .teacherKanji(member.number))
            }
        } header: {
            Text("担任  \(state.roster.teachers.count)名")
        }
    }

    private var hintSection: some View {
        Section {
            Label {
                Text("ふりがなは将来 CSV / Excel 取り込みや、漢字からの自動生成にも対応する予定です。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } icon: {
                Image(systemName: "lightbulb")
                    .foregroundStyle(.yellow)
            }
        }
    }

    // MARK: - フォーカス移動

    /// 入力欄を順に並べた一覧（移動順を決める）
    private var fieldOrder: [Field] {
        var arr: [Field] = []
        for m in state.roster.students {
            arr.append(.studentFurigana(m.number))
            arr.append(.studentKanji(m.number))
        }
        for m in state.roster.teachers {
            arr.append(.teacherFurigana(m.number))
            arr.append(.teacherKanji(m.number))
        }
        return arr
    }
    private func focusNext() {
        let order = fieldOrder
        guard let cur = focused, let i = order.firstIndex(of: cur) else {
            focused = order.first; return
        }
        focused = order[safe: i + 1] ?? order.first
    }
    private func focusPrevious() {
        let order = fieldOrder
        guard let cur = focused, let i = order.firstIndex(of: cur) else {
            focused = order.last; return
        }
        focused = order[safe: i - 1] ?? order.last
    }

    private func clearAllNames() {
        for m in state.roster.students {
            m.name = ""; m.furigana = ""
        }
        for m in state.roster.teachers {
            m.name = ""; m.furigana = ""
        }
    }
}

// MARK: - 1人分の行

private struct MemberRow: View {
    @ObservedObject var member: Member
    let numberLabel: String
    @FocusState.Binding var focusedFurigana: RosterEditorView.Field?
    let furiganaField: RosterEditorView.Field
    let kanjiField: RosterEditorView.Field

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(numberLabel)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 56, alignment: .leading)
                VStack(alignment: .leading, spacing: 6) {
                    TextField("ふりがな（例: たなか たろう）",
                              text: $member.furigana)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focusedFurigana, equals: furiganaField)
                    Divider()
                    TextField("漢字（例: 田中 太郎）",
                              text: $member.name)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focusedFurigana, equals: kanjiField)
                }
            }
        }
        .padding(.vertical, 2)
    }
}

// MARK: - 範囲外を nil で受ける小さなヘルパ

private extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}
