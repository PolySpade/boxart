import XCTest
@testable import BoxArtCore

final class NormalizationTests: XCTestCase {
    func testLivePSPIndexAndCover() async throws {
        guard ProcessInfo.processInfo.environment["BOXART_LIVE_TEST"] == "1" else { throw XCTSkip("Opt-in network test") }
        let service = ArtworkService()
        var game = Game(url: URL(fileURLWithPath: "/PSP/Ridge_Racer_2_EUR_PSP-pSyPSP.cso"), code: nil)
        let name = try await service.normalizedName(for: game)
        XCTAssertEqual(name, "Ridge Racer 2 (Europe) (En,Fr,De,Es,It)")
        game.lookupName = name
        let artwork = try await service.artwork(for: game)
        XCTAssertNotNil(artwork)
    }
    func testSceneNamesAndRegions() {
        let names = ["Ridge Racer 2 (Europe) (En,Fr,De,Es,It)", "Ridge Racer 2 (Europe, Australia) (En,Fr,De,Es,It)", "Ridge Racer (Europe)"]
        XCTAssertEqual(FilenameNormalization.match("Ridge_Racer_2_EUR_PSP-pSyPSP", names: names), names[0])
        XCTAssertEqual(FilenameNormalization.match("Loco_Roco_USA_PSP-pSyPSP", names: ["LocoRoco (USA) (En,Ja)"]), "LocoRoco (USA) (En,Ja)")
        XCTAssertEqual(FilenameNormalization.match("BURNOUT DOMINATOR - ULUS10236", names: ["Burnout Dominator (USA)"]), "Burnout Dominator (USA)")
        XCTAssertNil(FilenameNormalization.match("BurnOut_USA_MULTi5_PROPER_READNFO_PSP-MUPSP", names: ["Burnout Legends (USA)", "Burnout Dominator (USA)"]))
        XCTAssertNil(FilenameNormalization.match("Game_USA_PSP-team", names: ["Game (USA) (v1)", "Game (USA) (v2)"]))
    }
    func testRenamePreservesContentsAndRejectsCollisionsAndReferences() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let rom = folder.appendingPathComponent("old.cso")
        let bytes = Data([1,2,3,4]); try bytes.write(to: rom)
        let renamed = try FilenameNormalization.rename(rom, to: "Game (USA)")
        XCTAssertEqual(renamed.lastPathComponent, "Game (USA).cso")
        XCTAssertEqual(try Data(contentsOf: renamed), bytes)
        XCTAssertFalse(FileManager.default.fileExists(atPath: rom.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: folder.appendingPathComponent(".boxart-renames.jsonl").path))
        try bytes.write(to: rom)
        XCTAssertThrowsError(try FilenameNormalization.rename(rom, to: "Game (USA)"))
        XCTAssertThrowsError(try FilenameNormalization.rename(rom, to: "../unsafe"))
        try Data().write(to: folder.appendingPathComponent("games.m3u"))
        XCTAssertThrowsError(try FilenameNormalization.rename(rom, to: "Other"))
        XCTAssertEqual(try Data(contentsOf: rom), bytes)
    }
}
