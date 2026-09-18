#!/usr/bin/env python3
"""Check the capture region against the live game.

Grabs the whole game window and the configured region, saves both to debug/,
and prints what tesseract makes of the region. Use it to tune
[capture.region] in config.toml until the area name is read cleanly.

    tools/calibrate.py            # uses config.toml
    tools/calibrate.py 0.84 0.02 0.155 0.09   # try a region without editing config
"""

import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import areas  # noqa: E402
import capture  # noqa: E402
import ocr  # noqa: E402


def main(argv):
    config = tomllib.load(open(HERE / "config.toml", "rb"))["capture"]
    if len(argv) == 4:
        region = capture.Region(*map(float, argv))
    else:
        region = capture.Region(**config["region"])
    debug = HERE / "debug"
    debug.mkdir(exist_ok=True)

    cam = capture.make(config.get("backend", "xwayland"), display_name=config.get("display"))
    try:
        width, height = cam.window_size()
    except capture.CaptureError as exc:
        print(f"error: {exc}")
        return 1
    print(f"game window: {width}x{height}")
    print(f"region: {region} -> pixels {region.to_pixels(width, height)}")

    frame = cam.grab()
    frame.save(debug / "frame.png")
    crop = cam.grab(region)
    crop.save(debug / "crop.png")
    processed = ocr.preprocess(crop)
    processed.save(debug / "processed.png")
    print(f"saved {debug}/frame.png, crop.png, processed.png")

    raw = ocr.run_tesseract(processed)
    print("tesseract:")
    for line in raw.splitlines():
        print(f"    {line!r}")
    reading = ocr.recognise(raw, list(areas.load()))
    print(f"match: {reading.area!r} (score {reading.score:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
