import XCTest
@testable import BoxArtCore
final class RetroArchTests: XCTestCase {
    func testSuggestedRetroArchDirectoryFollowsROMRoot() {
        XCTAssertEqual(ExportSettings.suggestedRetroArchDirectory(for: URL(fileURLWithPath: "/Volumes/ExampleCard/Roms/NDS")).path, "/Volumes/ExampleCard/RetroArch/thumbnails")
        XCTAssertEqual(ExportSettings.suggestedRetroArchDirectory(for: URL(fileURLWithPath: "/tmp/ExampleLibrary/Roms")).path, "/tmp/ExampleLibrary/RetroArch/thumbnails")
    }
    func testSystemDetection() {
        XCTAssertEqual(GameSystem.infer(URL(fileURLWithPath: "/Roms/GBA/Game.gba")), .gba)
        XCTAssertEqual(GameSystem.infer(URL(fileURLWithPath: "/Roms/PS/Game.chd")), .ps)
        XCTAssertEqual(GameSystem.infer(URL(fileURLWithPath: "/Roms/PSP/Game.iso")), .psp)
        XCTAssertEqual(GameSystem.infer(URL(fileURLWithPath: "/Roms/SFC/Game.zip")), .snes)
        XCTAssertNil(GameSystem.infer(URL(fileURLWithPath: "/Roms/Unknown/Game.chd")))
    }
    func testPlaylistLabelsAndDevicePaths() throws {
        let game = Game(url: URL(fileURLWithPath: "/Volumes/DS/Roms/GBA/Metroid.gba"), code: nil)
        let json = #"{"items":[{"path":"/mnt/sdcard/Roms/GBA/Metroid.gba","label":"Metroid: Zero Mission (USA)","db_name":"Nintendo - Game Boy Advance.lpl"}]}"#
        let matches = try Playlist.match(data: Data(json.utf8), playlistName: "Favorites.lpl", games: [game])
        var settings = ExportSettings(); settings.profile = .retroarch; settings.destination = URL(fileURLWithPath: "/tmp/thumbnails"); settings.identities = matches
        XCTAssertEqual(try settings.output(for: game.url).path, "/tmp/thumbnails/Nintendo - Game Boy Advance/Named_Boxarts/Metroid_ Zero Mission (USA).png")
    }
    func testAmbiguousPlaylistMappingSkipped() throws {
        let games = ["/a/Game.gba", "/b/Game.gba"].map { Game(url: URL(fileURLWithPath: $0), code: nil) }
        let json = #"{"items":[{"path":"/device/Game.gba","label":"Game","db_name":"Nintendo - Game Boy Advance.lpl"}]}"#
        XCTAssertTrue(try Playlist.match(data: Data(json.utf8), playlistName: "GBA.lpl", games: games).isEmpty)
    }
    func testPlaylistCannotEscapeDestination() {
        let game = Game(url: URL(fileURLWithPath: "/a/Game.gba"), code: nil)
        let json = #"{"items":[{"path":"/device/Game.gba","label":"Game","db_name":"../../escape.lpl"}]}"#
        XCTAssertThrowsError(try Playlist.match(data: Data(json.utf8), playlistName: "GBA.lpl", games: [game]))
    }
    func testLiveGBAAndPSProviders() async throws {
        guard ProcessInfo.processInfo.environment["BOXART_LIVE_TEST"] == "1" else { throw XCTSkip("Opt-in network test") }
        for path in ["/Roms/GBA/Metroid - Zero Mission (USA).gba", "/Roms/PS/Final Fantasy VII (USA) (Disc 1).chd"] {
            let result = try await ArtworkService().artwork(for: Game(url: URL(fileURLWithPath: path), code: nil))
            XCTAssertNotNil(result, path)
        }
    }
}
