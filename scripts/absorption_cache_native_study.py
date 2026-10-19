#!/usr/bin/env python3
"""Measure direct versus 16-cubed smoke absorption cache in a native window."""
from __future__ import annotations

import argparse
import copy
from datetime import date
import hashlib
import json
import platform
import statistics
import subprocess
from pathlib import Path

from absorption_cache_study import ROOT, SOURCE, sha256, git_source_state, make_scenes

CAMERA = "absorption-study"
ROUTE = "absorption-cache-orbit"


def metric(run: dict, key: str, nested: tuple[str, ...] = ()) -> float:
    value = run
    for part in nested:
        value = value.get(part, {}) if isinstance(value, dict) else {}
    value = value.get(key) if isinstance(value, dict) else None
    if not isinstance(value, (int, float)):
        raise RuntimeError(f"native benchmark is missing {'.'.join((*nested, key))}")
    return float(value)


def checked_coverage(run: dict) -> dict:
    coverage = run.get("timing_coverage", {})
    rendered = coverage.get("rendered_frames", 0)
    timed = coverage.get("timed_render_frames", 0)
    if not coverage.get("gpu_timestamps_supported") or not rendered or timed / rendered < 0.99:
        raise RuntimeError(f"native GPU timing coverage below 99%: {timed}/{rendered}")
    return coverage


def make_native_scenes(out: Path) -> dict[str, Path]:
    generated = make_scenes(out / "generated", json.loads(SOURCE.read_text()))
    medium = generated["medium"]["direct"]
    baseline = json.loads(medium.read_text())
    baseline["render"]["absorption_cache_resolution"] = 16
    candidate = copy.deepcopy(baseline)
    baseline["render"]["experiments"]["smoke_absorption_cache"] = False
    candidate["render"]["experiments"]["smoke_absorption_cache"] = True
    comparison = copy.deepcopy(baseline)
    comparison["render"]["experiments"]["smoke_absorption_cache"] = True
    if comparison != candidate:
        raise RuntimeError("native scenes differ beyond the absorption-cache enable flag")
    paths = {"direct": out / "scenes/direct-16.json", "cached": out / "scenes/cache16.json"}
    for key, scene in (("direct", baseline), ("cached", candidate)):
        paths[key].parent.mkdir(parents=True, exist_ok=True)
        paths[key].write_text(json.dumps(scene, indent=2) + "\n")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o05/native-current-release")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o05-native-current-release.json")
    parser.add_argument("--resume", action="store_true", help="reuse existing raw native runs")
    args = parser.parse_args()
    binary, output, report_path = (p.resolve() for p in (args.binary, args.output, args.report))
    if not binary.is_file() or args.pairs < 1 or args.duration <= 0 or args.warmup < 0:
        parser.error("binary must exist; pairs/duration must be positive; warmup cannot be negative")
    output.mkdir(parents=True, exist_ok=True)
    scenes = make_native_scenes(output)
    binary_hash = sha256(binary)
    pairs = []
    for pair in range(1, args.pairs + 1):
        order = ("direct", "cached") if pair % 2 else ("cached", "direct")
        runs = {}
        for variant in order:
            raw = output / f"pair-{pair:02d}-{variant}.engine.json"
            command = [
                str(binary), "benchmark-native", "--scene", str(scenes[variant]),
                "--camera", CAMERA, "--seed", "42", "--resolution", "640x360",
                "--route", ROUTE, "--duration", str(args.duration), "--warmup", str(args.warmup),
                "--output", str(raw),
            ]
            if not (args.resume and raw.is_file()):
                with (output / f"pair-{pair:02d}-{variant}.log").open("w") as log:
                    subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            run = json.loads(raw.read_text())
            if sha256(binary) != binary_hash:
                raise RuntimeError("benchmark binary changed during the native study")
            if run.get("route", {}).get("id") != ROUTE or run.get("route_seconds") != args.duration:
                raise RuntimeError(f"{variant} run does not match the requested route/duration")
            if run.get("capabilities", {}).get("resolution") != [640, 360]:
                raise RuntimeError(f"{variant} run changed the selected 640x360 pixel grid")
            cache_bytes = run.get("capabilities", {}).get("resource_inventory", {}).get("smoke_absorption_cache_bytes")
            if not isinstance(cache_bytes, int) or (variant == "cached" and cache_bytes <= 0) or (variant == "direct" and cache_bytes != 0):
                raise RuntimeError(f"{variant} run did not select the intended cache mode: {cache_bytes}")
            coverage = checked_coverage(run)
            runs[variant] = (run, coverage)
        direct, direct_cov = runs["direct"]
        cached, cached_cov = runs["cached"]
        deltas = {
            "frames_per_second": metric(cached, "frames_per_second") - metric(direct, "frames_per_second"),
            "cpu_native_frame_ms": metric(cached, "median_ms", ("cpu_native_frame",)) - metric(direct, "median_ms", ("cpu_native_frame",)),
            "gpu_atmosphere_fire_ms": metric(cached, "median_ms", ("gpu_stages", "atmosphere_fire")) - metric(direct, "median_ms", ("gpu_stages", "atmosphere_fire")),
        }
        pairs.append({
            "pair": pair, "order": list(order), "deltas_cached_minus_direct": deltas,
            "direct": {"frames_per_second": direct["frames_per_second"], "cpu_native_frame": direct["cpu_native_frame"], "gpu_atmosphere_fire": direct["gpu_stages"]["atmosphere_fire"], "timing_coverage": direct_cov, "report": raw_name(output, pair, "direct"), "report_sha256": sha256(output / raw_name(output, pair, "direct"))},
            "cached": {"frames_per_second": cached["frames_per_second"], "cpu_native_frame": cached["cpu_native_frame"], "gpu_atmosphere_fire": cached["gpu_stages"]["atmosphere_fire"], "timing_coverage": cached_cov, "report": raw_name(output, pair, "cached"), "report_sha256": sha256(output / raw_name(output, pair, "cached"))},
        })
        print(json.dumps({"pair": pair, "order": order, "deltas": deltas}), flush=True)

    medians = {
        key: statistics.median(pair["deltas_cached_minus_direct"][key] for pair in pairs)
        for key in ("frames_per_second", "cpu_native_frame_ms", "gpu_atmosphere_fire_ms")
    }
    report = {
        "version": 1,
        "date": date.today().isoformat(),
        "study": "O05 native-window direct versus 16-cubed absorption cache current release",
        "host": {"device": runs["direct"][0].get("capabilities", {}).get("name"), "backend": runs["direct"][0].get("capabilities", {}).get("backend"), "os": platform.platform(), "native_window": True},
        "scenes": {key: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path), "cache_enabled": key == "cached", "cache_resolution": 16} for key, path in scenes.items()},
        "scene_difference": "render.experiments.smoke_absorption_cache only; both variants select cache resolution 16",
        "camera": CAMERA, "route": ROUTE, "seed": 42, "resolution": [640, 360],
        "duration_seconds_per_run": args.duration, "warmup_seconds": args.warmup,
        "source_state": git_source_state(), "binary_path": str(binary), "binary_sha256": binary_hash,
        "runner_sha256": sha256(Path(__file__).resolve()), "pairs": pairs,
        "paired_medians_cached_minus_direct": medians,
        "limitations": [
            "Native-window results include surface acquisition, UI, submit and vsync; GPU stage timing remains stage-local.",
            "This study measures medium-smoke coverage only; the paired offscreen three-scale study remains the scale matrix.",
            "The tested M1 Max/Metal host does not qualify Windows/DX12 or another adapter.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "pairs": len(pairs), "paired_medians_cached_minus_direct": medians}), flush=True)
    return 0


def raw_name(output: Path, pair: int, variant: str) -> str:
    return f"pair-{pair:02d}-{variant}.engine.json"


if __name__ == "__main__":
    raise SystemExit(main())
