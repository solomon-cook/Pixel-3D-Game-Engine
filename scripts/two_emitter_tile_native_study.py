#!/usr/bin/env python3
"""Compare native tiled/exhaustive rendering on the two-emitter stress route."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENE = ROOT / "assets/scenes/two-emitter-overflow-stress.json"
SOURCES = [
    "crates/engine-lab/src/main.rs", "crates/engine-lab/src/window.rs",
    "crates/engine/src/render/mod.rs", "crates/engine/src/render/shaders/tile_build.wgsl",
    "crates/engine/src/render/shaders/fire.wgsl", "crates/engine/src/render/shaders/volume.wgsl",
    "crates/engine/src/render/shaders/world.wgsl", "crates/engine/src/render/shaders/common.wgsl",
    "scripts/two_emitter_tile_native_study.py",
]

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def metric(run: dict, section: str, key: str) -> float | None:
    value = run
    for part in section.split("."):
        value = value.get(part, {}) if isinstance(value, dict) else {}
    result = value.get(key) if isinstance(value, dict) else None
    return result if isinstance(result, (int, float)) else None

def delta(after: float | None, before: float | None) -> float | None:
    return after - before if after is not None and before is not None else None

def summarise(run: dict) -> dict:
    return {"frames_per_second": run["frames_per_second"],
            "cpu_native_frame": run.get("cpu_native_frame"),
            "gpu_stages": run.get("gpu_stages"),
            "timing_coverage": run.get("timing_coverage"),
            "workload_counts": run.get("workload_counts"),
            "report_sha256": run["report_sha256"]}

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    ap.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    ap.add_argument("--camera", default="dual-wide")
    ap.add_argument("--route", default="clearing-orbit")
    ap.add_argument("--pairs", type=int, default=3)
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--warmup", type=float, default=10.0)
    ap.add_argument("--output", type=Path, default=ROOT / "artifacts/multi-emitter/tile-native")
    ap.add_argument("--report", type=Path, default=ROOT / "docs/measurements-multi-emitter-tile-native.json")
    args = ap.parse_args()
    if args.pairs < 3 or args.duration <= 0 or args.warmup < 0:
        ap.error("at least three pairs, positive duration, and nonnegative warmup are required")
    binary, scene = args.binary.resolve(), args.scene.resolve()
    output, report_path = args.output.resolve(), args.report.resolve()
    if not binary.is_file(): subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    source = json.loads(scene.read_text())
    if len(source.get("emitters", [])) != 2: ap.error("scene must contain exactly two emitters")
    if not any(x.get("id") == args.route for x in source.get("routes", [])): ap.error("scene has no selected route")
    if not any(x.get("id") == args.camera for x in source.get("cameras", [])): ap.error("scene has no selected camera")
    output.mkdir(parents=True, exist_ok=True); report_path.parent.mkdir(parents=True, exist_ok=True)
    pairs = []
    for i in range(1, args.pairs + 1):
        order = ["tiled", "exhaustive"] if i % 2 else ["exhaustive", "tiled"]
        runs = {}
        for name in order:
            path = output / f"pair-{i:02d}-{name}.engine.json"
            cmd = [str(binary), "benchmark-native", "--scene", str(scene), "--seed", "42",
                   "--camera", args.camera, "--route", args.route, "--duration", str(args.duration),
                   "--warmup", str(args.warmup), "--output", str(path)]
            if name == "exhaustive": cmd.append("--disable-tile-lists")
            with (output / f"pair-{i:02d}-{name}.log").open("w") as log:
                subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            data = json.loads(path.read_text())
            data["report_sha256"] = sha(path)
            if data.get("tile_lists_enabled") != (name == "tiled"): raise RuntimeError(f"unexpected tile mode in {name} report")
            if data.get("workload_counts", {}).get("emitters") != 2: raise RuntimeError(f"{name} report did not run two emitters")
            if not data.get("timing_coverage", {}).get("gpu_timestamps_supported"): raise RuntimeError("native GPU timestamps unavailable")
            runs[name] = data
        tiled, exhaustive = runs["tiled"], runs["exhaustive"]
        pairs.append({"pair": i, "order": order,
            "exhaustive_minus_tiled": {
                "frames_per_second": exhaustive["frames_per_second"] - tiled["frames_per_second"],
                "cpu_native_frame_ms": delta(metric(exhaustive, "cpu_native_frame", "median_ms"), metric(tiled, "cpu_native_frame", "median_ms")),
                "gpu_atmosphere_fire_ms": delta(metric(exhaustive, "gpu_stages.atmosphere_fire", "median_ms"), metric(tiled, "gpu_stages.atmosphere_fire", "median_ms")),
            },
            "tiled": summarise(tiled), "exhaustive": summarise(exhaustive)})
        print(json.dumps({"pair": i, "deltas": pairs[-1]["exhaustive_minus_tiled"]}), flush=True)
    deltas = [p["exhaustive_minus_tiled"] for p in pairs]
    first_path = output / f"pair-01-{pairs[0]['order'][0]}.engine.json"
    first = json.loads(first_path.read_text())
    report = {
        "version": 1, "date": "2026-10-18", "workstream": "O03 native-window tiled versus exhaustive on two-emitter maximum-budget route",
        "host": {"gpu": first["capabilities"].get("name"), "backend": first["capabilities"].get("backend"), "os": platform.platform(), "native_window": True},
        "scene": str(scene.relative_to(ROOT)) if scene.is_relative_to(ROOT) else str(scene), "scene_sha256": sha(scene),
        "emitters": sorted(e["id"] for e in source["emitters"]), "camera": args.camera, "route": args.route,
        "seed": 42, "resolution": first["capabilities"].get("resolution"), "duration_seconds_per_run": args.duration, "warmup_seconds": args.warmup,
        "source_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "binary_sha256": sha(binary), "source_sha256": {x: sha(ROOT / x) for x in SOURCES}, "pairs": pairs,
        "paired_medians_exhaustive_minus_tiled": {key: statistics.median(p[key] for p in deltas) for key in deltas[0]},
        "limitations": ["Native M1 Max/Metal window/display configuration only; no Windows/DX12 or other-adapter acceptance.", "Native timing includes surface acquisition, UI, submission and vsync; overlapping CPU spans and GPU intervals must not be summed.", "Timing is not image-parity evidence; fixed-tick parity is separately recorded in measurements-multi-emitter-native.json."]}
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "pairs": len(pairs), "paired_medians": report["paired_medians_exhaustive_minus_tiled"]}, indent=2))
    return 0
if __name__ == "__main__": raise SystemExit(main())
