import SwiftUI
import AppKit
import UniformTypeIdentifiers
import BoxArtCore

@MainActor final class LibraryModel: ObservableObject {
    @Published var folder = UserDefaults.standard.string(forKey: "romFolder") ?? "/Volumes/DS/Roms/NDS"
    @Published var games: [Game] = []
    @Published var selection: String?
    @Published var selectedIDs: Set<String> = []
    private var selectionAnchor: String?
    func select(_ id: String, shift: Bool = false, command: Bool = false) {
        let ids = visible.map(\.id)
        guard let end = ids.firstIndex(of: id) else { return }
        if shift, let anchor = selectionAnchor, let start = ids.firstIndex(of: anchor) {
            let range = Set(ids[min(start, end)...max(start, end)])
            selectedIDs = command ? selectedIDs.union(range) : range
        } else if command {
            if selectedIDs.contains(id) { selectedIDs.remove(id) } else { selectedIDs.insert(id) }
            selectionAnchor = id
        } else {
            selectedIDs = [id]; selectionAnchor = id
        }
        selection = selectedIDs.contains(id) ? id : ids.first { selectedIDs.contains($0) }
    }
    func setListSelection(_ ids: Set<String>) {
        selectedIDs = ids
        if selection.map({ !ids.contains($0) }) ?? true { selection = visible.first { ids.contains($0.id) }?.id }
        selectionAnchor = selection
    }
    func pruneSelection() {
        selectedIDs.formIntersection(Set(visible.map(\.id)))
        if selection.map({ !selectedIDs.contains($0) }) ?? true { selection = visible.first { selectedIDs.contains($0.id) }?.id }
        if selectionAnchor.map({ !selectedIDs.contains($0) }) ?? false { selectionAnchor = selection }
    }
    @Published var query = ""
    @Published var showSettings = false
    @Published var filter = "All games"
    @Published var systemFilter: GameSystem?
    @Published var profile: Profile = .anbernic
    @Published var size = 512
    @Published var normalizeFilenames = UserDefaults.standard.bool(forKey: "normalizeFilenames") {
        didSet { UserDefaults.standard.set(normalizeFilenames, forKey: "normalizeFilenames") }
    }
    @Published var jpeg = false
    @Published var identities: [String: PlaylistIdentity] = [:]
    @Published var destination: URL?
    @Published var busy = false
    @Published var progress = 0.0
    @Published var message = "Connect your SD card to get started."
    @Published var error: String?
    private var job: Task<Void, Never>?
    let service = ArtworkService()
    var settings: ExportSettings {
        var s = ExportSettings(); s.profile = profile; s.maxSize = size; s.jpeg = jpeg; s.destination = destination ?? (profile == .retroarch ? ExportSettings.suggestedRetroArchDirectory(for: URL(fileURLWithPath: folder)) : nil); s.identities = identities; return s
    }
    var matchingGames: [Game] {
        games.filter { (systemFilter == nil || $0.system == systemFilter) && (query.isEmpty || $0.title.localizedCaseInsensitiveContains(query) || ($0.code?.localizedCaseInsensitiveContains(query) ?? false)) }
    }
    func matchesArtworkFilter(_ game: Game, filter: String) -> Bool {
        switch filter {
        case "Ready to save": return game.status == "Ready"
        case "Saved": return game.savedURL != nil
        case "Needs artwork": return game.savedURL == nil && game.status != "Ready"
        default: return true
        }
    }
    var visible: [Game] { matchingGames.filter { matchesArtworkFilter($0, filter: filter) } }
    func filterCount(_ filter: String) -> Int { matchingGames.filter { matchesArtworkFilter($0, filter: filter) }.count }
    var ready: Int { games.filter { $0.status == "Ready" }.count }
    var saved: Int { games.filter { $0.savedURL != nil }.count }
    var selected: Game? { games.first { $0.id == selection } }
    func chooseFolder(destination choosingDestination: Bool = false) {
        let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.message = choosingDestination ? "Choose the artwork destination (SD root for TWiLight Menu++)." : "Choose your Roms folder or an individual system folder."
        if panel.runModal() == .OK, let url = panel.url {
            if choosingDestination { destination = url; refreshExisting() }
            else { folder = url.path; UserDefaults.standard.set(folder, forKey: "romFolder"); scan() }
        }
    }
    func scan() {
        guard !busy else { return }
        busy = true; message = "Reading ROM headers…"; progress = 0
        let root = URL(fileURLWithPath: folder)
        job = Task {
            do {
                let scanned = try await Task.detached { try Library.scan(root) }.value
                games = scanned; identities = [:]; refreshExisting(); selectedIDs = []; selection = nil; selectionAnchor = nil
                message = "\(games.count) games found. \(saved) already have artwork."
            } catch { self.error = error.localizedDescription; message = "Scan failed." }
            busy = false
        }
    }
    func refreshExisting() {
        for index in games.indices {
            games[index].savedURL = nil
            if let url = try? Library.existing(for: games[index].url, settings: settings) {
                games[index].savedURL = url; games[index].artwork = try? Data(contentsOf: url); games[index].status = "Saved"; games[index].source = "Existing artwork"
            } else { games[index].status = games[index].artwork == nil ? "Missing" : "Ready" }
        }
    }
    func download(selectedOnly: Bool = false, saveAfter: Bool = false, ids: Set<String>? = nil) {
        guard !busy else { return }
        let indices = games.indices.filter { games[$0].savedURL == nil && games[$0].status != "Ready" && (!selectedOnly || games[$0].id == selection) && (ids == nil || ids!.contains(games[$0].id)) }
        guard !indices.isEmpty else { return }
        busy = true; progress = 0
        let normalize = normalizeFilenames
        var batchIDs = ids
        job = Task {
            for (offset, index) in indices.enumerated() {
                if Task.isCancelled { break }
                message = "Finding artwork · \(games[index].title)"; games[index].status = "Searching"
                do {
                    var lookup = games[index]
                    var canonical: String?
                    if normalize {
                        guard identities[lookup.id] == nil, profile != .retroarch else { throw ArtError.message("Disable filename normalization for RetroArch or imported playlists; their paths must remain unchanged.") }
                        canonical = try await service.normalizedName(for: lookup)
                        lookup.lookupName = canonical ?? lookup.lookupName
                    }
                    if let (data, source) = try await service.artwork(for: lookup) {
                        if let canonical {
                            let oldID = games[index].id
                            if (try? Library.existing(for: games[index].url, settings: settings)) != nil { throw ArtError.message("Renaming skipped because this ROM already has artwork.") }
                            let target = games[index].url.deletingLastPathComponent().appendingPathComponent(canonical).appendingPathExtension(games[index].url.pathExtension)
                            if target != games[index].url, (try? Library.existing(for: target, settings: settings)) != nil { throw ArtError.message("Renaming skipped because the new name already has artwork.") }
                            try Task.checkCancellation()
                            let renamed = try FilenameNormalization.rename(games[index].url, to: canonical)
                            games[index].url = renamed; games[index].title = Game.clean(canonical)
                            games[index].lookupName = canonical
                            if selectedIDs.remove(oldID) != nil { selectedIDs.insert(renamed.path) }
                            if selection == oldID { selection = renamed.path }
                            if selectionAnchor == oldID { selectionAnchor = renamed.path }
                            if batchIDs?.remove(oldID) != nil { batchIDs?.insert(renamed.path) }
                        }
                        try Task.checkCancellation()
                        games[index].artwork = data; games[index].source = source; games[index].status = "Ready"
                    } else { games[index].status = "Not found"; games[index].source = "Try importing an image." }
                } catch {
                    if Task.isCancelled { games[index].status = "Missing"; break }
                    games[index].status = "Error"; games[index].source = error.localizedDescription
                }
                progress = Double(offset + 1) / Double(indices.count)
            }
            message = Task.isCancelled ? "Stopped. Downloaded artwork is ready to save." : "Search complete. \(ready) covers ready to save."
            busy = false
            if saveAfter && !Task.isCancelled { save(ids: batchIDs) }
        }
    }
    func downloadAndSaveAll() { downloadAndSave(ids: nil) }
    func getForSelected() {
        guard !selectedIDs.isEmpty else { return }
        downloadAndSave(ids: selectedIDs)
    }
    private func downloadAndSave(ids: Set<String>?) {
        guard !busy else { return }
        let targets = games.filter { $0.savedURL == nil && (ids == nil || ids!.contains($0.id)) }
        guard !targets.isEmpty else { message = "Selected games already have artwork."; return }
        do {
            for game in targets { _ = try settings.output(for: game.url) }
            if targets.contains(where: { $0.status != "Ready" }) { download(saveAfter: true, ids: ids) } else { save(ids: ids) }
        } catch { self.error = error.localizedDescription }
    }
    func stop() { job?.cancel() }
    func save(ids: Set<String>? = nil) {
        guard !busy else { return }
        let configuration = settings
        let pending = games.indices.filter { games[$0].status == "Ready" && (ids == nil || ids!.contains(games[$0].id)) }
        guard !pending.isEmpty else { return }
        // Detect collisions before writing any artwork into a shared destination.
        do {
            let paths = try pending.map { try configuration.output(for: games[$0].url).path.lowercased() }
            guard Set(paths).count == paths.count else { throw ArtError.message("Multiple ROMs would export to the same filename. Use per-ROM Imgs folders or separate the exports.") }
        } catch { self.error = error.localizedDescription; return }
        busy = true; progress = 0
        job = Task {
            var count = 0
            for (offset, index) in pending.enumerated() {
                if Task.isCancelled { break }
                guard let data = games[index].artwork else { continue }
                let rom = games[index].url
                do {
                    let output = try await Task.detached { try Library.save(data, rom: rom, settings: configuration) }.value
                    games[index].savedURL = output; games[index].status = "Saved"; count += 1
                } catch { games[index].status = "Save failed"; games[index].source = error.localizedDescription }
                progress = Double(offset + 1) / Double(pending.count)
            }
            message = "Saved \(count) covers. \(games.filter { $0.status == "Save failed" }.count) failed."
            busy = false
        }
    }
    func importPlaylists() {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = true; panel.canChooseDirectories = false
        panel.message = "Choose RetroArch JSON .lpl playlists. Entries are matched to ROMs by unique filename, even when device paths differ."
        if panel.runModal() == .OK {
            do {
                var matches = identities
                for url in panel.urls {
                    let imported = try Playlist.match(data: Data(contentsOf: url), playlistName: url.lastPathComponent, games: games)
                    matches.merge(imported) { _, new in new }
                }
                identities = matches
                for i in games.indices { games[i].lookupName = identities[games[i].id]?.label }
                refreshExisting(); message = "Matched playlist labels to \(matches.count) games. Ambiguous or absent filenames were skipped."
            } catch { self.error = error.localizedDescription }
        }
    }
    func importImage(for id: String? = nil) {
        guard !busy else { return }
        guard let index = games.firstIndex(where: { $0.id == (id ?? selection) }), games[index].savedURL == nil else { return }
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.png, .jpeg, .tiff, .webP]; panel.canChooseDirectories = false
        if panel.runModal() == .OK, let url = panel.url {
            do { let data = try Data(contentsOf: url); _ = try Library.render(data, settings: settings); games[index].artwork = data; games[index].source = "Imported · \(url.lastPathComponent)"; games[index].status = "Ready" }
            catch { self.error = error.localizedDescription }
        }
    }
}

@main struct BoxArtApp: App {
    @StateObject private var model = LibraryModel()
    var body: some Scene {
        WindowGroup {
            ContentView(model: model).frame(minWidth: 1020, minHeight: 680)
                .onAppear {
                    NSApplication.shared.setActivationPolicy(.regular)
                    // Refresh the running Dock icon after replacing a locally built app bundle.
                    if let url = Bundle.main.url(forResource: "BoxArt", withExtension: "icns"), let icon = NSImage(contentsOf: url) {
                        NSApplication.shared.applicationIconImage = icon
                    }
                    NSApplication.shared.activate(ignoringOtherApps: true)
                }
        }.defaultSize(width: 1240, height: 800)
        .commands {
            CommandGroup(replacing: .appSettings) {
                Button("Settings…") { model.showSettings = true }.keyboardShortcut(",", modifiers: .command)
            }
            CommandGroup(replacing: .newItem) {
                Button("Open ROM Folder…") { model.chooseFolder() }.keyboardShortcut("o").disabled(model.busy)
                Button("Scan Library") { model.scan() }.keyboardShortcut("r").disabled(model.busy)
            }
        }
    }
}

struct ContentView: View {
    @ObservedObject var model: LibraryModel
    @State private var gridView = true
    @State private var showInspector = false
    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 10) {
                    Image(systemName: "square.stack.3d.up.fill").font(.title2).foregroundStyle(.teal)
                    Text("BoxArt").font(.title2.bold())
                }.padding(20)
                List {
                    Section("Library") {
                        Button { model.systemFilter = nil } label: {
                            Label("All games", systemImage: "square.grid.2x2").badge(model.games.count)
                        }.listRowBackground(model.systemFilter == nil ? Color.teal.opacity(0.12) : .clear)
                    }
                    Section("Systems") {
                        ForEach(GameSystem.allCases.filter { system in model.games.contains { $0.system == system } }) { system in
                            Button { model.systemFilter = system } label: {
                                HStack { Image(systemName: "gamecontroller"); Text(system.rawValue.components(separatedBy: " - ").dropFirst().joined(separator: " · ")); Spacer(); Text("\(model.games.filter { $0.system == system }.count)").foregroundStyle(.secondary) }
                            }.listRowBackground(model.systemFilter == system ? Color.teal.opacity(0.12) : .clear)
                        }
                    }
                }.listStyle(.sidebar).buttonStyle(.plain)
                Divider()
                VStack(alignment: .leading, spacing: 8) {
                    Label("ROM library", systemImage: "sdcard").font(.callout.weight(.medium))
                    Text(model.folder).font(.caption).foregroundStyle(.secondary).lineLimit(2).truncationMode(.middle)
                    Button("Choose folder…") { model.chooseFolder() }.disabled(model.busy)
                }.padding(18)
            }.navigationSplitViewColumnWidth(min: 200, ideal: 230, max: 290)
        } detail: {
            VStack(spacing: 0) {
                header
                Divider()
                HStack(spacing: 0) {
                    library.frame(maxWidth: .infinity, maxHeight: .infinity)
                    if showInspector { Divider(); inspector.frame(width: 280) }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
                Divider()
                HStack(spacing: 12) {
                    if model.busy { ProgressView(value: model.progress).frame(width: 110) }
                    Text(model.message).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    Spacer()
                    if model.busy { Button("Stop") { model.stop() } }
                    Text("\(model.saved) / \(model.games.count) saved").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }.padding(14)
            }.background(Color(nsColor: .textBackgroundColor))
        }
        .searchable(text: $model.query, prompt: "Search games")
        .toolbar {
            ToolbarItemGroup {
                Picker("View", selection: $gridView) {
                    Image(systemName: "square.grid.2x2").tag(true)
                    Image(systemName: "list.bullet").tag(false)
                }.pickerStyle(.segmented).frame(width: 80)
                Button { showInspector.toggle() } label: { Image(systemName: "sidebar.right") }.help("Show artwork details")
                Button { model.showSettings = true } label: { Image(systemName: "gearshape") }.help("Artwork settings")
            }
        }
        .sheet(isPresented: $model.showSettings) { settingsPanel }
        .onChange(of: model.profile) { _, _ in model.refreshExisting() }
        .onChange(of: model.query) { _, _ in model.pruneSelection() }
        .onChange(of: model.filter) { _, _ in model.pruneSelection() }
        .onChange(of: model.systemFilter) { _, _ in model.pruneSelection() }
        .onChange(of: model.jpeg) { _, _ in model.refreshExisting() }
        .alert("BoxArt", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) { Button("OK") { model.error = nil } } message: { Text(model.error ?? "") }
        .task { model.scan() }
    }
    private var settingsPanel: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Artwork settings").font(.title2.bold())
            Form {
                Toggle("Normalize filenames when processing", isOn: $model.normalizeFilenames).disabled(model.busy)
                Text("Renames ROMs to uniquely matched artwork titles, keeping their extensions. Off by default. Skips ambiguous matches, existing artwork and playlist-based libraries. Saves a rename log beside the ROMs.")
                    .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                Picker("Export profile", selection: $model.profile) { ForEach(Profile.allCases) { Text($0.rawValue).tag($0) } }
                Text(model.profile.detail).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                if model.profile != .twilight {
                    Picker("Maximum edge", selection: $model.size) { ForEach([128, 256, 512, 1024], id: \.self) { Text("\($0) px").tag($0) } }
                }
                if model.profile == .custom { Picker("Format", selection: $model.jpeg) { Text("PNG").tag(false); Text("JPEG").tag(true) } }
                if model.profile != .anbernic {
                    Button("Choose destination…") { model.chooseFolder(destination: true) }
                    Text(model.settings.destination?.path ?? "No destination selected").font(.caption).foregroundStyle(.secondary)
                }
                if model.profile == .retroarch {
                    Text("Created automatically when saving. Set RetroArch’s Settings → Directory → Thumbnails to this folder on your device. You can choose another location above.").font(.caption).foregroundStyle(.secondary)
                    Button("Import .lpl playlists…") { model.importPlaylists() }.disabled(model.games.isEmpty)
                    Text("\(model.identities.count) playlist labels matched").font(.caption).foregroundStyle(.secondary)
                }
            }.disabled(model.busy)
            Divider()
            Text("Sources: GameTDB for DS game codes; Libretro for all systems. Existing artwork is preserved.").font(.callout).foregroundStyle(.secondary)
            HStack { Link("GameTDB", destination: URL(string: "https://www.gametdb.com")!); Link("Libretro", destination: URL(string: "https://github.com/libretro-thumbnails/libretro-thumbnails")!); Spacer(); Button("Done") { model.showSettings = false }.keyboardShortcut(.defaultAction) }
        }.padding(28).frame(width: 500)
    }
    private func icon(_ item: String) -> String {
        switch item { case "All games": return "square.grid.2x2"; case "Ready to save": return "arrow.down.circle"; case "Saved": return "checkmark.circle"; default: return "photo.badge.exclamationmark" }
    }
    private var header: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text(model.systemFilter?.rawValue.components(separatedBy: " - ").dropFirst().joined(separator: " · ") ?? "All games").font(.largeTitle.bold())
                    Text("\(model.visible.count) games · \(model.profile.rawValue)").foregroundStyle(.secondary)
                }
                Spacer()
                Button { model.scan() } label: { Image(systemName: "arrow.clockwise") }.help("Rescan library").disabled(model.busy)
                Button("Download & save all") { model.downloadAndSaveAll() }.buttonStyle(.borderedProminent).tint(.teal).disabled(model.busy || model.games.isEmpty).help("Find and save all missing covers across the entire scanned library")
            }
            HStack {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(["All games", "Needs artwork", "Ready to save", "Saved"], id: \.self) { item in
                            artworkFilter(item)
                        }
                    }.padding(3)
                }.fixedSize(horizontal: false, vertical: true)
                Spacer()
                if !model.selectedIDs.isEmpty {
                    Button("Get for selected (\(model.selectedIDs.count))") { model.getForSelected() }
                        .disabled(model.busy).help("Download and save artwork only for the selected games")
                }
                Menu {
                    Button("Download previews only") { model.download() }
                    Button("Save \(model.ready) ready covers") { model.save() }.disabled(model.ready == 0)
                } label: { Image(systemName: "ellipsis.circle") }.menuStyle(.borderlessButton).frame(width: 30).disabled(model.busy)
            }
            if model.filter == "Ready to save" {
                HStack(spacing: 10) {
                    Image(systemName: "tray.and.arrow.down").foregroundStyle(.teal)
                    Text("Covers in memory, not yet saved to your artwork folder.")
                        .font(.callout).foregroundStyle(.secondary)
                    Spacer()
                    Button("Save these covers") { model.save(ids: Set(model.visible.map(\.id))) }
                        .disabled(model.busy || model.visible.isEmpty)
                }
            }
        }.padding(24)
    }
    private func artworkFilter(_ item: String) -> some View {
        let selected = model.filter == item
        let title = item == "Ready to save" ? "Unsaved" : item == "All games" ? "All" : item == "Needs artwork" ? "Missing" : item
        let count = model.filterCount(item)
        return Button { model.filter = item } label: {
            HStack(spacing: 7) {
                Image(systemName: icon(item)).font(.system(size: 12, weight: .medium))
                Text(title).font(.system(size: 13, weight: selected ? .semibold : .medium))
                Text(count.formatted()).font(.system(size: 11, weight: .semibold)).monospacedDigit()
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(selected ? Color.teal.opacity(0.16) : Color.primary.opacity(0.06), in: Capsule())
            }
            .foregroundStyle(selected ? Color.primary : Color.secondary)
            .padding(.horizontal, 11).padding(.vertical, 8)
            .background(selected ? Color.teal.opacity(0.12) : Color.clear, in: RoundedRectangle(cornerRadius: 9))
            .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(selected ? Color.teal.opacity(0.45) : Color.clear))
            .contentShape(RoundedRectangle(cornerRadius: 9))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(title), \(count) games")
        .accessibilityAddTraits(selected ? [.isSelected] : [])
        .help(item == "Ready to save" ? "Downloaded or imported covers that have not been saved. Unsaved previews are lost when the app closes." : "Show \(item.lowercased()) in the current system and search")
    }
    private var library: some View {
        Group {
            if model.visible.isEmpty {
                ContentUnavailableView(model.games.isEmpty ? "Bring your games to life" : "No games here", systemImage: "rectangle.stack", description: Text(model.games.isEmpty ? "Choose your Roms folder to scan DS, GBA, PlayStation and more." : "Try another filter or search."))
            } else if gridView {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 155, maximum: 200), spacing: 20)], alignment: .leading, spacing: 24) {
                        ForEach(model.visible) { game in
                            Button {
                                let modifiers = NSEvent.modifierFlags
                                model.select(game.id, shift: modifiers.contains(.shift), command: modifiers.contains(.command))
                            } label: {
                                VStack(alignment: .leading, spacing: 9) {
                                    cover(game, width: 148, height: 154).frame(maxWidth: .infinity)
                                    Text(game.title).font(.callout.weight(.medium)).lineLimit(2).frame(height: 36, alignment: .topLeading)
                                    HStack(spacing: 5) {
                                        Circle().fill(game.status == "Saved" ? Color.green : game.status == "Ready" ? Color.teal : Color.secondary.opacity(0.4)).frame(width: 5, height: 5)
                                        Text(game.status).font(.caption).foregroundStyle(.secondary)
                                    }
                                }.padding(10).background(model.selectedIDs.contains(game.id) ? Color.teal.opacity(0.10) : .clear, in: RoundedRectangle(cornerRadius: 12))
                                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(model.selectedIDs.contains(game.id) ? Color.teal.opacity(0.5) : .clear))
                            }.buttonStyle(.plain)
                                .accessibilityAddTraits(model.selectedIDs.contains(game.id) ? .isSelected : [])
                                .contextMenu { coverMenu(game) }
                        }
                    }.padding(22)
                }
            } else {
                List(selection: Binding(get: { model.selectedIDs }, set: { model.setListSelection($0) })) {
                    ForEach(model.visible) { game in
                        HStack(spacing: 12) {
                            cover(game, width: 44, height: 44)
                            VStack(alignment: .leading, spacing: 4) { Text(game.title).font(.body.weight(.medium)).lineLimit(1); Text(game.system.rawValue + (game.code.map { " · " + $0 } ?? "")).font(.caption.monospaced()).foregroundStyle(.secondary) }
                            Spacer()
                            Text(game.status).font(.caption.weight(.medium)).foregroundStyle(game.status == "Saved" ? .green : game.status == "Ready" ? .teal : .secondary)
                        }.padding(.vertical, 5).tag(game.id)
                            .contextMenu { coverMenu(game) }
                    }
                }.listStyle(.inset)
            }
        }
    }
    @ViewBuilder private func coverMenu(_ game: Game) -> some View {
        Button("Show in Finder", systemImage: "folder") {
            NSWorkspace.shared.activateFileViewerSelecting([game.savedURL ?? game.url])
        }
        if game.savedURL != nil {
            Button("Show ROM in Finder", systemImage: "doc") {
                NSWorkspace.shared.activateFileViewerSelecting([game.url])
            }
        }
        Button("Show Info", systemImage: "info.circle") {
            model.select(game.id)
            showInspector = true
        }
        Divider()
        Button("Find Image", systemImage: "magnifyingglass") {
            model.download(ids: [game.id])
        }.disabled(model.busy || game.savedURL != nil || game.status == "Ready")
        Button("Search Images Online…", systemImage: "globe") {
            var components = URLComponents(string: "https://www.google.com/search")!
            components.queryItems = [URLQueryItem(name: "tbm", value: "isch"), URLQueryItem(name: "q", value: "\(game.title) \(game.system.rawValue) box art")]
            if let url = components.url { NSWorkspace.shared.open(url) }
        }
        Button("Import Image…", systemImage: "photo") { model.importImage(for: game.id) }
            .disabled(model.busy || game.savedURL != nil)
        Button("Save Image", systemImage: "square.and.arrow.down") { model.save(ids: [game.id]) }
            .disabled(model.busy || game.status != "Ready")
    }
    private var inspector: some View {
        ScrollView {
            if let game = model.selected {
                VStack(alignment: .leading, spacing: 18) {
                    Text("ARTWORK PREVIEW").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    cover(game, width: 232, height: 216)
                    Text(game.title).font(.title3.bold()).fixedSize(horizontal: false, vertical: true)
                    Text(game.source.isEmpty ? "Find artwork to preview the matching cover before saving it to your card." : game.source).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    Divider()
                    field("ROM FILE", game.url.lastPathComponent)
                    field("OUTPUT", (try? model.settings.output(for: game.url).path) ?? "Choose a destination")
                    field("IMAGE", model.profile == .twilight ? "PNG · fits within 128 × 115" : "\(model.jpeg && model.profile == .custom ? "JPEG" : "PNG") · up to \(model.size) px · preserves proportions")
                    if game.savedURL == nil {
                        Button("Find artwork for this game") { model.download(selectedOnly: true) }.disabled(model.busy || game.status == "Ready")
                        Button("Import image…") { model.importImage() }.disabled(model.busy)
                    }
                    if let url = game.savedURL { Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([url]) } }
                }.padding(24)
            } else { ContentUnavailableView("Select a game", systemImage: "photo", description: Text("Preview its artwork and export location.")).padding(.top, 70) }
        }.background(Color(nsColor: .controlBackgroundColor).opacity(0.45))
    }
    private func field(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 5) { Text(label).font(.caption2.weight(.semibold)).foregroundStyle(.secondary); Text(value).font(.caption).textSelection(.enabled).fixedSize(horizontal: false, vertical: true) }
    }
    private func cover(_ game: Game, width: CGFloat, height: CGFloat) -> some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8).fill(Color.secondary.opacity(0.07))
            if let data = game.artwork, let image = NSImage(data: data) { Image(nsImage: image).resizable().aspectRatio(contentMode: .fit).padding(width > 100 ? 8 : 2) }
            else { Image(systemName: "photo").font(width > 100 ? .system(size: 42, weight: .ultraLight) : .body).foregroundStyle(.tertiary) }
        }.frame(width: width, height: height).accessibilityLabel(game.artwork == nil ? "No cover artwork" : "Cover for \(game.title)")
    }
}
