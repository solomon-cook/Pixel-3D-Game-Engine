#!/usr/bin/env python3
"""Measure dual-source direct/cached absorption over paired sustained routes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/two-emitter-review.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_scenes(output: Path, source: dict, resolution: int) -> tuple[Path, Path]:
    paths = []
    for variant, enabled in (("direct", False), ("cached", True)):
        scene = json.loads(json.dumps(source))
        scene["render"]["absorption_cache_resolution"] = resolution
        scene.setdefault("render", {}).setdefault("experiments", {})["smoke_absorption_cache"] = enabled
        path = output / "scenes" / f"cache{resolution}" / f"{variant}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(scene, indent=2) + "\n")
        paths.append(path)
    return paths[0], paths[1]


def run_comparison(binary: Path, output: Path, baseline: Path, candidate: Path,
                   resolution: int, pairs: int, duration: float, warmup: float) -> dict:
    comparison_dir = output / f"cache{resolution}"
    command = [
        "python3", str(ROOT / "scripts/profile_compare.py"),
        "--baseline", str(baseline), "--candidate", str(candidate),
        "--route", "clearing-orbit", "--mode", "serial",
        "--duration", str(duration), "--warmup", str(warmup),
        "--pairs", str(pairs), "--seed", "42", "--camera", "dual-wide",
        "--resolution", "640x360", "--output", str(comparison_dir),
        "--binary", str(binary),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    comparison_path = comparison_dir / "comparison.json"
    comparison = json.loads(comparison_path.read_text())
    runs = {}
    for pair_index in range(1, pairs + 1):
        pair = {}
        for variant in ("baseline", "candidate"):
            name = f"pair-{pair_index:02d}-{variant}.engine.json"
            path = comparison_dir / name
            run = json.loads(path.read_text())
            if run.get("workload_counts", {}).get("emitters") != 2:
                raise RuntimeError(f"{name} did not report both emitters")
            if not run.get("timing_coverage", {}).get("gpu_timestamps_supported"):
                raise RuntimeError(f"{name} lacks GPU timestamp coverage")
            enabled = run.get("smoke_absorption_cache", {}).get("enabled")
            if enabled != (variant == "candidate"):
                raise RuntimeError(f"{name} reported unexpected cache state {enabled}")
            if not (run.get("timing_coverage", {}).get("rendered_frames", 0) > 0):
                raise RuntimeError(f"{name} did not record rendered frames")
            pair[variant] = {
                "report": name,
                "sha256": sha256(path),
                "cache_bytes": run["capabilities"]["resource_inventory"]["smoke_absorption_cache_bytes"],
                "frame_work": run.get("frame_work"),
                "gpu_render": run.get("gpu_render"),
                "gpu_stages": run.get("gpu_stages"),
                "smoke_absorption_cache": run.get("smoke_absorption_cache"),
                "cpu_encode": run.get("cpu_encode"),
                "workload_counts": run.get("workload_counts"),
                "timing_coverage": run.get("timing_coverage"),
            }
        runs[str(pair_index)] = pair
    if any(runs[str(i)]["baseline"]["cache_bytes"] != 0 for i in range(1, pairs + 1)):
        raise RuntimeError("direct baseline unexpectedly allocated an absorption cache")
    if any(runs[str(i)]["candidate"]["cache_bytes"] <= 0 for i in range(1, pairs + 1)):
        raise RuntimeError("cached candidate did not allocate the absorption cache")
    return {
        "scene_sha256": {"direct": sha256(baseline), "cached": sha256(candidate)},
        "comparison_sha256": sha256(comparison_path),
        "comparison": comparison["comparison"],
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o02/two-emitter-absorption-sustained")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-multi-emitter-absorption-sustained.json")
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    args = parser.parse_args()
    if args.pairs < 3 or args.duration <= 0 or args.warmup < 0:
        parser.error("at least three pairs, positive duration and nonnegative warmup are required")
    binary, output = args.binary.resolve(), args.output.resolve()
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    source = json.loads(SOURCE.read_text())
    if len(source.get("emitters", [])) != 2:
        raise SystemExit("study requires exactly two scene emitters")
    output.mkdir(parents=True, exist_ok=True)
    results = {}
    scene_hashes = {}
    for resolution in (8, 16):
        baseline, candidate = make_scenes(output, source, resolution)
        result = run_comparison(binary, output, baseline, candidate, resolution,
                                args.pairs, args.duration, args.warmup)
        results[str(resolution)] = result
        scene_hashes[str(resolution)] = result["scene_sha256"]
        print(json.dumps({
            "cache_resolution": resolution,
            "frame_work_delta_median_ms": result["comparison"]["frame_work"]["paired_delta_median_ms"],
            "gpu_render_delta_median_ms": result["comparison"]["gpu_render"]["paired_delta_median_ms"],
        }), flush=True)

    report = {
        "date": "2026-10-18",
        "workstream": "Dual-emitter absorption-cache sustained comparison",
        "host": {"device": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "source_scene": str(SOURCE.relative_to(ROOT)),
        "source_scene_sha256": sha256(SOURCE),
        "binary_sha256": sha256(binary),
        "study_script_sha256": sha256(Path(__file__).resolve()),
        "source_ids": sorted(emitter["id"] for emitter in source["emitters"]),
        "resolution": source["render"]["resolution"],
        "seed": 42,
        "camera": "dual-wide",
        "route": "clearing-orbit",
        "pairs_per_cache_resolution": args.pairs,
        "duration_seconds_per_run": args.duration,
        "warmup_seconds_per_run": args.warmup,
        "mode": "serial",
        "cache_resolutions": results,
        "scene_hashes": scene_hashes,
        "limitations": [
            "Offscreen Apple M1 Max/Metal only; no native-window, Windows/DX12, or other-adapter result.",
            "The comparison measures this route and workload only; it is not a cache promotion decision.",
            "GPU stage intervals may overlap; compare the full-frame metric separately and do not sum stages.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "cache_resolutions": [8, 16], "pairs_per_resolution": args.pairs}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
