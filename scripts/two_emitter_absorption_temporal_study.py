#!/usr/bin/env python3
"""Compare direct and cached absorption over a deterministic two-emitter orbit."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/two-emitter-review.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_error(image: Image.Image) -> tuple[float, int]:
    histogram = image.histogram()[:768]
    channels = (histogram[:256], histogram[256:512], histogram[512:768])
    total = sum(sum(channel) for channel in channels)
    weighted = sum(value * count for channel in channels for value, count in enumerate(channel))
    mean = weighted / total if total else 0.0
    maximum = max((value for channel in channels for value, count in enumerate(channel) if count), default=0)
    return mean, maximum


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o02/two-emitter-absorption-temporal")
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--start-tick", type=int, default=300)
    parser.add_argument("--cache-resolution", type=int, choices=(8, 16), default=8)
    args = parser.parse_args()
    if not 2 <= args.frames <= 600 or not 1 <= args.stride <= 60 or not 0 <= args.start_tick <= 36000:
        parser.error("frames must be 2..600, stride 1..60, and start-tick 0..36000")

    binary, output = args.binary.resolve(), args.output.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)
    source_scene = json.loads(SOURCE.read_text())
    if len(source_scene.get("emitters", [])) != 2:
        raise SystemExit("source scene must contain exactly two emitters")
    if not any(camera.get("id") == "dual-wide" for camera in source_scene.get("cameras", [])):
        raise SystemExit("source scene is missing the dual-wide camera")

    sequences = {}
    scene_paths = {}
    for name, enabled in (("direct", False), ("cached", True)):
        scene = json.loads(json.dumps(source_scene))
        scene["render"]["absorption_cache_resolution"] = args.cache_resolution
        scene["render"].setdefault("experiments", {})["smoke_absorption_cache"] = enabled
        scene_path = output / f"{name}.scene.json"
        scene_path.write_text(json.dumps(scene, indent=2) + "\n")
        scene_paths[name] = scene_path
        frame_dir = output / name
        subprocess.run([
            "python3", str(ROOT / "scripts/capture_motion.py"),
            "--binary", str(binary), "--scene", str(scene_path),
            "--camera", "dual-wide", "--seed", "42", "--profile", "",
            "--start-tick", str(args.start_tick),
            "--frames", str(args.frames), "--stride", str(args.stride),
            "--output", str(frame_dir),
        ], cwd=ROOT, check=True)
        sequences[name] = json.loads((frame_dir / "sequence.json").read_text())

    direct, cached = sequences["direct"]["frames"], sequences["cached"]["frames"]
    if len(direct) != len(cached):
        raise RuntimeError("frame counts differ")
    frame_mae, temporal_mae = [], []
    max_channel_difference = 0
    state_match = True
    previous_direct = previous_cached = None
    contact_indices = sorted(set((0, (args.frames - 1) // 4, (args.frames - 1) // 2,
                                  3 * (args.frames - 1) // 4, args.frames - 1)))
    contact = []
    for index, (base, candidate) in enumerate(zip(direct, cached)):
        if base["tick"] != candidate["tick"] or base["camera"] != candidate["camera"]:
            raise RuntimeError(f"frame {index}: tick/camera mismatch")
        base_metadata = json.loads(Path(base["metadata"]).read_text())
        candidate_metadata = json.loads(Path(candidate["metadata"]).read_text())
        base_metrics, candidate_metrics = base_metadata["metrics"], candidate_metadata["metrics"]
        state_match &= all(base_metrics.get(key) == candidate_metrics.get(key) for key in (
            "fire_primitives_full", "fire_segments_full", "embers", "particle_lights", "flame_fragments"
        ))
        base_image = Image.open(base["image"]).convert("RGB")
        candidate_image = Image.open(candidate["image"]).convert("RGB")
        difference = ImageChops.difference(base_image, candidate_image)
        mae, maximum = image_error(difference)
        frame_mae.append(mae)
        max_channel_difference = max(max_channel_difference, maximum)
        if previous_direct is not None:
            direct_motion = ImageChops.difference(base_image, previous_direct)
            candidate_motion = ImageChops.difference(candidate_image, previous_cached)
            temporal_mae.append(image_error(ImageChops.difference(direct_motion, candidate_motion))[0])
        if index in contact_indices:
            contact.append((index, base_image.copy(), candidate_image.copy(), difference.copy()))
        previous_direct, previous_cached = base_image, candidate_image

    sorted_frame, sorted_temporal = sorted(frame_mae), sorted(temporal_mae)
    p95 = lambda values: values[int(0.95 * (len(values) - 1))]
    report = {
        "date": "2026-10-18",
        "workstream": "O02 dual-source absorption-cache temporal comparison",
        "host": {"device": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "source_scene": str(SOURCE.relative_to(ROOT)),
        "source_scene_sha256": sha256(SOURCE),
        "scene_sha256": {name: sha256(path) for name, path in scene_paths.items()},
        "binary_sha256": sequences["direct"]["binary_sha256"],
        "capture_script_sha256": sequences["direct"]["capture_script_sha256"],
        "study_script_sha256": sha256(Path(__file__).resolve()),
        "source_ids": sorted(emitter["id"] for emitter in source_scene["emitters"]),
        "seed": 42,
        "camera": "dual-wide",
        "route": None,
        "resolution": source_scene["render"]["resolution"],
        "cache_resolution": [args.cache_resolution] * 3,
        "start_tick": args.start_tick,
        "end_tick": direct[-1]["tick"],
        "frames": args.frames,
        "fps": 60 / args.stride,
        "effect_counts_match_every_frame": state_match,
        "frame_rgb_mae_mean": statistics.mean(frame_mae),
        "frame_rgb_mae_p95": p95(sorted_frame),
        "frame_rgb_mae_max": max(frame_mae),
        "max_channel_difference": max_channel_difference,
        "temporal_change_magnitude_rgb_mae_mean": statistics.mean(temporal_mae),
        "temporal_change_magnitude_rgb_mae_p95": p95(sorted_temporal),
        "method": "The fixed dual-wide camera frames both emitters while simulation advances by the same fixed tick stride for direct and cached variants.",
        "visual_review": "Contact sheet is provided for inspection; continuous playback acceptance is not claimed.",
        "limitations": ["One M1 Max/Metal offscreen route; native-window and other-adapter behavior remain unverified."],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    sheet = Image.new("RGB", (970, 185 * len(contact)), (22, 22, 22))
    draw = ImageDraw.Draw(sheet)
    for row, (index, base, candidate, difference) in enumerate(contact):
        y = row * 185
        for x, image in ((0, base), (325, candidate), (650, difference.point(lambda channel: min(255, channel * 5)))):
            sheet.paste(image.resize((320, 180)), (x, y))
        draw.text((4, y + 2), f"{index}: direct", fill="white")
        draw.text((329, y + 2), f"{index}: cache", fill="white")
        draw.text((654, y + 2), f"{index}: 5x diff", fill="white")
    sheet.save(output / "temporal-contact.png")
    print(json.dumps({"report": str(output / "report.json"), "contact_sheet": str(output / "temporal-contact.png"),
                      "effect_counts_match_every_frame": state_match,
                      "frame_rgb_mae_mean": report["frame_rgb_mae_mean"]}))
    return 0 if state_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
