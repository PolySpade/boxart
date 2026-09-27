// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "BoxArt", platforms: [.macOS(.v14)], products: [.executable(name: "BoxArt", targets: ["BoxArt"])], targets: [.target(name: "BoxArtCore"), .executableTarget(name: "BoxArt", dependencies: ["BoxArtCore"]), .testTarget(name: "BoxArtCoreTests", dependencies: ["BoxArtCore", "BoxArt"])])
