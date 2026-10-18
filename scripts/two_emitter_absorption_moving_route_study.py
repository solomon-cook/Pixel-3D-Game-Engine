#!/usr/bin/env python3
"""Compare direct and cached two-emitter smoke absorption on a moving camera route."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/two-emitter-overflow-stress.json"
ROUTE = "clearing-orbit"
CAMERA = "dual-wide"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_metrics(image: Image.Image) -> dict:
    histogram = image.histogram()[:768]
    channels = (histogram[:256], histogram[256:512], histogram[512:768])
    pixels = image.width * image.height
    total_error = sum(value * count for channel in channels for value, count in enumerate(channel))
    maximum = max((value for channel in channels for value, count in enumerate(channel) if count), default=0)
    changed_mask = image.convert("L").point([0] + [1] * 255)
    changed = changed_mask.histogram()[1]
    return {
        "mae_0_255": total_error / (pixels * 3) if pixels else 0.0,
        "max_channel_error_0_255": maximum,
        "changed_pixels": changed,
        "pixel_count": pixels,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/multi-emitter/absorption-moving-route")
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--start-tick", type=int, default=300)
    parser.add_argument("--route-start", type=float, default=24.0)
    parser.add_argument("--full-route", action="store_true", help="sample the complete 120-second orbit in segments")
    parser.add_argument("--summarize-existing", action="store_true", help="reuse saved scene and sequence captures")
    parser.add_argument("--cache-resolution", type=int, choices=(8, 16), default=8)
    args = parser.parse_args()
    if not 2 <= args.frames <= 600 or not 1 <= args.stride <= 60 or not 0 <= args.start_tick <= 36000:
        parser.error("frames must be 2..600, stride 1..60, and start-tick 0..36000")

    binary, output = args.binary.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = json.loads(SOURCE.read_text())
    if len(source.get("emitters", [])) != 2:
        raise SystemExit("stress scene must contain exactly two emitters")
    if not any(item.get("id") == ROUTE for item in source.get("routes", [])):
        raise SystemExit(f"scene is missing route {ROUTE}")
    sequences = {}
    segment_records = []
    segment_duration = args.frames * args.stride / 60
    segment_count = max(1, int((120 + segment_duration - 1e-9) // segment_duration)) if args.full_route else 1
    if args.full_route and segment_duration <= 0:
        parser.error("segment duration must be positive")
    scene_hashes = {}
    for mode, enabled in (("direct", False), ("cached", True)):
        scene = json.loads(json.dumps(source))
        scene["render"]["absorption_cache_resolution"] = args.cache_resolution
        scene.setdefault("render", {}).setdefault("experiments", {})["smoke_absorption_cache"] = enabled
        scene_path = output / f"{mode}.scene.json"
        scene_path.write_text(json.dumps(scene, indent=2) + "\n")
        scene_hashes[mode] = sha256(scene_path)
        mode_frames = []
        capture_script_hash = None
        binary_hash = None
        for segment in range(segment_count):
            route_start = args.route_start + segment * segment_duration
            segment_start_offset = segment * segment_duration
            remaining = max(0.0, 120.0 - segment_start_offset) if args.full_route else segment_duration
            segment_frames = min(args.frames, max(2, int((remaining * 60 + args.stride - 1) // args.stride)))
            frame_dir = output / mode / (f"segment-{segment:02d}" if args.full_route else "")
            start_tick = args.start_tick + segment * args.frames * args.stride
            command = [
                "python3", str(ROOT / "scripts/capture_motion.py"),
                "--binary", str(binary), "--scene", str(scene_path),
                "--camera", CAMERA, "--route", ROUTE,
                "--route-start", str(route_start), "--seed", "42", "--profile", "",
                "--start-tick", str(start_tick), "--frames", str(segment_frames),
                "--stride", str(args.stride), "--output", str(frame_dir), "--gif",
            ]
            sequence_path = frame_dir / "sequence.json"
            if args.summarize_existing:
                if not sequence_path.is_file():
                    raise FileNotFoundError(f"missing saved motion sequence: {sequence_path}")
            else:
                print(f"{mode}: route {route_start:.2f}s, ticks from {start_tick}, {segment_frames} frames", flush=True)
                subprocess.run(command, cwd=ROOT, check=True)
            sequence = json.loads(sequence_path.read_text())
            capture_script_hash = sequence["capture_script_sha256"]
            binary_hash = sequence["binary_sha256"]
            mode_frames.extend(sequence["frames"])
            if mode == "direct":
                segment_records.append({
                    "index": segment,
                    "route_start_seconds": route_start,
                    "route_end_seconds": route_start + (segment_frames - 1) * args.stride / 60,
                    "start_tick": start_tick,
                    "end_tick": sequence["frames"][-1]["tick"],
                    "frames": segment_frames,
                })
        sequences[mode] = {
            "frames": mode_frames,
            "binary_sha256": binary_hash or sha256(binary),
            "capture_script_sha256": capture_script_hash,
        }

    direct_frames = sequences["direct"]["frames"]
    cached_frames = sequences["cached"]["frames"]
    frame_count = len(direct_frames)
    if len(direct_frames) != len(cached_frames):
        raise RuntimeError("direct/cached frame counts differ")
    frame_errors = []
    temporal_errors = []
    max_channel = 0
    effect_counts_match = True
    camera_poses_match = True
    direct_cache_mode_valid = True
    cached_cache_mode_valid = True
    cached_residency_valid = True
    contact_indices = sorted(set((0, (frame_count - 1) // 4, (frame_count - 1) // 2,
                                  3 * (frame_count - 1) // 4, frame_count - 1)))
    contact_frames = []
    previous_direct = previous_cached = None
    for index, (base, candidate) in enumerate(zip(direct_frames, cached_frames)):
        if base["tick"] != candidate["tick"] or base["camera"] != candidate["camera"]:
            raise RuntimeError(f"frame {index}: tick or camera mismatch")
        base_sidecar = json.loads(Path(base["metadata"]).read_text())
        candidate_sidecar = json.loads(Path(candidate["metadata"]).read_text())
        camera_poses_match &= base_sidecar.get("camera") == candidate_sidecar.get("camera")
        direct_cache_mode_valid &= base_sidecar.get("metrics", {}).get("smoke_absorption_cache_enabled") is False
        cached_cache_mode_valid &= candidate_sidecar.get("metrics", {}).get("smoke_absorption_cache_enabled") is True
        expected_cache_bytes = args.cache_resolution ** 3 * 8
        cached_residency_valid &= candidate_sidecar.get("capabilities", {}).get("resource_inventory", {}).get("smoke_absorption_cache_bytes") == expected_cache_bytes
        count_keys = ("fire_primitives_full", "fire_segments_full", "embers", "particle_lights", "flame_fragments")
        effect_counts_match &= all(
            base_sidecar.get("metrics", {}).get(key) == candidate_sidecar.get("metrics", {}).get(key)
            for key in count_keys
        )
        base_image = Image.open(base["image"]).convert("RGB")
        candidate_image = Image.open(candidate["image"]).convert("RGB")
        difference = ImageChops.difference(base_image, candidate_image)
        frame_metric = image_metrics(difference)
        frame_errors.append(frame_metric)
        max_channel = max(max_channel, frame_metric["max_channel_error_0_255"])
        if previous_direct is not None:
            direct_motion = ImageChops.difference(base_image, previous_direct)
            cached_motion = ImageChops.difference(candidate_image, previous_cached)
            temporal_errors.append(image_metrics(ImageChops.difference(direct_motion, cached_motion)))
        if index in contact_indices:
            contact_frames.append((index, base_image.copy(), candidate_image.copy(), difference.copy()))
        previous_direct, previous_cached = base_image, candidate_image

    def distribution(key: str, values: list[dict]) -> dict:
        ordered = sorted(item[key] for item in values)
        return {
            "mean": statistics.mean(ordered),
            "p95": ordered[int(0.95 * (len(ordered) - 1))],
            "max": max(ordered),
        }

    report = {
        "version": 1,
        "date": "2026-10-18",
        "workstream": "O05 dual-emitter absorption cache moving-camera temporal comparison",
        "host": {"device": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "source_scene": str(SOURCE.relative_to(ROOT)),
        "source_scene_sha256": sha256(SOURCE),
        "scene_sha256": scene_hashes,
        "binary_sha256": sequences["direct"]["binary_sha256"],
        "engine_source_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip(),
        "optical_shader_sha256": sha256(ROOT / "crates/engine/src/render/shaders/absorption.wgsl"),
        "capture_script_sha256": sequences["direct"]["capture_script_sha256"],
        "study_script_sha256": sha256(Path(__file__).resolve()),
        "source_ids": sorted(item["id"] for item in source["emitters"]),
        "seed": 42,
        "camera": CAMERA,
        "route": ROUTE,
        "route_start_seconds": args.route_start,
        "route_duration_seconds": (frame_count - 1) * args.stride / 60,
        "segments": segment_records,
        "resolution": source["render"]["resolution"],
        "cache_resolution": [args.cache_resolution] * 3,
        "start_tick": args.start_tick,
        "end_tick": direct_frames[-1]["tick"],
        "frames": frame_count,
        "fps": 60 / args.stride,
        "effect_counts_match_every_frame": effect_counts_match,
        "camera_poses_match_every_frame": camera_poses_match,
        "direct_cache_mode_valid_every_frame": direct_cache_mode_valid,
        "cached_mode_enabled_every_frame": cached_cache_mode_valid,
        "cached_residency_matches_8_byte_voxel_model_every_frame": cached_residency_valid,
        "frame_rgb_error": {
            key: distribution(key, frame_errors)
            for key in ("mae_0_255", "max_channel_error_0_255", "changed_pixels")
        },
        "maximum_channel_error_0_255": max_channel,
        "temporal_change_rgb_error": {
            key: distribution(key, temporal_errors)
            for key in ("mae_0_255", "max_channel_error_0_255", "changed_pixels")
        },
        "contact_sheet": str((output / "moving-route-contact.png").relative_to(ROOT)),
        "captures": {
            mode: [
                str(path.relative_to(ROOT))
                for path in sorted((output / mode).glob("segment-*/sequence.json" if args.full_route else "sequence.json"))
            ]
            for mode in sequences
        },
        "limitations": [
            "Offscreen M1 Max/Metal camera-route comparison; no native-window, sustained-performance, DX12 or other-adapter acceptance.",
            ("The full sampled orbit is split into deterministic segments whose simulation ticks are aligned with route time." if args.full_route else "The sample covers only part of the 120-second camera orbit."),
            "The cache is an approximation and remains disabled by default; error metrics do not replace continuous playback review.",
        ],
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    sheet = Image.new("RGB", (960, len(contact_frames) * 180), "#111")
    draw = ImageDraw.Draw(sheet)
    for row, (index, baseline, candidate, difference) in enumerate(contact_frames):
        y = row * 180
        for col, image in enumerate((baseline, candidate, difference.point(lambda value: min(255, value * 5)))):
            sheet.paste(image.resize((320, 180)), (col * 320, y))
        draw.text((4, y + 2), f"{index}: direct", fill="white")
        draw.text((324, y + 2), f"{index}: cache", fill="white")
        draw.text((644, y + 2), f"{index}: 5x diff", fill="white")
    sheet.save(output / "moving-route-contact.png")
    print(json.dumps({
        "report": str(report_path),
        "contact_sheet": str(output / "moving-route-contact.png"),
        "effect_counts_match_every_frame": effect_counts_match,
        "frame_rgb_mae_mean": report["frame_rgb_error"]["mae_0_255"]["mean"],
        "temporal_change_mae_mean": report["temporal_change_rgb_error"]["mae_0_255"]["mean"],
    }, indent=2))
    return 0 if all((effect_counts_match, camera_poses_match, direct_cache_mode_valid,
                     cached_cache_mode_valid, cached_residency_valid)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
