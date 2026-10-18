#!/usr/bin/env python3
"""Compare cached and forced shadow redraws in the two-emitter review scene."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FACE_COUNT = 6


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Session:
    def __init__(self, binary: Path, scene: Path, camera: str, seed: int, output: Path):
        self.process = subprocess.Popen(
            [str(binary), "serve", "--scene", str(scene), "--camera", camera, "--seed", str(seed)],
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

    def capture(self, label: str) -> dict:
        image_path = (self.output / f"{label}.png").resolve()
        self.request("capture_frame", path=str(image_path), scale=1)
        frame = self.request("get_metrics")["frame"]
        image_bytes = image_path.read_bytes()
        return {
            "image": image_path.name,
            "png_sha256": sha256(image_bytes),
            "shadow_source_ids": frame.get("shadow_source_ids", []),
            "shadow_dirty_faces": frame.get("shadow_dirty_faces", []),
            "shadow_maps_redrawn": frame.get("shadow_maps_redrawn"),
            "shadow_dirty_reason": frame.get("shadow_dirty_reason"),
            "shadow_cache_hit": frame.get("shadow_cache_hit"),
        }

    def compare(self, label: str) -> dict:
        cached = self.capture(f"{label}-cached")
        self.request("set_shadow_cache", force_redraw=True)
        try:
            forced = self.capture(f"{label}-forced")
        finally:
            self.request("set_shadow_cache", force_redraw=False)
        expected_forced_count = 1 + FACE_COUNT * len(cached["shadow_source_ids"])
        return {
            "event": label,
            "cached": cached,
            "forced": forced,
            "images_match": cached["png_sha256"] == forced["png_sha256"],
            "forced_all_maps_redrawn": forced["shadow_maps_redrawn"] == expected_forced_count
            and all(forced["shadow_dirty_faces"]),
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
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/two-emitter-review.json")
    parser.add_argument("--camera", default="dual-wide")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/multi-emitter-shadow-invalidation")
    args = parser.parse_args()

    scene_path = args.scene.resolve()
    binary = args.binary.resolve()
    output = args.output.resolve()
    scene = json.loads(scene_path.read_text())
    emitters = sorted(scene["emitters"], key=lambda emitter: emitter["id"])
    if len(emitters) != 2 or any(not emitter.get("light_id") for emitter in emitters):
        raise SystemExit("scene must contain exactly two emitters with explicit linked lights")

    session = Session(binary, scene_path, args.camera, args.seed, output / "captures")
    events = []
    try:
        session.request("step", ticks=120)
        session.capture("initial")
        events.append(session.compare("unchanged-cache"))

        for source_slot, emitter in enumerate(emitters):
            light = next(light for light in scene["lights"] if light["id"] == emitter["light_id"])
            moved = list(light["position"])
            moved[0] += 0.2
            session.request("set_parameter", path=f"lights.{emitter['light_id']}.position", value=moved)
            result = session.compare(f"{emitter['id']}-light-moved")
            expected = [False] * (1 + FACE_COUNT * len(emitters))
            start = 1 + source_slot * FACE_COUNT
            expected[start : start + FACE_COUNT] = [True] * FACE_COUNT
            result["expected_source_only_face_mask"] = expected
            result["source_only_invalidation"] = result["cached"]["shadow_dirty_faces"] == expected
            events.append(result)

        sun = next(light for light in scene["lights"] if light["kind"] == "directional")
        moved_sun = list(sun["position"])
        moved_sun[0] += 0.1
        session.request("set_parameter", path=f"lights.{sun['id']}.position", value=moved_sun)
        result = session.compare("sun-projection-moved")
        expected_sun = [True] + [False] * (FACE_COUNT * len(emitters))
        result["expected_sun_only_face_mask"] = expected_sun
        result["sun_only_invalidation"] = result["cached"]["shadow_dirty_faces"] == expected_sun
        events.append(result)

        caster = next(obj for obj in scene["objects"] if obj["id"] == "pine-0")
        moved_caster = list(caster["position"])
        moved_caster[0] += 0.2
        session.request("set_object_transform", id=caster["id"], position=moved_caster)
        events.append(session.compare("caster-moved"))

        pine = next(material for material in scene["materials"] if material["id"] == caster["material"])
        session.request(
            "set_parameter",
            path=f"materials.{pine['id']}.transmission",
            value=0.5,
        )
        events.append(session.compare("shadow-material-changed"))

        session.request("reload_shaders")
        events.append(session.compare("shader-reload"))
        session.request("reset", seed=args.seed)
        session.request("step", ticks=120)
        events.append(session.compare("reset-and-replay"))
    finally:
        session.close()

    expectations = {
        "all_cached_images_match_forced_redraw": all(event["images_match"] for event in events),
        "forced_redraw_covers_all_13_maps": all(event["forced_all_maps_redrawn"] for event in events),
        "campfire_move_dirties_only_its_faces": events[1]["source_only_invalidation"],
        "watchfire_move_dirties_only_its_faces": events[2]["source_only_invalidation"],
        "sun_move_dirties_only_directional_map": events[3]["sun_only_invalidation"],
    }
    report = {
        "date": "2026-10-18",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "scene": str(scene_path.relative_to(ROOT)) if scene_path.is_relative_to(ROOT) else str(scene_path),
        "scene_sha256": sha256(scene_path.read_bytes()),
        "camera": args.camera,
        "seed": args.seed,
        "fixed_tick": 120,
        "resolution": scene["render"]["resolution"],
        "shadow_source_order": [emitter["id"] for emitter in emitters],
        "face_order": ["sun"]
        + [f"{emitter['id']}:{face}" for emitter in emitters for face in ("+X", "-X", "+Y", "-Y", "+Z", "-Z")],
        "events": events,
        "expectations": expectations,
        "all_expectations_passed": all(expectations.values()),
        "limitations": [
            "Headless M1 Max/Metal fixed-tick cache correctness only; GPU timestamps are not used as a performance comparison.",
            "This route covers two-source light movement, one caster, one shadow material, shader reload and reset, not maximum tile or light-budget stress.",
            "Windows/DX12 and another physical adapter remain unverified.",
        ],
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), **expectations}))
    return 0 if report["all_expectations_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
