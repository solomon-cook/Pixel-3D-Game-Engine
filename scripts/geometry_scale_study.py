#!/usr/bin/env python3
"""Measure O07 culling/instancing at deterministic scene-size tiers."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import subprocess

from absorption_cache_study import image_error, sha256

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/clearing.json"
COUNTS = (276, 552, 1104, 2208)
ROUTE = "clearing-orbit"


def geometry_key(obj: dict) -> str:
    return json.dumps([obj["material"], obj["geometry"]], sort_keys=True, separators=(",", ":"))


def generate_scene(source: dict, target_count: int) -> tuple[dict, dict]:
    scene = copy.deepcopy(source)
    extra_count = target_count - len(scene["objects"])
    if extra_count < 0:
        raise ValueError(f"target count {target_count} is below source count")
    templates = {
        "pine": next(o for o in source["objects"] if o["id"] == "pine-0"),
        "rock": next(o for o in source["objects"] if o["id"] == "rock-0"),
        "grass": next(o for o in source["objects"] if o["id"] == "grass-0"),
    }
    # Spread additional content over a low-discrepancy ring. Four in five
    # objects stay within the clearing view envelope; the rest occupy the
    # forest perimeter so camera visibility and shadow visibility differ.
    generated = []
    counts = {"pine": 0, "rock": 0, "grass": 0}
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    for index in range(extra_count):
        # Six tenths pines, two tenths rocks, two tenths grass.
        if index % 10 < 6:
            category = "pine"
        elif index % 10 < 8:
            category = "rock"
        else:
            category = "grass"
        template = templates[category]
        obj = copy.deepcopy(template)
        obj["id"] = f"scale-{category}-{index:05d}"
        angle = index * golden_angle
        perimeter = index % 5 == 4
        radius = (20.0 + (index % 7) * 0.55) if perimeter else (10.0 + (index % 13) * 0.62)
        x, z = radius * math.cos(angle), radius * math.sin(angle)
        if category == "pine":
            obj["geometry"]["seed"] = 17 if index % 4 == 0 else 10000 + index
            obj["position"] = [x, 0.0, z]
            scale = 3.0 + ((index * 37) % 29) / 10.0
            obj["scale"] = [scale * 0.55, scale, scale * 0.55]
        elif category == "rock":
            obj["position"] = [x, 0.05, z]
            scale = 0.5 + ((index * 19) % 14) / 10.0
            obj["scale"] = [scale, scale * 0.8, scale * 0.9]
        else:
            obj["position"] = [x, 0.05, z]
            height = 0.2 + ((index * 23) % 6) / 10.0
            obj["scale"] = [0.12 + (index % 4) * 0.025, height, 0.13]
        generated.append(obj)
        counts[category] += 1
    generated.sort(key=geometry_key)
    scene["objects"].extend(generated)
    scene["render"]["resolution"] = [640, 360]
    unique_keys = len({geometry_key(obj) for obj in scene["objects"]})
    return scene, {
        "target_object_count": target_count,
        "source_object_count": len(source["objects"]),
        "generated_object_count": extra_count,
        "generated_categories": counts,
        "unique_geometry_material_keys": unique_keys,
        "shared_geometry_material_instances": target_count - unique_keys,
        "offscreen_perimeter_generation_fraction": 0.2,
        "pine_seed_reuse_fraction": 0.25,
    }


def save_scenes(output: Path) -> tuple[dict[int, Path], dict[int, dict]]:
    source = json.loads(SOURCE.read_text())
    scenes, metadata = {}, {}
    for count in COUNTS:
        scene, details = generate_scene(source, count)
        path = output / "scenes" / f"objects-{count}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(scene, indent=2) + "\n")
        scenes[count], metadata[count] = path, details
    return scenes, metadata


def capture_path(binary: Path, scene: Path, output: Path, mode: str) -> dict:
    flags = []
    if mode in ("baked", "instancing_only"):
        flags.append("--disable-object-culling")
    if mode == "baked":
        flags.append("--disable-instancing")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(binary), "capture", "--scene", str(scene), "--camera", "hero",
        "--resolution", "640x360", "--tick", "300", "--scale", "1",
        "--output", str(output.resolve()), *flags,
    ], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    image = str(output.resolve())
    metrics = json.loads(output.with_suffix(".json").read_text())
    return {
        "image": image,
        "sha256": sha256(Path(image)),
        "capabilities": metrics["capabilities"],
        "capture_metrics": metrics["metrics"],
    }


def compare_paths(binary: Path, scene: Path, output: Path, tier: str) -> dict:
    comparisons = {}
    pairs = [
        ("baked_vs_instancing_only", ["--baseline-disable-object-culling", "--baseline-disable-instancing"], ["--candidate-disable-object-culling"]),
        ("instancing_only_vs_culling_instancing", ["--baseline-disable-object-culling"], []),
    ]
    for name, baseline_flags, candidate_flags in pairs:
        directory = output / "benchmarks" / tier / name
        directory.mkdir(parents=True, exist_ok=True)
        command = [
            "python3", str(ROOT / "scripts/profile_compare.py"),
            "--baseline", str(scene), "--candidate", str(scene),
            "--route", ROUTE, "--camera", "hero", "--mode", "serial",
            "--duration", "120", "--warmup", "10", "--pairs", "3",
            "--seed", "42", "--resolution", "640x360", "--output", str(directory),
            "--binary", str(binary),
        ]
        flag_map = {
            "--baseline-disable-object-culling": "--baseline-disable-object-culling",
            "--baseline-disable-instancing": "--baseline-disable-instancing",
            "--candidate-disable-object-culling": "--candidate-disable-object-culling",
            "--candidate-disable-instancing": "--candidate-disable-instancing",
        }
        command.extend(flag_map[flag] for flag in baseline_flags + candidate_flags)
        subprocess.run(command, cwd=ROOT, check=True)
        report_path = directory / "comparison.json"
        comparisons[name] = {
            "comparison_file": str(report_path.relative_to(ROOT)),
            "comparison_sha256": sha256(report_path),
            "baseline_flags": baseline_flags,
            "candidate_flags": candidate_flags,
            "paired_deltas": json.loads(report_path.read_text())["comparison"],
        }
    return comparisons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o07/scale-study")
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    scenes, tiers = save_scenes(output)
    report = {
        "workstream": "O07 deterministic scene-scale study",
        "date": "2026-10-18",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal", "os": "macOS"},
        "seed": 42,
        "camera": "hero",
        "route": ROUTE,
        "resolution": [640, 360],
        "timing": {"enabled": args.benchmark, "duration_seconds_per_run": 120, "warmup_seconds": 10, "pairs": 3},
        "method": "Deterministic clearing-derived scenes preserve the source 276 objects, then add mixed shared/unique pines, rocks and grass. Twenty percent of generated placements lie on the perimeter for independent camera/shadow visibility. At each tier compare baked reference, instancing-only, and culling+instancing.",
        "tiers": {},
        "limitations": ["Offscreen serial Metal only; native-window and non-Metal support remain open.", "Object-count tiers stress draw submission and scene storage, but do not model gameplay edits or multi-emitter simulation.", "Generated geometry uses the existing procedural pine, sphere and cone set; no GLB unique-mesh workload is included."],
    }
    for count, scene in scenes.items():
        details = tiers[count]
        directory = output / "captures" / str(count)
        captures = {
            mode: capture_path(binary, scene, directory / f"{mode}.png", mode)
            for mode in ("baked", "instancing_only", "culling_instancing")
        }
        details["scene_sha256"] = sha256(scene)
        details["captures"] = {
            "baked_sha256": captures["baked"]["sha256"],
            "instancing_only_sha256": captures["instancing_only"]["sha256"],
            "culling_instancing_sha256": captures["culling_instancing"]["sha256"],
            "instancing_only_error_vs_baked": image_error(Path(captures["baked"]["image"]), Path(captures["instancing_only"]["image"])),
            "culling_instancing_error_vs_baked": image_error(Path(captures["baked"]["image"]), Path(captures["culling_instancing"]["image"])),
            "culling_instancing_error_vs_instancing_only": image_error(Path(captures["instancing_only"]["image"]), Path(captures["culling_instancing"]["image"])),
        }
        details["metrics"] = {
            mode: {
                "capabilities": capture["capabilities"],
                "capture_metrics": capture["capture_metrics"],
            }
            for mode, capture in captures.items()
        }
        if args.benchmark:
            details["benchmarks"] = compare_paths(binary, scene, output, str(count))
        report["tiers"][str(count)] = details
    report_path = output / "study.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"study": str(report_path), "tiers": list(report["tiers"]), "benchmark": args.benchmark}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
