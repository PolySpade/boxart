import Foundation
import AppKit
import ImageIO
import UniformTypeIdentifiers

public enum ArtError: LocalizedError {
    case message(String)
    public var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}
public enum Profile: String, CaseIterable, Identifiable {
    case anbernic = "Anbernic · Imgs / NNDDSS", retroarch = "RetroArch", twilight = "TWiLight Menu++", custom = "Custom folder"
    public var id: String { rawValue }
    public var detail: String {
        switch self {
        case .anbernic: return "Imgs beside each ROM • filename without .nds • PNG. Community-reported layout; 512 px was tested on RG DS Plus; size is configurable."
        case .retroarch: return "Choose RetroArch’s thumbnails directory. Uses system/Named_Boxarts/label.png. Import .lpl playlists to match their exact labels; otherwise uses standard system names and ROM stems."
        case .twilight: return "Select the SD card root as destination. Uses _nds/TWiLightMenu/boxart and the full ROM filename. PNG fitted within 128 × 115."
        case .custom: return "Choose a destination, size and format. Images use the ROM filename without its extension."
        }
    }
}
public struct ExportSettings {
    public var profile: Profile = .anbernic
    public var identities: [String: PlaylistIdentity] = [:]
    public var destination: URL?
    public var maxSize: Int = 512
    public var jpeg: Bool = false
    public init() {}
    public static func suggestedRetroArchDirectory(for romFolder: URL) -> URL {
        let parts = romFolder.standardizedFileURL.pathComponents
        let root: URL
        if let index = parts.firstIndex(where: { $0.caseInsensitiveCompare("Roms") == .orderedSame }) {
            root = URL(fileURLWithPath: NSString.path(withComponents: Array(parts.prefix(index))), isDirectory: true)
        } else if parts.count > 2 && parts[1] == "Volumes" {
            root = URL(fileURLWithPath: "/Volumes/" + parts[2], isDirectory: true)
        } else {
            root = romFolder.deletingLastPathComponent()
        }
        for suffix in ["RetroArch/thumbnails", "retroarch/thumbnails", ".config/retroarch/thumbnails"] {
            let candidate = root.appendingPathComponent(suffix, isDirectory: true)
            var directory: ObjCBool = false
            if FileManager.default.fileExists(atPath: candidate.path, isDirectory: &directory), directory.boolValue { return candidate }
        }
        return root.appendingPathComponent("RetroArch/thumbnails", isDirectory: true)
    }
    public func output(for rom: URL) throws -> URL {
        let folder: URL
        switch profile {
        case .anbernic: folder = rom.deletingLastPathComponent().appendingPathComponent("Imgs", isDirectory: true)
        case .retroarch:
            guard let destination else { throw ArtError.message("Choose RetroArch’s thumbnails directory.") }
            let identity = identities[rom.path]
            guard let system = identity?.database ?? GameSystem.infer(rom)?.rawValue else { throw ArtError.message("Cannot determine this ROM’s system.") }
            let name = PlaylistIdentity.safeName(identity?.label ?? rom.deletingPathExtension().lastPathComponent)
            return destination.appendingPathComponent(system, isDirectory: true).appendingPathComponent("Named_Boxarts", isDirectory: true).appendingPathComponent(name + ".png")
        case .twilight:
            guard let destination else { throw ArtError.message("Choose the SD card root for TWiLight Menu++.") }
            folder = destination.appendingPathComponent("_nds/TWiLightMenu/boxart", isDirectory: true)
        case .custom:
            guard let destination else { throw ArtError.message("Choose an artwork destination.") }
            folder = destination
        }
        let name = profile == .twilight ? rom.lastPathComponent : rom.deletingPathExtension().lastPathComponent
        return folder.appendingPathComponent(name).appendingPathExtension(profile == .custom && jpeg ? "jpg" : "png")
    }
}
public struct Game: Identifiable {
    public let url: URL
    public var id: String { url.path }
    public var system: GameSystem { GameSystem.infer(url) ?? .nds }
    public var lookupName: String?
    public let code: String?
    public let title: String
    public var artwork: Data?
    public var source: String = ""
    public var status: String = "Missing"
    public var savedURL: URL?
    public init(url: URL, code: String?) {
        self.url = url; self.code = code
        self.title = Self.clean(url.deletingPathExtension().lastPathComponent)
    }
    public static func clean(_ name: String) -> String {
        name.replacingOccurrences(of: #"\([^)]*\)|\[[^]]*\]"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: "_", with: " ").trimmingCharacters(in: .whitespaces)
    }
}
public enum Library {
    public static func gameCode(_ url: URL) throws -> String? {
        let file = try FileHandle(forReadingFrom: url); defer { try? file.close() }
        try file.seek(toOffset: 12)
        guard let bytes = try file.read(upToCount: 4), bytes.count == 4,
              bytes.allSatisfy({ (65...90).contains($0) || (48...57).contains($0) }) else { return nil }
        return String(data: bytes, encoding: .ascii)
    }
    public static func scan(_ root: URL) throws -> [Game] {
        var directory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: root.path, isDirectory: &directory), directory.boolValue else { throw ArtError.message("ROM folder is unavailable. Connect your card or choose another folder.") }
        var scanError: Error?
        guard let enumerator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey], options: [.skipsHiddenFiles], errorHandler: { _, error in scanError = error; return false }) else { throw ArtError.message("Cannot read the ROM folder.") }
        var games: [Game] = []
        for case let url as URL in enumerator {
            guard GameSystem.infer(url) != nil else { continue }
            if url.pathExtension.lowercased() == "bin", let siblings = try? FileManager.default.contentsOfDirectory(at: url.deletingLastPathComponent(), includingPropertiesForKeys: nil), siblings.contains(where: { ["cue", "gdi"].contains($0.pathExtension.lowercased()) }) { continue }
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
            guard values.isRegularFile == true, values.isSymbolicLink != true else { continue }
            let code = ["nds", "dsi"].contains(url.pathExtension.lowercased()) ? try gameCode(url) : nil
            games.append(Game(url: url, code: code))
        }
        if let scanError { throw scanError }
        return games.sorted { $0.title.localizedStandardCompare($1.title) == .orderedAscending }
    }
    public static func existing(for rom: URL, settings: ExportSettings) throws -> URL? {
        let target = try settings.output(for: rom)
        let alternatives = settings.profile == .anbernic ? [target, target.deletingPathExtension().appendingPathExtension("jpg"), target.deletingPathExtension().appendingPathExtension("jpeg")] : [target]
        return alternatives.first { FileManager.default.fileExists(atPath: $0.path) }
    }
    public static func render(_ data: Data, settings: ExportSettings) throws -> Data {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil), let image = CGImageSourceCreateImageAtIndex(source, 0, nil), image.width <= 10000, image.height <= 10000 else { throw ArtError.message("The source is not a supported image.") }
        let widthLimit = settings.profile == .twilight ? 128 : max(32, min(settings.maxSize, 2048))
        let heightLimit = settings.profile == .twilight ? 115 : widthLimit
        let scale = min(1, min(Double(widthLimit) / Double(image.width), Double(heightLimit) / Double(image.height)))
        let width = max(1, Int(Double(image.width) * scale)), height = max(1, Int(Double(image.height) * scale))
        guard let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { throw ArtError.message("Cannot resize image.") }
        context.setFillColor(NSColor.white.cgColor); context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        context.interpolationQuality = .high; context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        let result = NSMutableData()
        let format = settings.profile == .custom && settings.jpeg ? UTType.jpeg : UTType.png
        guard let rendered = context.makeImage(), let encoder = CGImageDestinationCreateWithData(result, format.identifier as CFString, 1, nil) else { throw ArtError.message("Cannot encode artwork.") }
        CGImageDestinationAddImage(encoder, rendered, [kCGImageDestinationLossyCompressionQuality: 0.92] as CFDictionary)
        guard CGImageDestinationFinalize(encoder) else { throw ArtError.message("Image encoding failed.") }
        return result as Data
    }
    public static func save(_ data: Data, rom: URL, settings: ExportSettings) throws -> URL {
        guard FileManager.default.fileExists(atPath: rom.path) else { throw ArtError.message("ROM unavailable. Reconnect the SD card and scan again.") }
        if try existing(for: rom, settings: settings) != nil { throw ArtError.message("Artwork already exists; preserved the existing file.") }
        let output = try settings.output(for: rom)
        let rendered = try render(data, settings: settings)
        try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
        let temporary = output.deletingLastPathComponent().appendingPathComponent(".boxart-" + UUID().uuidString + ".tmp")
        defer { try? FileManager.default.removeItem(at: temporary) }
        try rendered.write(to: temporary, options: .withoutOverwriting)
        // FileManager refuses to move onto an existing destination.
        try FileManager.default.moveItem(at: temporary, to: output)
        return output
    }
}

public actor ArtworkService {
    private let session: URLSession
    public init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 15; config.timeoutIntervalForResource = 30
        config.httpAdditionalHeaders = ["User-Agent": "BoxArt-macOS/1.0"]
        session = URLSession(configuration: config)
    }
    private func fetch(_ url: URL) async throws -> Data? {
        try Task.checkCancellation()
        let (data, response) = try await session.data(from: url)
        guard let response = response as? HTTPURLResponse else { throw ArtError.message("Invalid server response.") }
        if response.statusCode == 404 { return nil }
        guard response.statusCode == 200 else { throw ArtError.message("Artwork server returned HTTP \(response.statusCode). Try again later.") }
        guard data.count < 20_000_000, CGImageSourceCreateWithData(data as CFData, nil) != nil else { return nil }
        return data
    }
    public func artwork(for game: Game) async throws -> (Data, String)? {
        var lastError: Error?
        // Exact filename only: do not silently assign a similarly named sequel or region.
        let name = (game.lookupName ?? game.url.deletingPathExtension().lastPathComponent)
            .replacingOccurrences(of: #"[&*/:`<>?\\|\"]"#, with: "_", options: .regularExpression)
        let base = URL(string: "https://raw.githubusercontent.com/libretro-thumbnails/\(game.system.repository)/master/Named_Boxarts/")!
        do { if let data = try await fetch(base.appendingPathComponent(name + ".png")) { return (data, "Libretro · exact filename") } }
        catch { try Task.checkCancellation(); lastError = error }
        if let code = game.code {
            let region: String
            switch code.last { case "J": region = "JA"; case "K": region = "KO"; case "D": region = "DE"; case "F": region = "FR"; case "I": region = "IT"; case "S": region = "ES"; case "E": region = "US"; default: region = "EN" }
            var regions: [String] = []
            for value in [region, "US", "EN", "JA"] where !regions.contains(value) { regions.append(value) }
            for (kind, ext) in [("coverM", "jpg"), ("coverS", "png")] {
                for region in regions {
                    let url = URL(string: "https://art.gametdb.com/ds/\(kind)/\(region)/\(code).\(ext)")!
                    do { if let data = try await fetch(url) { return (data, "GameTDB · \(code) · \(region) · \(kind)") } }
                    catch { try Task.checkCancellation(); lastError = error; break }
                }
            }
        }
        if let lastError { throw lastError }
        return nil
    }
}
