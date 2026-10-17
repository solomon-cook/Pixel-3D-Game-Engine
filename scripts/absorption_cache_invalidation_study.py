#!/usr/bin/env python3
"""Check cache refresh against paused edits and deterministic fire motion."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from absorption_cache_study import image_error, sha256

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/clearing.json"
CAMERA = "smoke-close"
SEED = 42


class Session:
    def __init__(self, binary: Path, scene: Path, output: Path):
        self.process = subprocess.Popen(
            [str(binary), "serve", "--scene", str(scene), "--camera", CAMERA],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.request_id = 0
        self.output = output
        output.mkdir(parents=True, exist_ok=True)

    def request(self, method: str, **params):
        self.request_id += 1
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps({"id": self.request_id, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        if response.get("id") != self.request_id or "error" in response:
            raise RuntimeError(response)
        return response["result"]

    def capture(self, label: str) -> dict:
        state = self.request("inspect_effects")
        metrics = self.request("get_metrics")
        image = self.request("capture_frame", path=str((self.output / f"{label}.png").resolve()), scale=1)["image"]
        return {
            "fire_state": state,
            "image": image,
            "image_sha256": sha256(Path(image)),
            "cache_bytes": metrics["capabilities"]["resource_inventory"]["smoke_absorption_cache_bytes"],
            "cpu_cache_build_ms": metrics["frame"]["cpu_absorption_cache_ms"],
        }

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        self.process.wait(timeout=60)
        if self.process.returncode:
            raise RuntimeError(f"serve exited {self.process.returncode}")


def run_variant(binary: Path, output: Path, enabled: bool, resolution: int) -> dict:
    scene = json.loads(SOURCE.read_text())
    scene["render"]["resolution"] = [640, 360]
    scene["render"]["absorption_cache_resolution"] = resolution
    scene["render"].setdefault("experiments", {})["smoke_absorption_cache"] = enabled
    scene_path = output / "scenes" / f"{'cache' + str(resolution) if enabled else 'direct'}.json"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text(json.dumps(scene, indent=2) + "\n")

    session = Session(binary, scene_path, output / ("cache" + str(resolution) if enabled else "direct"))
    result = {"scene_sha256": sha256(scene_path), "checkpoints": {}}
    try:
        session.request("step", ticks=300)
        result["checkpoints"]["tick_300"] = session.capture("tick_300")

        actions = [
            ("paused_density_change", [("set_parameter", {"path": "emitters.campfire.smoke_density", "value": 3.6})], 1),
            ("rapid_density_edits", [
                ("set_parameter", {"path": "emitters.campfire.smoke_density", "value": 1.9}),
                ("set_parameter", {"path": "emitters.campfire.smoke_density", "value": 3.2}),
            ], 1),
            ("primary_light_motion", [("set_parameter", {"path": "lights.fire-light.position", "value": [0.32, 0.58, 0.24]})], 0),
            ("primary_light_range", [("set_parameter", {"path": "lights.fire-light.range", "value": 13.5})], 0),
            ("live_flicker", [("set_parameter", {"path": "lights.fire-light.flicker", "value": 0.9})], 0),
            ("pause_confirmation", [("pause", {"paused": True})], 0),
        ]
        for label, calls, step_ticks in actions:
            for method, params in calls:
                session.request(method, **params)
            if step_ticks:
                session.request("step", ticks=step_ticks)
            result["checkpoints"][label] = session.capture(label)

        motion = []
        for index, ticks in enumerate((15, 30, 45, 60), 1):
            session.request("step", ticks=ticks)
            label = f"ember_motion_{index}"
            checkpoint = session.capture(label)
            motion.append({"tick_offset": sum((15, 30, 45, 60)[:index]), "checkpoint": checkpoint})
        result["moving_particle_light_checkpoints"] = motion

        session.request("reload_shaders")
        result["checkpoints"]["shader_reload"] = session.capture("shader_reload")
        session.request("reset", seed=SEED)
        session.request("step", ticks=300)
        result["checkpoints"]["reset_seed_42_tick_300"] = session.capture("reset_seed_42_tick_300")
    finally:
        session.close()
    return result


def compare_state(left: dict, right: dict) -> dict:
    left_points = {key: value for key, value in left["checkpoints"].items()}
    right_points = {key: value for key, value in right["checkpoints"].items()}
    names = list(left_points) + [f"ember_motion_{i}" for i in range(1, 5)]
    left_motion = {f"ember_motion_{i}": item["checkpoint"] for i, item in enumerate(left["moving_particle_light_checkpoints"], 1)}
    right_motion = {f"ember_motion_{i}": item["checkpoint"] for i, item in enumerate(right["moving_particle_light_checkpoints"], 1)}
    out = {}
    for name in names:
        a = left_points.get(name, left_motion.get(name))
        b = right_points.get(name, right_motion.get(name))
        out[name] = {
            "fire_state_identical": a["fire_state"] == b["fire_state"],
            "direct_image_sha256": a["image_sha256"],
            "cached_image_sha256": b["image_sha256"],
            "cached_absolute_rgb_error_vs_direct": image_error(Path(a["image"]), Path(b["image"])),
            "direct_cache_bytes": a["cache_bytes"],
            "candidate_cache_bytes": b["cache_bytes"],
            "candidate_cpu_cache_build_ms": b["cpu_cache_build_ms"],
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o05/invalidation")
    parser.add_argument("--resolution", type=int, choices=(8, 16), default=8)
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    direct = run_variant(binary, output, False, args.resolution)
    cached = run_variant(binary, output, True, args.resolution)
    report = {
        "workstream": "O05 absorption-cache edit, reset and motion freshness study",
        "date": "2026-10-18",
        "host": {"device": "Apple M1 Max", "backend": "Metal"},
        "camera": CAMERA,
        "seed": SEED,
        "resolution": [640, 360],
        "cache_resolution": [args.resolution] * 3,
        "method": "Direct and cached serve sessions use the same scene, seed, fixed ticks and ordered paused edits. Density edits are followed by one explicit fixed tick while still paused so the smoke volume is recomputed; captures are compared at each matching checkpoint.",
        "direct_scene_sha256": direct["scene_sha256"],
        "cached_scene_sha256": cached["scene_sha256"],
        "checkpoints": compare_state(direct, cached),
        "limitations": ["serve is headless; native-window and non-Metal behavior are not covered", "the study checks discrete motion checkpoints, not continuous temporal pixel error", "pause remains active for edits and fixed-tick stepping; wall-clock resume timing is not compared"],
    }
    path = output / "report.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(path), "checkpoint_count": len(report["checkpoints"]), "fire_state_parity": all(v["fire_state_identical"] for v in report["checkpoints"].values())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
