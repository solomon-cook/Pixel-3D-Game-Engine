#!/usr/bin/env python3
"""Build and capture a repeatable projected-fire-detail threshold orbit study."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/clearing.json"
FOV_DEGREES = 52.0
TARGET = (0.0, 0.55, 0.0)
CAMERA_Y = 2.8
# Forward/back crossings exercise both 40/48 px and 20/24 px hysteresis.
CHECKPOINTS = [
    (0.0, 120.0, "close-smoke"),
    (2.0, 40.3, "tier0-before-40"),
    (3.0, 39.7, "tier1-after-40"),
    (4.0, 47.7, "tier1-before-48"),
    (5.0, 48.3, "tier0-after-48"),
    (7.0, 28.0, "medium"),
    (9.0, 20.3, "tier1-before-20"),
    (10.0, 19.7, "tier2-after-20"),
    (11.0, 23.7, "tier2-before-24"),
    (12.0, 24.3, "tier1-after-24"),
    (14.0, 17.0, "tier1-before-48-return"),
    (16.0, 49.0, "tier0-return"),
    (18.0, 19.0, "tier2-return"),
    (20.0, 120.0, "close-seam"),
]


def camera_at(time_seconds: float, height_px: float) -> dict:
    scene = json.loads(SOURCE.read_text())
    emitter = next(e for e in scene["emitters"] if e["id"] == "campfire")
    profile = next(p for p in scene["effects"] if p["id"] == emitter["effect_profile"])
    world_height = max(profile["fire"]["height"], profile["fire"]["width"] * 2.0)
    distance = world_height * 360.0 / (2.0 * math.tan(math.radians(FOV_DEGREES / 2.0)) * height_px)
    horizontal = math.sqrt(max(0.1, distance * distance - (CAMERA_Y - TARGET[1]) ** 2))
    angle = 2.0 * math.pi * time_seconds / 20.0
    return {
        "time": time_seconds,
        "position": [horizontal * math.cos(angle), CAMERA_Y, horizontal * math.sin(angle)],
        "target": list(TARGET),
    }


def write_scenes(directory: Path) -> tuple[Path, Path]:
    source = json.loads(SOURCE.read_text())
    route = {
        "id": "projected-detail-orbit",
        "duration_seconds": 20.0,
        "keyframes": [camera_at(t, h) for t, h, _ in CHECKPOINTS],
    }
    paths = []
    for name, enabled in (("baseline", False), ("candidate", True)):
        scene = copy.deepcopy(source)
        scene["render"]["experiments"]["projected_detail_lod"] = enabled
        scene["routes"] = [r for r in scene["routes"] if r["id"] != route["id"]]
        scene["routes"].append(route)
        path = directory / name / "scene.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(scene, indent=2) + "\n")
        paths.append(path)
    return paths[0], paths[1]


def session_capture(binary: Path, scene_path: Path, output: Path) -> list[dict]:
    scene = json.loads(scene_path.read_text())
    camera = next(c for c in scene["cameras"] if c["id"] == "hero")
    process = subprocess.Popen(
        [str(binary), "serve", "--scene", str(scene_path), "--camera", "hero"],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    sequence = 0

    def request(method: str, **params):
        nonlocal sequence
        sequence += 1
        assert process.stdin and process.stdout
        process.stdin.write(json.dumps({"id": sequence, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        if response.get("id") != sequence or "error" in response:
            raise RuntimeError(response)
        return response["result"]

    records = []
    try:
        request("step", ticks=300)
        for index, (time_seconds, height_px, label) in enumerate(CHECKPOINTS):
            if index:
                request("step", ticks=round((time_seconds - CHECKPOINTS[index - 1][0]) * 60))
            keyframe = camera_at(time_seconds, height_px)
            camera_obj = {**camera, "position": keyframe["position"], "target": keyframe["target"]}
            request("set_camera", camera=camera_obj)
            state = request("inspect_effects")
            capture = request("capture_frame", path=str((output / f"{label}.png").resolve()), scale=1)
            records.append({"time_seconds": time_seconds, "label": label, "state": state, "capture": capture})
    finally:
        if process.stdin:
            process.stdin.close()
        process.wait(timeout=60)
    if process.returncode:
        raise RuntimeError(f"serve exited {process.returncode}")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o04/slow-orbit")
    parser.add_argument("--benchmark", action="store_true", help="run three alternating 120-second profile pairs")
    args = parser.parse_args()
    binary = args.binary.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not binary.is_file():
        parser.error(f"engine-lab binary does not exist: {binary}")

    baseline_scene, candidate_scene = write_scenes(output)
    captures = {}
    for name, path in (("baseline", baseline_scene), ("candidate", candidate_scene)):
        folder = output / "captures" / name
        folder.mkdir(parents=True, exist_ok=True)
        captures[name] = session_capture(binary, path, folder)

    state_fields = ("counts", "bounds_min", "bounds_max", "lighting", "particle_lights")
    parity = []
    for index, (base, candidate) in enumerate(zip(captures["baseline"], captures["candidate"])):
        base_state, candidate_state = base["state"], candidate["state"]
        parity.append({
            "label": base["label"],
            "same_fire_state": all(base_state.get(k) == candidate_state.get(k) for k in state_fields),
            "baseline_projected_detail": base_state.get("projected_detail"),
            "candidate_projected_detail": candidate_state.get("projected_detail"),
            "capture_sha256": {
                name: hashlib.sha256(Path(captures[name][index]["capture"]["image"]).read_bytes()).hexdigest()
                for name in ("baseline", "candidate")
            },
        })

    report = {
        "workstream": "O04 projected detail slow orbit",
        "seed": 42,
        "simulation_start_tick": 300,
        "camera_route": "20-second circular orbit, repeated six times in the 120-second benchmark",
        "resolution": [640, 360],
        "profile": "clearing scene with branching tongues and ember lights",
        "threshold_checkpoints": parity,
        "state_comparison_fields": list(state_fields),
        "state_parity_all_checkpoints": all(item["same_fire_state"] for item in parity),
        "heat_note": "inspect_effects does not expose the heat field directly; projected detail is applied after deterministic FireFrame simulation, while counts, bounds, lighting and particle lights are compared here",
        "scenes": {"baseline": str(baseline_scene), "candidate": str(candidate_scene)},
        "benchmark": None,
        "limitations": ["captures are discrete checkpoints, not a continuous movie", "native-window and Windows/DX12 acceptance are not established"],
    }
    if not report["state_parity_all_checkpoints"]:
        raise RuntimeError("fire state diverged between projected-detail variants")
    if args.benchmark:
        benchmark_dir = output / "benchmark"
        subprocess.run([
            "python3", str(ROOT / "scripts/profile_compare.py"),
            "--baseline", str(baseline_scene), "--candidate", str(candidate_scene),
            "--route", "projected-detail-orbit", "--duration", "120", "--warmup", "10",
            "--pairs", "3", "--seed", "42", "--camera", "hero", "--resolution", "640x360",
            "--output", str(benchmark_dir), "--binary", str(binary),
        ], cwd=ROOT, check=True)
        summary_path = benchmark_dir / "comparison.json"
        if summary_path.exists():
            report["benchmark"] = str(summary_path)
    report_path = output / "study.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"study": str(report_path), "state_parity": report["state_parity_all_checkpoints"], "benchmark": args.benchmark}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
