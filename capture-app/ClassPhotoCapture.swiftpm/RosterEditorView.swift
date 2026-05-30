import SwiftUI

// ════════════════════════════════════════════════════════════════
//  RosterEditorView — 名簿手入力
//
//  担任 → 児童 の順に、漢字／ふりがなを入力。
//  キーボード操作は Excel ライク:
//    - Return（次へ）: 次の人の漢字欄へ
//    - Tab（外付けキーボード）: 同じ人の 漢字 → ふりがな → 次の人 と移動
//    - キーボード上の ▲▼ でも前後の欄に移動可能
//
//  AppState.roster を直接編集するので、戻った瞬間に反映される。
// ════════════════════════════════════════════════════════════════

struct RosterEditorView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss

    /// 入力フォーカス。role と番号で一意。漢字/ふりがなの2種。
    enum Field: Hashable {
        case kanji(MemberRole, Int)
        case furigana(MemberRole, Int)
    }
    @FocusState private var focused: Field?
    @State private var showImporter = false
    @State private var showOCR = false

    var body: some View {
        NavigationStack {
            Form {
                styleSection
                // 担任を先頭に（撮影は最後だが、名簿は担任から）
                if !state.roster.teachers.isEmpty {
                    teacherSection
                }
                studentSection
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
                            Label("Excel・CSV から取り込み", systemImage: "tablecells.badge.ellipsis")
                        }
                        Button {
                            showOCR = true
                        } label: {
                            Label("写真から取り込み（OCR）", systemImage: "doc.text.viewfinder")
                        }
                        Divider()
                        Button {
                            generateAllFurigana()
                        } label: {
                            Label("空欄のふりがなを自動生成", systemImage: "wand.and.stars")
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
                // キーボード上の前後移動
                ToolbarItemGroup(placement: .keyboard) {
                    Button { focusPrevious() } label: { Image(systemName: "chevron.up") }
                    Button { focusNext() } label: { Image(systemName: "chevron.down") }
                    Spacer()
                    Button("閉じる") { focused = nil }
                }
            }
            .onAppear {
                state.roster.ensureStudentCount(state.studentCount)
                state.roster.ensureTeacherCount(state.teacherCount)
            }
            .sheet(isPresented: $showImporter) {
                RosterImportView().environmentObject(state)
            }
            .sheet(isPresented: $showOCR) {
                RosterOCRView().environmentObject(state)
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

    private var teacherSection: some View {
        Section {
            ForEach(state.roster.teachers) { member in
                memberRow(member: member, role: .teacher,
                          numberLabel: state.roster.teachers.count > 1
                            ? "担任\(member.number)" : "担任")
            }
        } header: {
            Text("担任  \(state.roster.teachers.count)名")
        }
    }

    private var studentSection: some View {
        Section {
            ForEach(state.roster.students) { member in
                memberRow(member: member, role: .student,
                          numberLabel: "\(member.number)番")
            }
        } header: {
            Text("児童・生徒  \(state.roster.students.count)名")
        } footer: {
            Text("Return で次の人へ、外付けキーボードの Tab で漢字↔ふりがなを移動できます。")
                .font(.caption)
        }
    }

    private var hintSection: some View {
        Section {
            Label {
                Text("漢字を入れて「✨」を押すとふりがなを自動生成します（要確認）。Excel・CSV・写真からの一括取り込みは左上メニューから。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } icon: {
                Image(systemName: "lightbulb")
                    .foregroundStyle(.yellow)
            }
        }
    }

    // MARK: - 1人分の行（@FocusState を親で管理するためメソッドで構築）

    @ViewBuilder
    private func memberRow(member: Member, role: MemberRole, numberLabel: String) -> some View {
        let kanjiField = Field.kanji(role, member.number)
        let furiField = Field.furigana(role, member.number)
        HStack(alignment: .top) {
            Text(numberLabel)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 56, alignment: .leading)
                .padding(.top, 6)
            VStack(alignment: .leading, spacing: 6) {
                // 漢字（上）
                TextField("漢字（例: 田中 太郎）", text: bind(member, \.name))
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .focused($focused, equals: kanjiField)
                    .submitLabel(.next)
                    .onSubmit { advanceToNextPerson(after: member.number, role: role) }
                Divider()
                // ふりがな（下）＋ 自動生成
                HStack(spacing: 6) {
                    TextField("ふりがな（例: たなか たろう）", text: bind(member, \.furigana))
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focused, equals: furiField)
                        .submitLabel(.next)
                        .onSubmit { advanceToNextPerson(after: member.number, role: role) }
                    if !member.name.isEmpty {
                        Button {
                            let g = FuriganaGenerator.generate(member.name)
                            if !g.isEmpty { member.furigana = g }
                        } label: {
                            Image(systemName: "wand.and.stars")
                        }
                        .buttonStyle(.borderless)
                        .foregroundStyle(.purple)
                        .accessibilityLabel("漢字からふりがなを自動生成")
                    }
                }
            }
        }
        .padding(.vertical, 2)
    }

    /// Member の String プロパティへの Binding（@Published を直接束縛）
    private func bind(_ member: Member, _ keyPath: ReferenceWritableKeyPath<Member, String>) -> Binding<String> {
        Binding(
            get: { member[keyPath: keyPath] },
            set: { member[keyPath: keyPath] = $0 }
        )
    }

    // MARK: - フォーカス移動

    /// 担任 → 児童 の順で、各人 [漢字, ふりがな] と並べた全フィールド順
    private var fieldOrder: [Field] {
        var arr: [Field] = []
        for m in state.roster.teachers {
            arr.append(.kanji(.teacher, m.number))
            arr.append(.furigana(.teacher, m.number))
        }
        for m in state.roster.students {
            arr.append(.kanji(.student, m.number))
            arr.append(.furigana(.student, m.number))
        }
        return arr
    }

    /// Return（次へ）: 次の人の漢字欄へ。末尾ならキーボードを閉じる。
    private func advanceToNextPerson(after number: Int, role: MemberRole) {
        let order = fieldOrder
        // 現在の人の次の人の .kanji を探す
        guard let curIdx = order.firstIndex(where: {
            if case .kanji(let r, let n) = $0 { return r == role && n == number }
            if case .furigana(let r, let n) = $0 { return r == role && n == number }
            return false
        }) else { focused = nil; return }
        // curIdx 以降で、現在の人と違う最初の .kanji を探す
        for i in (curIdx + 1)..<order.count {
            if case .kanji(let r, let n) = order[i], !(r == role && n == number) {
                focused = order[i]
                return
            }
        }
        focused = nil   // 最後の人なら閉じる
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

    // MARK: - 一括操作

    private func generateAllFurigana() {
        for m in state.roster.teachers + state.roster.students {
            guard !m.name.isEmpty, m.furigana.isEmpty else { continue }
            let g = FuriganaGenerator.generate(m.name)
            if !g.isEmpty { m.furigana = g }
        }
    }

    private func clearAllNames() {
        for m in state.roster.students + state.roster.teachers {
            m.name = ""; m.furigana = ""
        }
    }
}

// MARK: - 範囲外を nil で受ける小さなヘルパ

private extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}
