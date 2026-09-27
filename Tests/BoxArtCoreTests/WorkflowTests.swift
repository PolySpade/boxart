import XCTest
@testable import BoxArt
import BoxArtCore
final class WorkflowTests: XCTestCase {
    @MainActor func testDownloadAndSaveAllEndToEnd() async throws {
        guard ProcessInfo.processInfo.environment["BOXART_LIVE_TEST"] == "1" else { throw XCTSkip("Opt-in network test") }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let rom = root.appendingPathComponent("Oddly named game.nds")
        var header = Data(repeating: 0, count: 512); header.replaceSubrange(12..<16, with: Data("B6ZE".utf8)); try header.write(to: rom)
        let model = LibraryModel(); model.games = [Game(url: rom, code: "B6ZE")]
        model.downloadAndSaveAll()
        let deadline = Date().addingTimeInterval(45)
        while model.busy && Date() < deadline { try await Task.sleep(nanoseconds: 50_000_000) }
        XCTAssertFalse(model.busy); XCTAssertEqual(model.saved, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("Imgs/Oddly named game.png").path))
        XCTAssertEqual(try Data(contentsOf: rom), header)
    }
}
