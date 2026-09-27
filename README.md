# BoxArt for macOS

A native SwiftUI app for finding and exporting multi-system cover art. macOS 14+, no third-party dependencies or API keys. The supplied build runs on Apple Silicon.

## Run

Open `build/BoxArt.app`. It initially scans `/Volumes/DS/Roms/NDS` (read-only). Use **Download & save all** to fetch and export missing covers across the scanned library in one run. The toolbar’s More menu also offers downloads for preview only and saving ready covers separately. Use **Choose folder** for another library. The sidebar navigates systems; the toolbar switches grid/list and opens artwork settings. Click a cover, then Shift-click another to select a range; Command-click adds or removes individual games. **Get for selected** downloads and saves only that selection. List view supports native multi-selection too. Changing search, system or status filters removes hidden games from the selection; an in-progress batch keeps its original selection. ROMs are never renamed or modified; existing PNG/JPEG covers are preserved. The app is locally ad-hoc signed, not notarized for distribution.

## Profiles

- **RG DS Plus / NNDDSS**: `Imgs/<exact ROM stem>.png` beside each ROM, including nested folders. PNG, default maximum edge 512 pixels, no cropping or stretching. A 512 × 458 cover was tested successfully on RG DS Plus / NNDDSS. The folder and filename convention is community-reported; this is not an official size specification. Size is configurable.
- **TWiLight Menu++**: choose the SD root as the destination. Exports `_nds/TWiLightMenu/boxart/<full ROM filename>.png`, fitted within 128 × 115 pixels. Intended for normal box-art mode; the Cached mode's separate 44 KiB limit is not enforced.
- **Custom folder**: choose the output folder, PNG/JPEG and maximum edge. Uses ROM stems. This supports other frontends with compatible layouts, but does not generate their databases, playlists or gamelist.xml files.

## RetroArch and other systems

Choose `/Volumes/DS/Roms` to scan across system folders. Supports DS, GBA, GB/GBC, NES/FDS, SNES, N64, PlayStation, PSP, Mega Drive, Master System, Game Gear, Dreamcast, Saturn, Sega CD/32X, PC Engine, Atari 2600/Lynx, Neo Geo Pocket/Color and WonderSwan/Color. Disc images and ZIP/7z archives are identified by their enclosing system folder (e.g. `PS`, `GBA`, `SFC`); archives are matched by filename, not unpacked. BIN files are skipped in folders with CUE/GDI descriptors to avoid treating audio tracks as games.

For **RetroArch**, choose the directory configured as **Settings → Directory → Thumbnails** on your handheld. Export uses `<system>/Named_Boxarts/<label>.png`. Import JSON `.lpl` playlists to get exact display labels and database names. Android/Linux paths are matched to local ROMs by unique basename; ambiguous names are skipped. Without a playlist, the app uses standard Libretro system names and ROM stems, which only works if your playlist labels match. Import playlists again after rescanning. Legacy six-line playlists are not supported.

Other frontend layouts can use Anbernic `Imgs` or Custom folder export. Emulator-specific databases and gamelist.xml are not generated, and universal compatibility is not claimed.

## Matching

Reads only the four-byte game code at offset 0x0C from `.nds` and `.dsi` headers. Tries the appropriate Libretro system’s box art with exact filename matching and Libretro character substitutions first. Falls back to GameTDB medium front covers using the exact DS game code, trying the ROM region first, then small covers. No fuzzy matching that might confuse sequels. Translations keep their underlying game code. Homebrew and unrecognized titles can use **Import image**. Non-DS and archived games use Libretro filename/playlist-label matching.

Downloads remain in memory until saved. Stop preserves completed downloads for the current session. Network failures appear per game and can be retried with Find missing artwork. Artwork is written through a temporary sibling file and moved into place; existing artwork is never replaced. Flat destinations are checked for duplicate names before the batch writes. Filesystem failures appear per game. Reconnect/rescan after disconnecting a card. Close and reopen discards unsaved previews.

## Build and test

```sh
swift test
./scripts/build-app.sh
open build/BoxArt.app
```

Open `Package.swift` in Xcode to develop. The package separates the scanner, image conversion, providers and export rules from the SwiftUI application. Tests exercise hidden-file filtering, header reads, exact naming, dimensions, preservation of ROMs and existing images, invalid images and disconnected-card handling.

## References and credits

- [GameTDB](https://www.gametdb.com/) — Nintendo DS artwork, exact game-code lookup.
- [Libretro thumbnails](https://github.com/libretro-thumbnails/libretro-thumbnails) — fallback artwork and naming conventions.
- [TWiLight Menu++ box-art documentation](https://wiki.ds-homebrew.com/twilightmenu/how-to-get-box-art) — PNG naming and size limits.
- [RG DS Plus owners reporting the Imgs convention](https://www.reddit.com/r/ANBERNIC/comments/1wnvhxj/rg_ds_plus_received_and_its_great/) — community evidence, not an official NNDDSS specification.

Artwork belongs to its respective rights holders. No ROMs or cover images are bundled.

## License

BoxArt's original source code, documentation, and app icon are licensed under the [MIT License](LICENSE), copyright 2026 XenoCode. Downloaded game artwork, game metadata, ROMs, and third-party service content are excluded from this license and remain subject to their respective rights and provider terms. MIT permits commercial reuse of the code; it does not grant access to artwork services or override their noncommercial restrictions.

- [RetroArch thumbnail documentation](https://docs.libretro.com/guides/roms-playlists-thumbnails/) — playlist labels, database names and folder conventions.

## Icon and settings

The editable layered icon is `Resources/BoxArt.icon`. The build compiles it with Apple actool into Assets.car and BoxArt.icns. Open the .icon file in Icon Composer to edit its layers. Settings is available with Command-comma or the gear button. RetroArch export suggests `RetroArch/thumbnails` beside the selected Roms directory (or at the selected removable volume root), reusing common existing thumbnail folders when present. Saving creates the directories. This is a suggested location, not automatic discovery of the emulator’s configuration; configure the handheld to use the same folder or choose its existing directory.

Artwork quality: Libretro exact-name covers are now tried first, followed by GameTDB medium covers matched by DS game code, then small covers as a last resort. The exporter never upscales; a larger maximum edge only preserves detail already present in the source. Existing saved covers remain protected and are not automatically replaced.
