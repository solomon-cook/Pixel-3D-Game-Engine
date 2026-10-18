#!/usr/bin/env python3
"""Compare serial-submit and batched fixed steps on matched offscreen routes."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
WORKLOADS = (
    ("clearing", "assets/scenes/clearing.json", "clearing-orbit"),
    ("profiling-heavy", "assets/scenes/profiling-heavy.json", "clearing-orbit"),
    ("materials", "assets/scenes/materials.json", "material-orbit"),
    ("two-emitter-review", "assets/scenes/two-emitter-review.json", "clearing-orbit"),
)
PAIR_ORDER = ("serial", "batched", "batched", "serial", "serial", "batched")
BATCH_CAPACITY = 6


def run_variant(binary, scene, route, variant, steps, warmup, duration, output_path):
    command = [
        str(binary),
        "benchmark",
        "--scene",
        str(scene),
        "--route",
        route,
        "--mode",
        "serial",
        "--warmup",
        str(warmup),
        "--duration",
        str(duration),
        "--simulation-steps-per-frame",
        str(steps),
        "--output",
        str(output_path),
    ]
    if variant == "serial":
        command.append("--disable-simulation-batching")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=max(600, int((duration + warmup) * 20)),
    )
    if completed.returncode:
        raise RuntimeError(
            f"benchmark failed ({variant}, {scene}):\n{completed.stdout}\n{completed.stderr}"
        )
    report = json.loads(output_path.read_text())
    if report["simulation_steps_per_frame"] != steps:
        raise RuntimeError(f"benchmark reported wrong step count: {report['simulation_steps_per_frame']}")
    if report["simulation_batching_enabled"] != (variant == "batched"):
        raise RuntimeError("benchmark reported the wrong simulation path")
    expected_samples = math.ceil(duration * 60 / steps)
    if len(report["samples"]) != expected_samples:
        raise RuntimeError(f"expected {expected_samples} samples, got {len(report['samples'])}")
    expected_submissions = math.ceil(steps / BATCH_CAPACITY) if variant == "batched" else steps
    for sample in report["samples"]:
        if sample["cpu_steps"] != steps:
            raise RuntimeError(f"expected {steps} ticks per sample, got {sample['cpu_steps']}")
        if sample["cpu_simulation_submissions"] != expected_submissions:
            raise RuntimeError(
                f"expected {expected_submissions} submissions per sample, "
                f"got {sample['cpu_simulation_submissions']}"
            )
    summaries = {
        key: report[key]
        for key in (
            "frame_work",
            "cpu_encode",
            "cpu_shadow_encode",
            "cpu_upload",
            "simulation_cpu",
            "simulation_encode_cpu",
            "queue_submit_cpu",
            "gpu_render",
            "gpu_stages",
            "timing_coverage",
            "workload_counts",
            "capabilities",
        )
    }
    route_signature = [
        [sample["route_tick"], sample["camera_position"], sample["camera_target"]]
        for sample in report["samples"]
    ]
    return {
        "variant": variant,
        "simulation_submissions_per_sample": expected_submissions,
        "rendered_samples": len(report["samples"]),
        "simulated_ticks": report["duration_simulation_ticks"],
        "sample_hz": report["sample_hz"],
        "submission_wall_seconds": report["submission_wall_seconds"],
        "wall_seconds": report["wall_seconds"],
        "submitted_frames_per_second": report["submitted_frames_per_second"],
        "drained_frames_per_second": report["drained_frames_per_second"],
        "submitted_simulation_ticks_per_second": report["simulation_ticks_per_second_submitted"],
        "drained_simulation_ticks_per_second": report["simulation_ticks_per_second_drained"],
        "route_samples_sha256": hashlib.sha256(
            json.dumps(route_signature, separators=(",", ":")).encode()
        ).hexdigest(),
        "route_start_pose": route_signature[0] if route_signature else None,
        "route_mid_pose": route_signature[len(route_signature) // 2] if route_signature else None,
        "route_end_pose": route_signature[-1] if route_signature else None,
        "summaries": summaries,
    }


def paired_deltas(runs):
    output = []
    for pair in range(1, len(PAIR_ORDER) // 2 + 1):
        baseline = next(run for run in runs if run["pair"] == pair and run["variant"] == "serial")
        batched = next(run for run in runs if run["pair"] == pair and run["variant"] == "batched")
        if baseline["route_samples_sha256"] != batched["route_samples_sha256"]:
            raise RuntimeError(f"route tick/camera mismatch in pair {pair}")
        delta = {"pair": pair}
        for metric in (
            "frame_work",
            "cpu_encode",
            "cpu_shadow_encode",
            "cpu_upload",
            "simulation_cpu",
            "simulation_encode_cpu",
            "queue_submit_cpu",
            "gpu_render",
        ):
            before = baseline["summaries"][metric]
            after = batched["summaries"][metric]
            delta[metric] = {
                "median_ms": after["median_ms"] - before["median_ms"]
                if after["median_ms"] is not None and before["median_ms"] is not None
                else None,
                "p95_ms": after["p95_ms"] - before["p95_ms"]
                if after["p95_ms"] is not None and before["p95_ms"] is not None
                else None,
            }
        output.append(delta)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--steps-per-frame", type=int, default=6)
    parser.add_argument("--warmup", type=float, default=10)
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.steps_per_frame <= 60:
        parser.error("--steps-per-frame must be in 1..60")
    binary = args.binary.resolve()
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    report = {
        "device": "Apple M1 Max",
        "backend": "Metal",
        "resolution": "scene-authored (default 640x360 in the measured scenes)",
        "seed": 42,
        "binary": str(binary),
        "binary_sha256": binary_hash,
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "steps_per_sample": args.steps_per_frame,
        "warmup_simulation_seconds": args.warmup,
        "measured_route_simulation_seconds": args.duration,
        "warmup_ticks": math.ceil(args.warmup * 60),
        "measured_ticks": math.ceil(args.duration * 60),
        "pair_count": len(PAIR_ORDER) // 2,
        "simulation_batch_capacity": BATCH_CAPACITY,
        "pair_order": list(PAIR_ORDER),
        "mode": "serial; timestamps enabled; each rendered sample advances the same fixed tick count in both variants",
        "baseline": "Session.step_unbatched: one smoke compute submission per fixed tick",
        "candidate": "Session.step: batches up to the renderer's six-tick capacity per submission",
        "scenes": {},
    }
    with tempfile.TemporaryDirectory(prefix="pixel-batch-route-") as temporary:
        temporary = Path(temporary)
        for name, scene_relative, route in WORKLOADS:
            scene = ROOT / scene_relative
            runs = []
            for index, variant in enumerate(PAIR_ORDER):
                output = temporary / f"{name}-{index}.json"
                run = run_variant(
                    binary,
                    scene,
                    route,
                    variant,
                    args.steps_per_frame,
                    args.warmup,
                    args.duration,
                    output,
                )
                run.update({"pair": index // 2 + 1, "order_in_pair": index % 2 + 1})
                runs.append(run)
                print(json.dumps({"scene": name, "run": index + 1, "variant": variant}), flush=True)
            report["scenes"][name] = {
                "scene_sha256": hashlib.sha256(scene.read_bytes()).hexdigest(),
                "route": route,
                "runs": runs,
                "paired_deltas_batched_minus_serial": paired_deltas(runs),
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "scenes": list(report["scenes"])}))


if __name__ == "__main__":
    main()
