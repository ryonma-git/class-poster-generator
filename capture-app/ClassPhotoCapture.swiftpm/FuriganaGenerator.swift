import Foundation

// ════════════════════════════════════════════════════════════════
//  FuriganaGenerator — 漢字 → ひらがな（補助変換）
//
//  Apple 公式の人名辞書は無いので、CFStringTokenizer の日本語ロケール
//  形態素解析 + Latin transcription → CFStringTransform で
//  ローマ字 → ひらがなへ。あくまで補助で、必ず人手確認が前提。
//
//  例:
//   "田中 太郎"  → "たなか たろう"
//   "佐藤 花子"  → "さとう はなこ"
//   "山田 一郎"  → "やまだ いちろう"
//   ※ 「中田」「上田」など読みの揺れる姓は誤読しやすい。
// ════════════════════════════════════════════════════════════════

enum FuriganaGenerator {

    /// 入力テキストに含まれる漢字を可能な限りひらがな化する。
    /// ひらがな・カタカナ・空白は維持。失敗（空文字列を含む）は空文字列を返す。
    static func generate(_ text: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "" }

        let cf = trimmed as CFString
        let range = CFRangeMake(0, CFStringGetLength(cf))
        // CFLocaleIdentifier 直接渡しが Swift で固いので NSLocale 経由
        let locale = NSLocale(localeIdentifier: "ja_JP") as CFLocale
        let tokenizer = CFStringTokenizerCreate(
            kCFAllocatorDefault,
            cf,
            range,
            kCFStringTokenizerUnitWord,
            locale
        )

        var output = ""
        var lastWasSpace = true   // 連続空白を1つに

        while CFStringTokenizerAdvanceToNextToken(tokenizer).rawValue != 0 {
            let tokenRange = CFStringTokenizerGetCurrentTokenRange(tokenizer)
            guard tokenRange.length > 0 else { continue }

            // トークン本文
            let tokenStr = (trimmed as NSString)
                .substring(with: NSRange(location: tokenRange.location, length: tokenRange.length))

            // 空白だけのトークンは区切りとして1つに
            if tokenStr.trimmingCharacters(in: CharacterSet.whitespaces).isEmpty {
                if !lastWasSpace {
                    output.append(" ")
                    lastWasSpace = true
                }
                continue
            }

            // ローマ字転写を取得
            let romaji: String? = CFStringTokenizerCopyCurrentTokenAttribute(
                tokenizer, kCFStringTokenizerAttributeLatinTranscription
            ) as? String

            let hira: String
            if let r = romaji, !r.isEmpty {
                hira = latinToHiragana(r)
            } else {
                // 取得できなければ原文（ひらがな/カタカナ/英数は維持）
                hira = tokenStr
            }
            output.append(hira)
            lastWasSpace = false
        }
        return output.trimmingCharacters(in: CharacterSet.whitespaces)
    }

    /// ローマ字 → ひらがな変換
    private static func latinToHiragana(_ romaji: String) -> String {
        let mutable = NSMutableString(string: romaji)
        var range = CFRangeMake(0, mutable.length)
        let ok = CFStringTransform(mutable, &range, kCFStringTransformLatinHiragana, false)
        return ok ? (mutable as String) : romaji
    }
}
