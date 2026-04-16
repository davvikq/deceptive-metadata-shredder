"""Convert the bundled SVG app icon to a multi-size ICO file.

Pillow's ICO writer (``image.save(..., format="ICO", append_images=[...])``)
silently ignores all but the first frame, so the resulting file ends up
containing only a single 16x16 entry.  We therefore write the ICO binary
format ourselves: each size is encoded as a standalone PNG chunk inside the
ICO container.  Windows Vista and later (including all modern Windows 10/11)
support PNG-in-ICO natively.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image

try:
    import cairosvg  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    cairosvg = None

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


SVG_PATH = Path("src/dms/data/icon.svg")
ICO_PATH = Path("src/dms/data/icon.ico")
SIZES = [16, 32, 48, 64, 128, 256]


def main() -> None:
    images: list[Image.Image] = []
    for size in SIZES:
        images.append(_render_size(size))

    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_ico(images, ICO_PATH)

    for image in images:
        image.close()

    print(f"Saved: {ICO_PATH}  ({ICO_PATH.stat().st_size:,} bytes, {len(SIZES)} sizes)")


def _write_ico(images: list[Image.Image], path: Path) -> None:
    """Write a multi-size ICO file with one embedded PNG chunk per size.

    ICO binary layout::

        ICONDIR  (6 bytes)
        ICONDIRENTRY × n  (16 bytes each)
        PNG data chunks  (variable)
    """
    # Encode every image as a lossless PNG in memory.
    chunks: list[bytes] = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        chunks.append(buf.getvalue())

    n = len(chunks)
    # ICONDIR: reserved(2) type=1(2) count(2)
    header = struct.pack("<HHH", 0, 1, n)

    # Each ICONDIRENTRY: width(1) height(1) palette(1) reserved(1)
    #                    planes(2) bit_count(2) size(4) offset(4)
    # Width/height of 0 means 256 px.
    data_offset = 6 + 16 * n
    entries = b""
    for img, chunk in zip(images, chunks):
        w, h = img.size
        w_b = w if w < 256 else 0
        h_b = h if h < 256 else 0
        entries += struct.pack("<BBBBHHII", w_b, h_b, 0, 0, 1, 32, len(chunk), data_offset)
        data_offset += len(chunk)

    path.write_bytes(header + entries + b"".join(chunks))


def _render_size(size: int) -> Image.Image:
    """Rasterise the SVG at exactly *size* × *size* pixels."""
    if cairosvg is not None:
        try:
            png_bytes = cairosvg.svg2png(url=str(SVG_PATH), output_width=size, output_height=size)
            return Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        except Exception:
            pass

    # Qt fallback — works without cairosvg.
    app = QGuiApplication.instance() or QGuiApplication([])
    _ = app  # keep reference alive
    svg_bytes = SVG_PATH.read_bytes()
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return Image.open(io.BytesIO(bytes(byte_array))).convert("RGBA")


if __name__ == "__main__":
    main()
