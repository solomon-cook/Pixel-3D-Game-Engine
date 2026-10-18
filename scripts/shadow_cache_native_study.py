#!/usr/bin/env python3
"""Compare native shadow-cache reuse with forced redraw on a moving caster."""
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
    "crates/engine/src/render/shaders/shadow.wgsl",
    "scripts/shadow_cache_native_study.py",
]


def delta(before: float | None, after: float | None) -> float | None:
    return after - before if before is not None and after is not None else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--duration", type=float, default=120.)
    parser.add_argument("--warmup", type=float, default=10.)
    parser.add_argument("--output", type=Path, default=Path("artifacts/o02/native-shadow-cache"))
    args = parser.parse_args()
    if args.pairs < 1 or args.duration <= 0 or args.warmup < 0:
        parser.error("pairs and duration must be positive; warmup cannot be negative")
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    binary = ROOT / "target/release/engine-lab"
    pairs = []
    for index in range(1, args.pairs + 1):
        order = ["cached", "forced"] if index % 2 else ["forced", "cached"]
        runs = {}
        for variant in order:
            report_path = output / f"pair-{index:02d}-{variant}.engine.json"
            command = [
                str(binary), "benchmark-native", "--seed", "42", "--camera", "hero",
                "--route", "clearing-orbit", "--moving-caster", "rock-0",
                "--caster-orbit-radius", "5", "--caster-orbit-period", "20",
                "--duration", str(args.duration), "--warmup", str(args.warmup),
                "--output", str(report_path),
            ]
            if variant == "forced":
                command.append("--force-shadow-redraw")
            with (output / f"pair-{index:02d}-{variant}.log").open("w") as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            run = json.loads(report_path.read_text())
            if run.get("force_shadow_redraw") != (variant == "forced"):
                raise RuntimeError(f"{variant} report has an unexpected shadow mode")
            if run.get("moving_caster", {}).get("object") != "rock-0":
                raise RuntimeError("native report did not record the requested moving caster")
            if run.get("route_seconds") != args.duration or run.get("warmup_seconds") != args.warmup:
                raise RuntimeError("native report duration does not match the requested study")
            runs[variant] = run
        cached, forced = runs["cached"], runs["forced"]
        pairs.append({
            "pair": index,
            "order": order,
            "deltas_forced_minus_cached": {
                "frames_per_second": delta(cached["frames_per_second"], forced["frames_per_second"]),
                "cpu_native_frame_ms": delta(
                    cached["cpu_native_frame"]["median_ms"], forced["cpu_native_frame"]["median_ms"]
                ),
                "gpu_shadow_maps_ms": delta(
                    cached["gpu_stages"]["shadow_maps"]["median_ms"],
                    forced["gpu_stages"]["shadow_maps"]["median_ms"],
                ),
            },
            "runs": {},
        })
        for variant, run in runs.items():
            raw_name = f"pair-{index:02d}-{variant}.engine.json"
            pairs[-1]["runs"][variant] = {
                "report": raw_name,
                "report_sha256": hashlib.sha256((output / raw_name).read_bytes()).hexdigest(),
                "frames_per_second": run["frames_per_second"],
                "cpu_native_frame": run["cpu_native_frame"],
                "gpu_stages": run["gpu_stages"],
                "shadow_cache": run["shadow_cache"],
                "timing_coverage": run["timing_coverage"],
            }
        print(json.dumps({"pair": index, "order": order, "deltas": pairs[-1]["deltas_forced_minus_cached"]}))

    values = [pair["deltas_forced_minus_cached"] for pair in pairs]
    first = json.loads((output / f"pair-01-{pairs[0]['order'][0]}.engine.json").read_text())
    report = {
        "workstream": "O02 native-window moving-caster shadow-cache comparison",
        "host": {
            "gpu": first["capabilities"].get("name"),
            "backend": first["capabilities"].get("backend"),
            "os": platform.platform(),
        },
        "scene": "assets/scenes/clearing.json",
        "scene_sha256": hashlib.sha256((ROOT / "assets/scenes/clearing.json").read_bytes()).hexdigest(),
        "camera": "hero",
        "route": "clearing-orbit",
        "moving_caster": {"object_id": "rock-0", "radius": 5., "period_seconds": 20.},
        "seed": 42,
        "resolution": first["capabilities"].get("resolution"),
        "present_mode": first.get("present_mode"),
        "duration_seconds_per_run": args.duration,
        "warmup_seconds": args.warmup,
        "git_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "source_sha256": {source: hashlib.sha256((ROOT / source).read_bytes()).hexdigest() for source in SOURCES},
        "pairs": pairs,
        "paired_medians_forced_minus_cached": {
            key: statistics.median(pair[key] for pair in values if pair[key] is not None)
            for key in ("frames_per_second", "cpu_native_frame_ms", "gpu_shadow_maps_ms")
        },
        "limitations": [
            "Native-window results include surface acquisition, UI, submission and vsync.",
            "CPU spans overlap and must not be summed; stage timing and native frame throughput are distinct.",
            "This is one M1 Max/Metal route and does not qualify other adapters or Windows/DX12.",
        ],
    }
    study_path = output / "study.json"
    study_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"study": str(study_path), "pairs": len(pairs)}))


if __name__ == "__main__":
    main()
