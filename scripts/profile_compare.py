#!/usr/bin/env python3
"""Run paired, alternating offscreen benchmarks and write a provenance report."""

from __future__ import annotations

import argparse
import hashlib
import math
import json
import platform
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "crates/engine/src", ROOT / "crates/engine-lab/src")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprints(paths: list[Path]) -> dict[str, str]:
    files: set[Path] = set()
    for path in paths:
        if path.is_file():
            files.add(path)
        elif path.is_dir():
            files.update(child for child in path.rglob("*") if child.is_file())
    return {
        str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path): sha256(path)
        for path in sorted(files)
    }


def scene_asset_paths(scene_path: Path) -> list[Path]:
    scene = json.loads(scene_path.read_text())
    assets = []
    for obj in scene.get("objects", []):
        geometry = obj.get("geometry", {})
        if geometry.get("kind") == "glb" and geometry.get("path"):
            assets.append((scene_path.parent / geometry["path"]).resolve())
    return assets


def scene_route_ids(scene_path: Path) -> list[str]:
    scene = json.loads(scene_path.read_text())
    return [route["id"] for route in scene.get("routes", []) if isinstance(route.get("id"), str)]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = max(0, min(len(values) - 1, math.ceil(len(values) * fraction) - 1))
    return values[index]


def summarize(values: list[float]) -> dict[str, float | int | None]:
    return {
        "median_ms": percentile(values, 0.5),
        "p95_ms": percentile(values, 0.95),
        "samples": len(values),
    }


def paired_deltas(baseline: list[float | None], candidate: list[float | None]) -> list[float]:
    """Keep pair alignment when a stage is unavailable in either run."""
    return [
        candidate_value - baseline_value
        for baseline_value, candidate_value in zip(baseline, candidate)
        if baseline_value is not None and candidate_value is not None
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=Path("assets/scenes/clearing.json"))
    parser.add_argument("--candidate", type=Path, required=True, help="candidate scene JSON")
    parser.add_argument("--route", help="route ID; defaults to the first route shared by both scenes")
    parser.add_argument("--mode", choices=("serial", "buffered"), default="serial")
    parser.add_argument("--duration", type=float, default=120.0, help="measured route seconds")
    parser.add_argument("--warmup", type=float, default=10.0, help="warmup seconds per run")
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--measure-overhead", action="store_true", help="repeat every run without GPU timestamps")
    parser.add_argument("--baseline-force-shadow-redraw", action="store_true", help="disable shadow caching for the baseline runs")
    parser.add_argument("--candidate-force-shadow-redraw", action="store_true", help="disable shadow caching for the candidate runs")
    parser.add_argument("--baseline-disable-tile-lists", action="store_true", help="use exhaustive candidate evaluation in baseline runs")
    parser.add_argument("--candidate-disable-tile-lists", action="store_true", help="use exhaustive candidate evaluation in candidate runs")
    parser.add_argument("--baseline-force-tile-overflow", action="store_true", help="force exhaustive overflow fallback in baseline runs")
    parser.add_argument("--candidate-force-tile-overflow", action="store_true", help="force exhaustive overflow fallback in candidate runs")
    parser.add_argument("--baseline-disable-object-culling", action="store_true", help="draw all objects in every applicable pass for baseline runs")
    parser.add_argument("--candidate-disable-object-culling", action="store_true", help="draw all objects in every applicable pass for candidate runs")
    parser.add_argument("--baseline-disable-instancing", action="store_true", help="issue one object draw per instance in baseline runs")
    parser.add_argument("--candidate-disable-instancing", action="store_true", help="issue one object draw per instance in candidate runs")
    parser.add_argument("--moving-caster", help="move this scene object around the primary fire light in both benchmark variants")
    parser.add_argument("--caster-orbit-radius", type=float, default=5.0)
    parser.add_argument("--caster-orbit-period", type=float, default=20.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--camera", default="hero")
    parser.add_argument("--resolution", help="explicit scene buffer, for example 640x360")
    parser.add_argument("--output", type=Path, default=Path("artifacts/profile-comparison"))
    parser.add_argument("--binary", type=Path, help="use an existing engine-lab binary")
    parser.add_argument("--shaders", type=Path, help="shader directory passed to engine-lab")
    args = parser.parse_args()

    if args.pairs < 1:
        parser.error("--pairs must be at least 1")
    baseline = (ROOT / args.baseline).resolve() if not args.baseline.is_absolute() else args.baseline
    candidate = (ROOT / args.candidate).resolve() if not args.candidate.is_absolute() else args.candidate
    for scene in (baseline, candidate):
        if not scene.is_file():
            parser.error(f"scene does not exist: {scene}")
    if args.route is None:
        candidate_routes = scene_route_ids(candidate)
        baseline_routes = set(scene_route_ids(baseline))
        args.route = next((route for route in candidate_routes if route in baseline_routes), None)
        if args.route is None:
            parser.error("baseline and candidate have no shared route; specify --route")

    output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
    output.mkdir(parents=True, exist_ok=True)
    build_seconds = 0.0
    if args.binary:
        binary = args.binary.resolve()
    else:
        build_started = time.perf_counter()
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
        build_seconds = time.perf_counter() - build_started
        binary = ROOT / "target/release/engine-lab"
    if not binary.is_file():
        parser.error(f"engine-lab binary does not exist: {binary}")

    source_files = [path for root in SOURCE_ROOTS for path in root.rglob("*.rs")]
    shader_path = args.shaders.resolve() if args.shaders else ROOT / "crates/engine/src/render/shaders"
    build_inputs = [ROOT / "Cargo.toml", ROOT / "Cargo.lock", ROOT / "rust-toolchain.toml"]
    fixed_fingerprints = fingerprints([*source_files, *build_inputs, shader_path])
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    scenes = {"baseline": baseline, "candidate": candidate}
    reports: dict[str, list[dict]] = {
        "baseline": [],
        "candidate": [],
        "baseline_without_gpu_timing": [],
        "candidate_without_gpu_timing": [],
    }
    run_order: list[dict[str, str | int]] = []

    for pair in range(args.pairs):
        variants = ["baseline", "candidate"] if pair % 2 == 0 else ["candidate", "baseline"]
        order = [(variant, True) for variant in variants]
        if args.measure_overhead:
            order = [(variant, enabled) for variant in variants for enabled in (True, False)]
        for variant, gpu_timing_enabled in order:
            no_timing_suffix = "" if gpu_timing_enabled else "-no-gpu-timing"
            run_id = f"pair-{pair + 1:02d}-{variant}{no_timing_suffix}"
            raw_path = output / f"{run_id}.engine.json"
            report_path = output / f"{run_id}.json"
            command = [
                str(binary), "benchmark", "--scene", str(scenes[variant]),
                "--mode", args.mode, "--route", args.route, "--duration", str(args.duration),
                "--warmup", str(args.warmup), "--seed", str(args.seed),
                "--camera", args.camera, "--output", str(raw_path),
            ]
            if args.moving_caster:
                command.extend([
                    "--moving-caster", args.moving_caster,
                    "--caster-orbit-radius", str(args.caster_orbit_radius),
                    "--caster-orbit-period", str(args.caster_orbit_period),
                ])
            if args.resolution:
                command.extend(["--resolution", args.resolution])
            if args.shaders:
                command.extend(["--shaders", str(shader_path)])
            force_shadow_redraw = (
                args.baseline_force_shadow_redraw
                if variant == "baseline"
                else args.candidate_force_shadow_redraw
            )
            if force_shadow_redraw:
                command.append("--force-shadow-redraw")
            disable_tile_lists = (
                args.baseline_disable_tile_lists
                if variant == "baseline"
                else args.candidate_disable_tile_lists
            )
            force_tile_overflow = (
                args.baseline_force_tile_overflow
                if variant == "baseline"
                else args.candidate_force_tile_overflow
            )
            if disable_tile_lists:
                command.append("--disable-tile-lists")
            if force_tile_overflow:
                command.append("--force-tile-overflow")
            disable_object_culling = (
                args.baseline_disable_object_culling
                if variant == "baseline"
                else args.candidate_disable_object_culling
            )
            disable_instancing = (
                args.baseline_disable_instancing
                if variant == "baseline"
                else args.candidate_disable_instancing
            )
            if disable_object_culling:
                command.append("--disable-object-culling")
            if disable_instancing:
                command.append("--disable-instancing")
            if not gpu_timing_enabled:
                command.append("--disable-gpu-timing")
            print(f"[{run_id}] starting", flush=True)
            subprocess.run(command, cwd=ROOT, check=True)
            report = json.loads(raw_path.read_text())
            report["run_id"] = run_id
            report["variant"] = variant
            report["gpu_timing_enabled"] = gpu_timing_enabled
            report["provenance"] = {
                "scene_path": str(scenes[variant]),
                "force_shadow_redraw": force_shadow_redraw,
                "disable_tile_lists": disable_tile_lists,
                "force_tile_overflow": force_tile_overflow,
                "disable_object_culling": disable_object_culling,
                "disable_instancing": disable_instancing,
                "scene_sha256": sha256(scenes[variant]),
                "scene_assets_sha256": fingerprints(scene_asset_paths(scenes[variant])),
                "git_revision": revision,
                "source_and_shader_sha256": fixed_fingerprints,
                "platform": platform.platform(),
                "python": sys.version.split()[0],
            }
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            report_key = variant if gpu_timing_enabled else f"{variant}_without_gpu_timing"
            reports[report_key].append(report)
            run_order.append({"pair": pair + 1, "variant": variant, "run_id": run_id})

    metric_keys = ("frame_work", "cpu_encode", "cpu_tile_list_encode", "cpu_shadow_encode", "cpu_upload", "simulation_cpu", "simulation_encode_cpu", "queue_submit_cpu", "gpu_render")
    stage_names = sorted(
        set(reports["baseline"][0].get("gpu_stages", {}))
        | set(reports["candidate"][0].get("gpu_stages", {}))
    )
    metric_keys += tuple(f"gpu_stages.{stage}" for stage in stage_names)
    comparison = {}
    for key in metric_keys:
        group, _, field = key.partition(".")
        baseline_values = [run[group].get(field, {}).get("median_ms") if field else run[group]["median_ms"] for run in reports["baseline"]]
        candidate_values = [run[group].get(field, {}).get("median_ms") if field else run[group]["median_ms"] for run in reports["candidate"]]
        deltas = paired_deltas(baseline_values, candidate_values)
        baseline_measured = [value for value in baseline_values if value is not None]
        candidate_measured = [value for value in candidate_values if value is not None]
        comparison[key] = {
            "baseline_run_medians_ms": baseline_values,
            "candidate_run_medians_ms": candidate_values,
            "paired_candidate_minus_baseline_ms": deltas,
            "paired_delta_median_ms": percentile(deltas, 0.5),
            "paired_delta_p95_ms": percentile(deltas, 0.95),
            "baseline_median_of_run_medians_ms": percentile(baseline_measured, 0.5),
            "candidate_median_of_run_medians_ms": percentile(candidate_measured, 0.5),
        }

    measurement_overhead = {}
    if args.measure_overhead:
        for variant in ("baseline", "candidate"):
            enabled = reports[variant]
            disabled = reports[f"{variant}_without_gpu_timing"]
            measurement_overhead[variant] = {}
            for key in ("frame_work", "cpu_encode", "cpu_tile_list_encode", "cpu_shadow_encode", "cpu_upload", "simulation_cpu", "simulation_encode_cpu", "queue_submit_cpu"):
                on_values = [run[key]["median_ms"] for run in enabled]
                off_values = [run[key]["median_ms"] for run in disabled]
                deltas = paired_deltas(off_values, on_values)
                measurement_overhead[variant][key] = {
                    "timed_minus_untimed_run_medians_ms": deltas,
                    "median_overhead_ms": percentile(deltas, 0.5),
                }
            for key in ("submitted_frames_per_second", "drained_frames_per_second"):
                on_values = [run[key] for run in enabled]
                off_values = [run[key] for run in disabled]
                deltas = paired_deltas(off_values, on_values)
                measurement_overhead[variant][key] = {
                    "timed_minus_untimed_run_deltas": deltas,
                    "median_delta": percentile(deltas, 0.5),
                }

    measurement_gaps = [
        "exact CPU-to-GPU queue latency: wgpu timestamps have no calibrated host-clock mapping; readback completion latency is reported separately",
        "native presentation and vsync are measured by benchmark-native, not included in this offscreen comparison",
    ]
    if args.mode == "serial":
        measurement_gaps.append("buffered throughput was not measured in this serial comparison")
    if args.binary:
        measurement_gaps.append("engine-lab build time was not measured because an existing binary was supplied")

    report = {
        "version": 1,
        "workflow": "alternating paired offscreen route benchmarks",
        "scope": "Serial runs wait for GPU completion per frame; buffered runs queue frames and drain once. Both exclude native presentation, inspector and vsync. GPU timings are asynchronous and frame/tick tagged. Paired deltas are candidate minus baseline.",
        "configuration": {
            "route": args.route,
            "mode": args.mode,
            "route_seconds": args.duration,
            "warmup_seconds": args.warmup,
            "pairs": args.pairs,
            "engine_lab_build_seconds": build_seconds,
            "measure_profiling_overhead": args.measure_overhead,
            "baseline_force_shadow_redraw": args.baseline_force_shadow_redraw,
            "candidate_force_shadow_redraw": args.candidate_force_shadow_redraw,
            "baseline_disable_tile_lists": args.baseline_disable_tile_lists,
            "candidate_disable_tile_lists": args.candidate_disable_tile_lists,
            "baseline_force_tile_overflow": args.baseline_force_tile_overflow,
            "candidate_force_tile_overflow": args.candidate_force_tile_overflow,
            "baseline_disable_object_culling": args.baseline_disable_object_culling,
            "candidate_disable_object_culling": args.candidate_disable_object_culling,
            "baseline_disable_instancing": args.baseline_disable_instancing,
            "candidate_disable_instancing": args.candidate_disable_instancing,
            "seed": args.seed,
            "camera": args.camera,
            "resolution_override": args.resolution,
            "moving_caster": args.moving_caster,
            "caster_orbit_radius": args.caster_orbit_radius if args.moving_caster else None,
            "caster_orbit_period_seconds": args.caster_orbit_period if args.moving_caster else None,
        },
        "pair_interpretation": (
            "same scene content with different tile-list settings; paired deltas compare tiled candidate evaluation against exhaustive baseline evaluation"
            if sha256(baseline) == sha256(candidate)
            and (args.baseline_disable_tile_lists != args.candidate_disable_tile_lists
                 or args.baseline_force_tile_overflow != args.candidate_force_tile_overflow)
            else "same scene content with different geometry-culling or instancing settings; paired deltas compare the selected object-draw path"
            if sha256(baseline) == sha256(candidate)
            and (args.baseline_disable_object_culling != args.candidate_disable_object_culling
                 or args.baseline_disable_instancing != args.candidate_disable_instancing)
            else "same scene content with different forced-shadow-redraw settings; paired deltas compare full-map cache reuse against redraw-every-frame"
            if sha256(baseline) == sha256(candidate)
            and args.baseline_force_shadow_redraw != args.candidate_force_shadow_redraw
            else "baseline and candidate use identical scene content; paired deltas estimate run-to-run variation, not an optimization gain"
            if sha256(baseline) == sha256(candidate)
            else "paired deltas compare the supplied baseline and candidate scene inputs; this is not a code-version comparison unless their provenance differs"
        ),
        "run_order": run_order,
        "comparison": comparison,
        "measurement_overhead": measurement_overhead if args.measure_overhead else None,
        "runs": {name: [run["run_id"] for run in variants] for name, variants in reports.items()},
        "measurement_gaps": measurement_gaps,
    }
    result_path = output / "comparison.json"
    result_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"comparison": str(result_path), "pairs": args.pairs}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
