import Foundation
import UIKit
import Vision

// ════════════════════════════════════════════════════════════════
//  VisionOCRImporter — 名簿画像 → 番号 / 漢字 / ふりがな 行リスト
//
//  Vision Framework の VNRecognizeTextRequest を日本語認識精度モードで
//  使い、画像から行を抽出する。
//
//  1. 認識結果の bounding box を y 座標でクラスタリングして「行」に
//  2. 各行内では x 昇順でソート
//  3. 各セルを文字種で分類:
//       - 数字のみ        → 番号
//       - ひらがな/カタカナのみ → ふりがな
//       - 漢字を含む       → 漢字
//
//  認識精度は写真の品質に強く依存するため、結果は必ず手直し前提で
//  RosterOCRView の表で編集してから適用する。
// ════════════════════════════════════════════════════════════════

/// OCR で抽出した1行分
struct OCRRow: Identifiable, Equatable {
    let id = UUID()
    var number: String = ""
    var kanji: String = ""
    var furigana: String = ""

    var hasAnything: Bool {
        !(number.isEmpty && kanji.isEmpty && furigana.isEmpty)
    }
}

enum OCRError: Error, LocalizedError {
    case noCGImage
    case visionFailed(String)
    case noText

    var errorDescription: String? {
        switch self {
        case .noCGImage:          return "画像を読み込めませんでした。"
        case .visionFailed(let s): return "Vision の認識に失敗しました: \(s)"
        case .noText:              return "画像から文字を検出できませんでした。"
        }
    }
}

enum VisionOCRImporter {

    /// 画像 → 行リスト
    static func recognize(_ image: UIImage) async throws -> [OCRRow] {
        guard let cg = image.cgImage else { throw OCRError.noCGImage }

        let request = VNRecognizeTextRequest()
        request.recognitionLanguages = ["ja-JP", "ja", "en-US"]
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true

        let orientation = cgOrientation(from: image.imageOrientation)
        let handler = VNImageRequestHandler(cgImage: cg, orientation: orientation, options: [:])

        return try await withCheckedThrowingContinuation { cont in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    try handler.perform([request])
                    let obs = (request.results ?? [])
                    let rows = cluster(obs)
                    if rows.isEmpty {
                        cont.resume(throwing: OCRError.noText)
                    } else {
                        cont.resume(returning: rows)
                    }
                } catch {
                    cont.resume(throwing: OCRError.visionFailed(error.localizedDescription))
                }
            }
        }
    }

    // MARK: - クラスタリング

    /// 観測結果を「行」にまとめる。
    /// boundingBox は Vision の正規化座標 (0..1, 原点左下)
    private static func cluster(_ obs: [VNRecognizedTextObservation]) -> [OCRRow] {
        struct Item {
            let text: String
            let yMid: CGFloat   // 0..1 上が大きい
            let xMid: CGFloat
            let height: CGFloat
        }
        var items: [Item] = []
        for o in obs {
            guard let cand = o.topCandidates(1).first else { continue }
            let s = cand.string.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !s.isEmpty else { continue }
            let bb = o.boundingBox
            items.append(Item(text: s,
                              yMid: bb.midY,
                              xMid: bb.midX,
                              height: bb.height))
        }
        guard !items.isEmpty else { return [] }

        // 平均高さの 0.6 倍を「同じ行」と見なす閾値に
        let meanH = items.map(\.height).reduce(0, +) / CGFloat(items.count)
        let yThreshold = max(0.005, meanH * 0.6)

        // 上から下 = y が大きい → 小さい
        let sorted = items.sorted { $0.yMid > $1.yMid }

        // 行グループ化
        var clusters: [[Item]] = []
        var current: [Item] = []
        var currentY: CGFloat = sorted[0].yMid
        for item in sorted {
            if abs(item.yMid - currentY) <= yThreshold {
                current.append(item)
                currentY = (currentY + item.yMid) / 2
            } else {
                if !current.isEmpty { clusters.append(current) }
                current = [item]
                currentY = item.yMid
            }
        }
        if !current.isEmpty { clusters.append(current) }

        // 行内は x 昇順
        let lines: [[Item]] = clusters.map { $0.sorted { $0.xMid < $1.xMid } }

        // 各行を分類
        var rows: [OCRRow] = []
        for line in lines {
            let row = classify(line.map { $0.text })
            if row.hasAnything { rows.append(row) }
        }
        return rows
    }

    /// 1行のテキスト配列を 番号/漢字/ふりがな に振り分け
    private static func classify(_ cells: [String]) -> OCRRow {
        var row = OCRRow()
        var leftover: [String] = []

        for raw in cells {
            let t = raw.replacingOccurrences(of: "　", with: "")
            // 数字のみ → 番号（未設定なら）
            if row.number.isEmpty,
               let n = Int(t.trimmedAsciiDigits()), n > 0, n < 10000,
               isAllDigits(t) {
                row.number = String(n)
                continue
            }
            if isAllHiragana(t) || isAllKatakana(t) {
                if row.furigana.isEmpty {
                    row.furigana = t
                } else {
                    row.furigana += t  // ふりがなが2セルに分かれて取れた場合の結合
                }
                continue
            }
            if hasKanji(t) {
                if row.kanji.isEmpty {
                    row.kanji = t
                } else {
                    row.kanji += t  // 漢字が複数セルになった場合
                }
                continue
            }
            leftover.append(t)
        }

        // どこにも入らなかった文字列は、ふりがなと漢字どちらかに寄せる
        for l in leftover {
            if row.kanji.isEmpty { row.kanji = l }
            else if row.furigana.isEmpty { row.furigana = l }
        }
        return row
    }

    // MARK: - 文字種判定

    private static func isAllDigits(_ s: String) -> Bool {
        let stripped = s.trimmedAsciiDigits()
        guard !stripped.isEmpty else { return false }
        return Int(stripped) != nil
    }

    private static func isAllHiragana(_ s: String) -> Bool {
        var sawHira = false
        for scalar in s.unicodeScalars {
            let v = scalar.value
            // ひらがな + 長音 + 空白
            if (0x3040...0x309F).contains(v) || v == 0x30FC {
                sawHira = true
            } else if v == 0x0020 || v == 0x3000 {
                continue
            } else {
                return false
            }
        }
        return sawHira
    }

    private static func isAllKatakana(_ s: String) -> Bool {
        var sawKana = false
        for scalar in s.unicodeScalars {
            let v = scalar.value
            if (0x30A0...0x30FF).contains(v) {
                sawKana = true
            } else if v == 0x0020 || v == 0x3000 {
                continue
            } else {
                return false
            }
        }
        return sawKana
    }

    private static func hasKanji(_ s: String) -> Bool {
        for scalar in s.unicodeScalars {
            let v = scalar.value
            // CJK Unified Ideographs（一般的な漢字範囲）
            if (0x4E00...0x9FFF).contains(v) { return true }
            // 拡張Aもざっくり
            if (0x3400...0x4DBF).contains(v) { return true }
        }
        return false
    }

    // MARK: - 画像向き

    private static func cgOrientation(from o: UIImage.Orientation) -> CGImagePropertyOrientation {
        switch o {
        case .up:            return .up
        case .upMirrored:    return .upMirrored
        case .down:          return .down
        case .downMirrored:  return .downMirrored
        case .left:          return .left
        case .leftMirrored:  return .leftMirrored
        case .right:         return .right
        case .rightMirrored: return .rightMirrored
        @unknown default:    return .up
        }
    }
}
