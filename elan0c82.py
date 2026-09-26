#!/usr/bin/env python3
"""Experimental image capture for the ELAN 04f3:0c82 fingerprint reader."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import closing
from pathlib import Path

VENDOR_ID = 0x04F3
PRODUCT_ID = 0x0C82
INTERFACE = 0
COMMAND_OUT = 0x01
RESPONSE_IN = 0x83
IMAGE_IN = 0x82
SIZE_COMMAND = b"\x00\x0c"
CAPTURE_COMMAND = b"\x00\x09"


def decode_size(response: bytes) -> tuple[int, int]:
    if len(response) != 4:
        raise ValueError(f"size response has {len(response)} bytes, expected 4")
    width, height = response[0] + 1, response[2] + 1
    if not (16 <= width <= 256 and 16 <= height <= 256):
        raise ValueError(f"implausible sensor size: {width}x{height}")
    return width, height


def normalize_image(data: bytes, width: int, height: int) -> bytes:
    expected = width * height * 2
    if len(data) != expected:
        raise ValueError(f"image has {len(data)} bytes, expected {expected}")
    pixels = [int.from_bytes(data[i : i + 2], "little") for i in range(0, expected, 2)]
    low, high = min(pixels), max(pixels)
    if low == high:
        raise ValueError("all pixels have the same value; no usable image was returned")
    return bytes(round((pixel - low) * 255 / (high - low)) for pixel in pixels)


def get_size(handle) -> tuple[int, int]:
    handle.bulkWrite(COMMAND_OUT, SIZE_COMMAND, timeout=2000)
    return decode_size(bytes(handle.bulkRead(RESPONSE_IN, 4, timeout=2000)))


def save_png(path: Path, pixels: bytes, width: int, height: int) -> None:
    from PIL import Image

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            Image.frombytes("L", (width, height), pixels).save(output, format="PNG")
            output.flush()
            os.fsync(output.fileno())
        if os.geteuid() == 0 and "SUDO_UID" in os.environ:
            os.chown(path, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("probe", help="query the sensor dimensions")
    capture = subparsers.add_parser("capture", help="capture one image as PNG")
    capture.add_argument("output", type=Path)
    capture.add_argument("--yes", action="store_true", help="skip the touch-and-Enter prompt")
    args = parser.parse_args()

    if args.action == "capture" and args.output.exists():
        parser.error(f"output already exists: {args.output}")

    try:
        import usb1

        with usb1.USBContext() as context:
            handle = context.openByVendorIDAndProductID(VENDOR_ID, PRODUCT_ID)
            if handle is None:
                raise RuntimeError("ELAN 04f3:0c82 not found or cannot be opened")
            with closing(handle):
                with handle.claimInterface(INTERFACE):
                    width, height = get_size(handle)
                    print(f"Sensor reports {width}x{height} pixels")
                    if args.action == "probe":
                        return 0
                    if not args.yes:
                        input("Touch the sensor with your finger, then press Enter...")
                    handle.bulkWrite(COMMAND_OUT, CAPTURE_COMMAND, timeout=2000)
                    data = bytes(handle.bulkRead(IMAGE_IN, 2 * width * height, timeout=10000))

        pixels = normalize_image(data, width, height)
        save_png(args.output, pixels, width, height)
        print(f"Saved {args.output}")
        return 0
    except (OSError, RuntimeError, ValueError, EOFError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        if error.__class__.__module__.startswith("usb1"):
            print(f"USB error: {error}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
