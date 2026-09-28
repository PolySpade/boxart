import Foundation

public enum FilenameNormalization {
    public static func title(_ input: String) -> String {
        var value = input.replacingOccurrences(of: "_", with: " ")
        value = value.replacingOccurrences(of: #"(?i)\b(?:EUR|EUROPE|USA|JPN|JAPAN|MULTI\d*|PROPER|READNFO|PSP)\b.*$"#, with: "", options: .regularExpression)
        value = value.replacingOccurrences(of: #"(?i)\s*-?\s*\b(?:ULUS|ULES|ULJM|ULJS|UCUS|UCES)[ -]?\d+.*$"#, with: "", options: .regularExpression)
        value = value.replacingOccurrences(of: #"\([^)]*\)|\[[^]]*\]"#, with: "", options: .regularExpression)
        return value.lowercased().filter { $0.isLetter || $0.isNumber }
    }
    public static func region(_ input: String) -> String? {
        let upper = input.uppercased().replacingOccurrences(of: "_", with: " ")
        for (pattern, region) in [(#"\b(EUR|EUROPE|ULES|UCES)"#, "Europe"), (#"\b(USA|ULUS|UCUS)"#, "USA"), (#"\b(JPN|JAPAN|ULJM|ULJS)"#, "Japan")] {
            if upper.range(of: pattern, options: .regularExpression) != nil { return region }
        }
        return nil
    }
    public static func match(_ input: String, names: [String]) -> String? {
        let key = title(input)
        guard !key.isEmpty else { return nil }
        var matches = names.filter { title($0) == key }
        if let region = region(input) { matches = matches.filter { $0.contains("(\(region))") } }
        // Never choose arbitrarily between editions or different regional covers.
        return matches.count == 1 ? matches[0] : nil
    }
    public static func rename(_ rom: URL, to name: String) throws -> URL {
        guard !name.isEmpty, !name.hasPrefix("."), !name.contains("/"), !name.contains(":"), !name.contains("\\"), name.utf8.count < 220 else { throw ArtError.message("Unsafe normalized filename.") }
        let target = rom.deletingLastPathComponent().appendingPathComponent(name).appendingPathExtension(rom.pathExtension)
        if target == rom { return rom }
        let fm = FileManager.default
        let siblings = try fm.contentsOfDirectory(at: rom.deletingLastPathComponent(), includingPropertiesForKeys: nil)
        guard !siblings.contains(where: { ["cue", "m3u", "gdi"].contains($0.pathExtension.lowercased()) }) else { throw ArtError.message("Renaming skipped: this folder contains playlists or disc descriptors that may reference ROM filenames.") }
        guard !siblings.contains(where: { $0.lastPathComponent.caseInsensitiveCompare(target.lastPathComponent) == .orderedSame && $0 != rom }) else { throw ArtError.message("Normalized filename already exists.") }
        let attrs = try fm.attributesOfItem(atPath: rom.path)
        guard attrs[.type] as? FileAttributeType == .typeRegular else { throw ArtError.message("Only regular ROM files can be renamed.") }
        // A durable record precedes the move; if the move fails the original still exists.
        let log = rom.deletingLastPathComponent().appendingPathComponent(".boxart-renames.jsonl")
        var record = try JSONSerialization.data(withJSONObject: ["from": rom.lastPathComponent, "to": target.lastPathComponent, "date": ISO8601DateFormatter().string(from: Date())])
        record.append(10)
        if !fm.fileExists(atPath: log.path) { try Data().write(to: log, options: .withoutOverwriting) }
        let handle = try FileHandle(forWritingTo: log); defer { try? handle.close() }
        try handle.seekToEnd(); try handle.write(contentsOf: record); try handle.synchronize()
        try fm.moveItem(at: rom, to: target)
        return target
    }
}
