#!/usr/bin/env python3
"""Compare native-window dual-emitter captures against exhaustive shading."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import select
import subprocess

from absorption_cache_study import image_error

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/scenes/two-emitter-overflow-stress.json"


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
            raise TimeoutError(f"timed out waiting for native {method} response")
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
    result = session.request("capture_frame", path=str(path.resolve()), scale=1)
    image = Path(result["image"])
    sidecar = json.loads(image.with_suffix(".json").read_text())
    metrics = sidecar.get("metrics", {})
    caps = sidecar.get("capabilities", {})
    return {
        "image": str(image.relative_to(ROOT)) if image.is_relative_to(ROOT) else str(image),
        "sha256": sha256(image),
        "tick": sidecar.get("tick"),
        "device": caps.get("name"),
        "backend": caps.get("backend"),
        "metrics": {
            key: metrics.get(key)
            for key in ("fire_primitives", "particle_lights", "particle_lights_dropped", "tile_overflow_tiles")
        },
    }


def compare_scene(binary: Path, scene: Path, camera: str, output: Path, seed: int) -> dict:
    session = NativeSession(binary, scene, seed)
    try:
        session.request("step", ticks=300)
        session.request("set_camera", id=camera)
        name = scene.stem
        enabled_a = capture(session, output / f"{name}-{camera}-tiled-a.png")
        session.request("set_tile_lists", enabled=False)
        exhaustive = capture(session, output / f"{name}-{camera}-exhaustive.png")
        session.request("set_tile_lists", enabled=True)
        enabled_b = capture(session, output / f"{name}-{camera}-tiled-b.png")
        def image_path(capture_result: dict) -> Path:
            path = Path(capture_result["image"])
            return path if path.is_absolute() else ROOT / path

        errors = {
            "tiled_a_vs_exhaustive": image_error(image_path(enabled_a), image_path(exhaustive)),
            "tiled_a_vs_tiled_b": image_error(image_path(enabled_a), image_path(enabled_b)),
        }
        return {
            "scene": str(scene.relative_to(ROOT)) if scene.is_relative_to(ROOT) else str(scene),
            "scene_sha256": sha256(scene),
            "camera": camera,
            "seed": seed,
            "tick": 300,
            "captures": {"tiled_a": enabled_a, "exhaustive": exhaustive, "tiled_b": enabled_b},
            "image_error": errors,
            "tiled_matches_exhaustive": enabled_a["sha256"] == exhaustive["sha256"],
            "tiled_repeat_identical": enabled_a["sha256"] == enabled_b["sha256"],
        }
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--scene", type=Path, default=SCENE)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/multi-emitter/native-captures")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-multi-emitter-native.json")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    binary, source_scene = args.binary.resolve(), args.scene.resolve()
    output, report_path = args.output.resolve(), args.report.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    source = json.loads(source_scene.read_text())
    emitters = sorted(source.get("emitters", []), key=lambda item: item["id"])
    if len(emitters) != 2:
        parser.error("scene must contain exactly two emitters")

    camera_results = {}
    for camera in (item["id"] for item in source.get("cameras", [])):
        print(f"native camera: {camera}", flush=True)
        camera_results[camera] = compare_scene(binary, source_scene, camera, output, args.seed)

    scene_dir = output / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)
    isolation_results = {}
    for emitter in emitters:
        isolated = json.loads(json.dumps(source))
        for candidate in isolated["emitters"]:
            candidate["enabled"] = candidate["id"] == emitter["id"]
        isolated_path = scene_dir / f"{emitter['id']}-only.json"
        isolated_path.write_text(json.dumps(isolated, indent=2) + "\n")
        print(f"native source isolation: {emitter['id']}", flush=True)
        isolation_results[emitter["id"]] = compare_scene(binary, isolated_path, "stress-close", output, args.seed)

    reversed_scene = json.loads(json.dumps(source))
    reversed_scene["emitters"].reverse()
    reversed_path = scene_dir / "reversed-emitter-order.json"
    reversed_path.write_text(json.dumps(reversed_scene, indent=2) + "\n")
    print("native reversed emitter order", flush=True)
    reversed_result = compare_scene(binary, reversed_path, "stress-close", output, args.seed)
    reference = camera_results["stress-close"]["captures"]["tiled_a"]
    reversed_matches = reference["sha256"] == reversed_result["captures"]["tiled_a"]["sha256"]
    adapter_capture = camera_results["stress-close"]["captures"]["tiled_a"]
    checks = {
        "all_cameras_match_exhaustive": all(item["tiled_matches_exhaustive"] for item in camera_results.values()),
        "all_cameras_repeat_identically": all(item["tiled_repeat_identical"] for item in camera_results.values()),
        "isolated_sources_match_exhaustive": all(item["tiled_matches_exhaustive"] for item in isolation_results.values()),
        "reversed_order_matches": reversed_matches,
    }
    report = {
        "version": 1,
        "study": "native-window two-emitter tiled versus exhaustive correctness",
        "date": "2026-10-18",
        "host": {"device": adapter_capture["device"], "backend": adapter_capture["backend"], "native_window": True},
        "binary_sha256": sha256(binary),
        "source_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "scene": str(source_scene.relative_to(ROOT)) if source_scene.is_relative_to(ROOT) else str(source_scene),
        "scene_sha256": sha256(source_scene),
        "seed": args.seed,
        "tick": 300,
        "resolution": source["render"]["resolution"],
        "cameras": camera_results,
        "source_isolation": isolation_results,
        "reversed_emitter_order": {"result": reversed_result, "matches_tiled_reference": reversed_matches},
        "checks": checks,
        "result": "passed" if all(checks.values()) else "failed",
        "limitations": [
            "Fixed-tick native-window captures on one M1 Max/Metal adapter; no temporal, sustained-performance, DX12 or other-adapter acceptance.",
            "Natural overflow metrics are captured, but the session comparison does not force overflow; forced fallback remains covered by the offscreen study.",
            "Derived particle-light selection remains capped at 12, with overflow accounting reported in per-capture metrics.",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"result": report["result"], "checks": checks, "report": str(report_path)}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
