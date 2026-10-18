#!/usr/bin/env python3
"""Measure absorption-cache builds and reuse across unchanged and dirty frames."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/clearing.json"
CAMERA = "smoke-close"
SEED = 42


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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

    def checkpoint(self, label: str) -> dict:
        image = self.request("capture_frame", path=str((self.output / f"{label}.png").resolve()), scale=1)["image"]
        metrics = self.request("get_metrics")
        frame = metrics["frame"]
        inventory = metrics["capabilities"]["resource_inventory"]
        effects = self.request("inspect_effects")
        return {
            "render_frame": frame["frame"],
            "absorption_cache_builds": frame["absorption_cache_builds"],
            "absorption_cache_skips": frame["absorption_cache_skips"],
            "cpu_absorption_cache_ms": frame["cpu_absorption_cache_ms"],
            "cache_bytes": inventory["smoke_absorption_cache_bytes"],
            "image": image,
            "image_sha256": sha256(Path(image)),
            "fire_counts": effects["counts"],
            "particle_light_count": effects["lighting"][0],
        }

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        self.process.wait(timeout=60)
        if self.process.returncode:
            raise RuntimeError(f"serve exited {self.process.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o05/refresh-policy")
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    scene = json.loads(SOURCE.read_text())
    scene["render"]["resolution"] = [640, 360]
    scene["render"]["absorption_cache_resolution"] = 16
    scene["render"]["experiments"]["smoke_absorption_cache"] = True
    scene_path = output / "scene.json"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text(json.dumps(scene, indent=2) + "\n")
    session = Session(binary, scene_path, output / "captures")
    checkpoints = {}
    try:
        session.request("step", ticks=300)
        checkpoints["first_render_after_300_ticks"] = session.checkpoint("first_render")
        checkpoints["unchanged_paused_render"] = session.checkpoint("unchanged_paused")
        session.request("set_parameter", path="lights.fire-light.position", value=[0.32, 0.58, 0.24])
        checkpoints["light_edit_same_tick"] = session.checkpoint("light_edit")
        session.request("step", ticks=1)
        checkpoints["simulation_step"] = session.checkpoint("simulation_step")
        session.request("reload_shaders")
        checkpoints["shader_reload"] = session.checkpoint("shader_reload")
        session.request("reset", seed=SEED)
        session.request("step", ticks=300)
        checkpoints["reset_and_replay"] = session.checkpoint("reset_replay")
        session.request("set_parameter", path="render.experiments.smoke_absorption_cache", value=False)
        checkpoints["disabled"] = session.checkpoint("disabled")
        session.request("set_parameter", path="render.experiments.smoke_absorption_cache", value=True)
        checkpoints["re_enabled"] = session.checkpoint("re_enabled")
    finally:
        session.close()

    names = list(checkpoints)
    expectations = {
        "unchanged_paused_render_skips_build": checkpoints[names[1]]["absorption_cache_builds"] == checkpoints[names[0]]["absorption_cache_builds"] and checkpoints[names[1]]["absorption_cache_skips"] > checkpoints[names[0]]["absorption_cache_skips"],
        "light_edit_builds": checkpoints["light_edit_same_tick"]["absorption_cache_builds"] == checkpoints["unchanged_paused_render"]["absorption_cache_builds"] + 1,
        "simulation_step_builds": checkpoints["simulation_step"]["absorption_cache_builds"] == checkpoints["light_edit_same_tick"]["absorption_cache_builds"] + 1,
        "shader_reload_builds": checkpoints["shader_reload"]["absorption_cache_builds"] == checkpoints["simulation_step"]["absorption_cache_builds"] + 1,
        "reset_builds": checkpoints["reset_and_replay"]["absorption_cache_builds"] == checkpoints["shader_reload"]["absorption_cache_builds"] + 1,
        "disabled_has_no_cache": checkpoints["disabled"]["cache_bytes"] == 0,
        "re_enable_builds": checkpoints["re_enabled"]["absorption_cache_builds"] == checkpoints["reset_and_replay"]["absorption_cache_builds"] + 1,
        "fire_counts_stable_for_paused_reuse": checkpoints["first_render_after_300_ticks"]["fire_counts"] == checkpoints["unchanged_paused_render"]["fire_counts"],
        "paused_image_is_identical": checkpoints["first_render_after_300_ticks"]["image_sha256"] == checkpoints["unchanged_paused_render"]["image_sha256"],
    }
    report = {
        "workstream": "O05 dirty-input absorption-cache refresh policy",
        "date": "2026-10-18",
        "host": {"device": "Apple M1 Max", "backend": "Metal"},
        "scene": str(SOURCE.relative_to(ROOT)),
        "scene_sha256": sha256(scene_path),
        "camera": CAMERA,
        "seed": SEED,
        "resolution": [640, 360],
        "cache_resolution": [16, 16, 16],
        "method": "One paused serve session steps to tick 300, then captures after an unchanged render, primary-light edit, simulation step, shader reload, reset/replay, disable and re-enable. Build/skip counters and cache residency are read after each capture.",
        "checkpoints": checkpoints,
        "expectations": expectations,
        "all_expectations_passed": all(expectations.values()),
        "limitations": ["Headless serve on M1 Max/Metal only; no native-window or cross-adapter performance claim", "Repeated-render reuse primarily benefits unchanged states such as paused inspection; a moving scene still requires a cache build after each simulation tick", "This study measures build/skip correctness, not a whole-frame speedup"],
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "all_expectations_passed": report["all_expectations_passed"], "expectations": expectations}))
    return 0 if report["all_expectations_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
