#!/usr/bin/env python3
"""Compare optimized and legacy smoke-tick Globals uploads in native playback."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "crates/engine-lab/src/main.rs",
    "crates/engine-lab/src/window.rs",
    "crates/engine/src/render/mod.rs",
    "crates/engine-lab/src/window.rs",
    "crates/engine/src/render/shaders/fire_projected_bounds.wgsl",
    "scripts/fire_bounds_native_study.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def median_delta(candidate: dict, baseline: dict, key: str) -> float | None:
    after, before = candidate.get(key), baseline.get(key)
    if not isinstance(after, (int, float)) or not isinstance(before, (int, float)):
        return None
    return after - before


def metric(run: dict, path: tuple[str, ...]) -> dict:
    value = run
    for key in path:
        value = value.get(key, {}) if isinstance(value, dict) else {}
    if isinstance(value, dict):
        return {key: value.get(key) for key in ("median_ms", "p95_ms", "samples")}
    return {}


def validate_timing_coverage(run: dict) -> None:
    coverage = run.get("timing_coverage", {})
    rendered = coverage.get("rendered_frames", 0)
    timed = coverage.get("timed_render_frames", 0)
    if not coverage.get("gpu_timestamps_supported"):
        raise RuntimeError("native adapter did not provide GPU timestamps")
    if not rendered or timed / rendered < 0.99:
        raise RuntimeError(f"native GPU timing coverage below 99%: {timed}/{rendered}")
    compute = coverage.get("smoke_compute_samples", 0)
    expected_compute = round(run.get("route_seconds", 0) * 60)
    if not expected_compute or compute / expected_compute < 0.99:
        raise RuntimeError(f"native smoke-compute timing coverage below 99%: {compute}/{expected_compute}")


def mean_sample(run: dict, key: str) -> float | None:
    values = [sample[key] for sample in run.get("samples", []) if isinstance(sample.get(key), (int, float))]
    return statistics.mean(values) if values else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/clearing.json")
    parser.add_argument("--camera", default="hero")
    parser.add_argument("--route", default="clearing-orbit")
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o08/globals-upload-native")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o08-globals-upload-native.json")
    parser.add_argument("--resume", action="store_true", help="reuse completed pair reports in the output directory")
    args = parser.parse_args()
    binary = args.binary.resolve()
    scene = args.scene.resolve()
    output = args.output.resolve()
    report_path = args.report.resolve()
    if not binary.is_file() or not scene.is_file():
        parser.error("binary and scene must exist")
    if args.pairs < 1 or args.duration <= 0 or args.warmup < 0:
        parser.error("pairs and duration must be positive; warmup cannot be negative")
    output.mkdir(parents=True, exist_ok=True)

    pairs = []
    for pair in range(1, args.pairs + 1):
        order = ("optimized", "legacy") if pair % 2 else ("legacy", "optimized")
        runs = {}
        for variant in order:
            report = output / f"pair-{pair:02d}-{variant}.engine.json"
            command = [
                str(binary), "benchmark-native", "--scene", str(scene), "--camera", args.camera,
                "--seed", "42", "--route", args.route, "--duration", str(args.duration),
                "--warmup", str(args.warmup), "--output", str(report),
            ]
            if variant == "legacy":
                command.append("--legacy-smoke-globals-upload")
            if not (args.resume and report.is_file()):
                with (output / f"pair-{pair:02d}-{variant}.log").open("w") as log:
                    subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            run = json.loads(report.read_text())
            if run.get("legacy_smoke_globals_upload") is not (variant == "legacy"):
                raise RuntimeError(f"{variant} run reports the wrong Globals upload setting")
            if run.get("tile_lists_enabled") is not True:
                raise RuntimeError(f"{variant} run did not use tile lists")
            validate_timing_coverage(run)
            runs[variant] = run
        baseline, candidate = runs["legacy"], runs["optimized"]
        pairs.append({
            "pair": pair,
            "order": list(order),
            "deltas_optimized_minus_legacy": {
                "frames_per_second": median_delta(candidate, baseline, "frames_per_second"),
                "cpu_native_frame_ms": median_delta(
                    candidate.get("cpu_native_frame", {}), baseline.get("cpu_native_frame", {}), "median_ms"
                ),
                "cpu_upload_ms": median_delta(candidate.get("cpu_upload", {}), baseline.get("cpu_upload", {}), "median_ms"),
                "gpu_atmosphere_fire_ms": median_delta(
                    candidate.get("gpu_stages", {}).get("atmosphere_fire", {}),
                    baseline.get("gpu_stages", {}).get("atmosphere_fire", {}), "median_ms"
                ),
                "globals_uploads_per_frame": (mean_sample(candidate, "globals_uploads") or 0)
                    - (mean_sample(baseline, "globals_uploads") or 0),
                "globals_upload_bytes_per_frame": (mean_sample(candidate, "globals_upload_bytes") or 0)
                    - (mean_sample(baseline, "globals_upload_bytes") or 0),
            },
            "legacy": {
                "frames_per_second": baseline["frames_per_second"],
                "cpu_native_frame": metric(baseline, ("cpu_native_frame",)),
                "gpu_atmosphere_fire": metric(baseline, ("gpu_stages", "atmosphere_fire")),
                "timing_coverage": baseline["timing_coverage"],
                "cpu_upload": metric(baseline, ("cpu_upload",)),
                "mean_globals_uploads_per_frame": mean_sample(baseline, "globals_uploads"),
                "mean_globals_upload_bytes_per_frame": mean_sample(baseline, "globals_upload_bytes"),
                "report": f"pair-{pair:02d}-legacy.engine.json",
                "report_sha256": sha256(output / f"pair-{pair:02d}-legacy.engine.json"),
            },
            "optimized": {
                "frames_per_second": candidate["frames_per_second"],
                "cpu_native_frame": metric(candidate, ("cpu_native_frame",)),
                "gpu_atmosphere_fire": metric(candidate, ("gpu_stages", "atmosphere_fire")),
                "timing_coverage": candidate["timing_coverage"],
                "cpu_upload": metric(candidate, ("cpu_upload",)),
                "mean_globals_uploads_per_frame": mean_sample(candidate, "globals_uploads"),
                "mean_globals_upload_bytes_per_frame": mean_sample(candidate, "globals_upload_bytes"),
                "report": f"pair-{pair:02d}-optimized.engine.json",
                "report_sha256": sha256(output / f"pair-{pair:02d}-optimized.engine.json"),
            },
        })
        print(json.dumps({"pair": pair, "order": order, "deltas": pairs[-1]["deltas_optimized_minus_legacy"]}))

    fields = (
        "frames_per_second", "cpu_native_frame_ms", "cpu_upload_ms", "gpu_atmosphere_fire_ms",
        "globals_uploads_per_frame", "globals_upload_bytes_per_frame",
    )
    paired = {}
    for key in fields:
        values = [
            pair["deltas_optimized_minus_legacy"][key]
            for pair in pairs if pair["deltas_optimized_minus_legacy"][key] is not None
        ]
        paired[key] = statistics.median(values) if values else None
    first_run = json.loads((output / f"pair-01-{pairs[0]['order'][0]}.engine.json").read_text())
    report = {
        "workstream": "O08 native-window smoke Globals upload cleanup",
        "host": {
            "adapter": first_run["capabilities"].get("name"),
            "backend": first_run["capabilities"].get("backend"),
            "os": platform.platform(),
        },
        "scene": str(scene.relative_to(ROOT)) if scene.is_relative_to(ROOT) else str(scene),
        "scene_sha256": sha256(scene),
        "camera": args.camera,
        "route": args.route,
        "seed": 42,
        "resolution": first_run["capabilities"].get("resolution"),
        "duration_seconds_per_run": args.duration,
        "warmup_seconds": args.warmup,
        "git_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE
        ).stdout.strip(),
        "binary_sha256": sha256(binary),
        "source_sha256": {source: sha256(ROOT / source) for source in SOURCES},
        "pairs": pairs,
        "paired_medians_optimized_minus_legacy": paired,
        "limitations": [
            "Native-window results include surface acquisition, UI, submission and vsync.",
            "CPU spans overlap and must not be summed; the atmosphere/fire GPU stage and full-window measures are separate.",
            "This host and route do not qualify Windows/DX12 or other adapters.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "pairs": len(pairs), "paired_medians": paired}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
