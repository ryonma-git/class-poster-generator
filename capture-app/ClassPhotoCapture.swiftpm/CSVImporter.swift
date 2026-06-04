import Foundation

// ════════════════════════════════════════════════════════════════
//  CSVImporter — 名簿 CSV/TSV の読み込みと自動列マッピング
//
//  - エンコーディング自動判定（UTF-8 BOM / UTF-8 / Shift-JIS）
//  - 区切り自動判定（カンマ / タブ）
//  - ヘッダーから列の役割を推定（番号/氏名/ふりがな/学年/組）
//  - 本体の名簿（Excel ベース）の慣習列（C=学年 D=組 E=番号 R=ふりがな）にも対応
// ════════════════════════════════════════════════════════════════

enum ImportField: String, CaseIterable, Identifiable {
    case ignore     = "—（使わない）"
    case grade      = "学年"
    case cls        = "組"
    case number     = "番号"
    case kanji      = "氏名（漢字）"
    case furigana   = "ふりがな"
    var id: String { rawValue }
}

/// 取り込んだ生データ＋自動推定された列マッピング
struct ImportedRoster {
    var headers: [String]         // 1行目（推定ヘッダー）
    var rows: [[String]]          // データ行
    var mapping: [Int: ImportField] // 列インデックス → 役割
    var detectedDelimiter: Character
    var detectedEncoding: String
    var hasHeader: Bool            // 1行目がヘッダーか
}

enum CSVImportError: Error, LocalizedError {
    case decodeFailed
    case emptyFile

    var errorDescription: String? {
        switch self {
        case .decodeFailed: return "ファイルの文字コードを判定できませんでした。UTF-8 か Shift-JIS で保存してください。"
        case .emptyFile:    return "ファイルが空です。"
        }
    }
}

enum CSVImporter {

    /// 拡張子に応じて Excel(.xlsx) / CSV / TSV を読み分けて取り込む。
    static func loadAny(from url: URL) throws -> ImportedRoster {
        let ext = url.pathExtension.lowercased()
        if ext == "xlsx" {
            let rawRows = try XLSXImporter.loadRows(from: url)
            return makeImported(rawRows: rawRows,
                                delimiter: ",",
                                encoding: "Excel (.xlsx)")
        }
        return try load(from: url)
    }

    /// CSV/TSV ファイルを読み込んで構造化済みデータを返す。
    static func load(from url: URL) throws -> ImportedRoster {
        let didStart = url.startAccessingSecurityScopedResource()
        defer { if didStart { url.stopAccessingSecurityScopedResource() } }

        let data = try Data(contentsOf: url)
        let (text, encoding) = try decode(data)
        let (delim, _) = detectDelimiter(text)
        let rawRows = parse(text, delimiter: delim)

        guard !rawRows.isEmpty else { throw CSVImportError.emptyFile }
        return makeImported(rawRows: rawRows, delimiter: delim, encoding: encoding)
    }

    /// 生の行配列から ImportedRoster（ヘッダー判定＋列推定）を組み立てる。
    /// CSV / TSV / XLSX 共通の後段処理。
    static func makeImported(rawRows: [[String]],
                             delimiter: Character,
                             encoding: String) -> ImportedRoster {
        let nonEmpty = rawRows.filter { !$0.allSatisfy { $0.trimmingCharacters(in: .whitespaces).isEmpty } }
        let source = nonEmpty.isEmpty ? rawRows : nonEmpty

        // ヘッダー判定（最初の行に数字以外が多ければヘッダーとみなす）
        let isHeader = source.isEmpty ? false : looksLikeHeader(source[0])
        let headers: [String]
        let dataRows: [[String]]
        if isHeader {
            headers = source[0]
            dataRows = Array(source.dropFirst())
        } else {
            // 列番号でヘッダーを仮置き（"C","D","E"…のExcel列風）
            let n = source.first?.count ?? 0
            headers = (0..<n).map { excelColumnName($0) }
            dataRows = source
        }

        let mapping = guessMapping(headers: headers,
                                   hasHeaderRow: isHeader,
                                   sampleRows: dataRows.prefix(5).map { $0 })

        return ImportedRoster(
            headers: headers,
            rows: dataRows,
            mapping: mapping,
            detectedDelimiter: delimiter,
            detectedEncoding: encoding,
            hasHeader: isHeader
        )
    }

    /// マッピングに従って roster に書き込む。
    /// - grade/cls フィルタ: 列がマップされていれば、現在の AppState の学年・組と一致する行のみ採用。
    static func apply(_ imported: ImportedRoster,
                      to roster: Roster,
                      group: GroupConfig) -> (applied: Int, skipped: Int) {
        let mapping = imported.mapping

        func colIndex(_ field: ImportField) -> Int? {
            mapping.first(where: { $0.value == field })?.key
        }

        let numIdx = colIndex(.number)
        let nameIdx = colIndex(.kanji)
        let furiIdx = colIndex(.furigana)
        let gradeIdx = colIndex(.grade)
        let clsIdx = colIndex(.cls)

        // 集団モードでは grade/cls フィルタは効かせない
        let filterByClass = (group.mode == .school) && (gradeIdx != nil || clsIdx != nil)

        var applied = 0
        var skipped = 0

        for row in imported.rows {
            // クラスフィルタ
            if filterByClass {
                if let gi = gradeIdx, let v = row[safe: gi],
                   let gNum = Int(v.trimmedAsciiDigits()),
                   gNum != group.grade {
                    skipped += 1; continue
                }
                if let ci = clsIdx, let v = row[safe: ci] {
                    let trimmed = v.trimmedAsciiDigits()
                    let asInt = Int(trimmed)
                    switch group.classLabel {
                    case .number(let n) where asInt != n:
                        skipped += 1; continue
                    case .letter(let s) where trimmed.uppercased() != s.uppercased():
                        skipped += 1; continue
                    default: break
                    }
                }
            }

            // 番号
            guard let ni = numIdx, let raw = row[safe: ni],
                  let num = Int(raw.trimmedAsciiDigits()), num > 0
            else { skipped += 1; continue }

            // 番号で該当 Member を引き当てる（無ければ拡張）
            if roster.studentByNumber(num) == nil {
                roster.students.append(Member(role: .student, number: num))
            }
            guard let member = roster.studentByNumber(num) else { skipped += 1; continue }

            if let ki = nameIdx, let v = row[safe: ki] {
                let s = v.trimmingCharacters(in: .whitespaces)
                if !s.isEmpty { member.name = s }
            }
            if let fi = furiIdx, let v = row[safe: fi] {
                let s = v.trimmingCharacters(in: .whitespaces)
                if !s.isEmpty { member.furigana = s }
            }
            applied += 1
        }

        // 番号順に並べ替え（新規追加が末尾に挿入されている可能性があるため）
        roster.students.sort { $0.number < $1.number }
        return (applied, skipped)
    }

    // MARK: - エンコーディング

    private static func decode(_ data: Data) throws -> (String, String) {
        // UTF-8 BOM
        if data.starts(with: [0xEF, 0xBB, 0xBF]) {
            let stripped = data.dropFirst(3)
            if let s = String(data: stripped, encoding: .utf8) { return (s, "UTF-8 (BOM)") }
        }
        if let s = String(data: data, encoding: .utf8) { return (s, "UTF-8") }
        if let s = String(data: data, encoding: .shiftJIS) { return (s, "Shift-JIS") }
        // 一応 UTF-16 も
        if let s = String(data: data, encoding: .utf16) { return (s, "UTF-16") }
        throw CSVImportError.decodeFailed
    }

    // MARK: - 区切り判定

    private static func detectDelimiter(_ text: String) -> (Character, Int) {
        let head = text.prefix(2000)
        let commas = head.filter { $0 == "," }.count
        let tabs   = head.filter { $0 == "\t" }.count
        return tabs > commas ? ("\t", tabs) : (",", commas)
    }

    // MARK: - CSV/TSV パーサ（クォート対応）

    static func parse(_ s: String, delimiter: Character) -> [[String]] {
        var rows: [[String]] = []
        var row: [String] = []
        var field = ""
        var inQuotes = false
        var iter = s.unicodeScalars.makeIterator()
        var current: Unicode.Scalar? = iter.next()

        while let c = current {
            let ch = Character(c)
            if inQuotes {
                if ch == "\"" {
                    let next = iter.next()
                    if let n = next, n == "\"" {
                        field.append("\"")
                        current = iter.next()
                        continue
                    } else {
                        inQuotes = false
                        current = next
                        continue
                    }
                } else {
                    field.append(ch)
                }
            } else {
                switch ch {
                case "\"":
                    inQuotes = true
                case delimiter:
                    row.append(field); field = ""
                case "\n":
                    row.append(field); field = ""
                    rows.append(row); row = []
                case "\r":
                    break   // \r\n の \r は捨てる（次の \n でフラッシュ）
                default:
                    field.append(ch)
                }
            }
            current = iter.next()
        }
        // 末尾フラッシュ
        if !field.isEmpty || !row.isEmpty {
            row.append(field)
            rows.append(row)
        }
        // 全カラム空の行は除外
        return rows.filter { !$0.allSatisfy { $0.trimmingCharacters(in: .whitespaces).isEmpty } }
    }

    // MARK: - ヘッダー / 列推定

    /// 1行目がヘッダーかどうかをヒューリスティックに判定
    /// （数値が多い行はデータと判断）
    private static func looksLikeHeader(_ row: [String]) -> Bool {
        var numeric = 0
        var nonEmpty = 0
        for v in row {
            let trimmed = v.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty else { continue }
            nonEmpty += 1
            if Int(trimmed.trimmedAsciiDigits()) != nil { numeric += 1 }
        }
        return nonEmpty > 0 && Double(numeric) / Double(nonEmpty) < 0.3
    }

    /// ヘッダー名から各列の役割を推定。
    /// ヘッダーが無い場合（=Excel列名 A,B,C…）は本体慣習列（C=学年, D=組, E=番号, R=ふりがな）にマップ。
    private static func guessMapping(headers: [String],
                                     hasHeaderRow: Bool,
                                     sampleRows: [[String]]) -> [Int: ImportField] {
        var result: [Int: ImportField] = [:]

        if hasHeaderRow {
            // 正規化した見出し
            let norm = headers.map {
                $0.replacingOccurrences(of: "　", with: "")
                  .replacingOccurrences(of: " ", with: "")
                  .lowercased()
            }
            // 各列を ignore で初期化
            for i in 0..<headers.count { result[i] = .ignore }

            // 役割ごとに「最もスコアの高い列」を1つ選ぶ。
            // これにより C4th 名簿のように「姓ふりがな/名ふりがな/ふりがな」が併存しても
            // フル氏名・フルふりがなの列を正しく選べる。
            func assignBest(_ field: ImportField, _ score: (String) -> Int) {
                var bestIdx = -1, bestScore = 0
                for (i, n) in norm.enumerated() {
                    let s = score(n)
                    if s > bestScore { bestScore = s; bestIdx = i }
                }
                if bestIdx >= 0 { result[bestIdx] = field }
            }
            assignBest(.number,   scoreNumber)
            assignBest(.grade,    scoreGrade)
            assignBest(.cls,      scoreCls)
            assignBest(.kanji,    scoreKanji)
            assignBest(.furigana, scoreFurigana)
        } else {
            // ヘッダーなし：本体（make_poster.py）の慣習列にマップ
            // C(2)=学年, D(3)=組, E(4)=番号, R(17)=ふりがな
            for i in 0..<headers.count {
                switch i {
                case 2:  result[i] = .grade
                case 3:  result[i] = .cls
                case 4:  result[i] = .number
                case 17: result[i] = .furigana
                default: result[i] = .ignore
                }
            }
        }

        // 何も検出できなかった場合のフォールバック：数値の多い列を「番号」に
        if !result.values.contains(.number), let cnt = sampleRows.first?.count, cnt > 0 {
            for i in 0..<cnt {
                let values = sampleRows.compactMap { $0[safe: i] }
                let ints = values.compactMap { Int($0.trimmedAsciiDigits()) }
                if ints.count >= max(1, values.count - 1), values.count > 0 {
                    result[i] = .number
                    break
                }
            }
        }

        return result
    }

    private static func matches(_ s: String, _ candidates: [String]) -> Bool {
        for c in candidates {
            if s.contains(c.lowercased()) { return true }
        }
        return false
    }

    // MARK: - 列スコアリング（C4th 等で正しい列を選ぶ）
    //
    // すべて正規化済み（空白除去・小文字）の見出し文字列 h を受け取り、
    // その役割としての「ふさわしさ」を整数で返す。0 以下は不採用。

    private static func has(_ h: String, _ ks: [String]) -> Bool { ks.contains { h.contains($0) } }
    private static let furiKeys = ["ふりがな", "ふり仮名", "フリガナ", "ﾌﾘｶﾞﾅ", "よみがな", "よみ", "ヨミ", "かな", "カナ", "yomi", "kana"]

    /// 出席番号: 郵便/電話/FAX/管理/コード/学級番号 等は強く除外
    private static func scoreNumber(_ h: String) -> Int {
        if has(h, ["郵便", "電話", "fax", "ﾌｧｸｽ", "指導要録", "管理", "支援", "コード", "ｺｰﾄﾞ", "id"]) { return 0 }
        if has(h, furiKeys) { return 0 }
        if h == "出席番号" || h.contains("出席") { return 100 }
        if h == "番号" || h == "no" || h == "no." { return 90 }
        if h.contains("番号") { return 60 }
        if h.contains("number") || h == "#" { return 50 }
        return 0
    }

    private static func scoreGrade(_ h: String) -> Int {
        if has(h, furiKeys) { return 0 }
        if h == "学年" { return 100 }
        if h.contains("学年") { return 80 }
        if h.contains("grade") { return 70 }
        return 0
    }

    /// 組: 学級番号・支援学級などは除外し、純粋な「組/学級/クラス」を選ぶ
    private static func scoreCls(_ h: String) -> Int {
        if has(h, ["番号", "支援"]) || has(h, furiKeys) { return 0 }
        if h == "組" || h == "学級" || h == "クラス" { return 100 }
        if h.contains("組") || h.contains("学級") || h.contains("クラス") { return 70 }
        if h == "cls" || h.contains("class") { return 60 }
        return 0
    }

    /// 氏名（漢字）: ふりがな列は除外。「名前/氏名」フル名を最優先、姓・名単独は最後の手段。
    private static func scoreKanji(_ h: String) -> Int {
        if has(h, furiKeys) { return 0 }                      // 読み列は対象外
        if h.contains("正式") { return 0 }                     // 「正式名前」は通常使わない
        if h == "氏名" || h == "名前" || h == "生徒氏名" || h == "児童氏名" { return 100 }
        if h.contains("氏名") || h.contains("名前") { return 90 }
        if h.contains("生徒名") || h.contains("児童名") || h.contains("name") { return 60 }
        if h == "姓" || h == "名" { return 20 }                 // 分割列は最後の手段
        return 0
    }

    /// ふりがな: フル読みを最優先。「姓ふりがな/名ふりがな」など分割や「正式」は低スコア。
    private static func scoreFurigana(_ h: String) -> Int {
        guard has(h, furiKeys) else { return 0 }
        if h.contains("正式") { return 30 }                    // 正式名前ふりがな等は控えめ
        if h == "ふりがな" || h == "フリガナ" || h == "よみがな" { return 100 }
        if h.contains("名前") || h.contains("氏名") { return 90 } // 名前ふりがな = フル
        if h.contains("姓") || h.contains("名") { return 40 }    // 姓ふりがな/名ふりがな = 分割
        return 70
    }

    /// Excel 列名（A, B, C, ..., AA, AB...）
    private static func excelColumnName(_ index: Int) -> String {
        var i = index
        var s = ""
        repeat {
            let r = i % 26
            s = String(UnicodeScalar(65 + r)!) + s
            i = i / 26 - 1
        } while i >= 0
        return s
    }
}

// MARK: - 小ヘルパ

private extension Array {
    subscript(safe i: Int) -> Element? {
        indices.contains(i) ? self[i] : nil
    }
}

extension String {
    /// 全角数字や前後空白を取り除き ASCII 数字のみを残す
    /// （Phase 5 で導入、Phase 7 で再利用するため internal に昇格）
    func trimmedAsciiDigits() -> String {
        var s = self.trimmingCharacters(in: .whitespacesAndNewlines)
        // 全角→半角
        let zeros = "０１２３４５６７８９"
        let halfs = "0123456789"
        for (z, h) in zip(zeros, halfs) {
            s = s.replacingOccurrences(of: String(z), with: String(h))
        }
        return s
    }
}
