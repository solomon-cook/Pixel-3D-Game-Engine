#!/usr/bin/env python3
"""Compare direct and cached smoke-candidate generation in native playback."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_SCENE = ROOT / "assets/scenes/two-emitter-review.json"
CANDIDATE_SCENE = ROOT / "assets/scenes/smoke-candidate-review.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_metric(run: dict, key: str, nested: tuple[str, ...] = ()) -> float | None:
    value = run
    for part in nested:
        value = value.get(part, {}) if isinstance(value, dict) else {}
    value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, (int, float)) else None


def timing_coverage(run: dict) -> dict:
    coverage = run.get("timing_coverage", {})
    rendered = coverage.get("rendered_frames", 0)
    timed = coverage.get("timed_render_frames", 0)
    if not coverage.get("gpu_timestamps_supported") or not rendered or timed / rendered < 0.99:
        raise RuntimeError(f"native GPU timing coverage below 99%: {timed}/{rendered}")
    return coverage


def validate_scene_pair() -> tuple[dict, dict]:
    baseline = json.loads(BASELINE_SCENE.read_text())
    candidate = json.loads(CANDIDATE_SCENE.read_text())
    baseline_enabled = baseline.get("render", {}).get("experiments", {}).get("smoke_candidate_cache", False)
    candidate_enabled = candidate.get("render", {}).get("experiments", {}).get("smoke_candidate_cache", False)
    if baseline_enabled is not False or candidate_enabled is not True:
        raise RuntimeError("study scenes do not select the intended direct/cached variants")
    baseline["render"]["experiments"]["smoke_candidate_cache"] = True
    if baseline != candidate:
        raise RuntimeError("study scenes differ beyond render.experiments.smoke_candidate_cache")
    return baseline, candidate


def capture_fixed_tick(binary: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    captures = {}
    for variant, scene in (("direct", BASELINE_SCENE), ("cached", CANDIDATE_SCENE)):
        image = output / f"{variant}.png"
        subprocess.run([
            str(binary), "capture", "--scene", str(scene), "--camera", "hero",
            "--seed", "42", "--tick", "300", "--resolution", "640x360",
            "--scale", "1", "--output", str(image),
        ], cwd=ROOT, check=True, capture_output=True, text=True)
        metadata = json.loads(image.with_suffix(".json").read_text())
        metrics = metadata["metrics"]
        captures[variant] = {
            "scene": str(scene.relative_to(ROOT)),
            "scene_sha256": sha256(scene),
            "image": str(image.relative_to(ROOT)),
            "image_sha256": sha256(image),
            "tick": metadata["tick"],
            "smoke_candidate_cache_enabled": metrics["smoke_candidate_cache_enabled"],
            "smoke_candidate_cache_builds": metrics["smoke_candidate_cache_builds"],
            "smoke_candidate_cache_skips": metrics["smoke_candidate_cache_skips"],
            "tile_candidates": metrics["tile_candidates"],
            "tile_overflow_tiles": metrics["tile_overflow_tiles"],
            "tile_max_occupancy": metrics["tile_max_occupancy"],
            "fire_primitives_rendered": metrics["fire_primitives_rendered"],
        }
    direct, cached = captures["direct"], captures["cached"]
    result = {
        "camera": "hero",
        "tick": 300,
        "resolution": [640, 360],
        "pixel_identical": direct["image_sha256"] == cached["image_sha256"],
        "same_tile_metrics": all(
            direct[key] == cached[key]
            for key in ("tile_candidates", "tile_overflow_tiles", "tile_max_occupancy")
        ),
        "direct": direct,
        "cached": cached,
    }
    if direct["smoke_candidate_cache_enabled"] is not False or cached["smoke_candidate_cache_enabled"] is not True:
        raise RuntimeError("fixed-tick capture did not activate the intended cache states")
    if not result["pixel_identical"] or not result["same_tile_metrics"]:
        raise RuntimeError("direct/cached fixed-tick output or tile metrics differ")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o03/smoke-candidate-native-current-build")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o03-smoke-candidate-native-current-build.json")
    parser.add_argument("--resume", action="store_true", help="reuse existing raw native runs in output")
    args = parser.parse_args()
    binary, output, report_path = (p.resolve() for p in (args.binary, args.output, args.report))
    if not binary.is_file() or args.pairs < 1 or args.duration <= 0 or args.warmup < 0:
        parser.error("binary must exist; pairs/duration must be positive; warmup cannot be negative")
    validate_scene_pair()
    output.mkdir(parents=True, exist_ok=True)

    scene_paths = {"direct": BASELINE_SCENE, "cached": CANDIDATE_SCENE}
    pairs = []
    for pair in range(1, args.pairs + 1):
        order = ("direct", "cached") if pair % 2 else ("cached", "direct")
        runs = {}
        for variant in order:
            report = output / f"pair-{pair:02d}-{variant}.engine.json"
            command = [
                str(binary), "benchmark-native", "--scene", str(scene_paths[variant]),
                "--camera", "hero", "--seed", "42", "--resolution", "640x360",
                "--route", "clearing-orbit", "--duration", str(args.duration),
                "--warmup", str(args.warmup), "--output", str(report),
            ]
            if not (args.resume and report.is_file()):
                with (output / f"pair-{pair:02d}-{variant}.log").open("w") as log:
                    subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            run = json.loads(report.read_text())
            route = run.get("route", {})
            if route.get("id") != "clearing-orbit" or run.get("route_seconds") != args.duration:
                raise RuntimeError(f"{variant} run does not match the requested route duration")
            if run.get("capabilities", {}).get("resolution") != [640, 360]:
                raise RuntimeError(f"{variant} run did not retain 640x360")
            if run.get("tile_lists_enabled") is not True or run.get("fire_bounds_precompute") is not False:
                raise RuntimeError(f"{variant} run changed the surrounding O03 tile-list settings")
            coverage = timing_coverage(run)
            runs[variant] = (run, coverage)

        direct, direct_coverage = runs["direct"]
        cached, cached_coverage = runs["cached"]
        pairs.append({
            "pair": pair,
            "order": list(order),
            "deltas_cached_minus_direct": {
                "frames_per_second": run_metric(cached, "frames_per_second") - run_metric(direct, "frames_per_second"),
                "cpu_native_frame_ms": run_metric(cached, "median_ms", ("cpu_native_frame",)) - run_metric(direct, "median_ms", ("cpu_native_frame",)),
                "gpu_atmosphere_fire_ms": run_metric(cached, "median_ms", ("gpu_stages", "atmosphere_fire")) - run_metric(direct, "median_ms", ("gpu_stages", "atmosphere_fire")),
            },
            "direct": {
                "frames_per_second": direct["frames_per_second"],
                "cpu_native_frame": direct["cpu_native_frame"],
                "gpu_atmosphere_fire": direct.get("gpu_stages", {}).get("atmosphere_fire", {}),
                "timing_coverage": direct_coverage,
                "report": f"pair-{pair:02d}-direct.engine.json",
                "report_sha256": sha256(output / f"pair-{pair:02d}-direct.engine.json"),
            },
            "cached": {
                "frames_per_second": cached["frames_per_second"],
                "cpu_native_frame": cached["cpu_native_frame"],
                "gpu_atmosphere_fire": cached.get("gpu_stages", {}).get("atmosphere_fire", {}),
                "timing_coverage": cached_coverage,
                "report": f"pair-{pair:02d}-cached.engine.json",
                "report_sha256": sha256(output / f"pair-{pair:02d}-cached.engine.json"),
            },
        })
        print(json.dumps({"pair": pair, "order": order, "deltas": pairs[-1]["deltas_cached_minus_direct"]}))

    metric_keys = ("frames_per_second", "cpu_native_frame_ms", "gpu_atmosphere_fire_ms")
    paired = {
        key: statistics.median(pair["deltas_cached_minus_direct"][key] for pair in pairs)
        for key in metric_keys
    }
    baseline_scene, candidate_scene = scene_paths["direct"], scene_paths["cached"]
    fixed_tick = capture_fixed_tick(binary, output / "fixed-tick-review")
    report = {
        "version": 1,
        "date": "2026-10-19",
        "study": "O03 native-window smoke-candidate cache current-build comparison",
        "host": {
            "device": runs["direct"][0].get("capabilities", {}).get("name"),
            "backend": runs["direct"][0].get("capabilities", {}).get("backend"),
            "os": platform.platform(),
            "native_window": True,
        },
        "scenes": {
            "direct": {"path": str(baseline_scene.relative_to(ROOT)), "sha256": sha256(baseline_scene), "smoke_candidate_cache": False},
            "cached": {"path": str(candidate_scene.relative_to(ROOT)), "sha256": sha256(candidate_scene), "smoke_candidate_cache": True},
            "difference": "render.experiments.smoke_candidate_cache only",
        },
        "camera": "hero",
        "route": "clearing-orbit",
        "seed": 42,
        "resolution": [640, 360],
        "duration_seconds_per_run": args.duration,
        "warmup_seconds": args.warmup,
        "git_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE).stdout.strip(),
        "binary_sha256": sha256(binary),
        "runner_sha256": sha256(Path(__file__)),
        "pairs": pairs,
        "paired_medians_cached_minus_direct": paired,
        "current_release_fixed_tick_parity": fixed_tick,
        "limitations": [
            "Native-window results include surface acquisition, inspector, submission and vsync.",
            "GPU timings are stage-local and do not prove a whole-window throughput gain.",
            "The fixed-tick correctness matrix is reported separately; this run measures sustained native performance only.",
            "This host does not qualify Windows/DX12 or other adapters.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "pairs": len(pairs), "paired_medians": paired}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
