"""Tests for app icons."""

import pathlib
import struct

import pytest


@pytest.mark.parametrize("size", [192, 512])
def test_icon_files_exist(size):
    """Check that icon files exist."""
    web_dir = pathlib.Path(__file__).parent.parent.parent / "web"
    icons_dir = web_dir / "icons"
    icon_path = icons_dir / f"icon-{size}.png"
    assert icon_path.exists(), f"Icon file not found: {icon_path}"


@pytest.mark.parametrize("size", [192, 512])
def test_icon_png_signature(size):
    """Check PNG signature."""
    web_dir = pathlib.Path(__file__).parent.parent.parent / "web"
    icons_dir = web_dir / "icons"
    icon_path = icons_dir / f"icon-{size}.png"
    data = icon_path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), (
        f"Invalid PNG signature in icon-{size}.png"
    )


@pytest.mark.parametrize("width,height", [(192, 192), (512, 512)])
def test_icon_ihdr(width, height):
    """Check IHDR chunk width and height."""
    web_dir = pathlib.Path(__file__).parent.parent.parent / "web"
    icons_dir = web_dir / "icons"
    icon_path = icons_dir / f"icon-{width}.png"
    data = icon_path.read_bytes()

    # IHDR chunk is at offset 8, length 13 bytes (1 byte type + 8 bytes data + 4 bytes CRC)
    # IHDR data starts at offset 8 + 4 (length) + 4 (type) = 16
    ihdr_data = data[16:24]
    ihdr_width, ihdr_height = struct.unpack(">II", ihdr_data)
    assert ihdr_width == width, (
        f"IHDR width mismatch: expected {width}, got {ihdr_width}"
    )
    assert ihdr_height == height, (
        f"IHDR height mismatch: expected {height}, got {ihdr_height}"
    )


def test_manifest_lists_icons():
    """Check that manifest.json lists both icon files."""
    manifest_path = (
        pathlib.Path(__file__).parent.parent.parent / "web" / "manifest.json"
    )
    manifest = manifest_path.read_text()
    assert "icon-192.png" in manifest, "manifest.json should list icon-192.png"
    assert "icon-512.png" in manifest, "manifest.json should list icon-512.png"
