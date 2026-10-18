#!/usr/bin/env python3
"""Compare fixed-tick images across pre-batch and batched simulation builds."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCENES = (
    "assets/scenes/clearing.json",
    "assets/scenes/profiling-heavy.json",
    "assets/scenes/two-emitter-review.json",
)


def run_capture(binary, cwd, scene, parts, capture_path):
    stderr_log = tempfile.TemporaryFile(mode="w+t")
    process = subprocess.Popen(
        [str(binary), "serve", "--scene", str(scene)],
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
        if response.get("id") != sequence or "result" not in response:
            raise RuntimeError(f"unexpected {method} response: {response}")
        return response["result"]

    error = None
    try:
        for count in parts:
            request("step", ticks=count)
        metrics = request("get_metrics")["frame"]
        result = request("capture_frame", path=str(capture_path), scale=1)
        if result["tick"] != sum(parts):
            raise RuntimeError(f"expected tick {sum(parts)}, got {result['tick']}")
    except Exception as exception:  # preserve stderr when a renderer rejects a dispatch
        error = exception
    finally:
        process.stdin.close()
        try:
            return_code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise RuntimeError(f"{binary} did not exit after stdin closed")
    stderr_log.seek(0)
    stderr = stderr_log.read()
    stderr_log.close()
    if error:
        raise RuntimeError(f"{error}\n{stderr}") from error
    if return_code:
        raise RuntimeError(f"{binary} exited {return_code}\n{stderr}")
    data = capture_path.read_bytes()
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "fixed_steps_reported": metrics["cpu_steps_this_frame"],
        "simulation_submissions_reported": metrics.get(
            "cpu_simulation_submissions_this_frame"
        ),
        "queue_submit_cpu_ms": metrics["cpu_queue_submit_ms"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-binary", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--candidate-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--captures", type=Path, required=True)
    args = parser.parse_args()
    baseline_binary = args.baseline_binary.resolve()
    baseline_root = args.baseline_root.resolve()
    candidate_binary = args.candidate_binary.resolve()
    candidate_root = args.candidate_root.resolve()
    captures = args.captures.resolve()
    captures.mkdir(parents=True, exist_ok=True)
    report = {
        "device": "Apple M1 Max",
        "backend": "Metal",
        "resolution": [640, 360],
        "seed": 42,
        "method": "Headless fixed-tick PNG hash comparison using real GPU renderer",
        "timing_status": "single captures only; timing values are not performance evidence",
        "baseline": str(baseline_binary),
        "candidate": str(candidate_binary),
        "baseline_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=baseline_root, text=True
        ).strip(),
        "candidate_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=candidate_root, text=True
        ).strip(),
        "scenes": {},
        "all_images_identical": True,
    }
    partitions = {
        "one_batch_request": [120],
        "twenty_six_tick_requests": [6] * 20,
        "one_tick_requests": [1] * 120,
        "mixed_request_boundaries": [7] + [6] * 18 + [5],
    }
    with tempfile.TemporaryDirectory(prefix="pixel-simulation-batch-") as temp:
        temp = Path(temp)
        for scene_index, scene_relative in enumerate(SCENES):
            scene = (ROOT / scene_relative).resolve()
            scene_name = Path(scene_relative).stem
            baseline_capture = temp / f"{scene_name}-baseline.png"
            baseline = run_capture(
                baseline_binary, baseline_root, scene, [120], baseline_capture
            )
            stable_baseline = captures / f"{scene_name}-baseline.png"
            stable_baseline.write_bytes(baseline_capture.read_bytes())
            results = {
                "scene_sha256": hashlib.sha256(scene.read_bytes()).hexdigest(),
                "baseline": baseline,
                "batched_partitions": {},
            }
            for partition_name, parts in partitions.items():
                candidate_capture = temp / f"{scene_name}-{partition_name}.png"
                candidate = run_capture(
                    candidate_binary,
                    candidate_root,
                    scene,
                    parts,
                    candidate_capture,
                )
                identical = candidate["sha256"] == baseline["sha256"]
                results["batched_partitions"][partition_name] = {
                    **candidate,
                    "step_requests": len(parts),
                    "identical_to_baseline": identical,
                }
                report["all_images_identical"] &= identical
                # Preserve the canonical single-request candidate for direct review.
                if partition_name == "one_batch_request":
                    (captures / f"{scene_name}-batched.png").write_bytes(
                        candidate_capture.read_bytes()
                    )
            report["scenes"][scene_name] = results
    if not report["all_images_identical"]:
        raise SystemExit("batch parity failed; see the report for differing hashes")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"all_images_identical": True, "scenes": list(report["scenes"])}))


if __name__ == "__main__":
    main()
