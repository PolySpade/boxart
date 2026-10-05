import io
import os

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

live = pytest.mark.skipif(os.environ.get("BOXART_LIVE_TEST") != "1", reason="Opt-in network test")


def png(width=512, height=460) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(out, "PNG")
    return out.getvalue()


def make_rom(folder, name="Mario (USA).nds", code="ASME"):
    data = bytearray(512)
    data[12:16] = code.encode()
    path = folder / name
    path.write_bytes(bytes(data))
    return path


class MemoryStore:
    """Stands in for QSettings so tests never touch the user's configuration."""
    def __init__(self):
        self.values = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value
