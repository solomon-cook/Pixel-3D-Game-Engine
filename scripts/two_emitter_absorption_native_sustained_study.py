#!/usr/bin/env python3
"""Measure direct versus cached dual-emitter absorption in native-window routes."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/two-emitter-review.json"
ROUTE = "clearing-orbit"
CAMERA = "dual-wide"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_scenes(output: Path, source: dict, cache_resolution: int) -> dict[str, Path]:
    paths = {}
    for name, enabled in (("direct", False), ("cached", True)):
        scene = json.loads(json.dumps(source))
        scene["render"]["absorption_cache_resolution"] = cache_resolution
        scene.setdefault("render", {}).setdefault("experiments", {})["smoke_absorption_cache"] = enabled
        path = output / "scenes" / f"cache{cache_resolution}" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(scene, indent=2) + "\n")
        paths[name] = path
    return paths


def metric(run: dict, category: str, name: str) -> dict | None:
    if category == "fps":
        value = run.get("frames_per_second")
        return {"median": value} if isinstance(value, (int, float)) else None
    if category == "gpu":
        return run.get("gpu_stages", {}).get(name)
    return run.get(category, {})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--scene", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/multi-emitter/absorption-native-sustained")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-multi-emitter-absorption-native-sustained.json")
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--cache-resolution", type=int, choices=(8, 16), default=8)
    args = parser.parse_args()
    if args.pairs < 3 or args.duration <= 0 or args.warmup < 0:
        parser.error("at least three pairs, positive duration and nonnegative warmup are required")
    binary, source_path = args.binary.resolve(), args.scene.resolve()
    output = args.output.resolve()
    report_path = args.report.resolve() if args.report.is_absolute() else ROOT / args.report
    output.mkdir(parents=True, exist_ok=True)
    source = json.loads(source_path.read_text())
    if len(source.get("emitters", [])) != 2:
        parser.error("scene must contain exactly two emitters")
    if not any(item.get("id") == ROUTE for item in source.get("routes", [])):
        parser.error(f"scene is missing route {ROUTE}")
    if not any(item.get("id") == CAMERA for item in source.get("cameras", [])):
        parser.error(f"scene is missing camera {CAMERA}")
    scenes = make_scenes(output, source, args.cache_resolution)
    order = []
    for pair in range(args.pairs):
        order.extend(("direct", "cached") if pair % 2 == 0 else ("cached", "direct"))
    runs = []
    raw_dir = output / "runs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for index, variant in enumerate(order[: args.pairs * 2], start=1):
        report_file = raw_dir / f"{index:02d}-{variant}.json"
        command = [
            str(binary), "benchmark-native", "--scene", str(scenes[variant]),
            "--seed", "42", "--resolution", "640x360", "--route", ROUTE,
            "--camera", CAMERA, "--duration", str(args.duration),
            "--warmup", str(args.warmup), "--absorption-cache-resolution", str(args.cache_resolution),
            "--output", str(report_file),
        ]
        print(f"[{index}/{args.pairs * 2}] native {variant}: starting {args.duration:g}s route", flush=True)
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(f"native benchmark failed ({completed.returncode}): {completed.stderr[-4000:]}\n{completed.stdout[-4000:]}")
        run = json.loads(report_file.read_text())
        expected_bytes = args.cache_resolution ** 3 * 8 if variant == "cached" else 0
        actual_bytes = run.get("capabilities", {}).get("resource_inventory", {}).get("smoke_absorption_cache_bytes")
        if actual_bytes != expected_bytes:
            raise RuntimeError(f"{variant} reported {actual_bytes} cache bytes, expected {expected_bytes}")
        if run.get("workload_counts", {}).get("emitters") != 2:
            raise RuntimeError(f"{variant} benchmark did not render both emitters")
        if not run.get("timing_coverage", {}).get("gpu_timestamps_supported"):
            raise RuntimeError(f"{variant} benchmark lacks GPU timestamp coverage")
        if run.get("timing_coverage", {}).get("rendered_frames", 0) <= 0:
            raise RuntimeError(f"{variant} benchmark rendered no frames")
        run["study_variant"] = variant
        run["study_run"] = index
        runs.append(run)
        print(json.dumps({
            "run": index,
            "variant": variant,
            "fps": run.get("frames_per_second"),
            "frame_work_ms": run.get("cpu_native_frame", {}).get("median_ms"),
            "smoke_compute_ms": run.get("gpu_stages", {}).get("smoke_compute", {}).get("median_ms"),
        }), flush=True)

    comparisons = []
    for pair_index in range(args.pairs):
        first, second = runs[pair_index * 2 : pair_index * 2 + 2]
        by_variant = {run["study_variant"]: run for run in (first, second)}
        if set(by_variant) != {"direct", "cached"}:
            raise RuntimeError(f"pair {pair_index + 1} lacks one variant")
        direct, cached = by_variant["direct"], by_variant["cached"]
        deltas = {}
        for label, category, name in (
            ("fps", "fps", ""),
            ("cpu_native_frame", "cpu_native_frame", ""),
            ("cpu_renderer_encode", "cpu_renderer_encode", ""),
            ("cpu_surface_acquire", "cpu_surface_acquire", ""),
            ("cpu_present_submit", "cpu_present_submit", ""),
            ("gpu_smoke_compute", "gpu", "smoke_compute"),
            ("gpu_atmosphere_fire", "gpu", "atmosphere_fire"),
        ):
            base_metric = metric(direct, category, name)
            candidate_metric = metric(cached, category, name)
            if not base_metric or not candidate_metric:
                deltas[label] = None
                continue
            base = base_metric["median"] if "median" in base_metric else base_metric.get("median_ms")
            candidate = candidate_metric["median"] if "median" in candidate_metric else candidate_metric.get("median_ms")
            deltas[label] = {
                "direct": base,
                "cached": candidate,
                "cached_minus_direct": candidate - base if isinstance(base, (int, float)) and isinstance(candidate, (int, float)) else None,
            }
        comparisons.append({"pair": pair_index + 1, "order": [first["study_variant"], second["study_variant"]], "deltas": deltas})

    median_deltas = {}
    for key in comparisons[0]["deltas"]:
        values = [item["deltas"][key]["cached_minus_direct"] for item in comparisons if item["deltas"][key] and item["deltas"][key]["cached_minus_direct"] is not None]
        if values:
            median_deltas[key] = statistics.median(values)
    report = {
        "version": 1,
        "date": "2026-10-18",
        "study": "native-window dual-emitter absorption-cache sustained comparison",
        "host": {key: runs[0].get("capabilities", {}).get(key) for key in ("name", "backend", "device_type")},
        "native_window": True,
        "source_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "binary_sha256": sha256(binary),
        "source_scene": str(source_path.relative_to(ROOT)) if source_path.is_relative_to(ROOT) else str(source_path),
        "source_scene_sha256": sha256(source_path),
        "scene_sha256": {key: sha256(value) for key, value in scenes.items()},
        "shader_sha256": sha256(ROOT / "crates/engine/src/render/shaders/absorption.wgsl"),
        "study_script_sha256": sha256(Path(__file__).resolve()),
        "source_ids": sorted(item["id"] for item in source["emitters"]),
        "seed": 42,
        "camera": CAMERA,
        "route": ROUTE,
        "resolution": [640, 360],
        "cache_resolution": args.cache_resolution,
        "pairs": args.pairs,
        "duration_seconds_per_run": args.duration,
        "warmup_seconds_per_run": args.warmup,
        "run_order": order[: args.pairs * 2],
        "runs": [{
            "run": item["study_run"],
            "variant": item["study_variant"],
            "path": str((raw_dir / f"{item['study_run']:02d}-{item['study_variant']}.json").relative_to(ROOT)),
            "sha256": sha256(raw_dir / f"{item['study_run']:02d}-{item['study_variant']}.json"),
            "actual_measured_seconds": item.get("actual_measured_seconds"),
            "frames_per_second": item.get("frames_per_second"),
            "cpu_native_frame": item.get("cpu_native_frame"),
            "gpu_stages": item.get("gpu_stages"),
            "timing_coverage": item.get("timing_coverage"),
            "cache_bytes": item.get("capabilities", {}).get("resource_inventory", {}).get("smoke_absorption_cache_bytes"),
            "workload_counts": item.get("workload_counts"),
        } for item in runs],
        "paired_comparisons": comparisons,
        "median_pair_deltas": median_deltas,
        "limitations": [
            "One Apple M1 Max/Metal native window and display configuration; no DX12/other-adapter acceptance.",
            "The 8³ or 16³ cache is rebuilt during moving simulation; this route does not prove other workloads benefit.",
            "GPU stages may overlap and are not summed; FPS and CPU frame work are reported separately.",
            "No image quality metric is gathered by this timing study; fixed-tick and motion-image comparisons are separate reports.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "median_pair_deltas": median_deltas}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
