#!/usr/bin/env python3
"""Exercise the RGBA16F effect-target fallback on an adapter with Rg16Float."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("profiling-heavy", "assets/scenes/profiling-heavy.json", "fire-study"),
    ("materials", "assets/scenes/materials.json", "hero"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_images(baseline: Path, fallback: Path) -> dict:
    with Image.open(baseline) as image:
        baseline_pixels = image.convert("RGB")
    with Image.open(fallback) as image:
        fallback_pixels = image.convert("RGB")
    if baseline_pixels.size != fallback_pixels.size:
        raise RuntimeError("capture resolutions differ")
    difference = ImageChops.difference(baseline_pixels, fallback_pixels)
    extrema = difference.getextrema()
    return {
        "pixel_identical": baseline_pixels.tobytes() == fallback_pixels.tobytes(),
        "changed_pixels": sum(any(pixel) for pixel in difference.getdata()),
        "total_pixels": baseline_pixels.width * baseline_pixels.height,
        "mean_absolute_channel_error": sum(ImageStat.Stat(difference).mean) / 3,
        "max_channel_error": max(high for _, high in extrema),
        "difference_bounds": list(difference.getbbox()) if difference.getbbox() else None,
    }


def capture(binary: Path, scene: Path, camera: str, output: Path, force_fallback: bool) -> dict:
    command = [
        str(binary), "capture", "--scene", str(scene), "--camera", camera,
        "--seed", "42", "--tick", "120", "--resolution", "640x360", "--scale", "1",
        "--output", str(output),
    ]
    if force_fallback:
        command.append("--force-rg16-fallback")
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return json.loads(output.with_suffix(".json").read_text())


def capture_motion(binary: Path, output: Path, force_fallback: bool) -> dict:
    command = [
        "python3", str(ROOT / "scripts/capture_motion.py"),
        "--binary", str(binary), "--scene", str(ROOT / "assets/scenes/profiling-heavy.json"),
        "--camera", "fire-study", "--seed", "42", "--route", "clearing-orbit",
        "--start-tick", "120", "--frames", "120", "--stride", "3", "--output", str(output),
    ]
    if force_fallback:
        command.append("--force-rg16-fallback")
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return json.loads((output / "sequence.json").read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o08/rg16-fallback")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o08-rg16-fallback.json")
    args = parser.parse_args()
    binary = args.binary.resolve()
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for name, scene_name, camera in CASES:
        scene = ROOT / scene_name
        baseline_image = output_dir / f"{name}-native-rg16.png"
        fallback_image = output_dir / f"{name}-forced-rgba16.png"
        baseline = capture(binary, scene, camera, baseline_image, False)
        fallback = capture(binary, scene, camera, fallback_image, True)
        base_caps = baseline["capabilities"]
        fallback_caps = fallback["capabilities"]
        base_inventory = base_caps["resource_inventory"]
        fallback_inventory = fallback_caps["resource_inventory"]
        if fallback_inventory.get("rg16_fallback_forced") is not True:
            raise RuntimeError(f"{name}: fallback override was not reported")
        if fallback_inventory["effect_depth_format"] != "Rgba16Float":
            raise RuntimeError(f"{name}: effect-depth fallback format was not selected")
        if fallback_inventory["smoke_volume_format"] != "Rgba16Float":
            raise RuntimeError(f"{name}: smoke-volume fallback format was not selected")
        if base_caps["backend"] != fallback_caps["backend"] or base_caps["name"] != fallback_caps["name"]:
            raise RuntimeError(f"{name}: comparison did not use the same adapter")
        results.append({
            "scene": scene_name,
            "scene_sha256": sha256(scene),
            "camera": camera,
            "adapter": base_caps["name"],
            "backend": base_caps["backend"],
            "seed": 42,
            "tick": 120,
            "resolution": [640, 360],
            "baseline": {
                "image": str(baseline_image.relative_to(ROOT)),
                "effect_depth_format": base_inventory["effect_depth_format"],
                "smoke_volume_format": base_inventory["smoke_volume_format"],
                "known_gpu_allocation_bytes": base_inventory["known_gpu_allocation_bytes"],
            },
            "fallback": {
                "image": str(fallback_image.relative_to(ROOT)),
                "forced": fallback_inventory["rg16_fallback_forced"],
                "effect_depth_format": fallback_inventory["effect_depth_format"],
                "smoke_volume_format": fallback_inventory["smoke_volume_format"],
                "known_gpu_allocation_bytes": fallback_inventory["known_gpu_allocation_bytes"],
            },
            "allocation_delta_bytes": fallback_inventory["known_gpu_allocation_bytes"] - base_inventory["known_gpu_allocation_bytes"],
            "image_comparison": compare_images(baseline_image, fallback_image),
        })
    motion_baseline_dir = output_dir / "motion-native-rg16"
    motion_fallback_dir = output_dir / "motion-forced-rgba16"
    motion_baseline = capture_motion(binary, motion_baseline_dir, False)
    motion_fallback = capture_motion(binary, motion_fallback_dir, True)
    if len(motion_baseline["frames"]) != len(motion_fallback["frames"]):
        raise RuntimeError("moving-route capture counts differ")
    motion_frames = []
    for index, (baseline_frame, fallback_frame) in enumerate(zip(motion_baseline["frames"], motion_fallback["frames"])):
        if baseline_frame["tick"] != fallback_frame["tick"]:
            raise RuntimeError("moving-route capture ticks differ")
        motion_frames.append({
            "index": index,
            "tick": baseline_frame["tick"],
            "image_comparison": compare_images(Path(baseline_frame["image"]), Path(fallback_frame["image"])),
        })
    report = {
        "version": 1,
        "date": "2026-10-18",
        "purpose": "Render the RGBA16F effect-depth and smoke-volume fallback on an adapter that normally selects Rg16Float.",
        "adapter": {
            "name": results[0]["adapter"],
            "backend": results[0]["backend"],
            "fallback_kind": "forced capability-selection fallback; not evidence from hardware lacking Rg16Float support",
        },
        "binary_sha256": sha256(binary),
        "cases": results,
        "moving_route": {
            "scene": "assets/scenes/profiling-heavy.json",
            "route": "clearing-orbit",
            "seed": 42,
            "start_tick": 120,
            "frame_stride_ticks": 3,
            "captured_frames_per_variant": len(motion_frames),
            "native_sequence": str((motion_baseline_dir / "sequence.json").relative_to(ROOT)),
            "fallback_sequence": str((motion_fallback_dir / "sequence.json").relative_to(ROOT)),
            "frame_comparisons": motion_frames,
            "all_frames_pixel_identical": all(frame["image_comparison"]["pixel_identical"] for frame in motion_frames),
            "mean_changed_pixels": sum(frame["image_comparison"]["changed_pixels"] for frame in motion_frames) / len(motion_frames),
            "max_channel_error": max(frame["image_comparison"]["max_channel_error"] for frame in motion_frames),
        },
        "all_pixel_identical": all(case["image_comparison"]["pixel_identical"] for case in results),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "motion_capture_runner_sha256": sha256(ROOT / "scripts/capture_motion.py"),
        "limitations": [
            "Both captures use the same Apple M1 Max/Metal adapter; the fallback is selected through a diagnostic CLI override.",
            "This exercises fallback resource and shader creation but does not replace physical validation on an adapter without the Rg16Float capabilities.",
            "Fixed-tick images do not establish temporal or performance parity.",
            "The moving-route comparison samples 120 frames at 20 fps; it is temporal evidence, not a 120-second sustained performance study.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(args.report), "all_pixel_identical": report["all_pixel_identical"], "cases": len(results)}))


if __name__ == "__main__":
    main()
