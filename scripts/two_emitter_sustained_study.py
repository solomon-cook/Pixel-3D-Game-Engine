#!/usr/bin/env python3
"""Measure tiled versus exhaustive rendering on a two-emitter scene and route."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/scenes/two-emitter-overflow-stress.json"
SOURCE_PATHS = (
    "crates/engine/src/render/mod.rs",
    "crates/engine/src/render/shaders/tile_build.wgsl",
    "crates/engine/src/render/shaders/volume.wgsl",
    "scripts/two_emitter_sustained_study.py",
)
METRICS = (
    ("gpu_render", "median_ms"),
    ("frame_work", "median_ms"),
    ("gpu_stages.atmosphere_fire", "median_ms"),
    ("gpu_stages.tile_list_build", "median_ms"),
    ("cpu_tile_list_encode", "median_ms"),
    ("simulation_cpu", "median_ms"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def path_reference(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def nested(report: dict, path: str):
    value = report
    for key in path.split("."):
        value = value.get(key, {}) if isinstance(value, dict) else {}
    return value


def summarize(report: dict) -> dict:
    return {
        "gpu_render": report.get("gpu_render"),
        "frame_work": report.get("frame_work"),
        "gpu_stages": report.get("gpu_stages"),
        "cpu_tile_list_encode": report.get("cpu_tile_list_encode"),
        "simulation_cpu": report.get("simulation_cpu"),
        "tile_lists": report.get("tile_lists"),
        "workload_counts": report.get("workload_counts"),
        "timing_coverage": report.get("timing_coverage"),
        "route_seconds": report.get("route_seconds"),
        "wall_seconds": report.get("wall_seconds"),
    }


def record_pair(pair_index: int, order: list[str], runs: dict, output: Path) -> dict:
    deltas = {}
    for path, metric in METRICS:
        tiled_value = nested(runs["tiled"], path).get(metric)
        exhaustive_value = nested(runs["exhaustive"], path).get(metric)
        deltas[f"exhaustive_minus_tiled.{path}.{metric}"] = (
            exhaustive_value - tiled_value
            if isinstance(tiled_value, (int, float)) and isinstance(exhaustive_value, (int, float))
            else None
        )
    return {
        "pair": pair_index,
        "order": order,
        "deltas": deltas,
        "tiled": summarize(runs["tiled"]),
        "exhaustive": summarize(runs["exhaustive"]),
        "reports": {
            name: {
                "path": path_reference(output / f"pair-{pair_index:02d}-{name}.json"),
                "sha256": sha256(output / f"pair-{pair_index:02d}-{name}.json"),
            }
            for name in ("tiled", "exhaustive")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--scene", type=Path, default=SCENE)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--camera", default="stress-close")
    parser.add_argument("--route", default="clearing-orbit")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/two-emitter-sustained")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-multi-emitter-sustained.json")
    parser.add_argument("--summarize-existing", action="store_true", help="rebuild the report from existing pair reports")
    args = parser.parse_args()
    if args.pairs < 3 or args.duration <= 0 or args.warmup < 0:
        parser.error("at least three pairs, positive duration, and nonnegative warmup are required")

    binary, scene = args.binary.resolve(), args.scene.resolve()
    output, report_path = args.output.resolve(), args.report.resolve()
    scene_data = json.loads(scene.read_text())
    if len(scene_data.get("emitters", [])) != 2:
        parser.error("selected scene must contain exactly two emitters")
    if not any(item.get("id") == args.camera for item in scene_data.get("cameras", [])):
        parser.error(f"selected scene has no camera {args.camera}")
    if not any(item.get("id") == args.route for item in scene_data.get("routes", [])):
        parser.error(f"selected scene has no route {args.route}")
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)
    pairs = []
    if args.summarize_existing:
        for pair_index in range(1, args.pairs + 1):
            order = ["tiled", "exhaustive"] if pair_index % 2 else ["exhaustive", "tiled"]
            runs = {
                variant: json.loads((output / f"pair-{pair_index:02d}-{variant}.json").read_text())
                for variant in ("tiled", "exhaustive")
            }
            for variant, run in runs.items():
                if run.get("tile_lists", {}).get("enabled") != (variant == "tiled"):
                    raise RuntimeError(f"existing {variant} report has unexpected tile-list state")
                if not run.get("timing_coverage", {}).get("gpu_timestamps_supported"):
                    raise RuntimeError("existing report lacks GPU timestamp coverage")
                if run.get("workload_counts", {}).get("emitters") != 2:
                    raise RuntimeError("existing report does not describe a two-emitter run")
            pairs.append(record_pair(pair_index, order, runs, output))
    else:
        subprocess.run([str(binary), "validate", str(scene)], cwd=ROOT, check=True, capture_output=True)
    for pair_index in range(1, args.pairs + 1) if not args.summarize_existing else ():
        order = ["tiled", "exhaustive"] if pair_index % 2 else ["exhaustive", "tiled"]
        runs = {}
        for variant in order:
            report_file = output / f"pair-{pair_index:02d}-{variant}.json"
            log_file = output / f"pair-{pair_index:02d}-{variant}.log"
            command = [
                str(binary), "benchmark", "--scene", str(scene), "--seed", "42",
                "--camera", args.camera, "--route", args.route,
                "--duration", str(args.duration), "--warmup", str(args.warmup),
                "--resolution", "640x360", "--mode", "serial", "--output", str(report_file),
            ]
            if variant == "exhaustive":
                command.append("--disable-tile-lists")
            with log_file.open("w") as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            run = json.loads(report_file.read_text())
            expected_enabled = variant == "tiled"
            if run.get("tile_lists", {}).get("enabled") != expected_enabled:
                raise RuntimeError(f"{variant} run reported unexpected tile-list state")
            if not run.get("timing_coverage", {}).get("gpu_timestamps_supported"):
                raise RuntimeError("GPU timestamps are unavailable; cannot compare this route")
            if run.get("workload_counts", {}).get("emitters") != 2:
                raise RuntimeError("benchmark did not report both emitters")
            runs[variant] = run

        pair = record_pair(pair_index, order, runs, output)
        pairs.append(pair)
        print(json.dumps({"pair": pair_index, "order": order, "deltas": pair["deltas"]}), flush=True)

    summary = {}
    for mode in ("tiled", "exhaustive"):
        summary[mode] = {}
        for path, metric in METRICS:
            values = [nested(pair[mode], path).get(metric) for pair in pairs]
            values = [value for value in values if isinstance(value, (int, float))]
            summary[mode][f"{path}.{metric}"] = {
                "median_of_pair_medians": statistics.median(values) if values else None,
                "pair_values": values,
            }
    paired_delta_keys = list(pairs[0]["deltas"])
    paired_delta_summary = {
        key: {
            "median": statistics.median(pair["deltas"][key] for pair in pairs),
            "pair_values": [pair["deltas"][key] for pair in pairs],
        }
        for key in paired_delta_keys
    }
    frame_work_delta_key = "exhaustive_minus_tiled.frame_work.median_ms"
    gpu_delta_key = "exhaustive_minus_tiled.gpu_render.median_ms"
    tile_delta_key = "exhaustive_minus_tiled.gpu_stages.tile_list_build.median_ms"
    atmosphere_delta_key = "exhaustive_minus_tiled.gpu_stages.atmosphere_fire.median_ms"
    frame_work_deltas = [pair["deltas"][frame_work_delta_key] for pair in pairs]
    first = json.loads((output / "pair-01-tiled.json").read_text())
    parity = {}
    for variant in ("tiled", "exhaustive"):
        path = output / f"capture-{variant}.png"
        command = [str(binary), "capture", "--scene", str(scene), "--seed", "42",
                   "--camera", args.camera, "--tick", "300", "--resolution", "640x360",
                   "--scale", "1", "--output", str(path),]
        if variant == "exhaustive": command.append("--disable-tile-lists")
        subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        parity[variant] = {"image": path_reference(path), "sha256": sha256(path)}
    parity["images_match"] = parity["tiled"]["sha256"] == parity["exhaustive"]["sha256"]
    report = {
        "version": 1,
        "date": "2026-10-18",
        "workstream": "two-emitter tiled versus exhaustive sustained rendering",
        "host": {
            "gpu": first["capabilities"].get("name"),
            "backend": first["capabilities"].get("backend"),
            "os": platform.platform(),
            "native_window": False,
        },
        "scene": path_reference(scene),
        "scene_sha256": sha256(scene),
        "binary_sha256": sha256(binary),
        "source_sha256": {path: sha256(ROOT / path) for path in SOURCE_PATHS},
        "route": args.route,
        "seed": 42,
        "camera_start": args.camera,
        "resolution": [640, 360],
        "budgets": {
            "emitters": first["workload_counts"].get("emitters"),
            "authored_point_lights": sum(light.get("kind") == "point" for light in json.loads(scene.read_text()).get("lights", [])),
            "derived_particle_lights": first["capabilities"].get("max_particle_lights"),
            "tile_list_capacity_bytes": first["tile_lists"].get("capacity_bytes"),
        },
        "mode": "serial",
        "duration_seconds_per_run": args.duration,
        "warmup_seconds_per_run": args.warmup,
        "pairs": pairs,
        "fixed_tick_capture_parity": parity,
        "summary": summary,
        "paired_delta_summary": paired_delta_summary,
        "interpretation": {
            "frame_work_improved_in_every_pair": all(value > 0 for value in frame_work_deltas),
            "median_frame_work_saved_ms": statistics.median(frame_work_deltas),
            "median_reported_gpu_render_delta_exhaustive_minus_tiled_ms": paired_delta_summary[gpu_delta_key]["median"],
            "median_tile_list_build_delta_exhaustive_minus_tiled_ms": paired_delta_summary[tile_delta_key]["median"],
            "median_atmosphere_fire_delta_exhaustive_minus_tiled_ms": paired_delta_summary[atmosphere_delta_key]["median"],
            "note": "The serial offscreen frame-work measure favors tiled in all three pairs. The reported GPU-render metric adds pass intervals that can overlap; tile build is higher and atmosphere/fire is lower. Keep this as workload-specific evidence, not a universal renderer win.",
        },
        "aggregation_policy": first.get("aggregation_policy"),
        "scope": "Offscreen M1 Max/Metal workload comparison. This report includes same-scene tick-300 tiled/exhaustive image hashes in addition to performance pairs.",
        "limitations": [
            "No native-window presentation, DX12, other-adapter, or continuous human playback evidence.",
            "Route timing does not establish behavior for other authored multi-emitter scenes or workloads.",
            "GPU stage intervals can overlap; do not sum stage distributions into a total.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "pairs": len(pairs), "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
