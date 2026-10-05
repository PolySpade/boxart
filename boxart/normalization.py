"""Matching scene-style ROM filenames to Libretro artwork titles."""
from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

from .errors import ArtError
from .fileops import move_no_replace

_SCENE = re.compile(r"(?i)\b(?:EUR|EUROPE|USA|JPN|JAPAN|MULTI\d*|PROPER|READNFO|PSP)\b.*$")
_SERIAL = re.compile(r"(?i)\s*-?\s*\b(?:ULUS|ULES|ULJM|ULJS|UCUS|UCES)[ -]?\d+.*$")
_TAGS = re.compile(r"\([^)]*\)|\[[^]]*\]")
_REGIONS = [(re.compile(r"\b(EUR|EUROPE|ULES|UCES)"), "Europe"), (re.compile(r"\b(USA|ULUS|UCUS)"), "USA"), (re.compile(r"\b(JPN|JAPAN|ULJM|ULJS)"), "Japan")]


def title(text: str) -> str:
    value = text.replace("_", " ")
    value = _SCENE.sub("", value)
    value = _SERIAL.sub("", value)
    value = _TAGS.sub("", value)
    return "".join(c for c in value.lower() if c.isalnum())


def region(text: str) -> str | None:
    upper = text.upper().replace("_", " ")
    for pattern, name in _REGIONS:
        if pattern.search(upper):
            return name
    return None


def match(text: str, names: list[str]) -> str | None:
    key = title(text)
    if not key:
        return None
    matches = [n for n in names if title(n) == key]
    if (found := region(text)) is not None:
        matches = [n for n in matches if f"({found})" in n]
    # Never choose arbitrarily between editions or different regional covers.
    return matches[0] if len(matches) == 1 else None


def rename(rom: Path, name: str) -> Path:
    if not name or name.startswith(".") or any(c in name for c in "/:\\\0") or len(name.encode()) >= 220:
        raise ArtError("Unsafe normalized filename.")
    target = rom.with_name(name + rom.suffix)
    if target == rom:
        return rom
    siblings = list(rom.parent.iterdir())
    if any(s.suffix[1:].lower() in ("cue", "m3u", "gdi") for s in siblings):
        raise ArtError("Renaming skipped: this folder contains playlists or disc descriptors that may reference ROM filenames.")
    if any(s.name.casefold() == target.name.casefold() and s != rom for s in siblings):
        raise ArtError("Normalized filename already exists.")
    if not stat.S_ISREG(os.lstat(rom).st_mode):
        raise ArtError("Only regular ROM files can be renamed.")
    # A durable record precedes the move; if the move fails the original still exists.
    record = json.dumps({"from": rom.name, "to": target.name, "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, ensure_ascii=False)
    with open(rom.parent / ".boxart-renames.jsonl", "a", encoding="utf-8") as log:
        log.write(record + "\n")
        log.flush()
        os.fsync(log.fileno())
    move_no_replace(rom, target)
    return target
