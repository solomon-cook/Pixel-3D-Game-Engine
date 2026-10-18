#!/usr/bin/env python3
"""Check dual-emitter absorption-cache parity at native route poses."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import select
import subprocess

from absorption_cache_study import image_error
from capture_motion import route_camera_at

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/scenes/two-emitter-overflow-stress.json"
ROUTE_ID = "clearing-orbit"
CAMERA_ID = "dual-wide"
ROUTE_TIMES = (0.0, 24.0, 48.0, 72.0, 96.0, 119.95)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class NativeSession:
    def __init__(self, binary: Path, scene: Path, seed: int) -> None:
        self.process = subprocess.Popen(
            [str(binary), "run", "--agent-stdio", "--scene", str(scene), "--seed", str(seed)],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.request_id = 0

    def request(self, method: str, **params):
        self.request_id += 1
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps({"id": self.request_id, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        ready, _, _ = select.select([self.process.stdout], [], [], 90)
        if not ready:
            raise TimeoutError(f"timed out waiting for native {method}")
        response = json.loads(self.process.stdout.readline())
        if response.get("id") != self.request_id or "error" in response:
            raise RuntimeError(f"native {method} failed: {response}")
        return response["result"]

    def close(self) -> None:
        try:
            self.request("shutdown")
        except Exception:
            self.process.terminate()
        self.process.wait(timeout=60)


def capture(session: NativeSession, path: Path) -> dict:
    image = Path(session.request("capture_frame", path=str(path.resolve()), scale=1)["image"])
    metadata = json.loads(image.with_suffix(".json").read_text())
    metrics = metadata.get("metrics", {})
    capabilities = metadata.get("capabilities", {})
    return {
        "image": str(image.relative_to(ROOT)) if image.is_relative_to(ROOT) else str(image),
        "sha256": sha256(image),
        "tick": metadata.get("tick"),
        "camera": metadata.get("camera"),
        "device": capabilities.get("name"),
        "backend": capabilities.get("backend"),
        "cache_enabled": metrics.get("smoke_absorption_cache_enabled"),
        "cache_builds": metrics.get("absorption_cache_builds"),
        "cache_bytes": capabilities.get("resource_inventory", {}).get("smoke_absorption_cache_bytes"),
    }


def image_path(result: dict) -> Path:
    path = Path(result["image"])
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--scene", type=Path, default=SCENE)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/multi-emitter/absorption-native")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-multi-emitter-absorption-native.json")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cache-resolution", type=int, choices=(8, 16), default=8)
    args = parser.parse_args()
    binary, scene = args.binary.resolve(), args.scene.resolve()
    output, report_path = args.output.resolve(), args.report.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    source = json.loads(scene.read_text())
    if len(source.get("emitters", [])) != 2:
        parser.error("scene must contain exactly two emitters")
    route = next((item for item in source.get("routes", []) if item.get("id") == ROUTE_ID), None)
    base_camera = next((item for item in source.get("cameras", []) if item.get("id") == CAMERA_ID), None)
    if route is None or base_camera is None:
        parser.error(f"scene must contain route {ROUTE_ID} and camera {CAMERA_ID}")

    source["render"]["absorption_cache_resolution"] = args.cache_resolution
    scene_path = output / "native-cache-off.scene.json"
    scene_path.write_text(json.dumps(source, indent=2) + "\n")
    session = NativeSession(binary, scene_path, args.seed)
    poses = []
    previous_route_time = 0.0
    current_tick = 0
    try:
        window = session.request("get_window")
        for index, route_time in enumerate(ROUTE_TIMES):
            if index == 0:
                session.request("step", ticks=300)
                current_tick = 300
            else:
                ticks = round((route_time - previous_route_time) * 60)
                session.request("step", ticks=ticks)
                current_tick += ticks
            camera = route_camera_at(route, base_camera, route_time)
            session.request("set_camera", camera=camera)
            captures = {}
            captures["direct_a"] = capture(session, output / f"pose-{index:02d}-direct-a.png")
            session.request("set_parameter", path="render.experiments.smoke_absorption_cache", value=True)
            captures["cached"] = capture(session, output / f"pose-{index:02d}-cached.png")
            session.request("set_parameter", path="render.experiments.smoke_absorption_cache", value=False)
            captures["direct_b"] = capture(session, output / f"pose-{index:02d}-direct-b.png")
            camera_metadata_matches = all(
                captures[mode]["camera"] == captures["direct_a"]["camera"] for mode in captures
            )
            direct_repeat_identical = captures["direct_a"]["sha256"] == captures["direct_b"]["sha256"]
            cache_mode_correct = captures["cached"]["cache_enabled"] is True and captures["direct_a"]["cache_enabled"] is False and captures["direct_b"]["cache_enabled"] is False
            expected_bytes = args.cache_resolution ** 3 * 8
            residency_correct = captures["cached"]["cache_bytes"] == expected_bytes and captures["direct_b"]["cache_bytes"] == 0
            poses.append({
                "index": index,
                "route_time_seconds": route_time,
                "tick": current_tick,
                "camera_pose": camera,
                "captures": captures,
                "direct_repeat_identical": direct_repeat_identical,
                "camera_metadata_matches": camera_metadata_matches,
                "cache_mode_correct": cache_mode_correct,
                "residency_correct": residency_correct,
                "direct_vs_cache": image_error(image_path(captures["direct_a"]), image_path(captures["cached"])),
            })
            previous_route_time = route_time
    finally:
        session.close()

    checks = {
        "direct_repeats_identical": all(item["direct_repeat_identical"] for item in poses),
        "camera_metadata_matches": all(item["camera_metadata_matches"] for item in poses),
        "cache_mode_toggled_correctly": all(item["cache_mode_correct"] for item in poses),
        "cache_residency_matches_model": all(item["residency_correct"] for item in poses),
        "all_native_direct_cache_captures_exact": all(item["direct_vs_cache"]["changed_pixel_count"] == 0 for item in poses),
    }
    report = {
        "version": 1,
        "date": "2026-10-18",
        "study": "native-window two-emitter absorption cache fixed-tick route-pose comparison",
        "host": {"device": poses[0]["captures"]["direct_a"]["device"], "backend": poses[0]["captures"]["direct_a"]["backend"], "native_window": True, "window": window},
        "source_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "binary_sha256": sha256(binary),
        "scene": str(scene.relative_to(ROOT)) if scene.is_relative_to(ROOT) else str(scene),
        "scene_sha256": sha256(scene),
        "runtime_scene_sha256": sha256(scene_path),
        "shader_sha256": sha256(ROOT / "crates/engine/src/render/shaders/absorption.wgsl"),
        "study_script_sha256": sha256(Path(__file__).resolve()),
        "source_ids": sorted(item["id"] for item in source["emitters"]),
        "seed": args.seed,
        "route": ROUTE_ID,
        "camera": CAMERA_ID,
        "resolution": source["render"]["resolution"],
        "cache_resolution": [args.cache_resolution] * 3,
        "poses": poses,
        "checks": checks,
        "result": "passed" if all(checks.values()) else "failed",
        "limitations": [
            "Six fixed-tick native-window poses in one M1 Max/Metal session; no continuous native playback or performance acceptance.",
            "DX12 and other-adapter cache creation, output and timing remain unverified.",
            "The cache remains disabled by default because sustained route measurements show no total-render win.",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"result": report["result"], "checks": checks, "report": str(report_path)}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
