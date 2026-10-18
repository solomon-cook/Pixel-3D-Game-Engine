#!/usr/bin/env python3
"""A/B the secondary emitter's opaque heat cue on a fixed two-source scene."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from absorption_cache_study import image_error


ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/scenes/two-emitter-review.json"
CAMERAS = ("hero", "smoke-close", "orthographic", "dual-wide", "watchfire-study")
SEED = 42
TICK = 300
HEAT_RESPONSE = 0.8


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_variant(source: dict, heat_response: float) -> dict:
    scene = copy.deepcopy(source)
    for emitter in scene["emitters"]:
        emitter["enabled"] = emitter["id"] == "watchfire"
    scene["cameras"] = [camera for camera in scene["cameras"] if camera["id"] != "watchfire-study"]
    scene["cameras"].append(
        {
            "id": "watchfire-study",
            "position": [-0.6, 1.35, 3.0],
            "target": [-3.0, 1.05, 0.0],
            "projection": {"kind": "perspective", "fov_degrees": 48.0},
        }
    )
    earth = next(material for material in scene["materials"] if material["id"] == "earth")
    earth["heat_response"] = heat_response
    return scene


def capture_variant(binary: Path, scene_path: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    captures = {}
    for camera in CAMERAS:
        path = output / f"{camera}.png"
        subprocess.run(
            [
                str(binary),
                "capture",
                "--scene",
                str(scene_path),
                "--seed",
                str(SEED),
                "--camera",
                camera,
                "--tick",
                str(TICK),
                "--resolution",
                "640x360",
                "--scale",
                "1",
                "--output",
                str(path.resolve()),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        captures[camera] = {"image": str(path), "sha256": digest(path)}
    return captures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/two-emitter-heat-response")
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = json.loads(SCENE.read_text())
    source_ids = sorted(emitter["id"] for emitter in source["emitters"])
    if source_ids != ["campfire", "watchfire"]:
        raise SystemExit(f"expected stable source order campfire/watchfire, got {source_ids}")

    captures = {}
    scene_hashes = {}
    temp_paths = []
    try:
        for label, response in (("heat-off", 0.0), ("heat-on", HEAT_RESPONSE)):
            scene = make_variant(source, response)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", prefix=f".heat-response-{label}-", dir=SCENE.parent, delete=False
            ) as temporary:
                json.dump(scene, temporary, indent=2)
                temporary.write("\n")
                scene_path = Path(temporary.name)
            temp_paths.append(scene_path)
            subprocess.run([str(binary), "validate", str(scene_path)], cwd=ROOT, check=True, capture_output=True)
            scene_hashes[label] = digest(scene_path)
            captures[label] = capture_variant(binary, scene_path, output / label)
    finally:
        for path in temp_paths:
            path.unlink(missing_ok=True)

    view_results = {}
    for camera in CAMERAS:
        off = captures["heat-off"][camera]
        on = captures["heat-on"][camera]
        view_results[camera] = {
            "heat_off": off,
            "heat_on": on,
            "rgba_error_heat_on_vs_off": image_error(Path(off["image"]), Path(on["image"])),
            "changed": off["sha256"] != on["sha256"],
        }

    report = {
        "date": "2026-10-18",
        "scope": "Focused source-one opaque heat-response A/B with the primary emitter disabled while retaining both stable source slots",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "base_scene": str(SCENE.relative_to(ROOT)),
        "base_scene_sha256": digest(SCENE),
        "variant_scene_sha256": scene_hashes,
        "source_ids": source_ids,
        "enabled_emitters": ["watchfire"],
        "disabled_emitters": ["campfire"],
        "heat_material": "earth",
        "heat_response_off": 0.0,
        "heat_response_on": HEAT_RESPONSE,
        "seed": SEED,
        "tick": TICK,
        "resolution": [640, 360],
        "views": view_results,
        "all_views_changed": all(view["changed"] for view in view_results.values()),
        "visual_review": "pending",
        "limitations": [
            "Fixed-tick source-isolated A/B only; no continuous motion or temporal error analysis.",
            "Changing heat_response enables the cue across the ground material, so the result establishes contribution/readability, not physical temperature accuracy.",
            "Headless M1 Max/Metal only; no performance conclusion, Windows/DX12 or other-adapter validation.",
        ],
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "all_views_changed": report["all_views_changed"]}))
    return 0 if report["all_views_changed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
