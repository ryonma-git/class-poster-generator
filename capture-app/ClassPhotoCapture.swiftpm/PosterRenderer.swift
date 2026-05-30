import Foundation
import UIKit
import CoreGraphics
import PDFKit

// ════════════════════════════════════════════════════════════════
//  PosterRenderer — クラス個人写真ポスター PDF 生成
//
//  make_poster.py の generate_poster() をベクター（CoreGraphics）で移植。
//  本体は PIL でラスター化してから PDF に貼っていたが、こちらは
//  ヘッダー・カード・テキストは全てベクター描画、写真のみラスタ。
//  → ファイルサイズが小さく、印刷時の文字くっきり。
//
//  PDF 座標系: pt 単位、原点は左下（PDFKit/CoreGraphics標準）。
//  本実装では描画前に Y軸を反転して「左上原点・mm/pt座標」で書ける
//  ようにする（make_poster.py と頭の中で対応を取りやすくするため）。
// ════════════════════════════════════════════════════════════════

enum PosterRenderError: Error {
    case noStudents
}

enum PosterRenderer {

    /// メインエントリ。指定パラメータで PDF を生成して URL を返す。
    static func renderPDF(group: GroupConfig,
                          roster: Roster,
                          shots: [StudentShot],
                          config: PosterConfig) throws -> URL {
        // 児童（番号順）＋担任（番号順）の順で並べる
        let students = shots.filter { $0.kind == .student }.sorted { $0.number < $1.number }
        let teachers = config.includeTeacher
            ? shots.filter { $0.kind == .teacher }.sorted { $0.number < $1.number }
            : []
        guard !students.isEmpty else { throw PosterRenderError.noStudents }

        // 出力先（一時ファイル）
        let fm = FileManager.default
        let stamp = Int(Date().timeIntervalSince1970)
        let fileName = "\(group.fileSafeID)_ポスター_\(config.paper.rawValue)_\(stamp).pdf"
        let url = fm.temporaryDirectory.appendingPathComponent(fileName)
        try? fm.removeItem(at: url)

        // PDF ページサイズ
        let pageRect = CGRect(origin: .zero, size: config.paper.sizePt)
        let renderer = UIGraphicsPDFRenderer(bounds: pageRect)

        let data = renderer.pdfData { ctx in
            ctx.beginPage()
            let cg = ctx.cgContext

            // 原点を左上に移動して y を反転（mm 座標で考えやすくする）
            cg.saveGState()
            cg.translateBy(x: 0, y: pageRect.height)
            cg.scaleBy(x: 1, y: -1)

            drawPage(
                cg: cg,
                pageSize: pageRect.size,
                group: group,
                roster: roster,
                students: students,
                teachers: teachers,
                config: config
            )

            cg.restoreGState()
        }
        try data.write(to: url)
        return url
    }

    // MARK: - ページ全体

    private static func drawPage(cg: CGContext,
                                 pageSize: CGSize,
                                 group: GroupConfig,
                                 roster: Roster,
                                 students: [StudentShot],
                                 teachers: [StudentShot],
                                 config: PosterConfig) {
        let mm = PosterLayout.mm

        // ── 背景 ──
        cg.setFillColor(config.design.backgroundUI.cgColor)
        cg.fill(CGRect(origin: .zero, size: pageSize))

        // 薄い方眼（本体準拠：40px相当を pt に変換）
        // pt 単位で 40px / 150dpi * 72pt = 19.2pt おき
        let gridPt: CGFloat = 19.2
        let gridColor = UIColor(hex: 0xDCE4EE).withAlphaComponent(0.6).cgColor
        cg.setStrokeColor(gridColor)
        cg.setLineWidth(0.4)
        cg.beginPath()
        var x: CGFloat = 0
        while x < pageSize.width {
            cg.move(to: CGPoint(x: x, y: 0))
            cg.addLine(to: CGPoint(x: x, y: pageSize.height))
            x += gridPt
        }
        var y: CGFloat = 0
        while y < pageSize.height {
            cg.move(to: CGPoint(x: 0, y: y))
            cg.addLine(to: CGPoint(x: pageSize.width, y: y))
            y += gridPt
        }
        cg.strokePath()

        // ── レイアウト計算 ──
        let mx = mm(PosterLayout.marginXMm)
        let mt = mm(PosterLayout.marginTopMm)
        let mb = mm(PosterLayout.marginBotMm)
        let hh = mm(PosterLayout.headerHMm)
        let gc = mm(PosterLayout.gapColMm)
        let gr = mm(PosterLayout.gapRowMm)
        let lh = mm(PosterLayout.labelHMm)

        let totalCells = students.count + teachers.count
        let useCols = max(1, config.cols)
        let autoRows = Int(ceil(Double(totalCells) / Double(useCols)))
        let useRows = max(autoRows, max(1, config.rows))

        let cw = (pageSize.width - 2 * mx - CGFloat(useCols - 1) * gc) / CGFloat(useCols)
        let availableH = (pageSize.height - mt - hh - mb) - CGFloat(useRows - 1) * gr
        let ch = availableH / CGFloat(useRows)

        // ── ヘッダー ──
        drawHeader(cg: cg, pageSize: pageSize, marginX: mx, marginTop: mt, headerH: hh,
                   total: students.count, design: config.design, group: group)

        // ── グリッド ──
        let gt = mt + hh + mm(2)  // ヘッダーの少し下
        let cells: [(StudentShot, MemberRole)] = teachers.map { ($0, .teacher) }
                                               + students.map { ($0, .student) }

        for (idx, (shot, role)) in cells.enumerated() {
            let col = idx % useCols
            let row = idx / useCols
            let cellX = mx + CGFloat(col) * (cw + gc)
            let cellY = gt + CGFloat(row) * (ch + gr)
            let rect = CGRect(x: cellX, y: cellY, width: cw, height: ch)

            switch role {
            case .student:
                let member = roster.studentByNumber(shot.number)
                drawStudentCell(cg: cg, rect: rect, labelH: lh,
                                shot: shot, member: member,
                                roster: roster, design: config.design)
            case .teacher:
                let member = roster.teacherByNumber(shot.number)
                drawTeacherCell(cg: cg, rect: rect, labelH: lh,
                                shot: shot, member: member,
                                roster: roster, design: config.design,
                                useTeacherPhoto: config.useTeacherPhoto)
            }
        }

        // ── フッター ──
        let footerText = "\(group.displayName)  \(group.displaySubtitle)"
        drawText(cg: cg, text: footerText,
                 rect: CGRect(x: 0, y: pageSize.height - mm(8),
                              width: pageSize.width, height: mm(6)),
                 fontSize: mm(2.5),
                 color: UIColor(hex: 0xA0AAB9),
                 alignment: .center, verticalAlign: .middle)
    }

    // MARK: - ヘッダー

    private static func drawHeader(cg: CGContext,
                                   pageSize: CGSize,
                                   marginX: CGFloat,
                                   marginTop: CGFloat,
                                   headerH: CGFloat,
                                   total: Int,
                                   design: PosterDesign,
                                   group: GroupConfig) {
        let mm = PosterLayout.mm
        let top = marginTop - mm(1.4)
        let accentH = max(2.5, headerH / 14.0)
        let mainRect = CGRect(x: 0, y: top, width: pageSize.width, height: headerH)

        // 主帯
        cg.setFillColor(design.headerBgUI.cgColor)
        cg.fill(mainRect)
        // アクセント帯（下端）
        cg.setFillColor(design.accentUI.cgColor)
        cg.fill(CGRect(x: 0, y: top + headerH - accentH,
                       width: pageSize.width, height: accentH))
        // 左の副帯
        cg.setFillColor(design.headerSubUI.cgColor)
        cg.fill(CGRect(x: 0, y: top,
                       width: pageSize.width * 0.28,
                       height: headerH - accentH))

        // タイトル（白）
        let title = "\(group.displayName)　\(group.displaySubtitle)"
        let titleRect = CGRect(
            x: pageSize.width * 0.32,
            y: top,
            width: pageSize.width * 0.55,
            height: headerH - accentH
        )
        drawText(cg: cg, text: title, rect: titleRect,
                 fontSize: headerH * 0.38, color: .white,
                 alignment: .left, verticalAlign: .middle)

        // 右上の人数
        let countRect = CGRect(
            x: pageSize.width * 0.6,
            y: top,
            width: pageSize.width - marginX - (pageSize.width * 0.6),
            height: headerH - accentH
        )
        drawText(cg: cg, text: "全\(total)名", rect: countRect,
                 fontSize: headerH * 0.24, color: design.accentUI,
                 alignment: .right, verticalAlign: .middle,
                 bold: true)
    }

    // MARK: - 児童セル

    private static func drawStudentCell(cg: CGContext,
                                        rect: CGRect,
                                        labelH: CGFloat,
                                        shot: StudentShot,
                                        member: Member?,
                                        roster: Roster,
                                        design: PosterDesign) {
        let r: CGFloat = PosterLayout.mm(2.5)  // 角丸
        let photoH = rect.height - labelH
        let photoRect = CGRect(x: rect.minX, y: rect.minY, width: rect.width, height: photoH)
        let labelRect = CGRect(x: rect.minX, y: rect.minY + photoH, width: rect.width, height: labelH)

        // ── カード背景（角丸） ──
        let bgPath = UIBezierPath(roundedRect: rect, cornerRadius: r)
        cg.saveGState()
        cg.setFillColor(design.cardBgUI.cgColor)
        cg.addPath(bgPath.cgPath); cg.fillPath()
        cg.restoreGState()

        // ── 写真エリア（上部、角丸はtopのみ） ──
        cg.saveGState()
        let photoClip = UIBezierPath(
            roundedRect: photoRect,
            byRoundingCorners: [.topLeft, .topRight],
            cornerRadii: CGSize(width: r, height: r))
        cg.addPath(photoClip.cgPath)
        cg.clip()

        if shot.status == .captured, let img = shot.image {
            drawCroppedPhoto(cg: cg, image: img, cropRect: shot.cropRect, into: photoRect)
        } else {
            drawPlaceholder(cg: cg, rect: photoRect, absent: shot.status == .absent)
        }
        cg.restoreGState()

        // ── ラベル（下部、角丸はbottomのみ） ──
        cg.saveGState()
        let labelClip = UIBezierPath(
            roundedRect: labelRect,
            byRoundingCorners: [.bottomLeft, .bottomRight],
            cornerRadii: CGSize(width: r, height: r))
        cg.addPath(labelClip.cgPath)
        cg.clip()
        cg.setFillColor(design.labelBgUI.cgColor)
        cg.fill(labelRect)
        cg.restoreGState()

        // ラベル上端のアクセント線
        cg.setStrokeColor(design.accentUI.withAlphaComponent(0.78).cgColor)
        cg.setLineWidth(0.8)
        cg.beginPath()
        cg.move(to: CGPoint(x: labelRect.minX, y: labelRect.minY))
        cg.addLine(to: CGPoint(x: labelRect.maxX, y: labelRect.minY))
        cg.strokePath()

        // ── 番号 ──
        let pad = rect.width * 0.05
        let numStr = String(format: "%02d", shot.number)
        let numFontSize = labelH * 0.32
        let numUI = makeFont(size: numFontSize, bold: true)
        let numWidth = textWidth(numStr, font: numUI)
        let numRect = CGRect(x: labelRect.minX + pad,
                             y: labelRect.minY,
                             width: numWidth,
                             height: labelH)
        drawText(cg: cg, text: numStr, rect: numRect,
                 fontSize: numFontSize, color: design.numberFgUI,
                 alignment: .left, verticalAlign: .middle, bold: true)

        // ── 名前 ──
        let displayName = member.map { roster.displayName(for: $0) } ?? ""
        let nameX = labelRect.minX + pad + numWidth + pad
        let availW = labelRect.maxX - pad - nameX
        let maxNameFontSize = labelH * 0.55
        let nameFont = fitFont(text: displayName.isEmpty ? "—" : displayName,
                               maxWidth: availW, maxSize: maxNameFontSize, minSize: maxNameFontSize * 0.5)
        let nameRect = CGRect(x: nameX, y: labelRect.minY, width: availW, height: labelH)
        drawText(cg: cg, text: displayName.isEmpty ? "" : displayName,
                 rect: nameRect, fontSize: nameFont.pointSize,
                 color: design.labelFgUI,
                 alignment: .left, verticalAlign: .middle)
    }

    // MARK: - 担任セル

    private static func drawTeacherCell(cg: CGContext,
                                        rect: CGRect,
                                        labelH: CGFloat,
                                        shot: StudentShot,
                                        member: Member?,
                                        roster: Roster,
                                        design: PosterDesign,
                                        useTeacherPhoto: Bool) {
        let r: CGFloat = PosterLayout.mm(2.5)
        let bgPath = UIBezierPath(roundedRect: rect, cornerRadius: r)
        cg.saveGState()
        cg.setFillColor(design.teacherBgUI.cgColor)
        cg.addPath(bgPath.cgPath); cg.fillPath()
        cg.restoreGState()

        // Phase 6 で写真ありに分岐するためのフック（現在は常に文字のみ）
        let _ = useTeacherPhoto

        // 「担　任」（小さく上）
        let topRect = CGRect(x: rect.minX, y: rect.minY + rect.height * 0.18,
                             width: rect.width, height: rect.height * 0.20)
        drawText(cg: cg, text: "担　任", rect: topRect,
                 fontSize: rect.height * 0.11,
                 color: design.accentUI.withAlphaComponent(0.86),
                 alignment: .center, verticalAlign: .middle, bold: true)

        // 担任名
        let name = member.map { roster.displayName(for: $0) } ?? ""
        let nameRect = CGRect(x: rect.minX, y: rect.minY + rect.height * 0.42,
                              width: rect.width, height: rect.height * 0.28)
        let nameFont = fitFont(text: name.isEmpty ? "（担任名未設定）" : name,
                               maxWidth: rect.width * 0.84,
                               maxSize: rect.height * 0.13,
                               minSize: rect.height * 0.07)
        drawText(cg: cg, text: name.isEmpty ? "（担任名未設定）" : name,
                 rect: nameRect, fontSize: nameFont.pointSize,
                 color: .white,
                 alignment: .center, verticalAlign: .middle, bold: !name.isEmpty)

        // 下のアクセントバー
        let bar = CGRect(x: rect.minX + rect.width * 0.2,
                         y: rect.minY + rect.height - PosterLayout.mm(1.2),
                         width: rect.width * 0.6,
                         height: PosterLayout.mm(0.8))
        cg.setFillColor(design.accentUI.withAlphaComponent(0.78).cgColor)
        cg.fill(bar)
    }

    // MARK: - 写真描画

    /// 撮影写真をクロップ枠（正規化矩形）でカットしてセルに収める
    private static func drawCroppedPhoto(cg: CGContext,
                                         image: UIImage,
                                         cropRect: CGRect?,
                                         into dst: CGRect) {
        guard let cgImage = image.cgImage else { return }
        let iw = CGFloat(cgImage.width)
        let ih = CGFloat(cgImage.height)

        // 切り抜き矩形（画像ピクセル座標）
        let srcRect: CGRect
        if let n = cropRect, n.width > 0, n.height > 0 {
            srcRect = CGRect(
                x: max(0, n.minX) * iw,
                y: max(0, n.minY) * ih,
                width: min(1, n.width) * iw,
                height: min(1, n.height) * ih
            ).integral
        } else {
            // クロップ未設定: セル比率でセンタークロップ
            let aspect = dst.width / dst.height
            if iw / ih > aspect {
                let w = ih * aspect
                srcRect = CGRect(x: (iw - w) / 2, y: 0, width: w, height: ih)
            } else {
                let h = iw / aspect
                srcRect = CGRect(x: 0, y: (ih - h) / 2, width: iw, height: h)
            }
        }

        guard let cropped = cgImage.cropping(to: srcRect) else { return }

        // CoreGraphics の画像描画は y反転して描く必要がある（今コンテキストはY反転中なので、
        // 画像描画時は一時的に元のY軸方向に戻す）
        cg.saveGState()
        cg.translateBy(x: dst.minX, y: dst.minY + dst.height)
        cg.scaleBy(x: 1, y: -1)
        cg.draw(cropped, in: CGRect(origin: .zero, size: dst.size))
        cg.restoreGState()
    }

    /// 写真がない場合のプレースホルダ
    private static func drawPlaceholder(cg: CGContext, rect: CGRect, absent: Bool) {
        cg.setFillColor(UIColor(hex: 0xE6ECF3).cgColor)
        cg.fill(rect)
        let icon = absent ? "person.slash" : "camera"
        let txt = absent ? "欠席" : "未撮影"
        if let img = UIImage(systemName: icon)?
            .withTintColor(UIColor(hex: 0xA0AAB9), renderingMode: .alwaysOriginal) {
            let iconSize: CGFloat = min(rect.width, rect.height) * 0.18
            let iconRect = CGRect(
                x: rect.midX - iconSize/2,
                y: rect.minY + rect.height * 0.35 - iconSize/2,
                width: iconSize, height: iconSize)
            cg.saveGState()
            cg.translateBy(x: iconRect.minX, y: iconRect.minY + iconRect.height)
            cg.scaleBy(x: 1, y: -1)
            if let ci = img.cgImage {
                cg.draw(ci, in: CGRect(origin: .zero, size: iconRect.size))
            }
            cg.restoreGState()
        }
        let textRect = CGRect(x: rect.minX, y: rect.minY + rect.height * 0.55,
                              width: rect.width, height: rect.height * 0.2)
        drawText(cg: cg, text: txt, rect: textRect,
                 fontSize: min(rect.width, rect.height) * 0.10,
                 color: UIColor(hex: 0x8A95A6),
                 alignment: .center, verticalAlign: .top)
    }

    // MARK: - テキスト描画

    enum HAlign { case left, center, right }
    enum VAlign { case top, middle, bottom }

    /// pt サイズで「ヒラギノ丸ゴ → 通常ヒラギノ → システム」の順にフォール
    /// バックするフォントを返す。bold=true なら太め (W6) を優先。
    private static func makeFont(size: CGFloat, bold: Bool = false) -> UIFont {
        let weight: UIFont.Weight = bold ? .bold : .regular
        // ヒラギノ丸ゴ ProN — 子ども向け定番。本体（make_poster.py）と一致。
        let maruName = bold ? "HiraMaruProN-W6" : "HiraMaruProN-W4"
        if let f = UIFont(name: maruName, size: size) { return f }
        // 通常のヒラギノ
        let sansName = bold ? "HiraginoSans-W6" : "HiraginoSans-W3"
        if let f = UIFont(name: sansName, size: size) { return f }
        // フォールバック
        return UIFont.systemFont(ofSize: size, weight: weight)
    }

    /// 与えられた幅に収まる最大フォントサイズを返す
    private static func fitFont(text: String,
                                maxWidth: CGFloat,
                                maxSize: CGFloat,
                                minSize: CGFloat,
                                bold: Bool = false) -> UIFont {
        guard !text.isEmpty else { return makeFont(size: maxSize, bold: bold) }
        var size = maxSize
        while size > minSize {
            let f = makeFont(size: size, bold: bold)
            if textWidth(text, font: f) <= maxWidth { return f }
            size -= 0.5
        }
        return makeFont(size: minSize, bold: bold)
    }

    private static func textWidth(_ s: String, font: UIFont) -> CGFloat {
        (s as NSString).size(withAttributes: [.font: font]).width
    }

    /// Y反転コンテキスト上でも普通に読める向きで文字を描く
    private static func drawText(cg: CGContext,
                                 text: String,
                                 rect: CGRect,
                                 fontSize: CGFloat,
                                 color: UIColor,
                                 alignment: HAlign,
                                 verticalAlign: VAlign,
                                 bold: Bool = false) {
        guard !text.isEmpty else { return }
        let font = makeFont(size: fontSize, bold: bold)
        let attrs: [NSAttributedString.Key: Any] = [
            .font: font,
            .foregroundColor: color
        ]
        let str = NSAttributedString(string: text, attributes: attrs)
        let textSize = str.size()

        let x: CGFloat
        switch alignment {
        case .left:   x = rect.minX
        case .center: x = rect.midX - textSize.width / 2
        case .right:  x = rect.maxX - textSize.width
        }
        let y: CGFloat
        switch verticalAlign {
        case .top:    y = rect.minY
        case .middle: y = rect.midY - textSize.height / 2
        case .bottom: y = rect.maxY - textSize.height
        }

        // Y反転中のコンテキストでテキストを正しい向きに描く
        cg.saveGState()
        cg.translateBy(x: x, y: y + textSize.height)
        cg.scaleBy(x: 1, y: -1)
        str.draw(at: .zero)
        cg.restoreGState()
    }
}
