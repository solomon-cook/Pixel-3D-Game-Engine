#!/usr/bin/env python3
"""Compare O07 geometry submission modes in the native window."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess

from geometry_scale_study import COUNTS, ROOT, save_scenes

COMPARISONS = {
    "baked_vs_instancing_only": (True, True, True, False),
    "instancing_only_vs_culling_instancing": (True, False, False, False),
    "baked_vs_culling_instancing": (True, True, False, False),
}
METRICS = (
    "frames_per_second",
    "cpu_native_frame",
    "cpu_renderer_encode",
    "cpu_simulation_submit",
    "cpu_simulation_encode",
    "cpu_queue_submit",
    "cpu_surface_acquire",
    "cpu_present_encode",
    "cpu_present_submit",
    "cpu_ui",
)
GPU_STAGES = (
    "shadow_maps",
    "opaque_geometry",
    "atmosphere_fire",
    "optical_resolve",
    "post",
    "smoke_compute",
    "native_presenter",
    "native_inspector",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def metric(report: dict, name: str) -> tuple[float | None, float | None]:
    if name == "frames_per_second":
        value = report.get(name)
        return (float(value), None) if isinstance(value, (int, float)) else (None, None)
    result = report.get(name, {})
    median = result.get("median_ms")
    p95 = result.get("p95_ms")
    return (
        float(median) if isinstance(median, (int, float)) else None,
        float(p95) if isinstance(p95, (int, float)) else None,
    )


def compact_report(report: dict) -> dict:
    keys = (
        "mode", "route", "route_seconds", "warmup_seconds", "actual_measured_seconds",
        "frames_per_second", "present_mode", "vsync", "seed", "geometry_rendering",
        "moving_caster", "shadow_cache", "workload_counts", "timing_coverage",
        *METRICS, "gpu_stages",
    )
    return {key: report[key] for key in keys if key in report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o07/native-moving-caster-scale-study")
    parser.add_argument("--moving-caster", default="rock-0")
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--tiers", default=",".join(map(str, COUNTS)), help="comma-separated object counts")
    parser.add_argument("--resume", action="store_true", help="reuse completed compact run reports")
    args = parser.parse_args()
    if not 1 <= args.pairs <= 3:
        parser.error("--pairs must be between 1 and 3")
    try:
        tiers = [int(value) for value in args.tiers.split(",")]
    except ValueError:
        parser.error("--tiers must be comma-separated object counts")
    if not tiers or any(tier not in COUNTS for tier in tiers) or len(set(tiers)) != len(tiers):
        parser.error(f"--tiers must contain unique values from {COUNTS}")
    if not math.isfinite(args.duration) or not 0.1 <= args.duration <= 600:
        parser.error("--duration must be between 0.1 and 600 seconds")
    if not math.isfinite(args.warmup) or not 0 <= args.warmup <= 120:
        parser.error("--warmup must be between 0 and 120 seconds")
    if not args.binary.is_file():
        parser.error(f"engine-lab binary does not exist: {args.binary}")

    args.output = args.output.resolve()
    scenes, tier_metadata = save_scenes(args.output)
    run_root = args.output / "runs"
    run_root.mkdir(parents=True, exist_ok=True)
    report = {
        "workstream": "O07 native-window moving-caster scene-scale study",
        "date": "2026-10-18",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal", "os": "macOS"},
        "resolution": [640, 360],
        "camera": "hero",
        "route": "clearing-orbit",
        "seed": 42,
        "moving_caster": {"object_id": args.moving_caster, "orbit_radius": 5.0, "orbit_period_seconds": 20.0},
        "timing": {"duration_seconds_per_run": args.duration, "warmup_seconds": args.warmup, "pairs": args.pairs, "presentation": "native window; present mode and vsync recorded per run"},
        "binary_sha256": sha256(args.binary.resolve()),
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {
            str(path.relative_to(ROOT)): sha256(path)
            for source_root in (ROOT / "crates/engine/src", ROOT / "crates/engine-lab/src")
            for path in sorted(source_root.rglob("*"))
            if path.is_file() and path.suffix in (".rs", ".wgsl")
        },
        "tiers": {},
        "limitations": ["Native-window runs include surface acquisition, UI encoding, submission and present; CPU spans can overlap.", "Offscreen and native-window timing results must remain separate.", "Non-Metal adapters remain unverified."],
    }

    for tier in tiers:
        scene_path = scenes[tier]
        tier_report = dict(tier_metadata[tier])
        tier_report["scene_sha256"] = sha256(scene_path)
        tier_report["benchmarks"] = {}
        for name, flags in COMPARISONS.items():
            baseline_no_culling, baseline_no_instancing, candidate_no_culling, candidate_no_instancing = flags
            directory = run_root / str(tier) / name
            directory.mkdir(parents=True, exist_ok=True)
            order = ["baseline", "candidate", "candidate", "baseline", "baseline", "candidate"][: args.pairs * 2]
            runs = []
            for run_index, variant in enumerate(order, start=1):
                path = directory / f"pair-{(run_index + 1) // 2:02d}-{variant}.json"
                if args.resume and path.is_file():
                    run_report = json.loads(path.read_text())
                    run_report["variant"] = variant
                    run_report["run_index"] = run_index
                    runs.append(run_report)
                    continue
                is_baseline = variant == "baseline"
                no_culling = baseline_no_culling if is_baseline else candidate_no_culling
                no_instancing = baseline_no_instancing if is_baseline else candidate_no_instancing
                raw_path = path.with_suffix(".engine.json")
                command = [
                    str(args.binary.resolve()), "benchmark-native", "--scene", str(scene_path.resolve()),
                    "--seed", "42", "--camera", "hero", "--resolution", "640x360",
                    "--route", "clearing-orbit", "--duration", str(args.duration),
                    "--warmup", str(args.warmup), "--moving-caster", args.moving_caster,
                    "--output", str(raw_path.resolve()),
                ]
                if no_culling:
                    command.append("--disable-object-culling")
                if no_instancing:
                    command.append("--disable-instancing")
                print(f"tier {tier} {name} pair {(run_index + 1) // 2}/{args.pairs} {variant}", flush=True)
                subprocess.run(command, cwd=ROOT, check=True)
                raw = json.loads(raw_path.read_text())
                run_report = compact_report(raw)
                run_report["variant"] = variant
                run_report["run_index"] = run_index
                run_report["geometry_flags"] = {"disable_object_culling": no_culling, "disable_instancing": no_instancing}
                path.write_text(json.dumps(run_report, indent=2) + "\n")
                raw_path.unlink()
                runs.append(run_report)

            pair_reports = []
            metric_deltas: dict[str, list[float]] = {key: [] for key in METRICS}
            p95_deltas: dict[str, list[float]] = {key: [] for key in METRICS if key != "frames_per_second"}
            for pair_index in range(args.pairs):
                first, second = runs[pair_index * 2 : pair_index * 2 + 2]
                by_variant = {first["variant"]: first, second["variant"]: second}
                if set(by_variant) != {"baseline", "candidate"}:
                    raise RuntimeError(f"tier {tier} {name}: pair {pair_index + 1} lacks a variant")
                baseline, candidate = by_variant["baseline"], by_variant["candidate"]
                deltas = {}
                for metric_name in METRICS:
                    b, bp = metric(baseline, metric_name)
                    c, cp = metric(candidate, metric_name)
                    delta = c - b if b is not None and c is not None else None
                    p95_delta = cp - bp if bp is not None and cp is not None else None
                    deltas[metric_name] = {"baseline_median": b, "candidate_median": c, "candidate_minus_baseline": delta, "candidate_minus_baseline_p95": p95_delta}
                    if delta is not None:
                        metric_deltas[metric_name].append(delta)
                    if metric_name in p95_deltas and p95_delta is not None:
                        p95_deltas[metric_name].append(p95_delta)
                for stage in GPU_STAGES:
                    baseline_stage = baseline.get("gpu_stages", {}).get(stage, {})
                    candidate_stage = candidate.get("gpu_stages", {}).get(stage, {})
                    b, bp = baseline_stage.get("median_ms"), baseline_stage.get("p95_ms")
                    c, cp = candidate_stage.get("median_ms"), candidate_stage.get("p95_ms")
                    deltas[f"gpu_{stage}"] = {"baseline_median_ms": b, "candidate_median_ms": c, "candidate_minus_baseline_ms": c - b if b is not None and c is not None else None, "candidate_minus_baseline_p95_ms": cp - bp if bp is not None and cp is not None else None}
                pair_reports.append({"pair": pair_index + 1, "order": [first["variant"], second["variant"]], "deltas": deltas})
            tier_report["benchmarks"][name] = {
                "baseline_flags": [flag for flag, enabled in (("--disable-object-culling", baseline_no_culling), ("--disable-instancing", baseline_no_instancing)) if enabled],
                "candidate_flags": [flag for flag, enabled in (("--disable-object-culling", candidate_no_culling), ("--disable-instancing", candidate_no_instancing)) if enabled],
                "paired_deltas": {
                    metric_name: {
                        "paired_candidate_minus_baseline_ms": values,
                        "paired_delta_median": statistics.median(values) if values else None,
                        "paired_delta_p95": percentile(values, 0.95),
                    }
                    for metric_name, values in metric_deltas.items()
                },
                "p95_paired_deltas": {
                    metric_name: {"values": values, "median": statistics.median(values) if values else None, "p95": percentile(values, 0.95)}
                    for metric_name, values in p95_deltas.items()
                },
                "gpu_stage_pairs": [
                    {"pair": pair["pair"], "metrics": {key: value for key, value in pair["deltas"].items() if key.startswith("gpu_")}}
                    for pair in pair_reports
                ],
                "pairs": pair_reports,
                "per_run": runs,
            }
        report["tiers"][str(tier)] = tier_report
        path = args.output / "study.json"
        path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"study": str(args.output / 'study.json'), "tiers": list(report['tiers']), "pairs": args.pairs}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
