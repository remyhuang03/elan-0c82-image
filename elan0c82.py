#!/usr/bin/env python3
"""Experimental image capture for the ELAN 04f3:0c82 fingerprint reader."""

from __future__ import annotations

import argparse
import os
import sys
import time
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


def read_frame(handle, width: int, height: int) -> bytes:
    handle.bulkWrite(COMMAND_OUT, CAPTURE_COMMAND, timeout=2000)
    data = bytes(handle.bulkRead(IMAGE_IN, 2 * width * height, timeout=10000))
    return normalize_image(data, width, height)


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


def save_mosaic(path: Path, rgba) -> None:
    from PIL import Image

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            Image.fromarray(rgba, "RGBA").save(output, format="PNG")
            output.flush()
            os.fsync(output.fileno())
        if os.geteuid() == 0 and "SUDO_UID" in os.environ:
            os.chown(temporary, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def run_mosaic(handle, width: int, height: int, output: Path, max_frames: int,
               frames_dir: Path | None) -> int:
    import numpy as np

    from fingerprint_mosaic import Mosaic

    mosaic = Mosaic()
    if frames_dir is not None:
        frames_dir.mkdir(mode=0o700)
        if os.geteuid() == 0 and "SUDO_UID" in os.environ:
            os.chown(frames_dir, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
    attempts = 0
    print("Capture adjacent patches of the same finger. Keep at least half of each patch overlapping.")
    print("Use similar pressure and avoid rotating the finger sharply.")
    while len(mosaic.tiles) < max_frames:
        if not mosaic.tiles:
            response = input("Touch the center of the finger to the sensor, then press Enter (q quits): ")
        else:
            response = input("Shift the finger slightly, then Enter to scan; q saves, u undoes: ")
        if response.lower().strip() == "q":
            break
        if response.lower().strip() == "u":
            if len(mosaic.tiles) > 1:
                mosaic.rebuild_without_last()
                image, _ = mosaic.render()
                save_mosaic(output, image)
                print(f"Undid last tile; {len(mosaic.tiles)} remain")
            else:
                print("Nothing to undo")
            continue
        if response.strip():
            print("Press Enter to scan, or q to finish")
            continue
        try:
            pixels = read_frame(handle, width, height)
        except ValueError as error:
            print(f"Frame rejected: {error}")
            continue
        attempts += 1
        if frames_dir is not None:
            save_png(frames_dir / f"frame-{attempts:03d}.png", pixels, width, height)
        tile = np.frombuffer(pixels, np.uint8).reshape(height, width).copy()
        match = mosaic.propose(tile)
        if match is None:
            print("No reliable overlap found. Move back toward the last position and try again.")
            continue
        if mosaic.tiles and match.new_fraction < 0.04:
            print(f"Only {match.new_fraction:.0%} new area. Move farther, keeping overlap.")
            continue
        mosaic.add(tile, match)
        image, _ = mosaic.render()
        save_mosaic(output, image)
        detail = "first tile" if match.reference < 0 else (
            f"match {match.correlation:.2f}, {match.inliers} inliers, {match.new_fraction:.0%} new area"
        )
        print(f"Accepted {len(mosaic.tiles)} tiles ({detail}); mosaic {image.shape[1]}x{image.shape[0]}")
        print(f"Preview: {output}")
    if not mosaic.tiles:
        print("No image captured")
        return 1
    print(f"Saved observed area to {output}. Transparent pixels have not been scanned.")
    return 0


def run_full(handle, width: int, height: int, output: Path, seconds: float,
             max_frames: int, passes: int, frames_dir: Path | None) -> int:
    import numpy as np

    from fingerprint_mosaic import Mosaic

    if frames_dir is not None:
        frames_dir.mkdir(mode=0o700)
        if os.geteuid() == 0 and "SUDO_UID" in os.environ:
            os.chown(frames_dir, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
    mosaic = Mosaic()
    for pass_number in range(1, passes + 1):
        response = input(f"Pass {pass_number}/{passes}: keep contact and slowly roll or slide. "
                         "Enter starts, q finishes: ")
        if response.strip().lower() == "q":
            break
        deadline = time.monotonic() + seconds
        frames = []
        blanks = 0
        while time.monotonic() < deadline and len(frames) < max_frames:
            try:
                pixels = read_frame(handle, width, height)
            except ValueError as error:
                if "all pixels have the same value" not in str(error):
                    raise
                if frames:
                    blanks += 1
                    if blanks >= 3:
                        break
                continue
            blanks = 0
            image = np.frombuffer(pixels, np.uint8).reshape(height, width).copy()
            if image.mean() < 60 or image.std() < 25:
                continue
            if frames and np.mean(np.abs(image.astype(np.int16) - frames[-1])) < 3:
                continue
            frames.append(image)
            if frames_dir is not None:
                pass_dir = frames_dir / f"pass-{pass_number:02d}"
                if not pass_dir.exists():
                    pass_dir.mkdir(mode=0o700)
                    if os.geteuid() == 0 and "SUDO_UID" in os.environ:
                        os.chown(pass_dir, int(os.environ["SUDO_UID"]),
                                 int(os.environ["SUDO_GID"]))
                save_png(pass_dir / f"frame-{len(frames):03d}.png", pixels, width, height)
        print(f"Pass {pass_number}: captured {len(frames)} candidate frames", flush=True)
        before = len(mosaic.tiles)
        for index, frame in enumerate(frames, 1):
            if mosaic.tiles and np.mean(np.abs(
                    frame.astype(np.int16) - mosaic.tiles[-1].image)) < 6:
                continue
            match = mosaic.propose(frame)
            if match is None or (mosaic.tiles and match.new_fraction < 0.025):
                continue
            mosaic.add(frame, match)
            if index % 20 == 0:
                print(f"  processed {index}/{len(frames)} frames", flush=True)
        added = len(mosaic.tiles) - before
        if not mosaic.tiles:
            print("No usable fingerprint frame in this pass")
            continue
        result, _ = mosaic.render()
        save_mosaic(output, result)
        coverage = float((result[:, :, 3] > 0).mean())
        print(f"Pass {pass_number}: added {added} tiles; observed "
              f"{result.shape[1]}x{result.shape[0]} px; "
              f"{coverage:.0%} of that rectangle scanned; preview {output}", flush=True)
        if added == 0:
            print("No overlap connected this pass to the existing mosaic. Try a closer position.")
    if not mosaic.tiles:
        print("No image captured")
        return 1
    if len(mosaic.tiles) == 1:
        print("Only one 80x80 tile was registered; full-area capture has not succeeded.")
        return 2
    print(f"Saved observed area to {output}. Transparent pixels were not scanned.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("probe", help="query the sensor dimensions")
    capture = subparsers.add_parser("capture", help="capture one image as PNG")
    capture.add_argument("output", type=Path)
    capture.add_argument("--yes", action="store_true", help="skip the touch-and-Enter prompt")
    mosaic = subparsers.add_parser("mosaic", help="join overlapping scans of one finger")
    mosaic.add_argument("output", type=Path)
    mosaic.add_argument("--max-frames", type=int, default=40)
    mosaic.add_argument("--keep-frames", type=Path, metavar="DIR",
                        help="save every nonblank frame locally for debugging")
    full = subparsers.add_parser("full", help="capture several overlapping rolls or slides")
    full.add_argument("output", type=Path)
    full.add_argument("--passes", type=int, default=4)
    full.add_argument("--seconds", type=float, default=8.0)
    full.add_argument("--max-frames", type=int, default=100)
    full.add_argument("--keep-frames", type=Path, metavar="DIR")
    args = parser.parse_args()

    if args.action in ("capture", "mosaic", "full") and args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.action in ("mosaic", "full") and args.max_frames < 1:
        parser.error("--max-frames must be positive")
    if args.action == "full" and args.passes < 1:
        parser.error("--passes must be positive")
    if args.action == "full" and args.seconds <= 0:
        parser.error("--seconds must be positive")
    if args.action in ("mosaic", "full") and args.keep_frames is not None and args.keep_frames.exists():
        parser.error(f"frames directory already exists: {args.keep_frames}")

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
                    if args.action == "mosaic":
                        return run_mosaic(handle, width, height, args.output,
                                          args.max_frames, args.keep_frames)
                    if args.action == "full":
                        return run_full(handle, width, height, args.output, args.seconds,
                                        args.max_frames, args.passes, args.keep_frames)
                    if not args.yes:
                        input("Touch the sensor with your finger, then press Enter...")
                    pixels = read_frame(handle, width, height)

        save_png(args.output, pixels, width, height)
        print(f"Saved {args.output}")
        return 0
    except (OSError, RuntimeError, ValueError, EOFError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped. Any accepted mosaic tiles remain in the output PNG.", file=sys.stderr)
        return 130
    except Exception as error:
        if error.__class__.__module__.startswith("usb1"):
            print(f"USB error: {error}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
