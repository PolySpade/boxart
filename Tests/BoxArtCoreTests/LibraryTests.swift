import XCTest
import AppKit
import ImageIO
@testable import BoxArtCore

final class LibraryTests: XCTestCase {
    var root: URL!
    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }
    override func tearDownWithError() throws { try FileManager.default.removeItem(at: root) }
    func rom(_ name: String = "Mario (USA).nds", code: String = "ASME") throws -> URL {
        let url = root.appendingPathComponent(name)
        var data = Data(repeating: 0, count: 512); data.replaceSubrange(12..<16, with: code.utf8)
        try data.write(to: url); return url
    }
    func image() -> Data {
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 512, pixelsHigh: 460, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        return bitmap.representation(using: .png, properties: [:])!
    }
    func testScanReadsHeadersAndIgnoresAppleDouble() throws {
        let file = try rom(); _ = try rom("._Mario.nds"); _ = try rom("Notes.txt")
        let games = try Library.scan(root)
        XCTAssertEqual(games.count, 1); XCTAssertEqual(games.first?.code, "ASME"); XCTAssertEqual(games.first?.url.resolvingSymlinksInPath(), file.resolvingSymlinksInPath())
    }
    func testLiveProvider() async throws {
        guard ProcessInfo.processInfo.environment["BOXART_LIVE_TEST"] == "1" else { throw XCTSkip("Opt-in network test") }
        let file = try rom(code: "B6ZE")
        let result = try await ArtworkService().artwork(for: Game(url: file, code: "B6ZE"))
        XCTAssertNotNil(result)
        if let result { _ = try Library.save(result.0, rom: file, settings: ExportSettings()) }
    }
    func testInvalidHeaderFallsBack() throws {
        let file = root.appendingPathComponent("Homebrew.nds"); try Data([0, 1]).write(to: file)
        XCTAssertNil(try Library.gameCode(file))
    }
    func testProfileNamingPreservesExactStem() throws {
        let file = try rom(" Mario.nds")
        var settings = ExportSettings()
        XCTAssertEqual(try settings.output(for: file).lastPathComponent, " Mario.png")
        XCTAssertEqual(try settings.output(for: file).deletingLastPathComponent().lastPathComponent, "Imgs")
        settings.profile = .twilight
        XCTAssertThrowsError(try settings.output(for: file))
        settings.destination = root
        XCTAssertEqual(try settings.output(for: file).lastPathComponent, " Mario.nds.png")
    }
    func testResizeAndNeverOverwrite() throws {
        let file = try rom(); let original = try Data(contentsOf: file)
        let settings = ExportSettings()
        let output = try Library.save(image(), rom: file, settings: settings)
        let data = try Data(contentsOf: output)
        let source = CGImageSourceCreateWithData(data as CFData, nil)!
        let decoded = CGImageSourceCreateImageAtIndex(source, 0, nil)!
        XCTAssertEqual(decoded.width, 512); XCTAssertEqual(decoded.height, 460)
        XCTAssertThrowsError(try Library.save(image(), rom: file, settings: settings))
        XCTAssertEqual(try Data(contentsOf: output), data)
        XCTAssertEqual(try Data(contentsOf: file), original)
    }
    func testJPEGExistingAndTwilightDimensions() throws {
        let file = try rom(); var settings = ExportSettings()
        let target = try settings.output(for: file).deletingPathExtension().appendingPathExtension("jpg")
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try image().write(to: target)
        XCTAssertEqual(try Library.existing(for: file, settings: settings), target)
        XCTAssertThrowsError(try Library.save(image(), rom: file, settings: settings))
        settings.profile = .twilight; settings.destination = root
        let data = try Library.render(image(), settings: settings)
        let source = CGImageSourceCreateWithData(data as CFData, nil)!
        let decoded = CGImageSourceCreateImageAtIndex(source, 0, nil)!
        XCTAssertLessThanOrEqual(decoded.width, 128); XCTAssertLessThanOrEqual(decoded.height, 115)
    }
    func testInvalidImageAndMissingCard() throws {
        let file = try rom()
        XCTAssertThrowsError(try Library.save(Data("bad".utf8), rom: file, settings: ExportSettings()))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("Imgs").path))
        try FileManager.default.removeItem(at: file)
        XCTAssertThrowsError(try Library.save(image(), rom: file, settings: ExportSettings()))
    }
}
