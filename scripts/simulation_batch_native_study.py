#!/usr/bin/env python3
"""Compare serial and batched smoke submissions in the native window."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENE = "assets/scenes/clearing.json"
SOURCES = (
    "crates/engine-lab/src/main.rs",
    "crates/engine-lab/src/window.rs",
    "crates/engine/src/session.rs",
    "crates/engine/src/render/mod.rs",
    "scripts/simulation_batch_native_study.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def delta(before: dict, after: dict, key: str) -> float | None:
    a, b = before.get(key), after.get(key)
    if isinstance(a, dict):
        a = a.get("median_ms")
    if isinstance(b, dict):
        b = b.get("median_ms")
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return b - a
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", default=SCENE)
    parser.add_argument("--camera", default="hero")
    parser.add_argument("--route", default="clearing-orbit")
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=Path("artifacts/o08/batch-native"))
    parser.add_argument("--report", type=Path, default=Path("docs/measurements-o08-batch-native.json"))
    args = parser.parse_args()
    if args.pairs < 1 or args.duration <= 0 or args.warmup < 0:
        parser.error("pairs and duration must be positive; warmup cannot be negative")

    scene = Path(args.scene)
    scene = scene if scene.is_absolute() else ROOT / scene
    output = args.output if args.output.is_absolute() else ROOT / args.output
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    binary = ROOT / "target/release/engine-lab"
    pairs = []
    first_capabilities = None

    for pair in range(1, args.pairs + 1):
        order = ["batched", "serial"] if pair % 2 else ["serial", "batched"]
        runs = {}
        for variant in order:
            path = output / f"pair-{pair:02d}-{variant}.json"
            command = [
                str(binary), "benchmark-native", "--scene", str(scene),
                "--seed", "42", "--camera", args.camera, "--route", args.route,
                "--duration", str(args.duration), "--warmup", str(args.warmup),
                "--output", str(path),
            ]
            if variant == "serial":
                command.append("--disable-simulation-batching")
            with (output / f"pair-{pair:02d}-{variant}.log").open("w") as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            run = json.loads(path.read_text())
            if run.get("simulation_batching_enabled") != (variant == "batched"):
                raise RuntimeError(f"{variant} report has incorrect simulation batching mode")
            accounting = run.get("simulation_accounting", {})
            if accounting.get("batching_enabled") != (variant == "batched"):
                raise RuntimeError(f"{variant} report has incorrect simulation accounting mode")
            if accounting.get("queue_submissions", 0) <= 0 or accounting.get("fixed_ticks", 0) <= 0:
                raise RuntimeError(f"{variant} report has no simulation tick/submission accounting")
            if variant == "serial" and accounting["queue_submissions"] != accounting["fixed_ticks"]:
                raise RuntimeError("serial baseline must submit once per fixed tick")
            if variant == "batched" and accounting["queue_submissions"] > accounting["fixed_ticks"]:
                raise RuntimeError("batched simulation submitted more times than fixed ticks")
            if not run.get("timing_coverage", {}).get("gpu_timestamps_supported"):
                raise RuntimeError("native adapter did not provide GPU timestamp coverage")
            if run.get("timing_coverage", {}).get("rendered_frames", 0) <= 0:
                raise RuntimeError("native benchmark rendered no frames")
            route = run.get("route")
            if not isinstance(route, dict) or route.get("id") != args.route or run.get("seed") != 42:
                raise RuntimeError("native benchmark route or seed differs from requested controls")
            first_capabilities = first_capabilities or run.get("capabilities", {})
            runs[variant] = run

        serial, batched = runs["serial"], runs["batched"]
        serial_submissions = serial["simulation_accounting"]["queue_submissions"]
        batched_submissions = batched["simulation_accounting"]["queue_submissions"]
        deltas = {
            "frames_per_second": delta(serial, batched, "frames_per_second"),
            "cpu_native_frame_ms": delta(serial, batched, "cpu_native_frame"),
            "cpu_simulation_submit_ms": delta(serial, batched, "cpu_simulation_submit"),
            "gpu_smoke_compute_ms": delta(
                serial.get("gpu_stages", {}), batched.get("gpu_stages", {}), "smoke_compute"
            ),
            "gpu_atmosphere_fire_ms": delta(
                serial.get("gpu_stages", {}), batched.get("gpu_stages", {}), "atmosphere_fire"
            ),
        }
        pair_record = {
            "pair": pair,
            "order": order,
            "batched_minus_serial": deltas,
            "simulation_submissions": {
                "serial": serial_submissions,
                "batched": batched_submissions,
                "reduction_fraction": 1. - batched_submissions / serial_submissions,
            },
        }
        for variant, run in runs.items():
            name = f"pair-{pair:02d}-{variant}.json"
            pair_record[variant] = {
                "report": name,
                "sha256": sha256(output / name),
                "frames_per_second": run.get("frames_per_second"),
                "cpu_native_frame": run.get("cpu_native_frame"),
                "cpu_simulation_submit": run.get("cpu_simulation_submit"),
                "simulation_accounting": run.get("simulation_accounting"),
                "gpu_stages": run.get("gpu_stages"),
                "timing_coverage": run.get("timing_coverage"),
                "actual_measured_seconds": run.get("actual_measured_seconds"),
            }
        pairs.append(pair_record)
        print(json.dumps({"pair": pair, "order": order, "batched_minus_serial": deltas}), flush=True)

    keys = tuple(pairs[0]["batched_minus_serial"])
    medians = {
        key: statistics.median(
            pair["batched_minus_serial"][key]
            for pair in pairs
            if pair["batched_minus_serial"][key] is not None
        )
        for key in keys
        if any(pair["batched_minus_serial"][key] is not None for pair in pairs)
    }
    report = {
        "version": 1,
        "study": "O08 native-window serial versus batched smoke submission",
        "host": {
            "gpu": (first_capabilities or {}).get("name"),
            "backend": (first_capabilities or {}).get("backend"),
            "os": platform.platform(),
        },
        "scene": str(scene.relative_to(ROOT)) if scene.is_relative_to(ROOT) else str(scene),
        "scene_sha256": sha256(scene),
        "camera": args.camera,
        "route": args.route,
        "seed": 42,
        "resolution": (first_capabilities or {}).get("resolution"),
        "duration_seconds_per_run": args.duration,
        "warmup_seconds": args.warmup,
        "pairs": pairs,
        "paired_median_batched_minus_serial": medians,
        "git_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip(),
        "source_worktree_dirty": bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, check=True, text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()),
        "binary_sha256": sha256(binary),
        "source_sha256": {source: sha256(ROOT / source) for source in SOURCES},
        "limitations": [
            "This report covers one M1 Max/Metal native window, scene, route and display configuration.",
            "CPU spans overlap and are not additive; GPU stages are reported separately.",
            "The timing comparison does not establish image parity or visual acceptance; those are separate gates.",
            "Windows/DX12 and other-adapter acceptance remain open.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "paired_medians": medians}, indent=2))


if __name__ == "__main__":
    main()
