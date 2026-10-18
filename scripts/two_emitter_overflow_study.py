#!/usr/bin/env python3
"""Compare tiled, exhaustive, and forced-fallback captures at the two-source budget."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from absorption_cache_study import image_error
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/scenes/two-emitter-overflow-stress.json"
SOURCE_ZERO_SCENE = ROOT / "assets/scenes/profiling-heavy.json"
SOURCE_ZERO_RGBA_SHA256 = "9faedb7b757c5043e8bf006f3e1bbffa0d4240e8ef6f0a2a85260612212a4a48"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(binary: Path, scene: Path, output: Path, camera: str, mode: str) -> dict:
    image = output / f"{camera}-{mode}.png"
    command = [
        str(binary), "capture", "--scene", str(scene), "--seed", "42",
        "--camera", camera, "--tick", "300", "--resolution", "640x360",
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
    category_order = capabilities["tile_lists"]["category_order"]
    capacities = capabilities["tile_lists"]["capacities"]
    capacity_keys = {
        "fire_primitives": "fire_primitives",
        "smoke_lobes": "smoke_lobes_total",
        "point_lights": "point_lights",
        "particle_lights": "particle_lights",
    }
    try:
        image_reference = str(image.relative_to(ROOT))
    except ValueError:
        image_reference = str(image)
    return {
        "image": image_reference,
        "sha256": sha256(image),
        "metrics": {
            "fire_primitives": metrics.get("fire_primitives"),
            "particle_lights": metrics.get("particle_lights"),
            "particle_lights_dropped": metrics.get("particle_lights_dropped"),
            "tile_overflow_tiles": metrics.get("tile_overflow_tiles"),
            "tile_candidates": metrics.get("tile_candidates"),
            "tile_max_occupancy": metrics.get("tile_max_occupancy"),
        },
        "tile_categories": {
            name: {
                "capacity": capacities[capacity_keys[name]],
                "candidate_memberships": metrics["tile_candidates"][index],
                "overflow_tiles": metrics["tile_overflow_tiles"][index],
                "max_occupancy": metrics["tile_max_occupancy"][index],
            }
            for index, name in enumerate(category_order)
        },
        "device": capabilities.get("name"),
        "backend": capabilities.get("backend"),
        "max_point_lights": capabilities.get("max_point_lights"),
        "max_particle_lights": capabilities.get("max_particle_lights"),
        "known_gpu_allocation_bytes": capabilities.get("resource_inventory", {}).get("known_gpu_allocation_bytes"),
        "tile_list_bytes": capabilities.get("resource_inventory", {}).get("tile_list_bytes"),
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
    source = json.loads(scene.read_text())
    emitters = sorted(source.get("emitters", []), key=lambda emitter: emitter["id"])
    if len(emitters) != 2:
        raise SystemExit("stress scene must contain exactly two emitters")
    cameras = [camera["id"] for camera in source.get("cameras", [])]
    camera_results = {}
    for camera in cameras:
        captures = {mode: capture(binary, scene, output, camera, mode) for mode in ("tiled", "exhaustive")}
        camera_results[camera] = {
            "captures": captures,
            "image_error": image_error(Path(captures["exhaustive"]["image"]), Path(captures["tiled"]["image"])),
            "exact_match": captures["tiled"]["sha256"] == captures["exhaustive"]["sha256"],
        }

    stress_camera = "stress-close"
    forced = capture(binary, scene, output, stress_camera, "forced-fallback")
    expected = camera_results[stress_camera]["captures"]["exhaustive"]
    natural_overflow = camera_results[stress_camera]["captures"]["tiled"]["tile_categories"]
    natural_fire_overflow = natural_overflow["fire_primitives"]["overflow_tiles"] > 0
    natural_nonfire_overflow = any(
        category["overflow_tiles"] > 0
        for name, category in natural_overflow.items()
        if name != "fire_primitives"
    )
    forced_all_categories = all(
        forced["tile_categories"][name]["overflow_tiles"] > 0
        for name in forced["tile_categories"]
    )
    if not natural_fire_overflow:
        raise SystemExit("stress-close scene did not naturally overflow fire primitive tiles")
    if natural_nonfire_overflow:
        raise SystemExit("unexpected natural non-fire tile overflow; investigate changed budgets")
    if not forced_all_categories:
        raise SystemExit("forced-overflow diagnostic did not reach every tile category")

    scenes_dir = output / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    isolated_results = {}
    for emitter in emitters:
        isolated = json.loads(json.dumps(source))
        for candidate in isolated["emitters"]:
            candidate["enabled"] = candidate["id"] == emitter["id"]
        isolated_path = scenes_dir / f"{emitter['id']}-only.json"
        isolated_path.write_text(json.dumps(isolated, indent=2) + "\n")
        subprocess.run([str(binary), "validate", str(isolated_path)], cwd=ROOT, check=True, capture_output=True)
        tiled = capture(binary, isolated_path, output, stress_camera, f"{emitter['id']}-only-tiled")
        exhaustive = capture(binary, isolated_path, output, stress_camera, f"{emitter['id']}-only-exhaustive")
        isolated_results[emitter["id"]] = {
            "tiled": tiled,
            "exhaustive": exhaustive,
            "exact_match": tiled["sha256"] == exhaustive["sha256"],
        }

    reversed_scene = json.loads(json.dumps(source))
    reversed_scene["emitters"].reverse()
    reversed_path = scenes_dir / "reversed-emitter-order.json"
    reversed_path.write_text(json.dumps(reversed_scene, indent=2) + "\n")
    subprocess.run([str(binary), "validate", str(reversed_path)], cwd=ROOT, check=True, capture_output=True)
    reversed_capture = capture(binary, reversed_path, output, stress_camera, "reversed-order-tiled")
    tiled_reference = camera_results[stress_camera]["captures"]["tiled"]

    source_zero_image = output / "source-zero-profiling-heavy.png"
    subprocess.run(
        [
            str(binary), "capture", "--scene", str(SOURCE_ZERO_SCENE), "--seed", "42",
            "--camera", "hero", "--tick", "120", "--resolution", "640x360", "--scale", "1",
            "--output", str(source_zero_image.resolve()),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    source_zero_rgba_sha256 = hashlib.sha256(Image.open(source_zero_image).convert("RGBA").tobytes()).hexdigest()
    source_zero_matches = source_zero_rgba_sha256 == SOURCE_ZERO_RGBA_SHA256

    all_camera_matches = all(result["exact_match"] for result in camera_results.values())
    isolated_matches = all(result["exact_match"] for result in isolated_results.values())
    forced_matches = forced["sha256"] == expected["sha256"]
    order_matches = reversed_capture["sha256"] == tiled_reference["sha256"]
    all_correctness_checks = all((all_camera_matches, isolated_matches, forced_matches, order_matches, source_zero_matches))
    report = {
        "date": "2026-10-18",
        "workstream": "bounded two-emitter maximum-budget tile-list correctness",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "scene": str(scene.relative_to(ROOT)),
        "scene_sha256": sha256(scene),
        "diagnosis": {
            "initial_changed_pixels": 9616,
            "cause": "The primary list used a 36-entry per-tile stride in a 72-entry layout, and the secondary reader omitted the 36-entry segment offset.",
            "correction": "Use a 72-entry per-tile stride and read source one from the second 36-entry segment.",
            "allocation_or_dispatch_change": False,
        },
        "seed": 42,
        "tick": 300,
        "cameras": cameras,
        "resolution": [640, 360],
        "camera_matrix": camera_results,
        "source_isolation": isolated_results,
        "forced_fallback": {"capture": forced, "matches_exhaustive": forced_matches},
        "natural_overflow": {
            "fire_category_overflows": natural_fire_overflow,
            "non_fire_categories_overflow": natural_nonfire_overflow,
            "interpretation": "Fire exceeds the 64-entry tile capacity; smoke and both light inputs are capped at or below their per-tile candidate capacities, so their natural overflow requires a runtime budget change. The forced-overflow mode independently verifies every category fallback.",
        },
        "reversed_emitter_order": {"capture": reversed_capture, "matches_tiled": order_matches},
        "source_zero_baseline": {
            "scene": str(SOURCE_ZERO_SCENE.relative_to(ROOT)),
            "camera": "hero",
            "seed": 42,
            "tick": 120,
            "reference_rgba_sha256": SOURCE_ZERO_RGBA_SHA256,
            "current_rgba_sha256": source_zero_rgba_sha256,
            "matches": source_zero_matches,
        },
        "comparisons": {
            "all_tiled_cameras_match_exhaustive": all_camera_matches,
            "source_isolation_matches_exhaustive": isolated_matches,
            "forced_fallback_matches_exhaustive": forced_matches,
            "natural_fire_overflow_reached": natural_fire_overflow,
            "natural_nonfire_overflow_absent_within_caps": not natural_nonfire_overflow,
            "forced_fallback_reaches_every_category": forced_all_categories,
            "reversed_emitter_order_matches": order_matches,
            "source_zero_baseline_matches": source_zero_matches,
        },
        "result": "passed" if all_correctness_checks else "failed",
        "limitations": [
            "Fixed-tick still captures on M1 Max/Metal; no temporal, native-window, DX12, or other-adapter acceptance.",
            "Derived particle-light selection is capped at 12; 38 additional candidates are reported dropped in this scene.",
            "Natural smoke, authored point-light and particle-light tile overflow cannot occur under current validated per-frame budgets: their maximum candidate counts match or stay below list capacities. Forced-overflow mode exercises their conservative fallback paths.",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["comparisons"], indent=2))
    return 0 if all_correctness_checks else 1


if __name__ == "__main__":
    raise SystemExit(main())
