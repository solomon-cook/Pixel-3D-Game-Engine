#!/usr/bin/env python3
"""Check live smoke-candidate cache toggles and dirty-state refresh parity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/smoke-candidate-review.json"
CAMERA = "dual-wide"
SEED = 42


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Session:
    def __init__(self, binary: Path, scene: Path, output: Path):
        self.process = subprocess.Popen(
            [str(binary), "serve", "--scene", str(scene), "--camera", CAMERA, "--seed", str(SEED)],
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
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("engine-lab serve ended before returning the Session response")
            response = json.loads(line)
            if response.get("id") != self.request_id:
                continue
            if "error" in response:
                raise RuntimeError(response)
            return response["result"]

    def capture(self, label: str) -> dict:
        image = Path(self.request(
            "capture_frame", path=str((self.output / f"{label}.png").resolve()), scale=1,
        )["image"])
        metadata = json.loads(image.with_suffix(".json").read_text())
        effects = self.request("inspect_effects")
        frame = self.request("get_metrics")["frame"]
        capabilities = metadata["capabilities"]
        return {
            "tick": metadata["tick"],
            "image": str(image),
            "sha256": sha256(image),
            "fire_state": effects,
            "smoke_candidate_bounds_bytes": capabilities["resource_inventory"]["smoke_candidate_bounds_bytes"],
            "cache_enabled": frame["smoke_candidate_cache_enabled"],
            "cache_builds": frame["smoke_candidate_cache_builds"],
            "cache_skips": frame["smoke_candidate_cache_skips"],
        }

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        self.process.wait(timeout=60)
        if self.process.returncode:
            raise RuntimeError(f"serve exited {self.process.returncode}")


def run_variant(binary: Path, output: Path, enabled: bool) -> dict:
    scene = json.loads(SOURCE.read_text())
    scene["render"]["experiments"]["smoke_candidate_cache"] = enabled
    scene_path = output / "scenes" / f"{'cached' if enabled else 'direct'}.json"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text(json.dumps(scene, indent=2) + "\n")
    session = Session(binary, scene_path, output / ("cached" if enabled else "direct"))
    checkpoints = {}
    try:
        session.request("step", ticks=120)
        checkpoints["initial_tick_120"] = session.capture("initial_tick_120")
        checkpoints["unchanged_paused_render"] = session.capture("unchanged_paused_render")
        session.request("set_parameter", path="emitters.campfire.smoke_density", value=3.1)
        checkpoints["paused_emitter_density_edit"] = session.capture("paused_emitter_density_edit")
        session.request("set_parameter", path="lights.fire-light.position", value=[0.32, 0.58, 0.24])
        checkpoints["paused_linked_light_edit"] = session.capture("paused_linked_light_edit")
        session.request("step", ticks=1)
        checkpoints["simulation_step"] = session.capture("simulation_step")
        session.request("reload_shaders")
        checkpoints["successful_shader_reload"] = session.capture("successful_shader_reload")
        session.request("reset", seed=SEED)
        session.request("step", ticks=120)
        checkpoints["reset_and_fixed_tick_replay"] = session.capture("reset_and_fixed_tick_replay")
    finally:
        session.close()
    return checkpoints


def run_toggle_check(binary: Path, output: Path) -> dict:
    scene = json.loads(SOURCE.read_text())
    scene["render"]["experiments"]["smoke_candidate_cache"] = False
    scene_path = output / "scenes" / "toggle.json"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text(json.dumps(scene, indent=2) + "\n")
    session = Session(binary, scene_path, output / "toggle")
    try:
        session.request("step", ticks=120)
        direct = session.capture("direct")
        on = session.request("set_parameter", path="render.experiments.smoke_candidate_cache", value=True)
        cached = session.capture("cached")
        off = session.request("set_parameter", path="render.experiments.smoke_candidate_cache", value=False)
        direct_again = session.capture("direct-again")
    finally:
        session.close()
    return {
        "enable_response": on,
        "disable_response": off,
        "direct_cached_pixel_identical": direct["sha256"] == cached["sha256"],
        "direct_again_pixel_identical": direct["sha256"] == direct_again["sha256"],
        "tick_match": direct["tick"] == cached["tick"] == direct_again["tick"],
        "direct_builds": direct["cache_builds"],
        "cached_builds": cached["cache_builds"],
        "direct_again_builds": direct_again["cache_builds"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o03/smoke-candidate-invalidation-current-build")
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    if not binary.is_file():
        parser.error(f"engine-lab binary does not exist: {binary}")

    direct = run_variant(binary, output, False)
    cached = run_variant(binary, output, True)
    checkpoints = {}
    for label in direct:
        a, b = direct[label], cached[label]
        checkpoints[label] = {
            "tick_match": a["tick"] == b["tick"],
            "fire_state_match": a["fire_state"] == b["fire_state"],
            "pixel_identical": a["sha256"] == b["sha256"],
            "direct_sha256": a["sha256"],
            "cached_sha256": b["sha256"],
            "candidate_buffer_bytes": b["smoke_candidate_bounds_bytes"],
            "direct_cache_enabled": a["cache_enabled"],
            "cached_cache_enabled": b["cache_enabled"],
            "direct_cache_builds": a["cache_builds"],
            "cached_cache_builds": b["cache_builds"],
            "direct_cache_skips": a["cache_skips"],
            "cached_cache_skips": b["cache_skips"],
        }
    toggle = run_toggle_check(binary, output)

    report = {
        "study": "O03 smoke-candidate live toggle and invalidation current-build check",
        "date": "2026-10-19",
        "host": {"device": "Apple M1 Max", "backend": "Metal"},
        "scene": str(SOURCE.relative_to(ROOT)),
        "camera": CAMERA,
        "seed": SEED,
        "resolution": [640, 360],
        "method": "Separate direct and cached serve sessions start from the same scene and seed and receive the same ordered fixed ticks, live parameter edits, shader reload, and reset/replay. The cached session stays enabled while dirty events occur, so toggles do not mask invalidation. Frame metrics report scheduled cache dispatches and clean enabled skips. A third session checks live enable/disable toggles at one fixed state.",
        "checkpoints": checkpoints,
        "live_toggle_check": toggle,
        "all_checks_pass": all(
            item["tick_match"] and item["fire_state_match"] and item["pixel_identical"]
            and item["candidate_buffer_bytes"] == 2304
            and item["direct_cache_enabled"] is False and item["cached_cache_enabled"] is True
            and item["direct_cache_builds"] == 0
            for item in checkpoints.values()
        ) and toggle["enable_response"] == {"path": "render.experiments.smoke_candidate_cache", "updated": True}
        and toggle["disable_response"] == {"path": "render.experiments.smoke_candidate_cache", "updated": True}
        and toggle["direct_cached_pixel_identical"] and toggle["direct_again_pixel_identical"] and toggle["tick_match"]
        and toggle["direct_builds"] == 0 and toggle["cached_builds"] == 1 and toggle["direct_again_builds"] == 1
        and checkpoints["unchanged_paused_render"]["cached_cache_builds"] == checkpoints["initial_tick_120"]["cached_cache_builds"]
        and checkpoints["unchanged_paused_render"]["cached_cache_skips"] > checkpoints["initial_tick_120"]["cached_cache_skips"]
        and [checkpoints[label]["cached_cache_builds"] for label in checkpoints] == [1, 1, 2, 3, 4, 5, 6],
        "limitations": [
            "Headless M1 Max/Metal only; native-window playback, Windows/DX12, and other adapters are not covered.",
            "Sampled state parity and shader-reload refresh are checked; continuous playback and visual acceptance are not established.",
            "Build counts record compute-dispatch encoding in the submitted command buffer, not GPU completion time or performance benefit.",
        ],
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "checkpoints": len(checkpoints), "all_checks_pass": report["all_checks_pass"]}))
    return 0 if report["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
