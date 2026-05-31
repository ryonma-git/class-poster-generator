import Foundation
import UIKit

// ════════════════════════════════════════════════════════════════
//  ProjectStore — 複数クラスの撮影プロジェクトをローカル保存
//
//  Documents/Projects/<id>/
//     project.json          （メタ情報＋名簿＋ショット記録）
//     images/<stem>.jpg     （撮影した元写真）
//
//  1プロジェクト = 1クラス（または1集団）の撮影セッション。
//  担当者が複数クラス分を順に撮影・保存・再開できる。
// ════════════════════════════════════════════════════════════════

/// ディスクに保存する1ショット分の記録（UIImage はファイル参照）
struct ShotRecord: Codable {
    var kind: String          // "student" / "teacher"
    var number: Int
    var status: String        // "pending" / "captured" / "absent"
    var cropRect: [Double]?   // [x, y, w, h]（正規化）
    var imageFile: String?    // images/ 以下のファイル名
}

/// project.json のスキーマ
struct ProjectFile: Codable {
    var id: String
    var createdAt: Double
    var updatedAt: Double
    var group: GroupConfig
    var roster: Roster
    var studentCount: Int
    var teacherCount: Int
    var imageFormat: String   // "JPEG" / "HEIC"
    var shots: [ShotRecord]
}

/// 一覧表示用の軽量サマリ
struct ProjectSummary: Identifiable {
    let id: String
    let displayName: String
    let subtitle: String
    let capturedCount: Int
    let totalCount: Int
    let updatedAt: Date
    let thumbnailPath: String?
}

enum ProjectStore {

    // MARK: - パス

    private static var projectsDir: URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let dir = docs.appendingPathComponent("Projects", isDirectory: true)
        if !FileManager.default.fileExists(atPath: dir.path) {
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        }
        return dir
    }

    private static func dir(for id: String) -> URL {
        projectsDir.appendingPathComponent(id, isDirectory: true)
    }
    private static func imagesDir(for id: String) -> URL {
        dir(for: id).appendingPathComponent("images", isDirectory: true)
    }
    private static func jsonURL(for id: String) -> URL {
        dir(for: id).appendingPathComponent("project.json")
    }

    // MARK: - 保存

    /// 現在の状態（group/roster/shots/設定）を1プロジェクトとして保存。
    static func save(id: String,
                     group: GroupConfig,
                     roster: Roster,
                     studentCount: Int,
                     teacherCount: Int,
                     imageFormat: ImageFormat,
                     shots: [StudentShot],
                     createdAt: Double) {
        let fm = FileManager.default
        let projectDir = dir(for: id)
        let imgDir = imagesDir(for: id)
        try? fm.createDirectory(at: imgDir, withIntermediateDirectories: true)

        var records: [ShotRecord] = []
        for shot in shots {
            let kindStr = (shot.kind == .student) ? "student" : "teacher"
            let statusStr: String = {
                switch shot.status {
                case .pending: return "pending"
                case .captured: return "captured"
                case .absent: return "absent"
                }
            }()
            var imageFile: String? = nil
            if shot.status == .captured, let img = shot.image {
                let stem = shot.fileStem(group: group)
                let fname = "\(stem).jpg"
                let url = imgDir.appendingPathComponent(fname)
                // 既に同名ファイルがあれば書き直さない（撮り直し時は事前に削除される）。
                // これで撮影1枚ごとの保存が O(全枚数) ではなく実質1枚で済む。
                if !fm.fileExists(atPath: url.path),
                   let data = img.jpegData(compressionQuality: 0.9) {
                    try? data.write(to: url)
                }
                imageFile = fname
            }
            let crop: [Double]? = shot.cropRect.map {
                [Double($0.minX), Double($0.minY), Double($0.width), Double($0.height)]
            }
            records.append(ShotRecord(kind: kindStr, number: shot.number,
                                      status: statusStr, cropRect: crop,
                                      imageFile: imageFile))
        }

        let file = ProjectFile(
            id: id,
            createdAt: createdAt,
            updatedAt: Date().timeIntervalSince1970,
            group: group,
            roster: roster,
            studentCount: studentCount,
            teacherCount: teacherCount,
            imageFormat: imageFormat.rawValue,
            shots: records
        )

        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted]
        if let data = try? enc.encode(file) {
            try? data.write(to: jsonURL(for: id))
        }

        // 不要になった画像（欠席化・撮り直しで残ったもの）を掃除
        cleanupOrphanImages(id: id, keep: Set(records.compactMap { $0.imageFile }))
    }

    private static func cleanupOrphanImages(id: String, keep: Set<String>) {
        let imgDir = imagesDir(for: id)
        guard let files = try? FileManager.default.contentsOfDirectory(atPath: imgDir.path) else { return }
        for f in files where !keep.contains(f) {
            try? FileManager.default.removeItem(at: imgDir.appendingPathComponent(f))
        }
    }

    // MARK: - 読み込み

    /// 一覧用サマリ（更新日時の新しい順）
    static func loadSummaries() -> [ProjectSummary] {
        let fm = FileManager.default
        guard let ids = try? fm.contentsOfDirectory(atPath: projectsDir.path) else { return [] }
        var result: [ProjectSummary] = []
        for id in ids {
            guard let data = try? Data(contentsOf: jsonURL(for: id)),
                  let file = try? JSONDecoder().decode(ProjectFile.self, from: data)
            else { continue }
            let captured = file.shots.filter { $0.status == "captured" }.count
            let thumb = file.shots.first(where: { $0.status == "captured" && $0.imageFile != nil })?.imageFile
            let thumbPath = thumb.map { imagesDir(for: id).appendingPathComponent($0).path }
            result.append(ProjectSummary(
                id: id,
                displayName: file.group.displayName,
                subtitle: file.group.displaySubtitle,
                capturedCount: captured,
                totalCount: file.studentCount + file.teacherCount,
                updatedAt: Date(timeIntervalSince1970: file.updatedAt),
                thumbnailPath: thumbPath
            ))
        }
        return result.sorted { $0.updatedAt > $1.updatedAt }
    }

    /// プロジェクトを読み込み、shots（画像復元込み）を返す。
    static func load(id: String) -> (file: ProjectFile, shots: [StudentShot])? {
        guard let data = try? Data(contentsOf: jsonURL(for: id)),
              let file = try? JSONDecoder().decode(ProjectFile.self, from: data)
        else { return nil }

        let imgDir = imagesDir(for: id)
        var shots: [StudentShot] = []
        for rec in file.shots {
            let kind: ShotKind = (rec.kind == "teacher") ? .teacher : .student
            let shot = StudentShot(kind: kind, number: rec.number)
            switch rec.status {
            case "captured": shot.status = .captured
            case "absent":   shot.status = .absent
            default:         shot.status = .pending
            }
            if let c = rec.cropRect, c.count == 4 {
                shot.cropRect = CGRect(x: c[0], y: c[1], width: c[2], height: c[3])
            }
            if let f = rec.imageFile {
                let url = imgDir.appendingPathComponent(f)
                shot.image = UIImage(contentsOfFile: url.path)
            }
            shots.append(shot)
        }
        return (file, shots)
    }

    static func delete(id: String) {
        try? FileManager.default.removeItem(at: dir(for: id))
    }

    /// 撮り直し時に古い画像ファイルを消す（次の保存で新しい画像が書かれる）。
    static func deleteImageFile(id: String, fileName: String) {
        try? FileManager.default.removeItem(
            at: imagesDir(for: id).appendingPathComponent(fileName))
    }

    static func newID() -> String { UUID().uuidString }
}
