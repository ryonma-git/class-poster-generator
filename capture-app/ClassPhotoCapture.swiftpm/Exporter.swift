import SwiftUI
import UniformTypeIdentifiers
import ImageIO

// ════════════════════════════════════════════════════════════════
//  Exporter — crop_adjuster がそのまま読める形で書き出す
//
//  <temp>/撮影_{g}年{c}組/
//     {g}年/{g}年{c}組/  {stem}.jpg|heic   （元の全体写真）
//     crop_check/crop_overrides.csv         （枠→クロップ情報）
//  → 上記フォルダを ZIP 化して共有（AirDrop / Files / Google Drive）。
// ════════════════════════════════════════════════════════════════

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

        for shot in shots where shot.status == .captured {
            guard let img = shot.image else { continue }
            let stem = shot.fileStem(grade: grade, cls: cls)
            // 児童は classDir 直下、担任は 担任/ サブフォルダへ（crop_adjuster の収集対象外）
            let saveDir = (shot.kind == .teacher) ? teacherDir : classDir
            let fileURL = saveDir.appendingPathComponent("\(stem).\(format.fileExtension)")

            // 画像書き出し（元の全体写真。クロップはしない）
            let data: Data?
            if format == .heic {
                data = img.heicData(quality: 0.92) ?? img.jpegData(compressionQuality: 0.92)
            } else {
                data = img.jpegData(compressionQuality: 0.92)
            }
            guard let data else { continue }
            try data.write(to: fileURL)

            // crop_overrides は児童のみ（crop_adjuster が読むのは児童データのみのため）
            if shot.kind == .student, let crop = shot.cropRect {
                let w = Double(img.size.width * img.scale)
                let h = Double(img.size.height * img.scale)
                let p = CropMath.params(forNormalizedRect: crop,
                                        imageW: w, imageH: h, aspect: Double(CELL_ASPECT))
                csv += String(format: "%d,%d,%d,%.4f,%.4f,%.4f\n",
                              grade, cls, shot.number, p.topPct, p.leftPct, p.zoom)
            }
        }

        try csv.data(using: .utf8)?.write(to: cropDir.appendingPathComponent("crop_overrides.csv"))

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
