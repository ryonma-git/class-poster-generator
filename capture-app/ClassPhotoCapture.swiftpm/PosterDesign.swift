import SwiftUI
import UIKit

// ════════════════════════════════════════════════════════════════
//  PosterDesign — ポスターの設計値（紙サイズ・配色・レイアウト定数）
//
//  本体（make_poster.py）の定数と完全に対応：
//   - mm 単位の余白・ヘッダー・ラベル高
//   - design_config.json と同じカラーキー
//   - A0〜B5 の用紙サイズ（pt）
// ════════════════════════════════════════════════════════════════

// MARK: - 用紙サイズ

enum PaperSize: String, CaseIterable, Identifiable, Codable {
    case A0, A1, A2, A3, A4, A5
    case B0, B1, B2, B3, B4, B5

    var id: String { rawValue }

    /// pt (1/72 inch) 単位、縦置き寸法
    var sizePt: CGSize {
        switch self {
        case .A0: return CGSize(width: 2383.937, height: 3370.394)
        case .A1: return CGSize(width: 1683.78,  height: 2383.937)
        case .A2: return CGSize(width: 1190.551, height: 1683.78)
        case .A3: return CGSize(width: 841.890,  height: 1190.551)
        case .A4: return CGSize(width: 595.276,  height: 841.890)
        case .A5: return CGSize(width: 419.528,  height: 595.276)
        case .B0: return CGSize(width: 2834.646, height: 4008.189)
        case .B1: return CGSize(width: 2004.094, height: 2834.646)
        case .B2: return CGSize(width: 1417.323, height: 2004.094)
        case .B3: return CGSize(width: 1000.630, height: 1417.323)
        case .B4: return CGSize(width: 708.661,  height: 1000.630)
        case .B5: return CGSize(width: 498.898,  height: 708.661)
        }
    }

    /// 実寸 mm（参考表示用）
    var sizeMm: (w: Int, h: Int) {
        let pt = sizePt
        return (Int(round(pt.width * 25.4 / 72.0)), Int(round(pt.height * 25.4 / 72.0)))
    }

    /// 表示名「A1 (594×841mm)」
    var displayName: String {
        let m = sizeMm
        return "\(rawValue) (\(m.w)×\(m.h)mm)"
    }

    /// シリーズ識別（"A" or "B"）— UI で A系/B系を分離表示するため
    var series: String {
        rawValue.hasPrefix("A") ? "A" : "B"
    }

    /// 推奨デフォルト列数（紙が小さくなるほど列を減らす）
    /// make_poster.py は固定で6列。本体互換のため大判はそのまま、小判は調整。
    var suggestedCols: Int {
        switch self {
        case .A0, .A1, .A2, .B0, .B1, .B2: return 6
        case .A3, .B3:                       return 6
        case .A4, .B4:                       return 5
        case .A5, .B5:                       return 4
        }
    }
    var suggestedRows: Int {
        switch self {
        case .A0, .A1, .A2, .B0, .B1, .B2: return 7
        case .A3, .B3:                       return 7
        case .A4, .B4:                       return 7
        case .A5, .B5:                       return 6
        }
    }
}

// MARK: - 配色（design_config.json 互換）
//
// Codable 安定性のために hex(UInt32) で保持。Color / UIColor は計算プロパティで提供。

struct PosterDesign: Equatable, Codable {
    var backgroundHex: UInt32
    var cardBgHex:     UInt32
    var labelBgHex:    UInt32
    var labelFgHex:    UInt32
    var numberFgHex:   UInt32
    var accentHex:     UInt32
    var headerBgHex:   UInt32
    var headerSubHex:  UInt32
    var teacherBgHex:  UInt32

    /// 本体デフォルト（make_poster.py と一致）
    static let `default` = PosterDesign(
        backgroundHex: 0xEEF3F8,
        cardBgHex:     0xF7F9FC,
        labelBgHex:    0x2B5F8E,
        labelFgHex:    0xFFFFFF,
        numberFgHex:   0xE89C2A,
        accentHex:     0xE89C2A,
        headerBgHex:   0x1A4D80,
        headerSubHex:  0x2B5F8E,
        teacherBgHex:  0x4A90C4
    )

    /// 桜（春・卒業）
    static let sakura = PosterDesign(
        backgroundHex: 0xFFF5F8,
        cardBgHex:     0xFFFDFE,
        labelBgHex:    0xC23B6A,
        labelFgHex:    0xFFFFFF,
        numberFgHex:   0xFFC857,
        accentHex:     0xFFC857,
        headerBgHex:   0x9B2046,
        headerSubHex:  0xC23B6A,
        teacherBgHex:  0xE489AA
    )

    /// 若葉（5月・運動会）
    static let wakaba = PosterDesign(
        backgroundHex: 0xF0F8EE,
        cardBgHex:     0xFAFDF8,
        labelBgHex:    0x2F7A3C,
        labelFgHex:    0xFFFFFF,
        numberFgHex:   0xE89C2A,
        accentHex:     0xE89C2A,
        headerBgHex:   0x1E5828,
        headerSubHex:  0x2F7A3C,
        teacherBgHex:  0x5BA968
    )

    /// プリセット一覧（UI用）
    static let presets: [(name: String, value: PosterDesign)] = [
        ("標準（青）", .default),
        ("桜",         .sakura),
        ("若葉",       .wakaba),
    ]

    // ── 表示用（SwiftUI / UIKit） ──
    var background: Color { Color(hex: backgroundHex) }
    var cardBg:     Color { Color(hex: cardBgHex) }
    var labelBg:    Color { Color(hex: labelBgHex) }
    var labelFg:    Color { Color(hex: labelFgHex) }
    var numberFg:   Color { Color(hex: numberFgHex) }
    var accent:     Color { Color(hex: accentHex) }
    var headerBg:   Color { Color(hex: headerBgHex) }
    var headerSub:  Color { Color(hex: headerSubHex) }
    var teacherBg:  Color { Color(hex: teacherBgHex) }
}

// MARK: - レイアウト定数（mm — make_poster.py と完全一致）

enum PosterLayout {
    static let marginXMm:   CGFloat = 15
    static let marginTopMm: CGFloat = 18
    static let marginBotMm: CGFloat = 12
    static let headerHMm:   CGFloat = 25
    static let gapColMm:    CGFloat = 5
    static let gapRowMm:    CGFloat = 6
    static let labelHMm:    CGFloat = 18

    /// mm → pt
    static func mm(_ v: CGFloat) -> CGFloat { v * 72.0 / 25.4 }
}

// MARK: - ポスター生成パラメータ

struct PosterConfig: Equatable, Codable {
    var paper: PaperSize = .A1
    var cols: Int = 6
    var rows: Int = 7
    var design: PosterDesign = .default
    /// 担任を含めるか
    var includeTeacher: Bool = true
    /// 担任セルに撮影写真を入れる（Phase 6 で本実装、現状は false）
    var useTeacherPhoto: Bool = false
}

// MARK: - Color ⇄ Hex（Codable & UIColor 変換）

extension Color {
    init(hex: UInt32) {
        let r = Double((hex >> 16) & 0xFF) / 255.0
        let g = Double((hex >> 8) & 0xFF) / 255.0
        let b = Double(hex & 0xFF) / 255.0
        self.init(.sRGB, red: r, green: g, blue: b, opacity: 1)
    }
}

extension UIColor {
    convenience init(hex: UInt32) {
        let r = CGFloat((hex >> 16) & 0xFF) / 255
        let g = CGFloat((hex >> 8) & 0xFF) / 255
        let b = CGFloat(hex & 0xFF) / 255
        self.init(red: r, green: g, blue: b, alpha: 1)
    }
    // SwiftUI Color → UIColor は標準 init(_ color: SwiftUI.Color) を使用。
}

// 描画用 UIColor 取得ヘルパ
extension PosterDesign {
    var backgroundUI: UIColor { UIColor(hex: backgroundHex) }
    var cardBgUI:     UIColor { UIColor(hex: cardBgHex) }
    var labelBgUI:    UIColor { UIColor(hex: labelBgHex) }
    var labelFgUI:    UIColor { UIColor(hex: labelFgHex) }
    var numberFgUI:   UIColor { UIColor(hex: numberFgHex) }
    var accentUI:     UIColor { UIColor(hex: accentHex) }
    var headerBgUI:   UIColor { UIColor(hex: headerBgHex) }
    var headerSubUI:  UIColor { UIColor(hex: headerSubHex) }
    var teacherBgUI:  UIColor { UIColor(hex: teacherBgHex) }
}

// MARK: - Color/Hex 相互変換（ColorPicker 用）

extension Color {
    /// SwiftUI Color → 0xRRGGBB の UInt32（α は無視）
    func hexUInt32() -> UInt32 {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        UIColor(self).getRed(&r, green: &g, blue: &b, alpha: &a)
        let R = UInt32(max(0, min(255, round(r * 255))))
        let G = UInt32(max(0, min(255, round(g * 255))))
        let B = UInt32(max(0, min(255, round(b * 255))))
        return (R << 16) | (G << 8) | B
    }
    /// 0xRRGGBB の UInt32 → "#RRGGBB" 文字列
    static func hexString(_ v: UInt32) -> String {
        String(format: "#%06X", v & 0xFFFFFF)
    }
}

// MARK: - design_config.json 互換書き出し
//
// 本体 (make_poster.py の load_design_config) が読めるキーで JSON 化。
// 配色をエクスポートして、本体側の出力も同じデザインに揃えられる。

extension PosterDesign {
    /// design_config.json として書ける辞書。キーは本体と同名。
    var designConfigJSON: [String: String] {
        [
            "background":  Color.hexString(backgroundHex),
            "card_bg":     Color.hexString(cardBgHex),
            "label_bg":    Color.hexString(labelBgHex),
            "label_fg":    Color.hexString(labelFgHex),
            "number_fg":   Color.hexString(numberFgHex),
            "accent":      Color.hexString(accentHex),
            "header_bg":   Color.hexString(headerBgHex),
            "header_sub":  Color.hexString(headerSubHex),
            "teacher_bg":  Color.hexString(teacherBgHex),
        ]
    }
}
