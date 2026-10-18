#!/usr/bin/env python3
"""Run alternating native-window tile-list versus exhaustive comparisons."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    "crates/engine-lab/src/main.rs",
    "crates/engine-lab/src/window.rs",
    "crates/engine/src/render/mod.rs",
    "crates/engine/src/render/shaders/tile_build.wgsl",
    "crates/engine/src/render/shaders/fire.wgsl",
    "crates/engine/src/render/shaders/volume.wgsl",
    "crates/engine/src/render/shaders/world.wgsl",
    "crates/engine/src/render/shaders/common.wgsl",
    "scripts/tile_lists_native_study.py",
]


def median_delta(baseline: dict, candidate: dict, key: str) -> float | None:
    before, after = baseline.get(key), candidate.get(key)
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return None
    return after - before


def summary_metric(run: dict, key: str) -> dict:
    value = run.get(key, {})
    if isinstance(value, dict):
        return {k: value.get(k) for k in ("median_ms", "p95_ms", "samples")}
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--duration", type=float, default=120.)
    parser.add_argument("--warmup", type=float, default=10.)
    parser.add_argument("--output", type=Path, default=Path("artifacts/o03/native-tile-lists"))
    args = parser.parse_args()
    if args.pairs < 1 or args.duration <= 0 or args.warmup < 0:
        parser.error("pairs and duration must be positive; warmup cannot be negative")

    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    binary = ROOT / "target/release/engine-lab"
    pairs = []
    for pair in range(1, args.pairs + 1):
        order = ["tiled", "exhaustive"] if pair % 2 else ["exhaustive", "tiled"]
        runs = {}
        for variant in order:
            report_path = output / f"pair-{pair:02d}-{variant}.engine.json"
            command = [
                str(binary), "benchmark-native", "--seed", "42", "--camera", "hero",
                "--route", "clearing-orbit", "--duration", str(args.duration),
                "--warmup", str(args.warmup), "--output", str(report_path),
            ]
            if variant == "exhaustive":
                command.append("--disable-tile-lists")
            with (output / f"pair-{pair:02d}-{variant}.log").open("w") as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            run = json.loads(report_path.read_text())
            if run.get("tile_lists_enabled") != (variant == "tiled"):
                raise RuntimeError(f"{variant} report has unexpected tile-list mode")
            if not run.get("timing_coverage", {}).get("gpu_timestamps_supported"):
                raise RuntimeError("native adapter did not provide GPU timestamps")
            runs[variant] = run
        tiled, exhaustive = runs["tiled"], runs["exhaustive"]
        pairs.append({
            "pair": pair,
            "order": order,
            "deltas_exhaustive_minus_tiled": {
                "frames_per_second": median_delta(tiled, exhaustive, "frames_per_second"),
                "cpu_native_frame_ms": median_delta(
                    tiled.get("cpu_native_frame", {}), exhaustive.get("cpu_native_frame", {}), "median_ms"
                ),
                "gpu_atmosphere_fire_ms": median_delta(
                    tiled.get("gpu_stages", {}).get("atmosphere_fire", {}),
                    exhaustive.get("gpu_stages", {}).get("atmosphere_fire", {}), "median_ms"
                ),
            },
            "tiled": {
                "frames_per_second": tiled["frames_per_second"],
                "cpu_native_frame": summary_metric(tiled, "cpu_native_frame"),
                "gpu_stages": tiled.get("gpu_stages", {}),
                "timing_coverage": tiled["timing_coverage"],
                "report": f"pair-{pair:02d}-tiled.engine.json",
                "report_sha256": hashlib.sha256(
                    (output / f"pair-{pair:02d}-tiled.engine.json").read_bytes()
                ).hexdigest(),
            },
            "exhaustive": {
                "frames_per_second": exhaustive["frames_per_second"],
                "cpu_native_frame": summary_metric(exhaustive, "cpu_native_frame"),
                "gpu_stages": exhaustive.get("gpu_stages", {}),
                "timing_coverage": exhaustive["timing_coverage"],
                "report": (output / f"pair-{pair:02d}-exhaustive.engine.json").name,
                "report_sha256": hashlib.sha256(
                    (output / f"pair-{pair:02d}-exhaustive.engine.json").read_bytes()
                ).hexdigest(),
            },
        })
        print(json.dumps({"pair": pair, "order": order, "deltas": pairs[-1]["deltas_exhaustive_minus_tiled"]}))

    deltas = [pair["deltas_exhaustive_minus_tiled"] for pair in pairs]
    first_run = json.loads((output / f"pair-01-{pairs[0]['order'][0]}.engine.json").read_text())
    binary_bytes = binary.read_bytes()
    report = {
        "workstream": "O03 native-window tile-list versus exhaustive comparison",
        "host": {
            "gpu": first_run["capabilities"].get("name"),
            "backend": first_run["capabilities"].get("backend"),
            "os": platform.platform(),
        },
        "scene": "assets/scenes/clearing.json",
        "scene_sha256": hashlib.sha256((ROOT / "assets/scenes/clearing.json").read_bytes()).hexdigest(),
        "camera": "hero",
        "route": "clearing-orbit",
        "seed": 42,
        "resolution": [640, 360],
        "duration_seconds_per_run": args.duration,
        "warmup_seconds": args.warmup,
        "git_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip(),
        "binary_sha256": hashlib.sha256(binary_bytes).hexdigest(),
        "source_sha256": {
            source: hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
            for source in SOURCES
        },
        "pairs": pairs,
        "paired_medians_exhaustive_minus_tiled": {
            key: statistics.median(v[key] for v in deltas if v[key] is not None)
            for key in ("frames_per_second", "cpu_native_frame_ms", "gpu_atmosphere_fire_ms")
        },
        "limitations": [
            "Native-window results include surface acquisition, UI, submission and vsync.",
            "CPU spans overlap and must not be summed; GPU stage and full-window measures are separate.",
            "This is one M1 Max/Metal route and does not qualify other adapters or Windows/DX12.",
        ],
    }
    (output / "study.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"study": str(output / 'study.json'), "pairs": len(pairs)}))


if __name__ == "__main__":
    main()
