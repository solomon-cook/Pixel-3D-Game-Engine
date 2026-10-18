#!/usr/bin/env python3
"""Exercise dual-source absorption-cache toggles at fixed ticks and named views."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from absorption_cache_study import image_error, sha256


ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/scenes/two-emitter-review.json"
CAMERAS = ("hero", "smoke-close", "orthographic", "dual-wide")
SEED = 42
TICK = 120


class Session:
    def __init__(self, binary: Path, output: Path):
        self.process = subprocess.Popen(
            [str(binary), "serve", "--scene", str(SCENE), "--camera", CAMERAS[0], "--seed", str(SEED)],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.request_id = 0
        self.output = output
        output.mkdir(parents=True, exist_ok=True)

    def request(self, method: str, **params):
        self.request_id += 1
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(
            json.dumps({"id": self.request_id, "method": method, "params": params}) + "\n"
        )
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        if response.get("id") != self.request_id or "error" in response:
            raise RuntimeError(f"{method}: {response}")
        return response["result"]

    def checkpoint(self, camera: str, label: str) -> dict:
        path = (self.output / f"{camera}-{label}.png").resolve()
        capture = self.request("capture_frame", path=str(path), scale=1)
        metrics = self.request("get_metrics")
        return {
            "image": capture["image"],
            "png_sha256": sha256(Path(capture["image"])),
            "cache_bytes": metrics["capabilities"]["resource_inventory"]["smoke_absorption_cache_bytes"],
            "cache_builds": metrics["frame"]["absorption_cache_builds"],
            "cache_skips": metrics["frame"]["absorption_cache_skips"],
            "cpu_cache_ms": metrics["frame"]["cpu_absorption_cache_ms"],
            "fire_state": self.request("inspect_effects"),
        }

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        self.process.wait(timeout=60)
        if self.process.returncode:
            raise RuntimeError(f"serve exited with status {self.process.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/two-emitter-absorption-cache")
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "-p", "engine-lab"], cwd=ROOT, check=True)

    scene = json.loads(SCENE.read_text())
    if len(scene.get("emitters", [])) != 2:
        raise SystemExit("the study requires the two-emitter review scene")
    session = Session(binary, output / "captures")
    views = {}
    try:
        session.request("step", ticks=TICK)
        for camera in CAMERAS:
            session.request("set_camera", id=camera)
            session.request("set_parameter", path="render.experiments.smoke_absorption_cache", value=False)
            direct = session.checkpoint(camera, "direct-before")
            session.request("set_parameter", path="render.experiments.smoke_absorption_cache", value=True)
            cached = session.checkpoint(camera, "cache-enabled")
            session.request("set_parameter", path="render.experiments.smoke_absorption_cache", value=False)
            direct_after = session.checkpoint(camera, "direct-after")
            views[camera] = {
                "direct_before": direct,
                "cache_enabled": cached,
                "direct_after": direct_after,
                "cache_image_error_vs_direct": image_error(Path(direct["image"]), Path(cached["image"])),
                "disabled_output_restored_exactly": direct["png_sha256"] == direct_after["png_sha256"],
                "fire_state_stable": direct["fire_state"] == cached["fire_state"] == direct_after["fire_state"],
            }
    finally:
        session.close()

    expectations = {
        "all_direct_images_restore_after_disable": all(
            view["disabled_output_restored_exactly"] for view in views.values()
        ),
        "fire_state_unchanged_by_cache_toggle": all(view["fire_state_stable"] for view in views.values()),
        "disabled_mode_releases_cache": all(
            view[mode]["cache_bytes"] == 0
            for view in views.values()
            for mode in ("direct_before", "direct_after")
        ),
        "enabled_mode_allocates_cache": all(
            view["cache_enabled"]["cache_bytes"] > 0 for view in views.values()
        ),
        "enabled_mode_builds_cache_for_each_view": all(
            view["cache_enabled"]["cache_builds"] == view["direct_before"]["cache_builds"] + 1
            for view in views.values()
        ),
    }
    report = {
        "date": "2026-10-18",
        "scope": "Dual-source absorption-cache toggle, allocation lifetime and fixed-tick image comparison",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "scene": str(SCENE.relative_to(ROOT)),
        "scene_sha256": sha256(SCENE),
        "source_ids": sorted(emitter["id"] for emitter in scene["emitters"]),
        "seed": SEED,
        "tick": TICK,
        "resolution": scene["render"]["resolution"],
        "cache_resolution": scene["render"].get("absorption_cache_resolution", 8),
        "method": "One paused serve session captures direct, cache-enabled and direct-again at each named camera without advancing the fixed tick. The candidate differs only by the cache experiment toggle; fire state and cache residency/build metrics are read from the live Session.",
        "views": views,
        "expectations": expectations,
        "all_expectations_passed": all(expectations.values()),
        "limitations": [
            "This is a fixed-tick visual/resource-lifecycle check, not a sustained performance or temporal-quality study.",
            "Cache-enabled image differences are measured against direct sampling; no approximation threshold or promotion decision is made here.",
            "Headless M1 Max/Metal only; Windows/DX12 and another adapter remain unverified.",
        ],
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), **expectations}))
    return 0 if report["all_expectations_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
