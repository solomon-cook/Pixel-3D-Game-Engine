#!/usr/bin/env python3
"""Compare direct and once-per-frame projected fire bounds on O03 routes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from tile_overflow_camera_route_study import CAMERA, ROUTE

ROOT = Path(__file__).resolve().parents[1]
WORKLOADS = (
    ("clearing", ROOT / "assets/scenes/clearing.json", "hero", "clearing-orbit"),
    ("heavy-plume", ROOT / "assets/scenes/profiling-heavy.json", "hero", "clearing-orbit"),
    ("material-atelier", ROOT / "assets/scenes/materials.json", "hero", "material-orbit"),
    ("camera-inside-overflow", ROOT / "assets/scenes/two-emitter-overflow-stress.json", CAMERA["id"], ROUTE),
)
NEAR_PLANE_CAMERA = {
    "id": "near-plane-intersection",
    "position": [-0.55, 0.62, 0.32],
    "projection": {"fov_degrees": 48.0, "kind": "perspective"},
    "target": [-0.55, 0.62, -0.25],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(binary: Path, scene: Path, camera: str, output: Path, precompute: bool) -> dict:
    name = "precomputed" if precompute else "direct"
    output.mkdir(parents=True, exist_ok=True)
    image = output / f"{name}.png"
    command = [
        str(binary), "capture", "--scene", str(scene), "--camera", camera,
        "--seed", "42", "--tick", "300", "--resolution", "640x360",
        "--scale", "1", "--output", str(image),
    ]
    if precompute:
        command.append("--precompute-fire-bounds")
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    metadata = json.loads(image.with_suffix(".json").read_text())
    metrics = metadata["metrics"]
    return {
        "image": str(image),
        "sha256": sha256(image),
        "tick": metadata["tick"],
        "fire_bounds_precompute": metadata["capabilities"]["tile_lists"]["fire_bounds_precompute"],
        "tile_candidates": metrics["tile_candidates"],
        "tile_overflow_tiles": metrics["tile_overflow_tiles"],
        "tile_max_occupancy": metrics["tile_max_occupancy"],
        "fire_projected_bounds_bytes": metadata["capabilities"]["resource_inventory"]["fire_projected_bounds_bytes"],
    }


def session_api_toggle_check(binary: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen([
        str(binary), "serve", "--scene", str(ROOT / "assets/scenes/clearing.json"),
        "--camera", "hero", "--seed", "42",
    ], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def request(request_id: int, method: str, params: dict) -> dict:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        while True:
            line = process.stdout.readline()
            if not line:
                raise RuntimeError("engine-lab serve ended before returning the Session response")
            response = json.loads(line)
            if response.get("id") == request_id:
                if "error" in response:
                    raise RuntimeError(response)
                return response

    try:
        enabled = request(1, "set_tile_lists", {"enabled": True, "precompute_fire_bounds": True})
        request(2, "capture_frame", {"path": str(output / "precomputed.png"), "scale": 1})
        disabled = request(3, "set_tile_lists", {"enabled": True, "precompute_fire_bounds": False})
        request(4, "capture_frame", {"path": str(output / "direct.png"), "scale": 1})
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
    direct_meta = json.loads((output / "direct.json").read_text())
    precomputed_meta = json.loads((output / "precomputed.json").read_text())
    direct_hash = sha256(output / "direct.png")
    precomputed_hash = sha256(output / "precomputed.png")
    return {
        "toggle_on_response": enabled,
        "toggle_off_response": disabled,
        "direct_flag": direct_meta["capabilities"]["tile_lists"]["fire_bounds_precompute"],
        "precomputed_flag": precomputed_meta["capabilities"]["tile_lists"]["fire_bounds_precompute"],
        "same_tick": direct_meta["tick"] == precomputed_meta["tick"],
        "pixel_identical": direct_hash == precomputed_hash,
        "tile_candidates_identical": direct_meta["metrics"]["tile_candidates"] == precomputed_meta["metrics"]["tile_candidates"],
        "tile_overflow_identical": direct_meta["metrics"]["tile_overflow_tiles"] == precomputed_meta["metrics"]["tile_overflow_tiles"],
        "tile_max_occupancy_identical": direct_meta["metrics"]["tile_max_occupancy"] == precomputed_meta["metrics"]["tile_max_occupancy"],
        "direct_sha256": direct_hash,
        "precomputed_sha256": precomputed_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o03/fire-projected-bounds")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o03-fire-projected-bounds.json")
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--reuse-paired-runs", action="store_true", help="reuse existing comparison reports when they match this exact protocol and setting matrix")
    args = parser.parse_args()
    binary, output, report_path = (path.resolve() for path in (args.binary, args.output, args.report))
    if not binary.is_file():
        parser.error(f"engine-lab binary does not exist: {binary}")
    output.mkdir(parents=True, exist_ok=True)

    workloads = []
    for workload_id, source_scene, camera, route in WORKLOADS:
        scene = json.loads(source_scene.read_text())
        if workload_id == "camera-inside-overflow":
            scene["cameras"].extend((CAMERA, NEAR_PLANE_CAMERA))
            scene["routes"].append({
                "id": ROUTE,
                "duration_seconds": args.duration,
                "keyframes": [
                    {"time": 0.0, "position": CAMERA["position"], "target": CAMERA["target"]},
                    {"time": args.duration, "position": CAMERA["position"], "target": CAMERA["target"]},
                ],
            })
        workload_dir = output / workload_id
        workload_dir.mkdir(parents=True, exist_ok=True)
        scene_path = workload_dir / "scene.json"
        scene_path.write_text(json.dumps(scene, indent=2) + "\n")
        subprocess.run([str(binary), "validate", str(scene_path)], cwd=ROOT, check=True, capture_output=True, text=True)

        captures_dir = workload_dir / "fixed-tick-parity"
        captures_dir.mkdir(exist_ok=True)
        fixed_tick_views = {}
        for view_id in (item["id"] for item in scene["cameras"]):
            direct = capture(binary, scene_path, view_id, captures_dir / view_id, False)
            precomputed = capture(binary, scene_path, view_id, captures_dir / view_id, True)
            fixed_tick_views[view_id] = {
                "pixel_identical": direct["sha256"] == precomputed["sha256"],
                "same_tick": direct["tick"] == precomputed["tick"],
                "same_tile_candidates": direct["tile_candidates"] == precomputed["tile_candidates"],
                "same_overflow_tiles": direct["tile_overflow_tiles"] == precomputed["tile_overflow_tiles"],
                "same_max_occupancy": direct["tile_max_occupancy"] == precomputed["tile_max_occupancy"],
                "direct": direct,
                "precomputed": precomputed,
            }
        parity = fixed_tick_views[camera]
        paired_dir = workload_dir / "paired-runs"
        comparison_path = paired_dir / "comparison.json"
        if args.reuse_paired_runs and comparison_path.is_file():
            paired = json.loads(comparison_path.read_text())
            config = paired["configuration"]
            expected = {
                "route": route,
                "route_seconds": args.duration,
                "warmup_seconds": args.warmup,
                "pairs": args.pairs,
                "seed": 42,
                "camera": camera,
                "resolution_override": "640x360",
                "baseline_precompute_fire_bounds": False,
                "candidate_precompute_fire_bounds": True,
            }
            if any(config.get(key) != value for key, value in expected.items()):
                raise RuntimeError(f"existing paired report does not match requested protocol: {comparison_path}")
        else:
            subprocess.run([
                sys.executable, str(ROOT / "scripts/profile_compare.py"),
                "--baseline", str(scene_path), "--candidate", str(scene_path),
                "--route", route, "--duration", str(args.duration),
                "--warmup", str(args.warmup), "--pairs", str(args.pairs),
                "--seed", "42", "--camera", camera, "--resolution", "640x360",
                "--candidate-precompute-fire-bounds", "--output", str(paired_dir),
                "--binary", str(binary),
            ], cwd=ROOT, check=True)
            paired = json.loads(comparison_path.read_text())
        first_run_id = next(iter(paired["runs"]["baseline"]))
        first_run = json.loads((paired_dir / f"{first_run_id}.engine.json").read_text())
        run_validity = []
        for variant, run_ids in paired["runs"].items():
            for run_id in run_ids:
                run = json.loads((paired_dir / f"{run_id}.engine.json").read_text())
                expected_precompute = variant == "candidate"
                overflow = run["tile_lists"]["overflow_by_category"]["fire_primitives"]
                coverage = run["timing_coverage"]
                run_validity.append({
                    "run": run_id,
                    "variant": variant,
                    "precompute_setting_matches": run["tile_lists"]["fire_bounds_precompute"] is expected_precompute,
                    "frames_complete": coverage["rendered_frames"] == int(round(args.duration * 60)),
                    "gpu_timestamps_complete": run["gpu_render"]["samples"] == coverage["rendered_frames"],
                    "fire_fallback_rate": overflow["fallback_rate"],
                    "expected_overflow_behavior": workload_id != "camera-inside-overflow" or overflow["fallback_rate"] == 1.0,
                    "skipped_samples": coverage["skipped_samples"],
                    "late_samples": coverage["late_samples"],
                })
        workloads.append({
            "id": workload_id,
            "scene": str(source_scene.relative_to(ROOT)),
            "scene_sha256": sha256(source_scene),
            "generated_scene": str(scene_path),
            "generated_scene_sha256": sha256(scene_path),
            "camera": camera,
            "route": route,
            "paired_reports_dir": str(paired_dir),
            "adapter": first_run["capabilities"]["name"],
            "backend": first_run["capabilities"]["backend"],
            "fixed_tick_parity": parity,
            "fixed_tick_views": fixed_tick_views,
            "paired_comparison": paired["comparison"],
            "runs": run_validity,
            "pair_protocol_passed": args.pairs >= 3 and len(run_validity) == args.pairs * 2 and all(
                all(run[key] for key in ("precompute_setting_matches", "frames_complete", "gpu_timestamps_complete"))
                and run["skipped_samples"] == 0
                and run["late_samples"] == 0
                and run["expected_overflow_behavior"]
                for run in run_validity
            ),
        })

    api_check = session_api_toggle_check(binary, output / "session-api")
    report = {
        "version": 1,
        "workstream": "O03 once-per-frame projected fire bounds",
        "date": "2026-10-18",
        "binary": str(binary),
        "binary_sha256": sha256(binary),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "profile_compare_sha256": sha256(ROOT / "scripts/profile_compare.py"),
        "duration_seconds": args.duration,
        "warmup_seconds": args.warmup,
        "pairs": args.pairs,
        "resolution": [640, 360],
        "workloads": workloads,
        "session_api_toggle_parity": api_check,
        "acceptance": {
            "fixed_tick_parity_all_workloads": all(
                all(all(view[key] for key in (
                    "pixel_identical", "same_tick", "same_tile_candidates", "same_overflow_tiles", "same_max_occupancy"
                )) for view in workload["fixed_tick_views"].values()) for workload in workloads
            ),
            "paired_protocol_all_workloads": all(workload["pair_protocol_passed"] for workload in workloads),
            "session_api_toggle_parity": all(api_check[key] for key in (
                "same_tick", "pixel_identical", "tile_candidates_identical", "tile_overflow_identical",
                "tile_max_occupancy_identical",
            )) and api_check["direct_flag"] is False and api_check["precomputed_flag"] is True,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "acceptance": report["acceptance"]}))
    return 0 if all(report["acceptance"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
