#!/usr/bin/env python3
"""Run or summarize sparse O01 shader counters on the optical material orbit."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/materials.json")
    parser.add_argument("--route", default="material-orbit")
    parser.add_argument("--duration", type=float, default=120.)
    parser.add_argument("--warmup", type=float, default=10.)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--raw-report", type=Path, default=ROOT / "artifacts/o01/optical-motion-shading-counters.json")
    parser.add_argument("--reuse-raw", action="store_true", help="summarize an existing benchmark report")
    parser.add_argument("--timing-reference-raw", type=Path, default=ROOT / "artifacts/o01/optical-motion-unstaged-timing.json")
    parser.add_argument("--reuse-timing", action="store_true", help="reuse an existing uninstrumented benchmark report")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o01-optical-counter-route.json")
    args = parser.parse_args()
    binary, scene = args.binary.resolve(), args.scene.resolve()
    raw_path, report_path = args.raw_report.resolve(), args.report.resolve()
    timing_path = args.timing_reference_raw.resolve()
    if not args.reuse_raw:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(binary), "benchmark", "--scene", str(scene), "--route", args.route,
            "--duration", str(args.duration), "--warmup", str(args.warmup),
            "--seed", str(args.seed), "--shading-counter-sampling",
            "--disable-gpu-timing", "--output", str(raw_path),
        ]
        subprocess.run(command, cwd=ROOT, check=True)
    raw = json.loads(raw_path.read_text())
    samples = raw["shading_counter_sampling"]["samples"]
    if len(samples) != 3:
        raise RuntimeError(f"expected three sparse counter samples, found {len(samples)}")
    if not any(sample["counters"]["optical_surface_interactions"] for sample in samples):
        raise RuntimeError("optical route did not exercise any instrumented optical surfaces")
    if not args.reuse_timing:
        timing_path.parent.mkdir(parents=True, exist_ok=True)
        timing_command = [
            str(binary), "benchmark", "--scene", str(scene), "--route", args.route,
            "--duration", str(args.duration), "--warmup", str(args.warmup),
            "--seed", str(args.seed), "--output", str(timing_path),
        ]
        subprocess.run(timing_command, cwd=ROOT, check=True)
    timing_raw = json.loads(timing_path.read_text())
    if timing_raw["route"]["id"] != args.route or timing_raw["seed"] != args.seed:
        raise RuntimeError("uninstrumented timing reference does not match this route and seed")
    report = {
        "version": 1,
        "purpose": "Sparse shader operation counts during a moving optical-material camera route; this instrumented run is not performance evidence.",
        "host": {
            "adapter": raw["capabilities"]["name"],
            "backend": raw["capabilities"]["backend"],
            "native_window": False,
        },
        "workload": {
            "scene": str(scene.relative_to(ROOT)),
            "scene_sha256": sha256(scene),
            "seed": raw["seed"],
            "route": raw["route"]["id"],
            "route_duration_seconds": raw["route_seconds"],
            "warmup_seconds": raw["warmup_seconds"],
            "sample_rate_hz": raw["sample_hz"],
            "resolution": raw["capabilities"]["resolution"],
            "workload_counts": raw["workload_counts"],
        },
        "timing_scope": {
            "gpu_timing_enabled": raw["gpu_timing_enabled"],
            "performance_data_usable": raw["performance_data_usable"],
            "reason": raw["performance_data_note"],
            "reference": {
                "report": str(timing_path.relative_to(ROOT)),
                "scene_sha256": sha256(scene),
                "route": timing_raw["route"]["id"],
                "duration_seconds": timing_raw["route_seconds"],
                "warmup_seconds": timing_raw["warmup_seconds"],
                "optical_resolve_median_ms": timing_raw["gpu_stages"]["optical_resolve"]["median_ms"],
                "gpu_render_median_ms": timing_raw["gpu_render"]["median_ms"],
                "frame_work_median_ms": timing_raw["frame_work"]["median_ms"],
                "note": "Separate uninstrumented benchmark launched with the same scene, route, seed, duration and warm-up; not timing from the atomic counter run.",
            },
        },
        "counter_samples": samples,
        "counter_instrumentation": {
            "renderer_source_sha256": sha256(ROOT / "crates/engine/src/render/mod.rs"),
            "optical_shader_sha256": sha256(ROOT / "crates/engine/src/render/shaders/optical.wgsl"),
            "binary_sha256": sha256(binary),
            "raw_report": str(raw_path.relative_to(ROOT)),
            "raw_report_sha256": sha256(raw_path),
        },
        "limitations": [
            "Three sparse samples characterize operation counts, not every route frame.",
            "Instrumented GPU timings are disabled and must not be used for performance conclusions.",
            "M1 Max/Metal only; native-window, Windows/DX12 and other adapters remain unverified.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "samples": len(samples), "optical_surface_interactions": [sample["counters"]["optical_surface_interactions"] for sample in samples]}))


if __name__ == "__main__":
    main()
