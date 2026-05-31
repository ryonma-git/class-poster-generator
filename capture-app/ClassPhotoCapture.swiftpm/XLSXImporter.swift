import Foundation
import Compression

// ════════════════════════════════════════════════════════════════
//  XLSXImporter — Excel(.xlsx) を直接読み込む
//
//  .xlsx は ZIP アーカイブ（中身は XML）。外部ライブラリ無しで:
//   1. MinimalZip で ZIP を展開（Apple の COMPRESSION_ZLIB = 生deflate）
//   2. xl/sharedStrings.xml（共有文字列）と
//      xl/worksheets/sheet1.xml（セル）を XMLParser で読む
//   3. 行 × 列の文字列配列にして CSVImporter と同じ後段（列マッピング）へ
//
//  最初のシートのみ対象。数式の計算結果（<v>）と共有文字列（t="s"）に対応。
// ════════════════════════════════════════════════════════════════

enum XLSXError: Error, LocalizedError {
    case notZip
    case noSheet
    case parseFailed

    var errorDescription: String? {
        switch self {
        case .notZip:      return "Excelファイルを開けませんでした（壊れている可能性があります）。"
        case .noSheet:     return "シートが見つかりませんでした。"
        case .parseFailed: return "Excelの内容を読み取れませんでした。CSV で書き出してからお試しください。"
        }
    }
}

enum XLSXImporter {

    /// .xlsx を読み込んで行×列の文字列配列にする
    static func loadRows(from url: URL) throws -> [[String]] {
        let didStart = url.startAccessingSecurityScopedResource()
        defer { if didStart { url.stopAccessingSecurityScopedResource() } }

        let data = try Data(contentsOf: url)
        let files = try MinimalZip.entries(from: data)

        // 共有文字列
        var sharedStrings: [String] = []
        if let ss = files["xl/sharedStrings.xml"] {
            sharedStrings = SharedStringsParser.parse(ss)
        }

        // 最初のシート（worksheets/sheet1.xml が基本。無ければ最初に見つかったもの）
        let sheetData: Data
        if let s1 = files["xl/worksheets/sheet1.xml"] {
            sheetData = s1
        } else if let anySheet = files.first(where: {
            $0.key.hasPrefix("xl/worksheets/") && $0.key.hasSuffix(".xml")
        })?.value {
            sheetData = anySheet
        } else {
            throw XLSXError.noSheet
        }

        let rows = SheetParser.parse(sheetData, sharedStrings: sharedStrings)
        guard !rows.isEmpty else { throw XLSXError.parseFailed }
        return rows
    }
}

// MARK: - 最小 ZIP リーダ

// ZIP 展開ユーティリティ（XLSX / .cpcap 共用）
enum MinimalZip {
    /// ZIP の中身を [パス: 展開後データ] で返す
    static func entries(from data: Data) throws -> [String: Data] {
        let bytes = [UInt8](data)
        let n = bytes.count

        // End Of Central Directory を末尾から探す（署名 0x06054b50）
        var eocd = -1
        if n >= 22 {
            var i = n - 22
            while i >= 0 {
                if bytes[i] == 0x50, bytes[i+1] == 0x4b, bytes[i+2] == 0x05, bytes[i+3] == 0x06 {
                    eocd = i; break
                }
                i -= 1
            }
        }
        guard eocd >= 0 else { throw XLSXError.notZip }

        let cdCount = Int(u16(bytes, eocd + 10))
        var cdOffset = Int(u32(bytes, eocd + 16))

        var result: [String: Data] = [:]
        for _ in 0..<cdCount {
            guard cdOffset + 46 <= n else { break }
            // 中央ディレクトリ署名 0x02014b50
            guard bytes[cdOffset] == 0x50, bytes[cdOffset+1] == 0x4b,
                  bytes[cdOffset+2] == 0x01, bytes[cdOffset+3] == 0x02 else { break }

            let method   = Int(u16(bytes, cdOffset + 10))
            let compSize = Int(u32(bytes, cdOffset + 20))
            let uncomp   = Int(u32(bytes, cdOffset + 24))
            let nameLen  = Int(u16(bytes, cdOffset + 28))
            let extraLen = Int(u16(bytes, cdOffset + 30))
            let commLen  = Int(u16(bytes, cdOffset + 32))
            let localOff = Int(u32(bytes, cdOffset + 42))

            let nameStart = cdOffset + 46
            guard nameStart + nameLen <= n else { break }
            let name = String(decoding: bytes[nameStart..<nameStart+nameLen], as: UTF8.self)

            // ローカルヘッダ（0x04034b50）から実データ位置を求める
            if localOff + 30 <= n,
               bytes[localOff] == 0x50, bytes[localOff+1] == 0x4b,
               bytes[localOff+2] == 0x03, bytes[localOff+3] == 0x04 {
                let lNameLen  = Int(u16(bytes, localOff + 26))
                let lExtraLen = Int(u16(bytes, localOff + 28))
                let dataStart = localOff + 30 + lNameLen + lExtraLen
                if dataStart + compSize <= n {
                    let comp = Array(bytes[dataStart..<dataStart+compSize])
                    let out: Data?
                    if method == 0 {
                        out = Data(comp)                 // 無圧縮(Store)
                    } else {
                        out = inflate(comp, expectedSize: uncomp)  // Deflate
                    }
                    if let out { result[name] = out }
                }
            }
            cdOffset = nameStart + nameLen + extraLen + commLen
        }
        return result
    }

    /// 生 deflate を展開（Apple の COMPRESSION_ZLIB は raw deflate）
    private static func inflate(_ comp: [UInt8], expectedSize: Int) -> Data? {
        let dstCap = max(expectedSize, comp.count * 8) + 4096
        var dst = [UInt8](repeating: 0, count: dstCap)
        let written = comp.withUnsafeBufferPointer { src -> Int in
            dst.withUnsafeMutableBufferPointer { dstBuf in
                compression_decode_buffer(dstBuf.baseAddress!, dstCap,
                                          src.baseAddress!, comp.count,
                                          nil, COMPRESSION_ZLIB)
            }
        }
        guard written > 0 else { return nil }
        return Data(dst[0..<written])
    }

    private static func u16(_ b: [UInt8], _ i: Int) -> UInt16 {
        UInt16(b[i]) | (UInt16(b[i+1]) << 8)
    }
    private static func u32(_ b: [UInt8], _ i: Int) -> UInt32 {
        UInt32(b[i]) | (UInt32(b[i+1]) << 8) | (UInt32(b[i+2]) << 16) | (UInt32(b[i+3]) << 24)
    }
}

// MARK: - sharedStrings.xml パーサ

private final class SharedStringsParser: NSObject, XMLParserDelegate {
    private var strings: [String] = []
    private var current = ""
    private var inSI = false      // <si> 内
    private var capture = false   // <t> 内

    static func parse(_ data: Data) -> [String] {
        let p = SharedStringsParser()
        let xml = XMLParser(data: data)
        xml.delegate = p
        xml.parse()
        return p.strings
    }

    func parser(_ parser: XMLParser, didStartElement elementName: String,
                namespaceURI: String?, qualifiedName qName: String?,
                attributes attributeDict: [String : String]) {
        if elementName == "si" { inSI = true; current = "" }
        if elementName == "t" { capture = true }
    }
    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if capture { current += string }
    }
    func parser(_ parser: XMLParser, didEndElement elementName: String,
                namespaceURI: String?, qualifiedName qName: String?) {
        if elementName == "t" { capture = false }
        if elementName == "si" { strings.append(current); inSI = false }
    }
}

// MARK: - worksheet パーサ

private final class SheetParser: NSObject, XMLParserDelegate {
    private let shared: [String]
    private var rows: [[String]] = []
    private var currentRow: [(col: Int, val: String)] = []
    private var cellType = ""        // s=共有文字列, str=数式文字列, inlineStr, 既定=数値
    private var cellRef = ""         // 例 "B3"
    private var cellValue = ""
    private var capturingValue = false
    private var inInlineStr = false

    init(shared: [String]) { self.shared = shared }

    static func parse(_ data: Data, sharedStrings: [String]) -> [[String]] {
        let p = SheetParser(shared: sharedStrings)
        let xml = XMLParser(data: data)
        xml.delegate = p
        xml.parse()
        return p.rows
    }

    func parser(_ parser: XMLParser, didStartElement elementName: String,
                namespaceURI: String?, qualifiedName qName: String?,
                attributes attributeDict: [String : String]) {
        switch elementName {
        case "row":
            currentRow = []
        case "c":
            cellType = attributeDict["t"] ?? ""
            cellRef = attributeDict["r"] ?? ""
            cellValue = ""
        case "v":
            capturingValue = true
            cellValue = ""
        case "t":
            // inlineStr の <is><t> または 共有文字列内
            if cellType == "inlineStr" { inInlineStr = true; cellValue = "" }
        default:
            break
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if capturingValue || inInlineStr { cellValue += string }
    }

    func parser(_ parser: XMLParser, didEndElement elementName: String,
                namespaceURI: String?, qualifiedName qName: String?) {
        switch elementName {
        case "v":
            capturingValue = false
        case "t":
            if inInlineStr { inInlineStr = false }
        case "c":
            let resolved: String
            if cellType == "s", let idx = Int(cellValue), idx >= 0, idx < shared.count {
                resolved = shared[idx]
            } else {
                resolved = cellValue
            }
            let col = SheetParser.columnIndex(fromRef: cellRef)
            currentRow.append((col, resolved))
        case "row":
            // 列インデックス順に並べ、欠けは空文字で埋める
            if let maxCol = currentRow.map({ $0.col }).max() {
                var line = [String](repeating: "", count: maxCol + 1)
                for cell in currentRow { line[cell.col] = cell.val }
                rows.append(line)
            } else {
                rows.append([])
            }
        default:
            break
        }
    }

    /// "B3" → 1（0始まりの列インデックス）
    static func columnIndex(fromRef ref: String) -> Int {
        var col = 0
        var found = false
        for ch in ref {
            if let s = ch.asciiValue, s >= 65, s <= 90 {       // A-Z
                col = col * 26 + Int(s - 65 + 1)
                found = true
            } else if let s = ch.asciiValue, s >= 97, s <= 122 { // a-z
                col = col * 26 + Int(s - 97 + 1)
                found = true
            } else {
                break
            }
        }
        return found ? col - 1 : 0
    }
}
