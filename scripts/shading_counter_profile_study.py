#!/usr/bin/env python3
"""Compare normal and instrumented fixed-tick captures across fire profiles/views."""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


PROFILES = ("effect-campfire", "effect-quiet", "effect-bonfire")
CAMERAS = ("hero", "smoke-close", "fire-study", "orthographic")
STYLES = ("ink", "volume")
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
    with tempfile.TemporaryDirectory(prefix="pixel-engine-counter-scenes-") as temporary:
        temporary = Path(temporary)
        for style in STYLES:
            scene_data = json.loads(args.scene.read_text())
            for emitter in scene_data["emitters"]:
                emitter["style"] = style
            scene_path = temporary / f"profiling-heavy-{style}.json"
            scene_path.write_text(json.dumps(scene_data))
            scene_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
            for profile in PROFILES:
                for camera in CAMERAS:
                    variants = {}
                    paths = {}
                    for label, diagnostic in (("normal", False), ("diagnostic", True)):
                        image = args.output / f"{style}-{profile}-{camera}-{label}.png"
                        paths[label] = image
                        command = [str(args.binary), "capture", "--scene", str(scene_path), "--camera", camera,
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
                                raise RuntimeError(f"missing shading counters: {style}/{profile}/{camera}")
                            variants["counters"] = counters
                            variants["diagnostic_scratch_bytes"] = metadata["capabilities"]["resource_inventory"][
                                "shading_diagnostic_targets_bytes"
                            ]
                    difference = pixel_difference(paths["normal"], paths["diagnostic"])
                    captures.append({
                        "style": style,
                        "profile": profile,
                        "camera": camera,
                        "scene": str(args.scene),
                        "scene_variant_sha256": scene_hash,
                        "seed": args.seed,
                        "tick": args.tick,
                        "normal": variants["normal"],
                        "diagnostic": variants["diagnostic"],
                        "pixel_identical": variants["normal"]["pixel_sha256"] == variants["diagnostic"]["pixel_sha256"],
                        "pixel_difference": difference,
                        "counters": variants["counters"],
                        "counts_per_output_pixel": {
                            name: count / (640 * 360)
                            for name, count in variants["counters"].items()
                        },
                        "volume_path_partition_valid": (
                            variants["counters"]["volume_pixel_invocations"]
                            == variants["counters"]["soft_volume_pixel_invocations"]
                            + variants["counters"]["inked_smoke_pixel_invocations"]
                        ),
                        "diagnostic_scratch_bytes": variants["diagnostic_scratch_bytes"],
                    })
    report = {
        "version": 1,
        "purpose": "Expand O01 counter coverage across inked and soft volume styles, three fire profiles and four named views; counts are not timings.",
        "scene": str(args.scene),
        "seed": args.seed,
        "tick": args.tick,
        "resolution": [640, 360],
        "profiles": list(PROFILES),
        "styles": list(STYLES),
        "cameras": list(CAMERAS),
        "binary_sha256": file_hash(args.binary),
        "runner_sha256": file_hash(Path(__file__).resolve()),
        "captures": captures,
        "expected_capture_count": len(STYLES) * len(PROFILES) * len(CAMERAS),
        "matrix_complete": len(captures) == len(STYLES) * len(PROFILES) * len(CAMERAS),
        "all_pixel_identical": all(row["pixel_identical"] for row in captures),
        "all_volume_path_partitions_valid": all(row["volume_path_partition_valid"] for row in captures),
        "scope": "Fixed-tick diagnostic counts, not timing. Counts per output pixel normalize workload coverage and are not per-operation costs. Normal rendering produces the image; instrumented world, volume and optical draws then write to lazily allocated scratch targets while reading the normal depth and scene inputs. No continuous-motion claim.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    passed = (
        report["matrix_complete"]
        and report["all_pixel_identical"]
        and report["all_volume_path_partitions_valid"]
    )
    print(json.dumps({"report": str(args.report), "captures": len(captures),
                      "path_partition_valid": report["all_volume_path_partitions_valid"],
                      "all_pixel_identical": report["all_pixel_identical"],
                      "matrix_complete": report["matrix_complete"]}))
    if not passed:
        raise SystemExit("counter profile study failed: inspect the report for incomplete captures, image changes, or invalid path counts")


if __name__ == "__main__":
    main()
