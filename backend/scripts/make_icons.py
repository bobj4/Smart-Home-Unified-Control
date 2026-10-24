#!/usr/bin/env python
"""Create app icons using only the Python standard library."""

import pathlib
import struct
import zlib


def crc32(data: bytes) -> int:
    """Calculate CRC32 checksum."""
    return zlib.crc32(data) & 0xFFFFFFFF


def make_png(size: int) -> bytes:
    """Create a PNG file with a house shape on a colored background."""

    # Colors
    fg_color = (0xFF, 0xFF, 0xFF)  # white

    # Create image data: each pixel is 3 bytes (RGB)
    width, height = size, size
    pixels = bytearray(width * height * 3)

    def set_pixel(x: int, y: int, r: int, g: int, b: int):
        """Set a pixel at (x, y)."""
        px = y * width + x
        pixels[px * 3 + 0] = r
        pixels[px * 3 + 1] = g
        pixels[px * 3 + 2] = b

    # Draw house shape centered, about 60% of width
    house_width = int(size * 0.6)
    house_x_start = (size - house_width) // 2
    house_height = int(size * 0.7)
    roof_height = int(house_height * 0.35)

    # Draw roof (triangle)
    roof_center = house_x_start + house_width // 2
    for y in range(roof_height):
        for x in range(house_width):
            # Triangle edges
            left_edge = roof_center - (roof_height - y) * 2
            right_edge = roof_center + (roof_height - y) * 2
            if left_edge <= x <= right_edge:
                set_pixel(house_x_start + x, y, *fg_color)

    # Draw house body (rectangle below roof)
    body_height = house_height - roof_height
    body_x_start = house_x_start
    body_x_end = house_x_start + house_width
    body_y_start = roof_height
    body_y_end = roof_height + body_height

    for y in range(body_y_start, body_y_end):
        for x in range(body_x_start, body_x_end):
            set_pixel(x, y, *fg_color)

    # Compress image data (filter byte 0 for each row)
    raw_data = bytearray()
    for y in range(height):
        raw_data.append(0)  # Filter byte
        row_start = y * width * 3
        raw_data.extend(pixels[row_start : row_start + width * 3])

    # Build PNG
    def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        """Create a PNG chunk with type, data, and CRC."""
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", crc32(chunk_type + data))
        return length + chunk_type + data + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = make_chunk(b"IHDR", ihdr_data)
    idat_data = (
        zlib.compressobj(
            zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -zlib.MAX_WBITS
        ).compress(raw_data)
        + zlib.compressobj(
            zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -zlib.MAX_WBITS
        ).flush()
    )
    idat = make_chunk(b"IDAT", idat_data)
    iend = make_chunk(b"IEND", b"")

    return signature + ihdr + idat + iend


def main() -> int:
    """Create icons for 192x192 and 512x512."""
    scripts_dir = pathlib.Path(__file__).parent.parent.parent
    icons_dir = scripts_dir / "web" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    sizes = [192, 512]
    for size in sizes:
        icon_path = icons_dir / f"icon-{size}.png"
        icon_path.write_bytes(make_png(size))
        print(f"Created {icon_path}")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
