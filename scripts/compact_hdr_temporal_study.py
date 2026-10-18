#!/usr/bin/env python3
"""Quantify compact-HDR frame and temporal errors on the O06xO08 stress route."""
import argparse
import copy
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from optical_factorial_study import variants  # noqa: E402


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def load_frames(directory: Path, count: int) -> list[Image.Image]:
    frames = []
    for index in range(count):
        with Image.open(directory / f"{index:04}.png") as image:
            frames.append(image.convert("RGB"))
    return frames


def frame_error(base: Image.Image, candidate: Image.Image) -> tuple[float, int]:
    difference = ImageChops.difference(base, candidate)
    return sum(ImageStat.Stat(difference).mean) / 3, max(high for _, high in difference.getextrema())


def run_motion(binary: Path, scene: Path, output: Path, frames: int, stride: int, route_start: float) -> None:
    subprocess.run([
        sys.executable, str(ROOT / "scripts/capture_motion.py"),
        "--binary", str(binary), "--scene", str(scene), "--camera", "mixed-close",
        "--seed", "42", "--profile", "", "--route", "mixed-smoke-material-orbit",
        "--route-start", str(route_start), "--start-tick", "300", "--frames", str(frames),
        "--stride", str(stride), "--output", str(output),
    ], cwd=ROOT, check=True)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o08/compact-hdr-temporal")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o08-compact-hdr-temporal.json")
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--route-start", type=float, default=8.0)
    parser.add_argument("--reuse-captures", action="store_true", help="analyze existing paired frame sequences")
    args = parser.parse_args()
    if not 2 <= args.frames <= 600 or not 1 <= args.stride <= 60:
        parser.error("frames must be 2..600 and stride 1..60")
    args.binary = args.binary.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    scene_dir = args.output / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)
    available = variants()
    baseline_scene = scene_dir / "direct_copy_rgba16.json"
    compact_scene = scene_dir / "direct_copy_rg11b10.json"
    baseline_scene.write_text(json.dumps(available["direct_copy_rgba16"], indent=2) + "\n")
    compact_scene.write_text(json.dumps(available["direct_copy_rg11b10"], indent=2) + "\n")
    baseline_definition = json.loads(baseline_scene.read_text())
    compact_definition = json.loads(compact_scene.read_text())
    compact_as_baseline = copy.deepcopy(compact_definition)
    compact_as_baseline["render"]["compact_hdr"] = False
    if compact_as_baseline != baseline_definition:
        raise RuntimeError("scene variants differ in fields other than render.compact_hdr")
    baseline_dir = args.output / "rgba16"
    compact_dir = args.output / "rg11b10"
    if not args.reuse_captures:
        run_motion(args.binary, baseline_scene, baseline_dir, args.frames, args.stride, args.route_start)
        run_motion(args.binary, compact_scene, compact_dir, args.frames, args.stride, args.route_start)
    baseline_sequence = json.loads((baseline_dir / "sequence.json").read_text())
    compact_sequence = json.loads((compact_dir / "sequence.json").read_text())
    if baseline_sequence["frames"][0]["tick"] != 300 or compact_sequence["frames"][0]["tick"] != 300:
        raise RuntimeError("captured sequence does not start at the configured fixed tick")
    for sequence in (baseline_sequence, compact_sequence):
        if len(sequence["frames"]) != args.frames or sequence["frame_stride_ticks"] != args.stride:
            raise RuntimeError("existing sequence does not match requested frame count/stride")
    for key in ("seed", "start_tick", "frame_stride_ticks", "route", "route_start_seconds", "binary_sha256"):
        if baseline_sequence[key] != compact_sequence[key]:
            raise RuntimeError(f"paired sequences differ in {key}")
    for baseline_frame, compact_frame in zip(baseline_sequence["frames"], compact_sequence["frames"]):
        if baseline_frame["tick"] != compact_frame["tick"] or baseline_frame["camera"] != compact_frame["camera"]:
            raise RuntimeError("paired sequences differ in a frame tick or camera")
    baseline = load_frames(baseline_dir, args.frames)
    compact = load_frames(compact_dir, args.frames)
    frame_means, frame_maxima = zip(*(frame_error(a, b) for a, b in zip(baseline, compact)))
    temporal_means, temporal_maxima = [], []
    for index in range(1, args.frames):
        baseline_change = ImageChops.difference(baseline[index], baseline[index - 1])
        compact_change = ImageChops.difference(compact[index], compact[index - 1])
        error = ImageChops.difference(baseline_change, compact_change)
        temporal_means.append(sum(ImageStat.Stat(error).mean) / 3)
        temporal_maxima.append(max(high for _, high in error.getextrema()))
    report = {
        "version": 1,
        "purpose": "Quantified temporal comparison of compact Rg11b10Ufloat HDR against Rgba16Float; no promotion decision is inferred.",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal"},
        "scene": "high-dynamic mixed fire/smoke/reflector/glass factorial workload",
        "scene_variants": {
            "baseline": str(baseline_scene.relative_to(ROOT)),
            "candidate": str(compact_scene.relative_to(ROOT)),
            "only_difference": "render.compact_hdr",
        },
        "provenance": {
            "baseline_scene_sha256": baseline_sequence["scene_sha256"],
            "candidate_scene_sha256": compact_sequence["scene_sha256"],
            "binary_sha256": baseline_sequence["binary_sha256"],
            "candidate_binary_sha256": compact_sequence["binary_sha256"],
            "capture_script_sha256": baseline_sequence["capture_script_sha256"],
            "study_script_sha256": sha256(Path(__file__).resolve()),
            "baseline_hdr_format": baseline_sequence["frames"][0]["capabilities"]["resource_inventory"]["hdr_color_format"],
            "candidate_hdr_format": compact_sequence["frames"][0]["capabilities"]["resource_inventory"]["hdr_color_format"],
            "compact_hdr_supported": compact_sequence["frames"][0]["capabilities"]["resource_inventory"]["rg11b10_renderable_feature_available"],
        },
        "route": "mixed-smoke-material-orbit",
        "camera": "mixed-close",
        "route_start_seconds": args.route_start,
        "seed": 42,
        "start_tick": 300,
        "frame_count": args.frames,
        "frame_stride_ticks": args.stride,
        "capture_rate_hz": 60 / args.stride,
        "resolution": [640, 360],
        "variants": {"baseline": "Rgba16Float", "candidate": "Rg11b10Ufloat"},
        "frame_error_rgb_255": {
            "mean_of_frame_means": sum(frame_means) / len(frame_means),
            "p95_frame_mean": percentile(list(frame_means), 0.95),
            "max_frame_mean": max(frame_means),
            "max_channel_error": max(frame_maxima),
        },
        "temporal_change_magnitude_error_rgb_255": {
            "mean_of_frame_means": sum(temporal_means) / len(temporal_means),
            "p95_frame_mean": percentile(temporal_means, 0.95),
            "max_frame_mean": max(temporal_means),
            "max_channel_error": max(temporal_maxima),
        },
        "limitations": [
            "One route, camera and M1 Max/Metal adapter; no native-window, DX12, other-adapter or human playback acceptance.",
            "Temporal metric compares per-pixel absolute frame-to-frame change magnitudes; it is not a perceptual threshold.",
            "Capture timing is not performance evidence.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(args.report), "frames": args.frames,
                      "frame_mae": report["frame_error_rgb_255"]["mean_of_frame_means"],
                      "temporal_mae": report["temporal_change_magnitude_error_rgb_255"]["mean_of_frame_means"]}))


if __name__ == "__main__":
    main()
