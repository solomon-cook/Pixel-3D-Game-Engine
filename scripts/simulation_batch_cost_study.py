#!/usr/bin/env python3
"""Measure fixed-step catch-up burst costs before and after submission batching.

This isolates Session.step submission/encoding overhead. It is not a moving-route,
render-throughput, or native-window performance study.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SCENES = (
    "assets/scenes/clearing.json",
    "assets/scenes/two-emitter-review.json",
)
WARMUP_TICKS = 600
MEASURED_TICKS = 7200
PAIRS = 3


def percentile(values, q):
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * q)]


def run_once(binary, cwd, scene, variant):
    stderr_log = tempfile.TemporaryFile(mode="w+t")
    process = subprocess.Popen(
        [str(binary), "serve", "--scene", str(scene), "--seed", "42"],
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr_log,
        text=True,
    )
    sequence = 0

    def request(method, **params):
        nonlocal sequence
        sequence += 1
        process.stdin.write(
            json.dumps({"id": sequence, "method": method, "params": params}) + "\n"
        )
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(f"{binary} exited before responding to {method}")
        response = json.loads(line)
        if response.get("id") != sequence:
            raise RuntimeError(f"unexpected response: {response}")
        if "error" in response:
            raise RuntimeError(f"{method} failed: {response['error']}")
        return response["result"]

    failure = None
    try:
        request("step", ticks=WARMUP_TICKS)
        before = request("get_metrics")["frame"]
        started = time.perf_counter()
        request("step", ticks=MEASURED_TICKS)
        request_elapsed_ms = (time.perf_counter() - started) * 1000
        after = request("get_metrics")["frame"]
        fields = (
            "cpu_simulation_submit_ms",
            "cpu_simulation_encode_ms",
            "cpu_queue_submit_ms",
            "cpu_upload_ms",
        )
        deltas = {key: after[key] - before[key] for key in fields}
        steps = after["cpu_steps_this_frame"] - before["cpu_steps_this_frame"]
        submission_field = "cpu_simulation_submissions_this_frame"
        reported_submissions = after.get(submission_field)
        if reported_submissions is None:
            # The baseline revision's Session::step submits once inside each tick.
            submissions = MEASURED_TICKS
            submissions_source = "pre-batch Session::step loop, one simulate call per tick"
        else:
            submissions = reported_submissions - before.get(submission_field, 0)
            submissions_source = "FrameMetrics.cpu_simulation_submissions_this_frame"
        if steps != MEASURED_TICKS:
            raise RuntimeError(f"expected {MEASURED_TICKS} measured steps, got {steps}")
        if variant == "batched" and submissions != (MEASURED_TICKS + 5) // 6:
            raise RuntimeError(f"expected 1200 batched submissions, got {submissions}")
        result = {
            "measured_ticks": steps,
            "simulation_submissions": submissions,
            "submission_count_source": submissions_source,
            "request_elapsed_ms": request_elapsed_ms,
            "request_ticks_per_second": MEASURED_TICKS / (request_elapsed_ms / 1000),
            **deltas,
        }
    except Exception as exception:
        failure = exception
        result = None
    finally:
        process.stdin.close()
        try:
            return_code = process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            stderr_log.close()
            raise RuntimeError(f"{binary} did not exit after 120 seconds")
    stderr_log.seek(0)
    stderr = stderr_log.read()
    stderr_log.close()
    if failure:
        raise RuntimeError(f"{failure}\n{stderr}") from failure
    if return_code:
        raise RuntimeError(f"{binary} exited {return_code}\n{stderr}")
    return result


def summarize(values):
    return {
        "median": statistics.median(values),
        "p95_nearest_rank": percentile(values, 0.95),
        "runs": values,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-binary", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--candidate-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline_binary = args.baseline_binary.resolve()
    baseline_root = args.baseline_root.resolve()
    candidate_binary = args.candidate_binary.resolve()
    candidate_root = args.candidate_root.resolve()
    revisions = {
        "baseline": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=baseline_root, text=True
        ).strip(),
        "batched": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=candidate_root, text=True
        ).strip(),
    }
    report = {
        "device": "Apple M1 Max",
        "backend": "Metal",
        "seed": 42,
        "warmup_ticks": WARMUP_TICKS,
        "measured_ticks_per_run": MEASURED_TICKS,
        "pair_count": PAIRS,
        "scene_scope": list(SCENES),
        "method": "Fixed-step catch-up burst through the headless Session protocol; one 7,200-tick request after a 600-tick (10 simulated second) warm-up; three alternating baseline/candidate pairs.",
        "limitations": [
            "No camera movement, frame rendering, native presentation, or 120-second wall-clock route.",
            "Queue-submit metrics are CPU submission-call time and do not measure GPU completion latency.",
            "Results characterize catch-up bursts only; do not infer ordinary one-tick-per-frame throughput.",
        ],
        "revisions": revisions,
        "scenes": {},
    }
    for scene_relative in SCENES:
        scene = (ROOT / scene_relative).resolve()
        scene_name = Path(scene_relative).stem
        order = ["baseline", "batched", "batched", "baseline", "baseline", "batched"]
        runs = []
        for run_index, variant in enumerate(order):
            binary, cwd = (
                (baseline_binary, baseline_root)
                if variant == "baseline"
                else (candidate_binary, candidate_root)
            )
            result = run_once(binary, cwd, scene, variant)
            runs.append({"pair": run_index // 2 + 1, "variant": variant, **result})
        variants = {}
        for variant in ("baseline", "batched"):
            selected = [run for run in runs if run["variant"] == variant]
            variants[variant] = {
                key: summarize([run[key] for run in selected])
                for key in (
                    "simulation_submissions",
                    "request_elapsed_ms",
                    "request_ticks_per_second",
                    "cpu_simulation_submit_ms",
                    "cpu_simulation_encode_ms",
                    "cpu_queue_submit_ms",
                    "cpu_upload_ms",
                )
            }
        report["scenes"][scene_name] = {
            "scene_sha256": hashlib.sha256(scene.read_bytes()).hexdigest(),
            "runs": runs,
            "summary": variants,
        }
    report["paired_median_deltas_batched_minus_baseline"] = {}
    for scene_name, data in report["scenes"].items():
        baseline = data["summary"]["baseline"]
        batched = data["summary"]["batched"]
        paired_deltas = []
        for pair in range(1, PAIRS + 1):
            baseline_run = next(
                run for run in data["runs"] if run["pair"] == pair and run["variant"] == "baseline"
            )
            batched_run = next(
                run for run in data["runs"] if run["pair"] == pair and run["variant"] == "batched"
            )
            paired_deltas.append(
                {
                    "pair": pair,
                    **{
                        f"{key}_delta": batched_run[key] - baseline_run[key]
                        for key in (
                            "request_elapsed_ms",
                            "request_ticks_per_second",
                            "cpu_simulation_submit_ms",
                            "cpu_simulation_encode_ms",
                            "cpu_queue_submit_ms",
                            "cpu_upload_ms",
                        )
                    },
                }
            )
        report["paired_median_deltas_batched_minus_baseline"][scene_name] = {
            "pairs": paired_deltas,
            "median_cpu_queue_submit_ms_delta": batched["cpu_queue_submit_ms"]["median"]
            - baseline["cpu_queue_submit_ms"]["median"],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "scenes": list(report["scenes"])}))


if __name__ == "__main__":
    main()
