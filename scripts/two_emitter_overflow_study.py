#!/usr/bin/env python3
"""Compare tiled, exhaustive, and forced-fallback captures at the two-source budget."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from absorption_cache_study import image_error


ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/scenes/two-emitter-overflow-stress.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(binary: Path, scene: Path, output: Path, mode: str) -> dict:
    image = output / f"{mode}.png"
    command = [
        str(binary), "capture", "--scene", str(scene), "--seed", "42",
        "--camera", "stress-close", "--tick", "300", "--resolution", "640x360",
        "--scale", "1", "--output", str(image.resolve()),
    ]
    if mode == "exhaustive":
        command.append("--disable-tile-lists")
    elif mode == "forced-fallback":
        command.append("--force-tile-overflow")
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    metadata_path = image.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text())
    metrics = metadata["metrics"]
    capabilities = metadata["capabilities"]
    return {
        "image": str(image.relative_to(ROOT)),
        "sha256": sha256(image),
        "metrics": {
            "fire_primitives": metrics.get("fire_primitives"),
            "particle_lights": metrics.get("particle_lights"),
            "particle_lights_dropped": metrics.get("particle_lights_dropped"),
            "tile_overflow_tiles": metrics.get("tile_overflow_tiles"),
        },
        "device": capabilities.get("name"),
        "backend": capabilities.get("backend"),
        "max_point_lights": capabilities.get("max_point_lights"),
        "max_particle_lights": capabilities.get("max_particle_lights"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--scene", type=Path, default=SCENE)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/two-emitter-overflow")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-multi-emitter-overflow.json")
    args = parser.parse_args()
    binary, scene, output = args.binary.resolve(), args.scene.resolve(), args.output.resolve()
    report_path = args.report.resolve()
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(binary), "validate", str(scene)], cwd=ROOT, check=True, capture_output=True)

    captures = {mode: capture(binary, scene, output, mode) for mode in ("tiled", "exhaustive", "forced-fallback")}
    report = {
        "date": "2026-10-18",
        "workstream": "bounded two-emitter maximum-budget tile-list correctness",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "scene": str(scene.relative_to(ROOT)),
        "scene_sha256": sha256(scene),
        "seed": 42,
        "tick": 300,
        "camera": "stress-close",
        "resolution": [640, 360],
        "captures": captures,
        "comparisons": {
            "tiled_vs_exhaustive": {
                "image_error": image_error(output / "exhaustive.png", output / "tiled.png"),
                "exact_match": captures["tiled"]["sha256"] == captures["exhaustive"]["sha256"],
            },
            "forced_fallback_vs_exhaustive": {
                "exact_match": captures["forced-fallback"]["sha256"] == captures["exhaustive"]["sha256"],
            },
        },
        "result": "failed: tiled evaluation differs from exhaustive evaluation; forced fallback matches exhaustive",
        "limitations": [
            "Single fixed-tick close camera on M1 Max/Metal; no temporal, native-window, DX12, or other-adapter acceptance.",
            "Derived particle-light selection is capped at 12; 38 additional candidates are reported dropped in this scene.",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["comparisons"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
