import Foundation

public enum GameSystem: String, CaseIterable, Identifiable {
    case nds = "Nintendo - Nintendo DS", gba = "Nintendo - Game Boy Advance", gb = "Nintendo - Game Boy", gbc = "Nintendo - Game Boy Color"
    case fds = "Nintendo - Family Computer Disk System"
    case nes = "Nintendo - Nintendo Entertainment System", snes = "Nintendo - Super Nintendo Entertainment System", n64 = "Nintendo - Nintendo 64"
    case ps = "Sony - PlayStation", psp = "Sony - PlayStation Portable", genesis = "Sega - Mega Drive - Genesis", sms = "Sega - Master System - Mark III", gg = "Sega - Game Gear", dreamcast = "Sega - Dreamcast", saturn = "Sega - Saturn", segacd = "Sega - Mega-CD - Sega CD", sega32x = "Sega - 32X"
    case ngpc = "SNK - Neo Geo Pocket Color", wsc = "Bandai - WonderSwan Color"
    case pce = "NEC - PC Engine - TurboGrafx 16", atari = "Atari - 2600", lynx = "Atari - Lynx", ngp = "SNK - Neo Geo Pocket", ws = "Bandai - WonderSwan"
    public var id: String { rawValue }
    public var repository: String { rawValue.replacingOccurrences(of: " ", with: "_") }
    public static func infer(_ url: URL) -> GameSystem? {
        let extensions: [String: GameSystem] = ["nds": .nds, "dsi": .nds, "gba": .gba, "gb": .gb, "gbc": .gbc, "nes": .nes, "fds": .fds, "sfc": .snes, "smc": .snes, "z64": .n64, "n64": .n64, "v64": .n64, "gen": .genesis, "md": .genesis, "sms": .sms, "gg": .gg, "pce": .pce, "a26": .atari, "lnx": .lynx, "ngp": .ngp, "ngc": .ngpc, "ws": .ws, "wsc": .wsc, "32x": .sega32x]
        if let result = extensions[url.pathExtension.lowercased()] { return result }
        guard ["zip", "7z", "chd", "cue", "pbp", "iso", "cso", "m3u", "bin", "gdi"].contains(url.pathExtension.lowercased()) else { return nil }
        let folders: [String: GameSystem] = ["NDS": .nds, "GBA": .gba, "GB": .gb, "GBC": .gbc, "FC": .nes, "FDS": .fds, "SFC": .snes, "SNES": .snes, "N64": .n64, "PS": .ps, "PS1": .ps, "PSX": .ps, "PSP": .psp, "MD": .genesis, "SMS": .sms, "GG": .gg, "DREAMCAST": .dreamcast, "SATURN": .saturn, "MDCD": .segacd, "SEGA32X": .sega32x, "PCE": .pce, "A2600": .atari, "LYNX": .lynx, "NGP": .ngp, "WS": .ws]
        for part in url.deletingLastPathComponent().pathComponents.reversed() {
            if let result = folders[part.uppercased()] { return result }
            if let result = allCases.first(where: { $0.rawValue.caseInsensitiveCompare(part) == .orderedSame }) { return result }
        }
        return nil
    }
}
public struct PlaylistIdentity {
    public let label: String
    public let database: String
    public init(label: String, database: String) { self.label = label; self.database = database }
    public static func safeName(_ text: String) -> String {
        text.replacingOccurrences(of: #"[&*/:`<>?\\|\"]"#, with: "_", options: .regularExpression)
    }
}
public enum Playlist {
    struct Document: Decodable { let items: [Item] }
    struct Item: Decodable { let path: String; let label: String; let db_name: String? }
    public static func match(data: Data, playlistName: String, games: [Game]) throws -> [String: PlaylistIdentity] {
        let doc = try JSONDecoder().decode(Document.self, from: data)
        var result: [String: PlaylistIdentity] = [:]
        for item in doc.items {
            let path = item.path.replacingOccurrences(of: "\\", with: "/").components(separatedBy: "#")[0]
            let name = (path as NSString).lastPathComponent
            let matches = games.filter { $0.url.lastPathComponent == name }
            guard matches.count == 1, let game = matches.first else { continue }
            let database = (item.db_name?.isEmpty == false ? item.db_name! : playlistName) as NSString
            let identity = PlaylistIdentity(label: item.label, database: database.deletingPathExtension)
            guard !identity.label.isEmpty, !identity.database.isEmpty, identity.database != ".", identity.database != "..", !identity.database.contains("/"), !identity.database.contains("\\") else { throw ArtError.message("Playlist contains an invalid thumbnail name.") }
            if let previous = result[game.id], previous.label != identity.label || previous.database != identity.database { throw ArtError.message("Playlist contains conflicting entries for \(name).") }
            result[game.id] = identity
        }
        return result
    }
}
