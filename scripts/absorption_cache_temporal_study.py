#!/usr/bin/env python3
"""Capture and compare direct versus cached smoke lighting on a fixed-tick route."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess

from PIL import Image, ImageChops, ImageDraw

from absorption_cache_study import ROOT, SOURCE, make_scenes, sha256


def rgb_mae(image: Image.Image) -> tuple[float, int]:
    histogram = image.histogram()
    channels = (histogram[:256], histogram[256:512], histogram[512:768])
    count = image.width * image.height * 3
    mean = sum(value * occurrences for channel in channels for value, occurrences in enumerate(channel)) / count
    maximum = max(value for channel in channels for value, occurrences in enumerate(channel) if occurrences)
    return mean, maximum


def summarize(output: Path, binary: Path, frames: int, stride: int, start_tick: int) -> dict:
    direct_path = output / "scenes/medium/direct.json"
    cache_path = output / "scenes/medium/cache16.json"
    direct_dir, cache_dir = output / "direct", output / "cache16"
    common = [
        "python3", str(ROOT / "scripts/capture_motion.py"), "--binary", str(binary),
        "--camera", "absorption-study", "--route", "absorption-cache-orbit",
        "--start-tick", str(start_tick), "--frames", str(frames), "--stride", str(stride),
    ]
    for scene, destination in ((direct_path, direct_dir), (cache_path, cache_dir)):
        subprocess.run(common + ["--scene", str(scene), "--output", str(destination)], cwd=ROOT, check=True)

    direct = json.loads((direct_dir / "sequence.json").read_text())
    cached = json.loads((cache_dir / "sequence.json").read_text())
    if len(direct["frames"]) != len(cached["frames"]):
        raise ValueError("direct and cached frame counts differ")

    frame_mae, temporal_mae = [], []
    max_channel_difference = 0
    state_match = True
    previous_direct = previous_cached = None
    contact_indices = sorted(set((0, (frames - 1) // 4, (frames - 1) // 2, 3 * (frames - 1) // 4, frames - 1)))
    contact = []
    for index, (base_frame, cache_frame) in enumerate(zip(direct["frames"], cached["frames"])):
        if base_frame["tick"] != cache_frame["tick"] or base_frame["camera"] != cache_frame["camera"]:
            raise ValueError(f"frame {index}: tick or camera mismatch")
        base_metadata = json.loads(Path(base_frame["metadata"]).read_text())
        cache_metadata = json.loads(Path(cache_frame["metadata"]).read_text())
        base_metrics, cache_metrics = base_metadata["metrics"], cache_metadata["metrics"]
        state_match &= all(base_metrics[key] == cache_metrics[key] for key in (
            "fire_primitives_full", "fire_segments_full", "embers", "particle_lights", "flame_fragments"
        ))
        base_image = Image.open(base_frame["image"]).convert("RGB")
        cache_image = Image.open(cache_frame["image"]).convert("RGB")
        difference = ImageChops.difference(base_image, cache_image)
        mae, maximum = rgb_mae(difference)
        frame_mae.append(mae)
        max_channel_difference = max(max_channel_difference, maximum)
        if previous_direct is not None:
            base_motion = ImageChops.difference(base_image, previous_direct)
            cache_motion = ImageChops.difference(cache_image, previous_cached)
            temporal_mae.append(rgb_mae(ImageChops.difference(base_motion, cache_motion))[0])
        if index in contact_indices:
            contact.append((index, base_image.copy(), cache_image.copy(), difference))
        previous_direct, previous_cached = base_image, cache_image

    ordered = sorted(frame_mae)
    ordered_temporal = sorted(temporal_mae)
    p95_index = lambda values: int(0.95 * (len(values) - 1))
    return {
        "date": "2026-10-18",
        "workstream": "O05 direct versus cached absorption temporal comparison",
        "method": "Matched fixed-tick route frames compare direct sampling and the 16-cubed cache. Temporal change magnitude compares absolute per-channel RGB movement between adjacent frames; it does not represent motion direction or replace playback review.",
        "host": {"device": "Apple M1 Max", "backend": "Metal"},
        "resolution": [640, 360],
        "seed": 42,
        "start_tick": start_tick,
        "end_tick": direct["frames"][-1]["tick"],
        "frames": frames,
        "fps": direct["fps"],
        "route": direct["route"],
        "cache_resolution": [16, 16, 16],
        "direct_scene_sha256": sha256(direct_path),
        "cached_scene_sha256": sha256(cache_path),
        "binary_sha256": direct["binary_sha256"],
        "capture_script_sha256": direct["capture_script_sha256"],
        "fire_and_effect_count_fields_match_every_frame": state_match,
        "frame_rgb_mae_mean": statistics.mean(frame_mae),
        "frame_rgb_mae_median": statistics.median(frame_mae),
        "frame_rgb_mae_p95": ordered[p95_index(ordered)],
        "frame_rgb_mae_max": max(frame_mae),
        "max_channel_difference": max_channel_difference,
        "temporal_change_magnitude_rgb_mae_mean": statistics.mean(temporal_mae),
        "temporal_change_magnitude_rgb_mae_median": statistics.median(temporal_mae),
        "temporal_change_magnitude_rgb_mae_p95": ordered_temporal[p95_index(ordered_temporal)],
        "visual_review": "See temporal-contact.png for sampled frames. This report does not claim continuous human playback acceptance.",
        "source_scene_sha256": sha256(SOURCE),
    }, contact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o05/continuous")
    parser.add_argument("--frames", type=int, default=400)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--start-tick", type=int, default=300)
    parser.add_argument("--report", type=Path, help="report destination; defaults to output/temporal-report.json")
    args = parser.parse_args()
    if not 2 <= args.frames <= 600 or not 1 <= args.stride <= 60 or not 0 <= args.start_tick <= 36000:
        parser.error("frames must be 2..600, stride 1..60, and start-tick 0..36000")
    binary, output = args.binary.resolve(), args.output.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)
    make_scenes(output, json.loads(SOURCE.read_text()))
    report, contact = summarize(output, binary, args.frames, args.stride, args.start_tick)
    (output / "temporal-report.json").write_text(json.dumps(report, indent=2) + "\n")
    sheet = Image.new("RGB", (970, 185 * len(contact)), (22, 22, 22))
    for row, (index, direct, cached, difference) in enumerate(contact):
        difference = difference.point(lambda channel: min(255, channel * 5))
        for image in (direct, cached, difference):
            image.thumbnail((320, 180))
        y = row * 185
        sheet.paste(direct, (0, y + 5))
        sheet.paste(cached, (325, y + 5))
        sheet.paste(difference, (650, y + 5))
        ImageDraw.Draw(sheet).text((2, y), f"frame {index}: direct | 16^3 | 5x difference", fill="white")
    sheet.save(output / "temporal-contact.png")
    report["limitations"] = [
        "Headless Apple M1 Max/Metal only; native-window and Windows/DX12 rendering are not covered.",
        "This run measures the 16-cubed cache at the medium-smoke scale; it does not establish a faster total-render range.",
        "Paused wall-clock and resumed wall-clock behavior are not included in this route capture.",
        "The contact sheet is sampled visual evidence; full continuous human playback review remains open.",
    ]
    report["artifacts"] = {}
    for label, path in (
        ("direct_sequence", output / "direct/sequence.json"),
        ("cache16_sequence", output / "cache16/sequence.json"),
        ("contact_sheet", output / "temporal-contact.png"),
    ):
        report["artifacts"][label] = {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
    report_path = (args.report or (output / "temporal-report.json")).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "contact_sheet": str(output / "temporal-contact.png"), "fire_state_match": report["fire_and_effect_count_fields_match_every_frame"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
