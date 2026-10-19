#!/usr/bin/env python3
"""Compare direct smoke-light sampling with 8^3 and 16^3 caches by view scale."""

from __future__ import annotations

import argparse
import copy
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/clearing.json"
ROUTE_ID = "absorption-cache-orbit"
CAMERA_ID = "absorption-study"
TARGET = [0.0, 2.1, 0.0]
SCALES = {"small": 2.5, "medium": 1.0, "screen-filling": 0.5}
ORBIT_START_RADIANS = math.pi / 4


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_source_state() -> dict:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty_paths = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    return {"revision": revision, "dirty_paths": dirty_paths}


def require_matching_binary(run_path: Path, expected_sha256: str) -> None:
    run = json.loads(run_path.read_text())
    actual_sha256 = run.get("provenance", {}).get("binary_sha256")
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"{run_path} has binary SHA-256 {actual_sha256!r}; expected current binary "
            f"{expected_sha256}. Rerun with --benchmark before summarizing sustained performance."
        )


def orbit_keyframes(offset: list[float]) -> list[dict]:
    frames = []
    for step in range(5):
        angle = ORBIT_START_RADIANS + math.tau * step / 4
        x = offset[0] * math.cos(angle) + offset[2] * math.sin(angle)
        z = -offset[0] * math.sin(angle) + offset[2] * math.cos(angle)
        frames.append({"time": step * 5.0, "position": [TARGET[0] + x, TARGET[1] + offset[1], TARGET[2] + z], "target": TARGET})
    return frames


def make_scenes(output: Path, source: dict) -> dict[str, dict[str, Path]]:
    original_camera = next(camera for camera in source["cameras"] if camera["id"] == "smoke-close")
    base_offset = [original_camera["position"][i] - original_camera["target"][i] for i in range(3)]
    result: dict[str, dict[str, Path]] = {}
    for size, scale in SCALES.items():
        result[size] = {}
        for mode, enabled, resolution in (("direct", False, 8), ("cache8", True, 8), ("cache16", True, 16)):
            scene = copy.deepcopy(source)
            scene["render"]["resolution"] = [640, 360]
            scene["render"]["absorption_cache_resolution"] = resolution
            scene["render"]["experiments"]["smoke_absorption_cache"] = enabled
            offset = [value * scale for value in base_offset]
            camera = {
                "id": CAMERA_ID,
                "position": [
                    TARGET[0] + offset[0] * math.cos(ORBIT_START_RADIANS) + offset[2] * math.sin(ORBIT_START_RADIANS),
                    TARGET[1] + offset[1],
                    TARGET[2] - offset[0] * math.sin(ORBIT_START_RADIANS) + offset[2] * math.cos(ORBIT_START_RADIANS),
                ],
                "target": list(TARGET),
                "projection": {"kind": "perspective", "fov_degrees": 48.0},
            }
            scene["cameras"] = [c for c in scene["cameras"] if c["id"] != CAMERA_ID]
            scene["cameras"].append(camera)
            scene["routes"] = [r for r in scene["routes"] if r["id"] != ROUTE_ID]
            scene["routes"].append({"id": ROUTE_ID, "duration_seconds": 20.0, "keyframes": orbit_keyframes(offset)})
            path = output / "scenes" / size / f"{mode}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(scene, indent=2) + "\n")
            result[size][mode] = path
    return result


def capture_variant(binary: Path, scene_path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [str(binary), "serve", "--scene", str(scene_path), "--camera", CAMERA_ID],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    request_id = 0

    def request(method: str, **params):
        nonlocal request_id
        request_id += 1
        assert process.stdin and process.stdout
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        if response.get("id") != request_id or "error" in response:
            raise RuntimeError(response)
        return response["result"]

    try:
        request("step", ticks=300)
        camera = next(c for c in json.loads(scene_path.read_text())["cameras"] if c["id"] == CAMERA_ID)
        request("set_camera", camera=camera)
        state = request("inspect_effects")
        metrics = request("get_metrics")
        capture = request("capture_frame", path=str((out_dir / "tick-300.png").resolve()), scale=1)
    finally:
        if process.stdin:
            process.stdin.close()
        process.wait(timeout=60)
    if process.returncode:
        raise RuntimeError(f"serve exited {process.returncode}")
    return {
        "fire_state": state,
        "cache_bytes": metrics["capabilities"]["resource_inventory"]["smoke_absorption_cache_bytes"],
        "cpu_cache_encode_ms": metrics["frame"]["cpu_absorption_cache_ms"],
        "capabilities": metrics["capabilities"],
        "capture": capture["image"],
        "capture_sha256": sha256(Path(capture["image"])),
    }


def image_error(reference: Path, candidate: Path) -> dict | None:
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    a = Image.open(reference).convert("RGB")
    b = Image.open(candidate).convert("RGB")
    if a.size != b.size:
        raise ValueError(f"capture size mismatch: {a.size} vs {b.size}")
    difference = ImageChops.difference(a, b)
    pixels = list(difference.getdata())
    count = sum(any(channel for channel in pixel) for pixel in pixels)
    means = [sum(pixel[channel] for pixel in pixels) / len(pixels) for channel in range(3)]
    maxima = [max(pixel[channel] for pixel in pixels) for channel in range(3)]
    return {"changed_pixel_count": count, "pixel_count": len(pixels), "mean_absolute_rgb_error_0_255": means, "maximum_absolute_rgb_error_0_255": maxima}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o05/size-study")
    parser.add_argument("--benchmark", action="store_true", help="run three alternating 120-second pairs per view/cache mode")
    parser.add_argument("--summarize-existing", action="store_true", help="rebuild the report from existing captures and benchmark files")
    args = parser.parse_args()
    binary = args.binary.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    source = json.loads(SOURCE.read_text())
    source_state = git_source_state()
    scenes = make_scenes(output, source)
    report = {
        "workstream": "O05 smoke absorption cache size study",
        "date": date.today().isoformat(),
        "provenance": {
            **source_state,
            "binary_path": str(binary),
            "binary_sha256": sha256(binary),
            "study_script_sha256": sha256(Path(__file__).resolve()),
            "profile_compare_script_sha256": sha256(ROOT / "scripts/profile_compare.py"),
            "capture_motion_script_sha256": sha256(ROOT / "scripts/capture_motion.py"),
        },
        "host": None,
        "seed": 42,
        "simulation_start_tick": 300,
        "resolution": [640, 360],
        "route": {"id": ROUTE_ID, "duration_seconds": 20, "benchmark_repetitions": 6},
        "method": "Matched direct/8^3/16^3 variants at each fixed camera scale; capture error is measured at identical tick, camera and scene state. The experiment changes only cache setting/resolution.",
        "sizes": {},
        "benchmark": {"warmup_seconds": 10, "duration_seconds_per_run": 120, "pairs": 3, "mode": "serial", "comparisons": {}},
        "limitations": ["The absorption lookup cost is included in atmosphere/fire GPU timing and is not separately timestamped.", "Native-window and non-Metal acceptance are not established."],
    }
    for size, variants in scenes.items():
        captures = {}
        for mode, scene_path in variants.items():
            captures[mode] = capture_variant(binary, scene_path, output / "captures" / size / mode)
        baseline_state = captures["direct"]["fire_state"]
        if report["host"] is None:
            caps = captures["direct"]["capabilities"]
            report["host"] = {"device": caps.get("name"), "backend": caps.get("backend")}
        parity = {mode: capture["fire_state"] == baseline_state for mode, capture in captures.items()}
        if not all(parity.values()):
            raise RuntimeError(f"fire-state parity failed in {size}: {parity}")
        report["sizes"][size] = {
            "camera": json.loads(variants["direct"].read_text())["cameras"][-1],
            "scene_sha256": {mode: sha256(path) for mode, path in variants.items()},
            "fire_state_parity": parity,
            "captures": {
                mode: {
                    "cache_bytes": capture["cache_bytes"],
                    "cpu_cache_encode_ms": capture["cpu_cache_encode_ms"],
                    "sha256": capture["capture_sha256"],
                    "absolute_rgb_error_vs_direct": None if mode == "direct" else image_error(Path(captures["direct"]["capture"]), Path(capture["capture"])),
                }
                for mode, capture in captures.items()
            },
        }

    if args.benchmark or args.summarize_existing:
        for size, variants in scenes.items():
            for mode in ("cache8", "cache16"):
                comparison_dir = output / "benchmarks" / size / mode
                if args.benchmark:
                    subprocess.run([
                        "python3", str(ROOT / "scripts/profile_compare.py"),
                        "--baseline", str(variants["direct"]), "--candidate", str(variants[mode]),
                        "--route", ROUTE_ID, "--mode", "serial", "--duration", "120", "--warmup", "10",
                        "--pairs", "3", "--seed", "42", "--camera", CAMERA_ID,
                        "--resolution", "640x360", "--output", str(comparison_dir), "--binary", str(binary),
                    ], cwd=ROOT, check=True)
                comparison_path = comparison_dir / "comparison.json"
                comparison = json.loads(comparison_path.read_text())
                expected_binary_sha256 = report["provenance"]["binary_sha256"]
                for pair in range(1, 4):
                    for variant in ("baseline", "candidate"):
                        run_path = comparison_dir / f"pair-{pair:02d}-{variant}.json"
                        require_matching_binary(run_path, expected_binary_sha256)
                baseline_run = json.loads((comparison_dir / "pair-01-baseline.engine.json").read_text())
                candidate_run = json.loads((comparison_dir / "pair-01-candidate.engine.json").read_text())
                candidate_runs = [json.loads((comparison_dir / f"pair-{pair:02d}-candidate.engine.json").read_text()) for pair in range(1, 4)]
                cache_build = {}
                for field in ("cpu_build_ms", "gpu_build"):
                    values = [run["smoke_absorption_cache"][field]["median_ms"] for run in candidate_runs]
                    ordered = sorted(values)
                    cache_build[field] = {"per_run_median_ms": values, "median_of_run_medians_ms": ordered[len(ordered) // 2]}
                report["benchmark"]["comparisons"][f"{size}_{mode}"] = {
                    "comparison_file": str(comparison_path.relative_to(output)),
                    "comparison_sha256": sha256(comparison_path),
                    "paired_deltas": comparison["comparison"],
                    "direct": {"gpu_stages": baseline_run.get("gpu_stages"), "gpu_render": baseline_run.get("gpu_render"), "frame_work": baseline_run.get("frame_work"), "cache_bytes": baseline_run["capabilities"]["resource_inventory"]["smoke_absorption_cache_bytes"]},
                    "candidate": {"gpu_stages": candidate_run.get("gpu_stages"), "gpu_render": candidate_run.get("gpu_render"), "frame_work": candidate_run.get("frame_work"), "cache_bytes": candidate_run["capabilities"]["resource_inventory"]["smoke_absorption_cache_bytes"], "cache_build": cache_build},
                }

    report_path = output / "study.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"study": str(report_path), "sizes": list(scenes), "benchmark": args.benchmark, "summarized_existing": args.summarize_existing}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
