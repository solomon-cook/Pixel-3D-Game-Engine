#!/usr/bin/env python3
"""Measure natural all-tile fire overflow against exhaustive evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCENE = ROOT / "assets/scenes/two-emitter-overflow-stress.json"
CAMERA = {
    "id": "camera-inside-plume",
    "position": [-0.55, 1.45, 0.0],
    "projection": {"fov_degrees": 48.0, "kind": "perspective"},
    "target": [-0.55, 2.2, -0.35],
}
ROUTE = "camera-inside-hold"
SEED = 42


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(binary: Path, scene: Path, output: Path, exhaustive: bool) -> dict:
    name = "exhaustive" if exhaustive else "tiled"
    image = output / f"fixed-tick-{name}.png"
    command = [
        str(binary), "capture", "--scene", str(scene), "--camera", CAMERA["id"],
        "--seed", str(SEED), "--tick", "300", "--resolution", "640x360",
        "--scale", "1", "--output", str(image.resolve()),
    ]
    if exhaustive:
        command.append("--disable-tile-lists")
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    metadata = json.loads(image.with_suffix(".json").read_text())
    try:
        image_path = str(image.relative_to(ROOT))
    except ValueError:
        image_path = str(image)
    return {
        "image": image_path,
        "sha256": sha256(image),
        "tile_lists_enabled": metadata["capabilities"]["tile_lists"]["enabled"],
        "tile_overflow_tiles": metadata["metrics"]["tile_overflow_tiles"],
        "tile_max_occupancy": metadata["metrics"]["tile_max_occupancy"],
        "tick": metadata["tick"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o03/camera-inside-overflow-cost")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o03-camera-inside-overflow.json")
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--pairs", type=int, default=3)
    args = parser.parse_args()
    binary = args.binary.resolve()
    output = args.output.resolve()
    report_path = args.report.resolve()
    output.mkdir(parents=True, exist_ok=True)

    scene = json.loads(SOURCE_SCENE.read_text())
    scene["cameras"].append(CAMERA)
    scene["routes"].append({
        "id": ROUTE,
        "duration_seconds": args.duration,
        "keyframes": [
            {"time": 0.0, "position": CAMERA["position"], "target": CAMERA["target"]},
            {"time": args.duration, "position": CAMERA["position"], "target": CAMERA["target"]},
        ],
    })
    scene_path = output / "scene.json"
    scene_path.write_text(json.dumps(scene, indent=2) + "\n")
    subprocess.run([str(binary), "validate", str(scene_path)], cwd=ROOT, check=True, capture_output=True, text=True)

    parity_dir = output / "fixed-tick-parity"
    parity_dir.mkdir(parents=True, exist_ok=True)
    tiled = capture(binary, scene_path, parity_dir, exhaustive=False)
    exhaustive = capture(binary, scene_path, parity_dir, exhaustive=True)
    parity = {
        "pixel_identical": tiled["sha256"] == exhaustive["sha256"],
        "same_tick": tiled["tick"] == exhaustive["tick"],
        "tiled": tiled,
        "exhaustive": exhaustive,
    }

    paired_dir = output / "paired-runs"
    subprocess.run([
        sys.executable, str(ROOT / "scripts/profile_compare.py"),
        "--baseline", str(scene_path), "--candidate", str(scene_path),
        "--route", ROUTE, "--duration", str(args.duration),
        "--warmup", str(args.warmup), "--pairs", str(args.pairs),
        "--seed", str(SEED), "--resolution", "640x360",
        "--candidate-disable-tile-lists", "--output", str(paired_dir),
    ], cwd=ROOT, check=True)
    paired = json.loads((paired_dir / "comparison.json").read_text())

    run_summaries = {"baseline": [], "candidate": []}
    all_runs_valid = True
    baseline_overflow_full_rate = True
    host = None
    for variant, ids in paired["runs"].items():
        if variant not in run_summaries:
            continue
        for run_id in ids:
            run_path = paired_dir / f"{run_id}.engine.json"
            run = json.loads(run_path.read_text())
            if host is None:
                host = {
                    "adapter": run["capabilities"]["name"],
                    "backend": run["capabilities"]["backend"],
                    "native_window": False,
                }
            elif (run["capabilities"]["name"], run["capabilities"]["backend"]) != (host["adapter"], host["backend"]):
                all_runs_valid = False
            categories = run["tile_lists"].get("overflow_by_category", {})
            fire = categories.get("fire_primitives", {})
            expected_tiled = variant == "baseline"
            timing = run["timing_coverage"]
            valid = (
                run["tile_lists"]["enabled"] is expected_tiled
                and timing["rendered_frames"] == int(round(args.duration * 60))
                and timing["skipped_samples"] == 0
                and timing["late_samples"] == 0
                and run["gpu_render"]["samples"] == timing["rendered_frames"]
            )
            all_runs_valid &= valid
            if expected_tiled:
                baseline_overflow_full_rate &= fire.get("fallback_rate") == 1.0
            run_summaries[variant].append({
                "run": run_id,
                "tile_lists_enabled": run["tile_lists"]["enabled"],
                "frames": timing["rendered_frames"],
                "gpu_timing_samples": run["gpu_render"]["samples"],
                "fire_overflow": fire,
                "frame_work_median_ms": run["frame_work"]["median_ms"],
                "gpu_render_median_ms": run["gpu_render"]["median_ms"],
                "atmosphere_fire_median_ms": run["gpu_stages"]["atmosphere_fire"]["median_ms"],
                "tile_list_build_median_ms": run["tile_lists"]["gpu_build"]["median_ms"],
            })

    correctness_pass = parity["pixel_identical"] and parity["same_tick"]
    performance_coverage_pass = all_runs_valid and len(run_summaries["baseline"]) == args.pairs and len(run_summaries["candidate"]) == args.pairs
    required_pair_protocol_pass = args.pairs >= 3 and performance_coverage_pass
    report = {
        "version": 1,
        "workstream": "O03 natural camera-inside fire-list overflow cost",
        "date": "2026-10-18",
        "host": host,
        "source_scene": str(SOURCE_SCENE.relative_to(ROOT)),
        "source_scene_sha256": sha256(SOURCE_SCENE),
        "generated_scene": str(scene_path.relative_to(ROOT)) if scene_path.is_relative_to(ROOT) else str(scene_path),
        "generated_scene_sha256": sha256(scene_path),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "profile_compare_sha256": sha256(ROOT / "scripts/profile_compare.py"),
        "binary_sha256": sha256(binary),
        "camera": CAMERA,
        "route": ROUTE,
        "seed": SEED,
        "resolution": [640, 360],
        "duration_seconds": args.duration,
        "warmup_seconds": args.warmup,
        "pairs": args.pairs,
        "required_pairs": 3,
        "fixed_tick_parity": parity,
        "comparison": paired["comparison"],
        "runs": run_summaries,
        "comparisons": {
            "fixed_tick_parity_passed": correctness_pass,
            "paired_timing_coverage_passed": performance_coverage_pass,
            "three_pair_protocol_passed": required_pair_protocol_pass,
            "natural_fire_fallback_rate_is_100_percent": baseline_overflow_full_rate,
        },
        "scope": "Serial offscreen 640x360 camera-held route. Baseline uses 16x16 tile lists with natural fire overflow in every tile; candidate uses exhaustive category evaluation. This isolates the cost of the overflow-heavy view and does not represent a moving gameplay camera.",
        "limitations": [
            "M1 Max/Metal only; native-window, DX12 and other-adapter acceptance remain open.",
            "The camera is deliberately inside the fire plume for a worst-case fallback probe and is not visual-quality evidence.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["comparisons"], indent=2))
    return 0 if correctness_pass and required_pair_protocol_pass and baseline_overflow_full_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
