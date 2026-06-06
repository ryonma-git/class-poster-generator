import SwiftUI

// ════════════════════════════════════════════════════════════════
//  NumberKeypad — アプリ内蔵のテンキー（数字パッド）
//
//  人数などの数値を、自由記述ではなくテンキーで入力する。
//  上限・下限を明示し、範囲外は入力できない（クランプ）。
//  端末のハードキーボードに依存しないので、シミュレータでも
//  必ずテンキーが出る。
// ════════════════════════════════════════════════════════════════

/// テンキーで数値を入力するボタン（タップでポップオーバー表示）
struct NumberKeypadButton: View {
    let title: String
    let unit: String
    let range: ClosedRange<Int>
    @Binding var value: Int

    @State private var showPad = false

    var body: some View {
        Button {
            showPad = true
        } label: {
            HStack(spacing: 8) {
                Text(title)
                Spacer()
                Text("\(value)")
                    .font(.title3.bold().monospacedDigit())
                    .foregroundStyle(.primary)
                Text(unit).foregroundStyle(.secondary)
                Image(systemName: "square.grid.3x3.fill")
                    .font(.caption)
                    .foregroundStyle(brandColor)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .popover(isPresented: $showPad) {
            NumberKeypadPad(value: $value, range: range, unit: unit,
                            title: title, isPresented: $showPad)
                .frame(minWidth: 280, minHeight: 380)
        }
    }
}

/// ポップオーバー内のテンキー本体
private struct NumberKeypadPad: View {
    @Binding var value: Int
    let range: ClosedRange<Int>
    let unit: String
    let title: String
    @Binding var isPresented: Bool

    @State private var entry: String = ""

    private var current: Int { Int(entry) ?? 0 }
    private var overMax: Bool { current > range.upperBound }

    var body: some View {
        VStack(spacing: 14) {
            Text(title)
                .font(.headline)
            // 現在値表示
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(entry.isEmpty ? "0" : entry)
                    .font(.system(size: 44, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(overMax ? .red : .primary)
                Text(unit).font(.title3).foregroundStyle(.secondary)
            }
            // 範囲明示
            Text("\(range.lowerBound)〜\(range.upperBound)\(unit) で入力できます")
                .font(.caption)
                .foregroundStyle(overMax ? .red : .secondary)

            // テンキー 3x4
            let cols = [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())]
            LazyVGrid(columns: cols, spacing: 10) {
                ForEach(1...9, id: \.self) { n in keyButton("\(n)") { append(n) } }
                keyButton("⌫", role: .delete) { backspace() }
                keyButton("0") { append(0) }
                keyButton("OK", role: .confirm) { commit() }
            }
        }
        .padding(20)
        .onAppear { entry = "\(value)" }
    }

    @ViewBuilder
    private func keyButton(_ label: String,
                           role: KeyRole = .digit,
                           action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.title2.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 56)
                .background(role.bg, in: RoundedRectangle(cornerRadius: 12))
                .foregroundStyle(role.fg)
        }
        .buttonStyle(.plain)
    }

    private enum KeyRole {
        case digit, delete, confirm
        var bg: Color {
            switch self {
            case .digit:   return Color(.secondarySystemBackground)
            case .delete:  return Color(.tertiarySystemBackground)
            case .confirm: return brandColor
            }
        }
        var fg: Color { self == .confirm ? .white : .primary }
    }

    private func append(_ n: Int) {
        // 先頭の 0 は無視。最大桁数は上限の桁数まで。
        var s = entry == "0" ? "" : entry
        s += "\(n)"
        if let v = Int(s), v <= range.upperBound * 10 {  // 入力途中は緩め、commitでクランプ
            entry = s
        }
    }
    private func backspace() {
        if !entry.isEmpty { entry.removeLast() }
    }
    private func commit() {
        let v = min(range.upperBound, max(range.lowerBound, current))
        value = v
        isPresented = false
    }
}
