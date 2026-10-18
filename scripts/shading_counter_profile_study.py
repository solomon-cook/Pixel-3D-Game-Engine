#!/usr/bin/env python3
"""Compare normal and instrumented fixed-tick captures across fire profiles/views."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


PROFILES = ("effect-campfire", "effect-quiet", "effect-bonfire")
CAMERAS = ("hero", "smoke-close", "fire-study", "orthographic")
def pixel_hash(path: Path) -> str:
    with Image.open(path) as image:
        pixels = image.convert("RGBA").tobytes()
    return hashlib.sha256(pixels).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixel_difference(normal: Path, diagnostic: Path) -> dict:
    with Image.open(normal) as image:
        baseline = image.convert("RGB")
    with Image.open(diagnostic) as image:
        candidate = image.convert("RGB")
    diff = ImageChops.difference(baseline, candidate)
    bbox = diff.getbbox()
    extrema = diff.getextrema()
    return {
        "changed_pixels": sum(any(pixel) for pixel in diff.getdata()),
        "total_pixels": baseline.width * baseline.height,
        "mean_absolute_channel_error": sum(ImageStat.Stat(diff).mean) / 3,
        "max_channel_error": max(high for _, high in extrema),
        "difference_bounds": list(bbox) if bbox else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=Path("target/debug/engine-lab"))
    parser.add_argument("--scene", type=Path, default=Path("assets/scenes/profiling-heavy.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/o01-counter-profile-scope"))
    parser.add_argument("--report", type=Path, default=Path("docs/measurements-o01-counter-profile-scope.json"))
    parser.add_argument("--tick", type=int, default=120)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    args.scene = args.scene.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    captures = []
    for profile in PROFILES:
        for camera in CAMERAS:
            variants = {}
            paths = {}
            for label, diagnostic in (("normal", False), ("diagnostic", True)):
                image = args.output / f"{profile}-{camera}-{label}.png"
                paths[label] = image
                command = [str(args.binary), "capture", "--scene", str(args.scene), "--camera", camera,
                           "--seed", str(args.seed), "--tick", str(args.tick), "--resolution", "640x360",
                           "--scale", "1", "--effect-profile", profile, "--output", str(image)]
                if diagnostic:
                    command.append("--shading-counters")
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
                metadata = json.loads(image.with_suffix(".json").read_text())
                variants[label] = {
                    "image": str(image),
                    "pixel_sha256": pixel_hash(image),
                    "backend": metadata["capabilities"]["backend"],
                    "adapter": metadata["capabilities"]["name"],
                    "resolution": metadata["capabilities"]["resolution"],
                }
                if diagnostic:
                    counters = metadata["metrics"].get("shading_counters")
                    if not counters:
                        raise RuntimeError(f"missing shading counters: {profile}/{camera}")
                    variants["counters"] = counters
                    variants["diagnostic_scratch_bytes"] = metadata["capabilities"]["resource_inventory"][
                        "shading_diagnostic_targets_bytes"
                    ]
            difference = pixel_difference(paths["normal"], paths["diagnostic"])
            captures.append({
                "profile": profile,
                "camera": camera,
                "scene": str(args.scene),
                "seed": args.seed,
                "tick": args.tick,
                "normal": variants["normal"],
                "diagnostic": variants["diagnostic"],
                "pixel_identical": variants["normal"]["pixel_sha256"] == variants["diagnostic"]["pixel_sha256"],
                "pixel_difference": difference,
                "counters": variants["counters"],
                "diagnostic_scratch_bytes": variants["diagnostic_scratch_bytes"],
            })
    report = {
        "version": 1,
        "purpose": "Expand O01 counter coverage across three fire profiles and four named views; counts are not timings.",
        "scene": str(args.scene),
        "seed": args.seed,
        "tick": args.tick,
        "resolution": [640, 360],
        "profiles": list(PROFILES),
        "cameras": list(CAMERAS),
        "binary_sha256": file_hash(args.binary),
        "runner_sha256": file_hash(Path(__file__).resolve()),
        "captures": captures,
        "all_pixel_identical": all(row["pixel_identical"] for row in captures),
        "scope": "Fixed-tick diagnostic counts, not timing. Normal rendering produces the image; instrumented world, volume and optical draws then write to lazily allocated scratch targets while reading the normal depth and scene inputs. No continuous-motion claim.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(args.report), "captures": len(captures),
                      "all_pixel_identical": report["all_pixel_identical"]}))


if __name__ == "__main__":
    main()
