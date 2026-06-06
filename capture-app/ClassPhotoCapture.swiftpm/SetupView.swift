import SwiftUI

// ════════════════════════════════════════════════════════════════
//  SetupView — 設定画面
//
//  2モード対応:
//   - 学校モード: 学年 + 組（数字 or 文字）+ 人数
//   - 集団モード: 集団名 + 副題 + 人数（職員室・会社・チームなど）
//  どちらも内部的に GroupConfig として保持される。
// ════════════════════════════════════════════════════════════════

struct SetupView: View {
    @EnvironmentObject var state: AppState

    /// 学校モードでの「組」表記スタイル（UI制御用）
    @State private var classKind: ClassKind = .number
    /// 名簿エディタの表示
    @State private var showRoster = false

    /// 人数（範囲内にクランプして反映）。+/- とテンキー入力の両方から使う。
    private var studentCountBinding: Binding<Int> {
        Binding(
            get: { state.studentCount },
            set: { state.studentCount = min(state.countRange.upperBound,
                                            max(state.countRange.lowerBound, $0)) }
        )
    }

    enum ClassKind: String, CaseIterable, Identifiable {
        case number = "数字"
        case letter = "ABC"
        var id: String { rawValue }
    }

    var body: some View {
        NavigationStack {
            Form {
                modeSection
                if state.group.mode == .school {
                    schoolSection
                } else {
                    customSection
                }
                countSection
                teacherSection
                rosterSection
                formatSection
                tipsSection
                startSection
            }
            .navigationTitle("撮影の設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        state.goHome()
                    } label: { Label("ホーム", systemImage: "house") }
                }
            }
            .onAppear {
                // 既存値から classKind を復元
                if case .letter = state.group.classLabel { classKind = .letter }
                else { classKind = .number }
            }
            .sheet(isPresented: $showRoster) {
                RosterEditorView().environmentObject(state)
            }
        }
    }

    // MARK: - 名簿（撮影前に作っておける）

    private var rosterSection: some View {
        Section {
            Button {
                // 名簿の枠を現在の人数に合わせてから開く
                state.roster.ensureStudentCount(state.studentCount)
                state.roster.ensureTeacherCount(state.teacherCount)
                showRoster = true
            } label: {
                HStack {
                    Image(systemName: "person.text.rectangle")
                    VStack(alignment: .leading, spacing: 2) {
                        Text(rosterEntered > 0 ? "名簿を編集" : "名簿を入力（任意）")
                            .fontWeight(.semibold)
                        Text(rosterStatusText)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                        .foregroundStyle(.tertiary)
                        .font(.caption)
                }
            }
            .tint(.primary)
        } header: {
            Text("名簿")
        } footer: {
            Text("先に名簿を入れておくと、撮影中に名前が表示され、撮影後すぐにポスターを作れます。あとから入力／取り込み（Excel・CSV・写真）もできます。")
                .font(.caption)
        }
    }

    private var rosterEntered: Int {
        (state.roster.students + state.roster.teachers)
            .filter { !$0.furigana.isEmpty || !$0.name.isEmpty }.count
    }
    private var rosterStatusText: String {
        let total = state.studentCount + state.teacherCount
        return rosterEntered == 0
            ? "未入力（撮影だけでも進められます）"
            : "\(rosterEntered) / \(total) 名 入力済み"
    }

    // MARK: - モード切替

    private var modeSection: some View {
        Section {
            Picker("モード", selection: Binding(
                get: { state.group.mode },
                set: { state.group.mode = $0 }
            )) {
                Text("学校（N年M組）").tag(GroupingMode.school)
                Text("集団（任意ラベル）").tag(GroupingMode.custom)
            }
            .pickerStyle(.segmented)
        } header: {
            Text("対象")
        } footer: {
            Text(state.group.mode == .school
                 ? "学校用。N年M組・出席番号で管理します。"
                 : "職員室・会社など、任意の集団名でも使えます。")
                .font(.caption)
        }
    }

    // MARK: - 学校モード

    private var schoolSection: some View {
        Section("クラス") {
            Stepper("学年: \(state.group.grade) 年",
                    value: Binding(
                        get: { state.group.grade },
                        set: { state.group.grade = $0 }),
                    in: state.gradeRange)

            // 組の表記スタイル
            Picker("組の表記", selection: $classKind) {
                ForEach(ClassKind.allCases) { k in Text(k.rawValue).tag(k) }
            }
            .pickerStyle(.segmented)
            .onChange(of: classKind) { new in
                switch new {
                case .number:
                    // 文字→数字: 既存数字があれば維持、無ければ 1
                    if case .number = state.group.classLabel { return }
                    state.group.classLabel = .number(1)
                case .letter:
                    // 数字→文字: 既存文字があれば維持、無ければ "A"
                    if case .letter = state.group.classLabel { return }
                    state.group.classLabel = .letter("A")
                }
            }

            // 組の値
            switch classKind {
            case .number:
                Stepper("組: \(state.group.classLabel.display)",
                        value: Binding(
                            get: {
                                if case .number(let n) = state.group.classLabel { return n }
                                return 1
                            },
                            set: { state.group.classLabel = .number($0) }),
                        in: state.clsNumberRange)
            case .letter:
                Picker("組", selection: Binding(
                    get: {
                        if case .letter(let s) = state.group.classLabel { return s }
                        return "A"
                    },
                    set: { state.group.classLabel = .letter($0) }
                )) {
                    ForEach(state.clsLetterChoices, id: \.self) { l in
                        Text("\(l)組").tag(l)
                    }
                }
            }
        }
    }

    // MARK: - 集団モード

    private var customSection: some View {
        Section {
            TextField("集団名（例: 職員室）", text: Binding(
                get: { state.group.groupName },
                set: { state.group.groupName = $0 }
            ))
            TextField("副題（例: 2026年度 / 任意）", text: Binding(
                get: { state.group.groupSubtitle },
                set: { state.group.groupSubtitle = $0 }
            ))
        } header: { Text("集団情報") } footer: {
            Text("集団名はヘッダーに、副題はその右に表示されます。空欄でも生成可能です。")
                .font(.caption)
        }
    }

    // MARK: - 人数

    private var countSection: some View {
        Section {
            // テンキーで直接入力（タップで数字パッド）
            NumberKeypadButton(title: "人数", unit: "人",
                               range: state.countRange, value: studentCountBinding)
            // +/- でも調整可能
            Stepper(value: studentCountBinding, in: state.countRange) {
                Text("＋ / − で調整")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Text(state.group.mode == .school
                 ? "出席番号 1 〜 \(state.studentCount) で順番に撮影します（最大 \(state.countRange.upperBound) 人）。"
                 : "管理番号 1 〜 \(state.studentCount) で順番に撮影します（個人名は名簿で設定）。")
                .font(.caption)
                .foregroundStyle(.secondary)
        } header: { Text("人数（\(state.countRange.lowerBound)〜\(state.countRange.upperBound)人）") }
    }

    // MARK: - 担任

    private var teacherSection: some View {
        Section {
            Stepper("\(teacherLabel(state.group.mode)): \(state.teacherCount) 人",
                    value: $state.teacherCount,
                    in: state.teacherRange)
            Text(state.teacherCount == 0
                 ? "なし"
                 : "メンバーの後に \(state.teacherCount) 人分を続けて撮影します")
                .font(.caption)
                .foregroundStyle(.secondary)
        } header: { Text(teacherLabel(state.group.mode)) }
    }

    private func teacherLabel(_ mode: GroupingMode) -> String {
        mode == .school ? "担任" : "リーダー"
    }

    // MARK: - 画像形式

    private var formatSection: some View {
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
    }

    // MARK: - ヒント

    private var tipsSection: some View {
        Section("撮影の進め方") {
            Label("顔を金色の枠に合わせて撮影します", systemImage: "viewfinder")
            Label("撮影 → 確認 → 自動で次の番号へ", systemImage: "arrow.right.circle")
            Label("欠席は「欠席」ボタンでスキップ", systemImage: "person.slash")
        }
    }

    // MARK: - 撮影開始

    /// 撮影が既に始まっている（撮影済みが1人以上）か
    private var captureInProgress: Bool {
        state.shots.contains { $0.status != .pending }
    }

    private var startSection: some View {
        Section {
            if captureInProgress {
                // 人数・担任など設定変更を反映する（撮影済みは番号ごとに引き継ぐ）
                Button {
                    state.startCapture()
                } label: {
                    HStack {
                        Spacer()
                        Label("この設定で更新する（\(state.studentCount)＋\(state.teacherCount)）",
                              systemImage: "arrow.triangle.2.circlepath")
                            .font(.headline)
                        Spacer()
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(brandColor)
                .disabled(!isReady)
                Text("人数や担任を変えたら必ずこちら。新しい人数で撮影リストを作り直します（撮影済みの写真は番号ごとに引き継がれます）。")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                // 設定を変えずに撮影へ戻る
                Button {
                    state.resumeCapture()
                } label: {
                    HStack {
                        Spacer()
                        Text("設定を変更せずに戻る（済 \(state.capturedCount) 名）")
                            .font(.subheadline)
                        Spacer()
                    }
                }
                .disabled(!isReady)
            } else {
                Button {
                    state.startCapture()
                } label: {
                    HStack {
                        Spacer()
                        Label("撮影をはじめる（\(state.studentCount)＋\(state.teacherCount)）",
                              systemImage: "camera.fill")
                            .font(.headline)
                        Spacer()
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!isReady)
            }
            if !isReady {
                Text(notReadyReason)
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
    }

    /// 撮影を始められる状態か
    private var isReady: Bool {
        if state.group.mode == .custom {
            return !state.group.groupName.trimmingCharacters(in: .whitespaces).isEmpty
        }
        return true
    }
    private var notReadyReason: String {
        if state.group.mode == .custom,
           state.group.groupName.trimmingCharacters(in: .whitespaces).isEmpty {
            return "集団名を入力してください。"
        }
        return ""
    }
}
