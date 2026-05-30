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
    // セルをタップしたときに表示するプレビュー（写真＋枠＋撮り直しボタン）
    @State private var previewing: StudentShot? = nil
    // 「写真を書き出し」のモード選択ダイアログ
    @State private var showPhotoModeDialog = false
    @State private var isSavingPhotos = false
    @State private var photoProgress: (Int, Int) = (0, 0)
    @State private var photoResult: String? = nil
    // 名簿エディタ（Phase 2）
    @State private var showRoster = false
    @State private var showPoster = false

    private let cols = [GridItem(.adaptive(minimum: 96), spacing: 10)]

    var body: some View {
        NavigationStack {
            ScrollView {
                summary
                LazyVGrid(columns: cols, spacing: 12) {
                    ForEach(state.shots) { shot in
                        cell(shot)
                            .onTapGesture { previewing = shot }
                    }
                }
                .padding()
                exportBanner
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
            .sheet(item: $previewing) { shot in
                ShotPreviewSheet(shot: shot,
                                 onClose: { previewing = nil },
                                 onRetake: {
                                     previewing = nil
                                     jumpTo(shot)
                                 })
                .environmentObject(state)
            }
            .sheet(isPresented: $showShare) {
                if let url = shareURL { ShareSheet(items: [url]) }
            }
            .sheet(isPresented: $showRoster) {
                RosterEditorView().environmentObject(state)
            }
            .sheet(isPresented: $showPoster) {
                PosterDesignView().environmentObject(state)
            }
            .alert("書き出しエラー", isPresented: .constant(exportError != nil)) {
                Button("OK") { exportError = nil }
            } message: {
                Text(exportError ?? "")
            }
        }
    }

    /// 画面下部の書き出し案内＋ボタン群
    private var exportBanner: some View {
        VStack(spacing: 12) {
            Divider().padding(.bottom, 2)

            // iPad 内でポスター PDF を直接生成
            Button {
                showPoster = true
            } label: {
                HStack {
                    Image(systemName: "doc.text.image")
                    Text("ポスターを作成（PDF）")
                        .fontWeight(.semibold)
                }
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .tint(.indigo)
            .disabled(state.capturedCount == 0)

            // crop_adjuster 用パッケージ書き出し（独自拡張子 .cpcap）
            Button {
                export()
            } label: {
                HStack {
                    if isExporting { ProgressView() }
                    else { Image(systemName: "shippingbox.and.arrow.backward") }
                    Text(isExporting ? "書き出し中…" : "crop_adjuster に書き出す（.cpcap）")
                        .fontWeight(.semibold)
                }
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .disabled(isExporting || isSavingPhotos || state.capturedCount == 0)

            // 写真ライブラリへの書き出し
            Button {
                showPhotoModeDialog = true
            } label: {
                HStack {
                    if isSavingPhotos { ProgressView() }
                    else { Image(systemName: "photo.on.rectangle.angled") }
                    if isSavingPhotos {
                        Text("保存中… \(photoProgress.0)/\(photoProgress.1)")
                            .fontWeight(.semibold)
                    } else {
                        Text("写真を書き出し（「写真」アプリへ）")
                            .fontWeight(.semibold)
                    }
                }
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .disabled(isExporting || isSavingPhotos || state.capturedCount == 0)

            if state.capturedCount == 0 {
                Text("※ 撮影済みが1人もありません")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
        }
        .padding(.horizontal, 20)
        .padding(.bottom, 24)
        .padding(.top, 10)
        .confirmationDialog("写真を「写真」アプリに書き出します",
                            isPresented: $showPhotoModeDialog,
                            titleVisibility: .visible) {
            Button("クロップ済みの写真を書き出し") { savePhotos(mode: .cropped) }
            Button("クロップ前のオリジナルを書き出し") { savePhotos(mode: .original) }
            Button("キャンセル", role: .cancel) {}
        } message: {
            Text("撮影済み \(state.capturedCount) 件を書き出します")
        }
        .alert("写真の書き出し", isPresented: .constant(photoResult != nil)) {
            Button("OK") { photoResult = nil }
        } message: {
            Text(photoResult ?? "")
        }
    }

    private var summary: some View {
        VStack(spacing: 4) {
            Text(state.group.displayName)
                .font(.title2.bold())
            Text("撮影済 \(state.capturedCount) ／ 欠席 \(state.absentCount) ／ 未撮影 \(state.shots.count - state.doneCount)")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text("形式: \(state.imageFormat.rawValue)　タップでプレビュー（そこから撮り直しできます）")
                .font(.caption)
                .foregroundStyle(.secondary)

            // ── 名簿の入力状況 ──
            rosterStatusBar
                .padding(.top, 6)
        }
        .padding(.top, 8)
        .padding(.horizontal)
    }

    /// 名簿入力済み件数と編集ボタン
    private var rosterStatusBar: some View {
        let total = state.roster.students.count + state.roster.teachers.count
        let entered = state.roster.students.filter { !$0.furigana.isEmpty || !$0.name.isEmpty }.count
            + state.roster.teachers.filter { !$0.furigana.isEmpty || !$0.name.isEmpty }.count

        return HStack(spacing: 12) {
            Image(systemName: entered == 0
                  ? "person.text.rectangle"
                  : (entered == total ? "checkmark.seal.fill" : "person.text.rectangle.fill"))
                .foregroundStyle(entered == total && total > 0 ? .green : .accentColor)
            VStack(alignment: .leading, spacing: 1) {
                Text(entered == 0
                     ? "名簿は未入力"
                     : "名簿: \(entered) / \(total) 名 入力済み")
                    .font(.subheadline.weight(.semibold))
                Text(entered == 0
                     ? "ポスター生成を使うには名前を入力してください"
                     : "タップで編集")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("編集") { showRoster = true }
                .buttonStyle(.bordered)
                .controlSize(.small)
        }
        .padding(10)
        .background(Color(.secondarySystemBackground),
                    in: RoundedRectangle(cornerRadius: 10))
        .contentShape(Rectangle())
        .onTapGesture { showRoster = true }
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
                Text(shot.kind == .teacher ? "担\(shot.number)" : "\(shot.number)")
                    .font(.caption2.bold())
                    .padding(3)
                    .background(shot.kind == .teacher
                                ? Color.indigo.opacity(0.85)
                                : Color.black.opacity(0.6),
                                in: RoundedRectangle(cornerRadius: 4))
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

    private func savePhotos(mode: PhotoExportMode) {
        guard !isSavingPhotos, !isExporting else { return }
        PhotoExporter.requestAddPermission { granted in
            guard granted else {
                photoResult = "「写真」アプリへの追加が許可されていません。設定で許可してください。"
                return
            }
            isSavingPhotos = true
            photoProgress = (0, 0)
            PhotoExporter.saveAll(shots: state.shots, mode: mode,
                                  progress: { done, total in
                photoProgress = (done, total)
            }, completion: { ok, ng in
                isSavingPhotos = false
                let modeLabel = (mode == .cropped) ? "クロップ済み" : "オリジナル"
                if ng == 0 {
                    photoResult = "「写真」アプリへ\(modeLabel) \(ok) 件 を書き出しました。"
                } else {
                    photoResult = "「写真」アプリへ \(modeLabel) \(ok) 件 を書き出しました。\(ng) 件は失敗しました。"
                }
            })
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

// ════════════════════════════════════════════════════════════════
//  ShotPreviewSheet — 撮影済み写真の拡大プレビュー＋撮り直しボタン
//  ReviewViewでセルをタップした際に表示される。
//  写真にクロップ枠も重ねて表示し、ボタンで撮り直し or 閉じる。
// ════════════════════════════════════════════════════════════════

struct ShotPreviewSheet: View {
    let shot: StudentShot
    let onClose: () -> Void
    let onRetake: () -> Void
    @EnvironmentObject var state: AppState

    private let gold = Color(red: 245/255, green: 175/255, blue: 60/255)

    var body: some View {
        NavigationStack {
            VStack(spacing: 14) {
                // 見出し
                Text(shot.displayLabel(grade: state.grade, cls: state.cls))
                    .font(.title2.bold())
                Text(statusText)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                // 写真＋クロップ枠 or プレースホルダ
                Group {
                    if let img = shot.image {
                        photoWithCrop(image: img, crop: shot.cropRect)
                    } else {
                        placeholder
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: 460)

                Spacer(minLength: 4)

                // ボタン
                VStack(spacing: 10) {
                    Button { onRetake() } label: {
                        Label(retakeLabel, systemImage: "camera.fill")
                            .font(.headline)
                            .frame(maxWidth: .infinity, minHeight: 14)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)

                    Button { onClose() } label: {
                        Text("閉じる").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 18)
            }
            .padding(.top, 12)
            .navigationTitle("プレビュー")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("閉じる") { onClose() }
                }
            }
        }
    }

    private var statusText: String {
        switch shot.status {
        case .captured: return "撮影済み"
        case .absent:   return "欠席"
        case .pending:  return "未撮影"
        }
    }

    private var retakeLabel: String {
        shot.status == .pending ? "この番号を撮影する" : "撮り直す"
    }

    @ViewBuilder
    private var placeholder: some View {
        VStack(spacing: 10) {
            Image(systemName: shot.status == .absent ? "person.slash" : "camera")
                .font(.system(size: 56))
            Text(statusText).font(.headline)
            Text(shot.status == .absent
                 ? "撮影に切り替えたい場合は下のボタンから"
                 : "下のボタンから撮影できます")
                .font(.caption).foregroundStyle(.secondary)
        }
        .foregroundStyle(.secondary)
        .padding(40)
        .frame(maxWidth: .infinity)
        .background(Color(.secondarySystemBackground),
                    in: RoundedRectangle(cornerRadius: 16))
        .padding(.horizontal, 24)
    }

    /// 写真をscaledToFitで表示し、cropRect（画像座標の正規化矩形）を金枠で重ねる
    @ViewBuilder
    private func photoWithCrop(image: UIImage, crop: CGRect?) -> some View {
        GeometryReader { g in
            ZStack(alignment: .topLeading) {
                Color.black
                Image(uiImage: image)
                    .resizable().scaledToFit()
                    .frame(width: g.size.width, height: g.size.height)
                if let c = crop {
                    let layout = fitLayout(image: image.size, in: g.size)
                    RoundedRectangle(cornerRadius: 4)
                        .stroke(gold, lineWidth: 3)
                        .frame(width: c.width * layout.size.width,
                               height: c.height * layout.size.height)
                        .position(x: layout.origin.x + (c.minX + c.width/2) * layout.size.width,
                                  y: layout.origin.y + (c.minY + c.height/2) * layout.size.height)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .padding(.horizontal, 16)
    }

    /// scaledToFit で画像が実際に占めるコンテナ内の矩形を返す
    private func fitLayout(image: CGSize, in container: CGSize) -> CGRect {
        let imgAR = image.width / max(1, image.height)
        let conAR = container.width / max(1, container.height)
        if imgAR > conAR {
            let w = container.width
            let h = w / imgAR
            return CGRect(x: 0, y: (container.height - h)/2, width: w, height: h)
        } else {
            let h = container.height
            let w = h * imgAR
            return CGRect(x: (container.width - w)/2, y: 0, width: w, height: h)
        }
    }
}
