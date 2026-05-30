// swift-tools-version: 5.9

// ════════════════════════════════════════════════════════════════
//  ClassPhotoCapture — クラス写真キャプチャ
//  Swift Playgrounds（.swiftpm App 形式）。iPad / iPhone / Mac で動作。
//
//  撮影時にポスターと同じ比率(1.13)の顔枠ガイドを表示し、番号順に
//  連続撮影。元の全体写真＋枠情報(crop_overrides.csv)を ZIP で書き出し、
//  既存の crop_adjuster（Python）でそのまま読み込める。
// ════════════════════════════════════════════════════════════════

import PackageDescription
import AppleProductTypes

let package = Package(
    name: "ClassPhotoCapture",
    platforms: [
        .iOS("16.0")
    ],
    products: [
        .iOSApplication(
            name: "クラス写真キャプチャ",
            targets: ["AppModule"],
            bundleIdentifier: "com.ryonma.classphotocapture",
            teamIdentifier: "",
            displayVersion: "1.0",
            bundleVersion: "1",
            appIcon: .placeholder(icon: .camera),
            accentColor: .presetColor(.indigo),
            supportedDeviceFamilies: [
                .pad,
                .phone
            ],
            supportedInterfaceOrientations: [
                .portrait,
                .landscapeRight,
                .landscapeLeft,
                .portraitUpsideDown(.when(deviceFamilies: [.pad]))
            ],
            capabilities: [
                .camera(purposeString: "クラスの個人写真を撮影するためにカメラを使用します。"),
                .photoLibraryAdd(purposeString: "撮影した写真を「写真」アプリに書き出すために使用します。")
            ]
        )
    ],
    targets: [
        .executableTarget(
            name: "AppModule",
            path: "."
        )
    ]
)
