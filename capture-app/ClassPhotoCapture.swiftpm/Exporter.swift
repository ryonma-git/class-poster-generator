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
struct CaptureManifest: Codable {
    let format: String       // 識別子: "ClassPhotoCapture"
    let version: Int         // スキーマバージョン
    let grade: Int
    let cls: Int
    let studentCount: Int
    let teacherCount: Int
    let imageFormat: String  // "jpg" / "heic"
    let exportedAt: String   // ISO8601
    let students: [StudentEntry]
    let teachers: [TeacherEntry]

    struct StudentEntry: Codable {
        let number: Int
        let status: String           // "captured" / "absent" / "pending"
        let file: String?            // 相対パス（capturedのみ）
        let topPct: Double?
        let leftPct: Double?
        let zoom: Double?
    }
    struct TeacherEntry: Codable {
        let number: Int
        let file: String             // 相対パス
    }
}

enum ExportError: Error { case noData, zipFailed }

enum Exporter {
    /// 撮影データを ZIP に書き出し、その URL を返す。
    static func makeZip(grade: Int, cls: Int,
                        shots: [StudentShot],
                        format: ImageFormat) throws -> URL {
        let fm = FileManager.default
        let root = fm.temporaryDirectory
            .appendingPathComponent("撮影_\(grade)年\(cls)組_\(Int(Date().timeIntervalSince1970))",
                                    isDirectory: true)
        // 既存を掃除
        try? fm.removeItem(at: root)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)

        // 画像フォルダ:  {g}年/{g}年{c}組/
        let classDir = root
            .appendingPathComponent("\(grade)年", isDirectory: true)
            .appendingPathComponent("\(grade)年\(cls)組", isDirectory: true)
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
        var csv = "\u{FEFF}grade,cls,num,top_pct,left_pct,zoom\n"

        // manifest 用のエントリ
        var studentEntries: [CaptureManifest.StudentEntry] = []
        var teacherEntries: [CaptureManifest.TeacherEntry] = []

        // 児童は出席番号順、担任は番号順で manifest にも記録
        let students = shots.filter { $0.kind == .student }.sorted(by: { $0.number < $1.number })
        let teachers = shots.filter { $0.kind == .teacher }.sorted(by: { $0.number < $1.number })

        for shot in students {
            switch shot.status {
            case .captured:
                guard let img = shot.image else {
                    studentEntries.append(.init(number: shot.number, status: "pending",
                        file: nil, topPct: nil, leftPct: nil, zoom: nil))
                    continue
                }
                let stem = shot.fileStem(grade: grade, cls: cls)
                let relPath = "\(grade)年/\(grade)年\(cls)組/\(stem).\(format.fileExtension)"
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
                    csv += String(format: "%d,%d,%d,%.4f,%.4f,%.4f\n",
                                  grade, cls, shot.number, p.topPct, p.leftPct, p.zoom)
                }
                studentEntries.append(.init(number: shot.number, status: "captured",
                    file: relPath, topPct: topPct, leftPct: leftPct, zoom: zoom))
            case .absent:
                studentEntries.append(.init(number: shot.number, status: "absent",
                    file: nil, topPct: nil, leftPct: nil, zoom: nil))
            case .pending:
                studentEntries.append(.init(number: shot.number, status: "pending",
                    file: nil, topPct: nil, leftPct: nil, zoom: nil))
            }
        }

        for shot in teachers where shot.status == .captured {
            guard let img = shot.image else { continue }
            let stem = shot.fileStem(grade: grade, cls: cls)
            let relPath = "\(grade)年/\(grade)年\(cls)組/担任/\(stem).\(format.fileExtension)"
            let fileURL = teacherDir.appendingPathComponent("\(stem).\(format.fileExtension)")
            let data: Data? = (format == .heic)
                ? (img.heicData(quality: 0.92) ?? img.jpegData(compressionQuality: 0.92))
                : img.jpegData(compressionQuality: 0.92)
            guard let data else { continue }
            try data.write(to: fileURL)
            teacherEntries.append(.init(number: shot.number, file: relPath))
        }

        try csv.data(using: .utf8)?.write(to: cropDir.appendingPathComponent("crop_overrides.csv"))

        // ── manifest.json を書き出し ──
        let iso = ISO8601DateFormatter()
        let manifest = CaptureManifest(
            format: "ClassPhotoCapture",
            version: 1,
            grade: grade, cls: cls,
            studentCount: students.count,
            teacherCount: teachers.count,
            imageFormat: format.fileExtension,
            exportedAt: iso.string(from: Date()),
            students: studentEntries,
            teachers: teacherEntries
        )
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        let manifestData = try enc.encode(manifest)
        try manifestData.write(to: root.appendingPathComponent("manifest.json"))

        // ZIP 化（NSFileCoordinator の forUploading でディレクトリを .zip 化）
        return try zipDirectory(root)
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
