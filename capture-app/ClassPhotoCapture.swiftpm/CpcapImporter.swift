import Foundation
import UIKit
import CoreGraphics

// ════════════════════════════════════════════════════════════════
//  CpcapImporter — 書き出した .cpcap（中身は ZIP）を読み込んで
//  プロジェクトとして復元する
//
//  「ファイル」アプリ等から選んだ .cpcap / .zip を展開し、
//  manifest.json から クラス情報・名簿・撮影状況・写真 を復元して
//  ProjectStore に新規プロジェクトとして保存する。
//
//  ZIP 展開は XLSX 用の MinimalZip を再利用。
// ════════════════════════════════════════════════════════════════

enum CpcapImportError: Error, LocalizedError {
    case readFailed
    case noManifest
    case badManifest
    case noStudents

    var errorDescription: String? {
        switch self {
        case .readFailed:  return "ファイルを読み込めませんでした。"
        case .noManifest:  return "このファイルは撮影データ（.cpcap）ではないようです（manifest.json が見つかりません）。"
        case .badManifest: return "撮影データの形式を解釈できませんでした。"
        case .noStudents:  return "撮影データに児童・生徒の情報がありません。"
        }
    }
}

enum CpcapImporter {

    /// .cpcap / .zip を取り込み、新規プロジェクトとして保存。新 ID を返す。
    static func importFile(at url: URL) throws -> String {
        let didStart = url.startAccessingSecurityScopedResource()
        defer { if didStart { url.stopAccessingSecurityScopedResource() } }

        guard let data = try? Data(contentsOf: url) else { throw CpcapImportError.readFailed }

        let entries: [String: Data]
        do {
            entries = try MinimalZip.entries(from: data)
        } catch {
            throw CpcapImportError.readFailed
        }
        guard !entries.isEmpty else { throw CpcapImportError.readFailed }
        // NSFileCoordinator(forUploading) はディレクトリごと ZIP 化するため、
        // 中のパスは「<ルート名>/manifest.json」のようにフォルダ名が前置される。
        // 完全一致ではなく末尾一致で manifest.json を探す。
        guard let manifestData = entries["manifest.json"]
                ?? entries.first(where: { $0.key.hasSuffix("manifest.json") })?.value
        else { throw CpcapImportError.noManifest }
        guard let manifest = try? JSONDecoder().decode(CaptureManifest.self, from: manifestData) else {
            throw CpcapImportError.badManifest
        }
        guard !manifest.students.isEmpty else { throw CpcapImportError.noStudents }

        // ── GroupConfig 復元 ──
        let group = buildGroup(manifest)

        // ── Roster 復元 ──
        let roster = Roster()
        roster.nameStyle = (manifest.nameStyle == "kanji") ? .kanji : .furigana
        for s in manifest.students.sorted(by: { $0.number < $1.number }) {
            roster.students.append(Member(role: .student, number: s.number,
                                          name: s.name ?? "", furigana: s.furigana ?? "",
                                          customLabel: s.customLabel))
        }
        for t in manifest.teachers.sorted(by: { $0.number < $1.number }) {
            roster.teachers.append(Member(role: .teacher, number: t.number,
                                          name: t.name ?? "", furigana: t.furigana ?? "",
                                          customLabel: t.customLabel))
        }

        // ── shots 復元（写真＋クロップ復元） ──
        var shots: [StudentShot] = []
        for s in manifest.students.sorted(by: { $0.number < $1.number }) {
            let shot = StudentShot(kind: .student, number: s.number)
            switch s.status {
            case "captured": shot.status = .captured
            case "absent":   shot.status = .absent
            default:         shot.status = .pending
            }
            if let f = s.file, let imgData = imageData(entries, path: f), let img = UIImage(data: imgData) {
                shot.image = img
                shot.status = .captured
                // 保存されている (top_pct, left_pct, zoom) からクロップ枠を復元
                if let top = s.topPct, let left = s.leftPct, let zoom = s.zoom {
                    shot.cropRect = reconstructCrop(image: img, topPct: top, leftPct: left, zoom: zoom)
                }
            }
            shots.append(shot)
        }
        for t in manifest.teachers.sorted(by: { $0.number < $1.number }) {
            let shot = StudentShot(kind: .teacher, number: t.number)
            if let imgData = imageData(entries, path: t.file), let img = UIImage(data: imgData) {
                shot.image = img
                shot.status = .captured
            }
            shots.append(shot)
        }

        // ── 画像形式 ──
        let fmt: ImageFormat = (manifest.imageFormat.lowercased() == "heic") ? .heic : .jpeg

        // ── プロジェクトとして保存 ──
        let id = ProjectStore.newID()
        ProjectStore.save(
            id: id,
            group: group,
            roster: roster,
            studentCount: manifest.studentCount,
            teacherCount: manifest.teacherCount,
            imageFormat: fmt,
            shots: shots,
            createdAt: Date().timeIntervalSince1970
        )
        return id
    }

    // MARK: - ヘルパ

    /// ZIP エントリから画像データを取り出す。パスの表記揺れ（先頭 ./ など）も吸収。
    private static func imageData(_ entries: [String: Data], path: String) -> Data? {
        if let d = entries[path] { return d }
        // 末尾一致でフォールバック（フォルダ階層の差異対策）
        if let hit = entries.first(where: { $0.key.hasSuffix(path) || path.hasSuffix($0.key) }) {
            return hit.value
        }
        // ファイル名のみで一致
        let base = (path as NSString).lastPathComponent
        if let hit = entries.first(where: { ($0.key as NSString).lastPathComponent == base }) {
            return hit.value
        }
        return nil
    }

    private static func buildGroup(_ m: CaptureManifest) -> GroupConfig {
        var g = GroupConfig()
        if let meta = m.group {
            if meta.mode == "custom" {
                g.mode = .custom
                g.groupName = meta.groupName ?? ""
                g.groupSubtitle = meta.groupSubtitle ?? ""
            } else {
                g.mode = .school
                g.grade = meta.grade ?? m.grade
                if meta.classLabelKind == "letter" {
                    g.classLabel = .letter(meta.classLabelValue ?? "A")
                } else {
                    g.classLabel = .number(Int(meta.classLabelValue ?? "\(m.cls)") ?? m.cls)
                }
            }
        } else {
            // v1 互換
            g.mode = .school
            g.grade = m.grade
            g.classLabel = .number(m.cls)
        }
        return g
    }

    /// (top_pct, left_pct, zoom) → 正規化クロップ矩形（make_poster.py smart_crop と同経路）
    private static func reconstructCrop(image: UIImage, topPct: Double, leftPct: Double, zoom: Double) -> CGRect {
        let w = Double(image.size.width * image.scale)
        let h = Double(image.size.height * image.scale)
        let params = CropParams(topPct: topPct, leftPct: leftPct, zoom: zoom)
        let px = CropMath.sourceCropRect(imageW: w, imageH: h, params: params, aspect: Double(CELL_ASPECT))
        guard w > 0, h > 0 else { return CGRect(x: 0, y: 0, width: 1, height: 1) }
        return CGRect(x: px.minX / w, y: px.minY / h, width: px.width / w, height: px.height / h)
    }
}
