#!/usr/bin/env python3
"""Compare the native-window optical snapshot and no-copy paths."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess

from optical_factorial_study import ROUTE, variants

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "direct_copy_rgba16"
CANDIDATE = "direct_no_copy_rgba16"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o08/native-no-copy")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--summary-only", action="store_true", help="rebuild summary from existing run JSON without launching benchmarks")
    args = parser.parse_args()
    if not 1 <= args.pairs <= 3:
        parser.error("--pairs must be between 1 and 3")
    args.output.mkdir(parents=True, exist_ok=True)
    scene_dir = args.output / "scenes"
    run_dir = args.output / "runs"
    scene_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    scenes = variants()
    scene_paths: dict[str, Path] = {}
    scene_hashes: dict[str, str] = {}
    for name in (BASELINE, CANDIDATE):
        path = scene_dir / f"{name}.json"
        path.write_text(json.dumps(scenes[name], indent=2) + "\n")
        scene_paths[name] = path
        scene_hashes[name] = sha256(path)

    order = [BASELINE, CANDIDATE, CANDIDATE, BASELINE, BASELINE, CANDIDATE]
    reports: list[dict] = []
    binary_hash = sha256(args.binary)
    source_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    shader_hashes = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in sorted((ROOT / "crates/engine/src/render/shaders").glob("*.wgsl"))
    }
    if args.summary_only:
        for index, variant in enumerate(order[: args.pairs * 2], start=1):
            report = json.loads((run_dir / f"{index:02d}-{variant}.json").read_text())
            report["study_variant"] = variant
            report["study_run"] = index
            reports.append(report)
    else:
        for index, variant in enumerate(order[: args.pairs * 2], start=1):
            output = run_dir / f"{index:02d}-{variant}.json"
            command = [
                str(args.binary), "benchmark-native", "--scene", str(scene_paths[variant]),
                "--seed", "42", "--resolution", "640x360", "--route", ROUTE,
                "--camera", "mixed-close", "--duration", str(args.duration),
                "--warmup", str(args.warmup), "--output", str(output),
            ]
            print(f"[{index}/{min(len(order), args.pairs * 2)}] {variant}: launching native route", flush=True)
            subprocess.run(command, cwd=ROOT, check=True)
            report = json.loads(output.read_text())
            report["study_variant"] = variant
            report["study_run"] = index
            reports.append(report)
            print(f"[{index}/{min(len(order), args.pairs * 2)}] {variant}: {report['actual_measured_seconds']:.1f}s, {report['frames_per_second']:.2f} fps", flush=True)

    def metric(report: dict, key: str) -> float | None:
        value = report.get(key, {}).get("median_ms")
        return value if isinstance(value, (int, float)) else None

    pairs = []
    for pair_index in range(args.pairs):
        first, second = reports[pair_index * 2 : pair_index * 2 + 2]
        by_variant = {first["study_variant"]: first, second["study_variant"]: second}
        if set(by_variant) != {BASELINE, CANDIDATE}:
            raise RuntimeError(f"pair {pair_index + 1} does not contain both variants")
        baseline = by_variant[BASELINE]
        candidate = by_variant[CANDIDATE]
        metrics = [
            "frames_per_second", "cpu_native_frame", "cpu_renderer_encode",
            "cpu_surface_acquire", "cpu_present_encode", "cpu_present_submit", "cpu_ui",
        ]
        pair = {"pair": pair_index + 1, "order": [first["study_variant"], second["study_variant"]], "deltas": {}}
        for name in metrics:
            if name == "frames_per_second":
                b = baseline.get(name)
                c = candidate.get(name)
                pair["deltas"][name] = {"baseline": b, "candidate": c, "candidate_minus_baseline": c - b if isinstance(b, (int, float)) and isinstance(c, (int, float)) else None}
            else:
                b, c = metric(baseline, name), metric(candidate, name)
                bp, cp = baseline.get(name, {}).get("p95_ms"), candidate.get(name, {}).get("p95_ms")
                pair["deltas"][name] = {"baseline_median_ms": b, "candidate_median_ms": c, "candidate_minus_baseline_ms": c - b if b is not None and c is not None else None, "baseline_p95_ms": bp, "candidate_p95_ms": cp, "candidate_minus_baseline_p95_ms": cp - bp if isinstance(bp, (int, float)) and isinstance(cp, (int, float)) else None}
        for stage in ("shadow_maps", "opaque_geometry", "atmosphere_fire", "optical_resolve", "post", "smoke_compute", "native_presenter", "native_inspector"):
            b = metric({"gpu": baseline.get("gpu_stages", {}).get(stage)}, "gpu")
            c = metric({"gpu": candidate.get("gpu_stages", {}).get(stage)}, "gpu")
            bp = baseline.get("gpu_stages", {}).get(stage, {}).get("p95_ms")
            cp = candidate.get("gpu_stages", {}).get(stage, {}).get("p95_ms")
            pair["deltas"][f"gpu_{stage}"] = {"baseline_median_ms": b, "candidate_median_ms": c, "candidate_minus_baseline_ms": c - b if b is not None and c is not None else None, "baseline_p95_ms": bp, "candidate_p95_ms": cp, "candidate_minus_baseline_p95_ms": cp - bp if isinstance(bp, (int, float)) and isinstance(cp, (int, float)) else None}
        pairs.append(pair)

    summary = {
        "version": 1,
        "study": "native-window optical no-copy vs snapshot copy",
        "route": ROUTE,
        "camera": "mixed-close",
        "seed": 42,
        "resolution": [640, 360],
        "duration_seconds": args.duration,
        "warmup_seconds": args.warmup,
        "binary": str(args.binary.resolve()),
        "binary_sha256": binary_hash,
        "source_revision": source_revision,
        "shader_sha256": shader_hashes,
        "scene_sha256": scene_hashes,
        "scene_options": {name: {"compact_hdr": scenes[name]["render"]["compact_hdr"], "optical_no_copy": scenes[name]["render"]["optical_no_copy"], "optical_surface_reuse": scenes[name]["render"]["experiments"].get("optical_surface_reuse", False)} for name in scene_paths},
        "pairs": pairs,
        "runs": [{
            "run": report["study_run"], "variant": report["study_variant"],
            "report": str((run_dir / f"{report['study_run']:02d}-{report['study_variant']}.json").resolve()),
            "actual_measured_seconds": report.get("actual_measured_seconds"),
            "frames_per_second": report.get("frames_per_second"),
            "cpu": {key: report.get(key) for key in ("cpu_native_frame", "cpu_renderer_encode", "cpu_surface_acquire", "cpu_present_encode", "cpu_present_submit", "cpu_ui")},
            "gpu_stages": report.get("gpu_stages"),
            "timing_coverage": report.get("timing_coverage"),
        } for report in reports],
        "adapter": {key: reports[0].get("capabilities", {}).get(key) for key in ("name", "backend", "device_type", "resolution", "gpu_timestamps")},
        "resource_inventory_by_variant": {
            variant: {
                key: reports[next(i for i, report in enumerate(reports) if report["study_variant"] == variant)]["capabilities"]["resource_inventory"].get(key)
                for key in ("known_gpu_allocation_bytes", "render_targets_bytes", "optical_snapshot_bytes", "optical_output_bytes", "optical_mask_bytes", "estimate_kind")
            }
            for variant in (BASELINE, CANDIDATE)
        },
        "median_pair_deltas": {},
        "raw_reports": [str((run_dir / f"{i:02d}-{report['study_variant']}.json").resolve()) for i, report in enumerate(reports, start=1)],
        "limitations": ["Native results include window surface acquisition and presentation; CPU spans overlap and are not additive.", "One host, adapter and display configuration; no target-adapter fallback or Windows/DX12 acceptance."],
    }
    keys = pairs[0]["deltas"].keys() if pairs else []
    for key in keys:
        values = [pair["deltas"][key].get("candidate_minus_baseline_ms", pair["deltas"][key].get("candidate_minus_baseline")) for pair in pairs]
        values = [value for value in values if isinstance(value, (int, float))]
        if values:
            summary["median_pair_deltas"][key] = statistics.median(values)
    summary_path = args.output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Saved native comparison to {summary_path}")


if __name__ == "__main__":
    run()
