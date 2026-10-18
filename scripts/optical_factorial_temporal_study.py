#!/usr/bin/env python3
"""Compare motion quality across all O06 x O08 optical factorial variants."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from optical_factorial_study import BASELINE, ROOT, ROUTE, variants

STATE_FIELDS = ("fire_primitives_full", "fire_segments_full", "embers", "particle_lights", "flame_fragments")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rgb_error(diff: Image.Image) -> tuple[float, int, int]:
    histogram = diff.histogram()
    channels = (histogram[:256], histogram[256:512], histogram[512:768])
    pixels = diff.width * diff.height
    mean = sum(value * count for channel in channels for value, count in enumerate(channel)) / (pixels * 3)
    maximum = max((value for channel in channels for value, count in enumerate(channel) if count), default=0)
    changed = sum(1 for pixel in diff.getdata() if pixel != (0, 0, 0))
    return mean, maximum, changed


def capture(binary: Path, scene: Path, output: Path, frames: int, stride: int,
            start_tick: int, shaders: Path | None) -> dict:
    command = [
        "python3", str(ROOT / "scripts/capture_motion.py"),
        "--binary", str(binary), "--scene", str(scene), "--camera", "mixed-close",
        "--seed", "42", "--route", ROUTE, "--start-tick", str(start_tick),
        "--frames", str(frames), "--stride", str(stride), "--output", str(output),
    ]
    if shaders:
        command.extend(("--shaders", str(shaders)))
    subprocess.run(command, cwd=ROOT, check=True)
    return json.loads((output / "sequence.json").read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o06-o08/factorial-temporal")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o06-o08-factorial-temporal.json")
    parser.add_argument("--shaders", type=Path, help="override WGSL shader directory for every variant")
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--start-tick", type=int, default=300)
    args = parser.parse_args()
    if not 2 <= args.frames <= 600 or not 1 <= args.stride <= 60 or not 0 <= args.start_tick <= 36000:
        parser.error("frames must be 2..600, stride 1..60, and start-tick 0..36000")
    binary, output = args.binary.resolve(), args.output.resolve()
    shaders = args.shaders.resolve() if args.shaders else None
    if shaders and not shaders.is_dir():
        parser.error(f"shader directory does not exist: {shaders}")
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)

    scenes = {}
    for name, scene in variants().items():
        scene_path = output / "scenes" / f"{name}.json"
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        scene_path.write_text(json.dumps(scene, indent=2) + "\n")
        scenes[name] = scene_path

    sequences = {}
    for name, scene_path in scenes.items():
        sequences[name] = capture(binary, scene_path, output / "frames" / name,
                                  args.frames, args.stride, args.start_tick, shaders)
        print(json.dumps({"variant": name, "frames": len(sequences[name]["frames"])}), flush=True)
    baseline = sequences[BASELINE]["frames"]
    results = {}
    contact_candidates = []
    for name, sequence in sequences.items():
        frames = sequence["frames"]
        if len(frames) != args.frames or len(frames) != len(baseline):
            raise RuntimeError(f"{name}: frame count mismatch")
        frame_errors, temporal_errors = [], []
        max_channel_difference = 0
        changed_pixel_max = 0
        state_match = True
        prior_base = prior_candidate = None
        contact_indices = sorted(set((0, (args.frames - 1) // 4, (args.frames - 1) // 2,
                                      3 * (args.frames - 1) // 4, args.frames - 1)))
        contacts = []
        for index, (base_frame, frame) in enumerate(zip(baseline, frames)):
            if base_frame["tick"] != frame["tick"] or base_frame["camera"] != frame["camera"]:
                raise RuntimeError(f"{name}: frame {index} tick/camera mismatch")
            base_meta = json.loads(Path(base_frame["metadata"]).read_text())["metrics"]
            meta = json.loads(Path(frame["metadata"]).read_text())["metrics"]
            state_match &= all(base_meta.get(field) == meta.get(field) for field in STATE_FIELDS)
            base_image = Image.open(base_frame["image"]).convert("RGB")
            image = Image.open(frame["image"]).convert("RGB")
            diff = ImageChops.difference(base_image, image)
            mean, maximum, changed = rgb_error(diff)
            frame_errors.append(mean)
            max_channel_difference = max(max_channel_difference, maximum)
            changed_pixel_max = max(changed_pixel_max, changed)
            if prior_base is not None:
                base_change = ImageChops.difference(base_image, prior_base)
                change = ImageChops.difference(image, prior_candidate)
                temporal_errors.append(rgb_error(ImageChops.difference(base_change, change))[0])
            if index in contact_indices:
                contacts.append((index, base_image.copy(), image.copy(), diff.copy()))
            prior_base, prior_candidate = base_image, image
        frame_sorted, temporal_sorted = sorted(frame_errors), sorted(temporal_errors)
        p95 = lambda values: values[int(0.95 * (len(values) - 1))]
        results[name] = {
            "scene_sha256": sha256(scenes[name]),
            "frame_count": len(frames),
            "effect_counts_match_every_frame": state_match,
            "frame_rgb_mae_mean": statistics.mean(frame_errors),
            "frame_rgb_mae_p95": p95(frame_sorted),
            "frame_rgb_mae_max": max(frame_errors),
            "temporal_change_magnitude_rgb_mae_mean": statistics.mean(temporal_errors),
            "temporal_change_magnitude_rgb_mae_p95": p95(temporal_sorted),
            "maximum_channel_difference": max_channel_difference,
            "maximum_changed_pixels": changed_pixel_max,
            "sequence_sha256": sha256(output / "frames" / name / "sequence.json"),
        }
        if name != BASELINE:
            contact_candidates.append((statistics.mean(frame_errors), name, contacts))
    if not all(result["effect_counts_match_every_frame"] for result in results.values()):
        raise RuntimeError("at least one factorial variant changed deterministic effect counts")

    # Preserve the most error-prone combination's matched frame samples for review.
    _, worst_name, worst_contacts = max(contact_candidates, key=lambda item: item[0])
    sheet = Image.new("RGB", (970, 185 * len(worst_contacts)), (22, 22, 22))
    draw = ImageDraw.Draw(sheet)
    for row, (index, base, candidate, diff) in enumerate(worst_contacts):
        y = row * 185
        for x, image in ((0, base), (325, candidate), (650, diff.point(lambda c: min(255, c * 5)))):
            sheet.paste(image.resize((320, 180)), (x, y))
        draw.text((4, y + 2), f"{index}: direct copy RGBA16", fill="white")
        draw.text((329, y + 2), f"{index}: {worst_name}", fill="white")
        draw.text((654, y + 2), f"{index}: 5x diff", fill="white")
    contact_path = output / "worst-variant-contact.png"
    sheet.save(contact_path)

    report = {
        "date": "2026-10-18",
        "workstream": "O06 x O08 factorial temporal comparison",
        "host": {"device": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "route": ROUTE,
        "camera": "mixed-close",
        "resolution": [640, 360],
        "seed": 42,
        "start_tick": args.start_tick,
        "end_tick": baseline[-1]["tick"],
        "frames": args.frames,
        "fps": 60 / args.stride,
        "baseline": BASELINE,
        "baseline_scene_sha256": sha256(scenes[BASELINE]),
        "binary_sha256": sequences[BASELINE]["binary_sha256"],
        "capture_script_sha256": sequences[BASELINE]["capture_script_sha256"],
        "study_script_sha256": sha256(Path(__file__).resolve()),
        "shader_sha256": sha256(shaders / "optical.wgsl") if shaders else sha256(ROOT / "crates/engine/src/render/shaders/optical.wgsl"),
        "variants": results,
        "worst_mean_error_variant": worst_name,
        "contact_sheet": {"path": str(contact_path.relative_to(ROOT)), "sha256": sha256(contact_path)},
        "limitations": [
            "One offscreen M1 Max/Metal route; native-window and other-adapter results are not included.",
            "The contact sheet samples five frames from the highest-mean-error variant; it does not replace continuous human playback review.",
            "This is image-quality evidence only and does not establish timing, bandwidth, or promotion thresholds.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "worst_variant": worst_name,
                      "worst_mean_frame_error": results[worst_name]["frame_rgb_mae_mean"],
                      "all_effect_counts_match": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
