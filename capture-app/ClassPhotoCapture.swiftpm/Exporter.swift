import SwiftUI
import UniformTypeIdentifiers
import ImageIO

// ════════════════════════════════════════════════════════════════
//  Exporter — crop_adjuster がそのまま読める形で書き出す
//
//  <temp>/撮影_{g}年{c}組/
//     manifest.json                          （メタ情報：クラス・担任・撮影状況）
//     {g}年/{g}年{c}組/  {stem}.jpg|heic    （児童の元の全体写真）
//     {g}年/{g}年{c}組/担任/ {stem}.jpg     （担任の元の全体写真）
//     crop_check/crop_overrides.csv          （児童の枠→クロップ情報）
//  → 上記フォルダを ZIP 化して共有（AirDrop / Files / Google Drive）。
//
//  受け取った crop_adjuster.py が「📥 撮影データを取り込み」で展開して
//  写真フォルダにマージし、overrides を取り込む。manifest.json があれば
//  「撮影アプリのデータ」として扱われる。
// ════════════════════════════════════════════════════════════════

/// manifest.json のスキーマ
///
/// v1: 学校×数字組のみ（grade, cls: Int）
/// v2: 任意ラベル方式に対応（group: GroupMeta）。v1 フィールドは互換のため残置。
struct CaptureManifest: Codable {
    let format: String       // 識別子: "ClassPhotoCapture"
    let version: Int         // スキーマバージョン（=2）
    let grade: Int           // 学校モード時の学年。互換用に常に出力。
    let cls: Int             // 数字組のとき組番号。それ以外は 0。
    let group: GroupMeta?    // v2: 集団設定の完全形
    let studentCount: Int
    let teacherCount: Int
    let imageFormat: String  // "jpg" / "heic"
    let exportedAt: String   // ISO8601
    let students: [StudentEntry]
    let teachers: [TeacherEntry]
    let nameStyle: String?   // v2: "furigana" or "kanji"

    /// 集団設定（学校 or 集団モード）。
    struct GroupMeta: Codable {
        let mode: String             // "school" or "custom"
        let grade: Int?              // school モードのみ
        let classLabelKind: String?  // school: "number" or "letter"
        let classLabelValue: String? // school: "1" or "A" など（表示は組をつけずに）
        let groupName: String?       // custom モードの集団名
        let groupSubtitle: String?
    }

    struct StudentEntry: Codable {
        let number: Int
        let status: String           // "captured" / "absent" / "pending"
        let file: String?            // 相対パス（capturedのみ）
        let topPct: Double?
        let leftPct: Double?
        let zoom: Double?
        // v2: 名簿情報（あれば。空文字は省略）
        let name: String?
        let furigana: String?
        let customLabel: String?
    }
    struct TeacherEntry: Codable {
        let number: Int
        let file: String             // 相対パス
        let name: String?            // v2
        let furigana: String?        // v2
        let customLabel: String?     // v2
    }
}

enum ExportError: Error { case noData, zipFailed }

enum Exporter {
    /// 旧 API（学校×数字組専用）。GroupConfig を組み立てて新APIへ委譲。
    static func makeZip(grade: Int, cls: Int,
                        shots: [StudentShot],
                        format: ImageFormat) throws -> URL {
        var g = GroupConfig()
        g.mode = .school
        g.grade = grade
        g.classLabel = .number(cls)
        return try makeZip(group: g, roster: Roster(), shots: shots, format: format)
    }

    /// 撮影データを ZIP（.cpcap）に書き出し、その URL を返す。
    /// 学校モードでは crop_adjuster.py が直接読めるフォルダ構造で出力。
    /// 集団モードでは `{groupID}/` 配下に出力（crop_adjuster は manifest を読む）。
    static func makeZip(group: GroupConfig,
                        roster: Roster,
                        shots: [StudentShot],
                        format: ImageFormat) throws -> URL {
        let fm = FileManager.default

        // ── ルートディレクトリ名 ──
        let stamp = Int(Date().timeIntervalSince1970)
        let rootName: String
        switch group.mode {
        case .school:
            rootName = "撮影_\(group.grade)年\(group.classLabel.display)_\(stamp)"
        case .custom:
            rootName = "撮影_\(group.fileSafeID)_\(stamp)"
        }
        let root = fm.temporaryDirectory.appendingPathComponent(rootName, isDirectory: true)
        try? fm.removeItem(at: root)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)

        // ── 画像フォルダ ──
        // 学校モード: "{grade}年/{grade}年{classLabel}/"（crop_adjuster 直読み互換）
        // 集団モード: "{groupID}/"
        let classDir: URL
        switch group.mode {
        case .school:
            classDir = root
                .appendingPathComponent("\(group.grade)年", isDirectory: true)
                .appendingPathComponent("\(group.grade)年\(group.classLabel.display)", isDirectory: true)
        case .custom:
            classDir = root.appendingPathComponent(group.fileSafeID, isDirectory: true)
        }
        try fm.createDirectory(at: classDir, withIntermediateDirectories: true)

        // 担任フォルダ（担任ショットがある場合のみ作成）
        let teacherDir = classDir.appendingPathComponent("担任", isDirectory: true)
        let hasTeacher = shots.contains { $0.kind == .teacher && $0.status == .captured }
        if hasTeacher {
            try fm.createDirectory(at: teacherDir, withIntermediateDirectories: true)
        }

        // crop_check/
        let cropDir = root.appendingPathComponent("crop_check", isDirectory: true)
        try fm.createDirectory(at: cropDir, withIntermediateDirectories: true)

        // CSV ヘッダ（BOM付きUTF-8、crop_adjuster と一致）
        // ※集団モードは crop_adjuster で扱わないので CSV は空ヘッダのみ。
        var csv = "\u{FEFF}grade,cls,num,top_pct,left_pct,zoom\n"

        // 互換用：旧 API 互換の grade/cls Int を取り出す
        let legacyGrade = group.mode == .school ? group.grade : 0
        let legacyCls = group.legacyClsInt

        // manifest 用のエントリ
        var studentEntries: [CaptureManifest.StudentEntry] = []
        var teacherEntries: [CaptureManifest.TeacherEntry] = []

        // 児童は出席番号順、担任は番号順で manifest にも記録
        let students = shots.filter { $0.kind == .student }.sorted(by: { $0.number < $1.number })
        let teachers = shots.filter { $0.kind == .teacher }.sorted(by: { $0.number < $1.number })

        // 名簿から名前情報を引く（roster が空でもクラッシュしない）
        func nameInfo(role: MemberRole, number: Int) -> (name: String?, furigana: String?, customLabel: String?) {
            let m: Member? = (role == .student)
                ? roster.studentByNumber(number)
                : roster.teacherByNumber(number)
            guard let m else { return (nil, nil, nil) }
            let n = m.name.isEmpty ? nil : m.name
            let f = m.furigana.isEmpty ? nil : m.furigana
            return (n, f, m.customLabel)
        }

        // 相対パス組み立て（学校モードは直読み互換、集団モードはフラット）
        func relPath(stem: String, ext: String, sub: String? = nil) -> String {
            switch group.mode {
            case .school:
                let base = "\(group.grade)年/\(group.grade)年\(group.classLabel.display)"
                if let sub { return "\(base)/\(sub)/\(stem).\(ext)" }
                return "\(base)/\(stem).\(ext)"
            case .custom:
                let base = group.fileSafeID
                if let sub { return "\(base)/\(sub)/\(stem).\(ext)" }
                return "\(base)/\(stem).\(ext)"
            }
        }

        for shot in students {
            let info = nameInfo(role: .student, number: shot.number)
            switch shot.status {
            case .captured:
                guard let img = shot.image else {
                    studentEntries.append(.init(number: shot.number, status: "pending",
                        file: nil, topPct: nil, leftPct: nil, zoom: nil,
                        name: info.name, furigana: info.furigana, customLabel: info.customLabel))
                    continue
                }
                let stem = shot.fileStem(group: group)
                let rel = relPath(stem: stem, ext: format.fileExtension)
                let fileURL = classDir.appendingPathComponent("\(stem).\(format.fileExtension)")
                let data: Data? = (format == .heic)
                    ? (img.heicData(quality: 0.92) ?? img.jpegData(compressionQuality: 0.92))
                    : img.jpegData(compressionQuality: 0.92)
                guard let data else { continue }
                try data.write(to: fileURL)

                var topPct: Double? = nil
                var leftPct: Double? = nil
                var zoom: Double? = nil
                if let crop = shot.cropRect {
                    let w = Double(img.size.width * img.scale)
                    let h = Double(img.size.height * img.scale)
                    let p = CropMath.params(forNormalizedRect: crop,
                                            imageW: w, imageH: h, aspect: Double(CELL_ASPECT))
                    topPct = p.topPct; leftPct = p.leftPct; zoom = p.zoom
                    // CSV は学校×数字組のときだけ crop_adjuster が利用するので、その形でのみ出力。
                    if group.mode == .school, case .number = group.classLabel {
                        csv += String(format: "%d,%d,%d,%.4f,%.4f,%.4f\n",
                                      legacyGrade, legacyCls, shot.number, p.topPct, p.leftPct, p.zoom)
                    }
                }
                studentEntries.append(.init(number: shot.number, status: "captured",
                    file: rel, topPct: topPct, leftPct: leftPct, zoom: zoom,
                    name: info.name, furigana: info.furigana, customLabel: info.customLabel))
            case .absent:
                studentEntries.append(.init(number: shot.number, status: "absent",
                    file: nil, topPct: nil, leftPct: nil, zoom: nil,
                    name: info.name, furigana: info.furigana, customLabel: info.customLabel))
            case .pending:
                studentEntries.append(.init(number: shot.number, status: "pending",
                    file: nil, topPct: nil, leftPct: nil, zoom: nil,
                    name: info.name, furigana: info.furigana, customLabel: info.customLabel))
            }
        }

        for shot in teachers where shot.status == .captured {
            guard let img = shot.image else { continue }
            let info = nameInfo(role: .teacher, number: shot.number)
            let stem = shot.fileStem(group: group)
            let rel = relPath(stem: stem, ext: format.fileExtension, sub: "担任")
            let fileURL = teacherDir.appendingPathComponent("\(stem).\(format.fileExtension)")
            let data: Data? = (format == .heic)
                ? (img.heicData(quality: 0.92) ?? img.jpegData(compressionQuality: 0.92))
                : img.jpegData(compressionQuality: 0.92)
            guard let data else { continue }
            try data.write(to: fileURL)
            teacherEntries.append(.init(number: shot.number, file: rel,
                name: info.name, furigana: info.furigana, customLabel: info.customLabel))
        }

        try csv.data(using: .utf8)?.write(to: cropDir.appendingPathComponent("crop_overrides.csv"))

        // ── manifest.json を書き出し ──
        let iso = ISO8601DateFormatter()
        let meta: CaptureManifest.GroupMeta
        switch group.mode {
        case .school:
            let kind: String
            let value: String
            switch group.classLabel {
            case .number(let n): kind = "number"; value = "\(n)"
            case .letter(let s): kind = "letter"; value = s
            }
            meta = .init(mode: "school", grade: group.grade,
                         classLabelKind: kind, classLabelValue: value,
                         groupName: nil, groupSubtitle: nil)
        case .custom:
            meta = .init(mode: "custom", grade: nil,
                         classLabelKind: nil, classLabelValue: nil,
                         groupName: group.groupName,
                         groupSubtitle: group.groupSubtitle.isEmpty ? nil : group.groupSubtitle)
        }

        let manifest = CaptureManifest(
            format: "ClassPhotoCapture",
            version: 2,
            grade: legacyGrade, cls: legacyCls,
            group: meta,
            studentCount: students.count,
            teacherCount: teachers.count,
            imageFormat: format.fileExtension,
            exportedAt: iso.string(from: Date()),
            students: studentEntries,
            teachers: teacherEntries,
            nameStyle: roster.nameStyle.rawValue
        )
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        let manifestData = try enc.encode(manifest)
        try manifestData.write(to: root.appendingPathComponent("manifest.json"))

        // ZIP 化（NSFileCoordinator の forUploading でディレクトリを .zip 化）→
        // ユーザー向けには独自拡張子 .cpcap に改名（中身はそのまま ZIP）。
        let zipURL = try zipDirectory(root)
        let cpcapURL = zipURL.deletingPathExtension().appendingPathExtension("cpcap")
        try? fm.removeItem(at: cpcapURL)
        try fm.moveItem(at: zipURL, to: cpcapURL)
        return cpcapURL
    }

    /// ディレクトリを ZIP 化して URL を返す
    private static func zipDirectory(_ dir: URL) throws -> URL {
        var zipURL: URL?
        var coordError: NSError?
        let coordinator = NSFileCoordinator()
        coordinator.coordinate(readingItemAt: dir,
                               options: [.forUploading],
                               error: &coordError) { tmpZip in
            // tmpZip は一時的な .zip。永続領域へコピーする。
            let dest = FileManager.default.temporaryDirectory
                .appendingPathComponent(dir.lastPathComponent + ".zip")
            try? FileManager.default.removeItem(at: dest)
            do {
                try FileManager.default.copyItem(at: tmpZip, to: dest)
                zipURL = dest
            } catch {
                zipURL = nil
            }
        }
        if let zipURL { return zipURL }
        throw ExportError.zipFailed
    }
}

// ── HEIC エンコード ──
extension UIImage {
    func heicData(quality: CGFloat) -> Data? {
        guard let cg = self.cgImage else { return nil }
        let data = NSMutableData()
        let type = UTType.heic.identifier as CFString
        guard let dest = CGImageDestinationCreateWithData(data, type, 1, nil) else { return nil }
        let options: [CFString: Any] = [kCGImageDestinationLossyCompressionQuality: quality]
        CGImageDestinationAddImage(dest, cg, options as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { return nil }
        return data as Data
    }
}

// ── 共有シート ──
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
