#!/usr/bin/env python3
"""Measure uninstrumented soft-volume rendering on a sustained moving route."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(path: Path) -> str:
    files = sorted(child for child in path.rglob("*") if child.is_file())
    digest = hashlib.sha256()
    for child in files:
        digest.update(str(child.relative_to(ROOT)).encode())
        digest.update(bytes.fromhex(sha256(child)))
    return digest.hexdigest()


def pixel_sha256(path: Path) -> str:
    with Image.open(path) as image:
        return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, default=Path("assets/scenes/profiling-heavy.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/o01-soft-volume-route"))
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--route", default="clearing-orbit")
    parser.add_argument("--report", type=Path, default=Path("docs/measurements-o01-soft-volume-route.json"))
    parser.add_argument("--reuse-existing", action="store_true", help="rebuild the summary from existing paired-runs outputs")
    parser.add_argument("--candidate-disable-tile-lists", action="store_true", help="compare the tiled baseline with exhaustive candidate evaluation")
    args = parser.parse_args()
    scene = (ROOT / args.scene).resolve() if not args.scene.is_absolute() else args.scene
    output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
    source_scene = json.loads(scene.read_text())
    for emitter in source_scene["emitters"]:
        emitter["style"] = "volume"

    with tempfile.TemporaryDirectory(prefix="pixel-engine-soft-volume-") as temporary:
        variant_scene = Path(temporary) / "profiling-heavy-volume.json"
        variant_scene.write_text(json.dumps(source_scene, separators=(",", ":")) + "\n")
        variant_hash = sha256(variant_scene)
        command = [
            sys.executable,
            str(ROOT / "scripts/profile_compare.py"),
            "--baseline", str(variant_scene),
            "--candidate", str(variant_scene),
            "--output", str(output / "paired-runs"),
            "--route", args.route,
            "--duration", str(args.duration),
            "--warmup", str(args.warmup),
            "--pairs", str(args.pairs),
            "--seed", str(args.seed),
            "--resolution", "640x360",
        ]
        if args.candidate_disable_tile_lists:
            command.append("--candidate-disable-tile-lists")
        if not args.reuse_existing:
            subprocess.run(command, cwd=ROOT, check=True)
        report_path = output / "paired-runs" / "comparison.json"
        report = json.loads(report_path.read_text())
        if report["configuration"]["candidate_disable_tile_lists"] != args.candidate_disable_tile_lists:
            raise RuntimeError("existing paired run does not match the requested tile-list variant")
        report["workload_override"] = {
            "source_scene": str(scene.relative_to(ROOT)) if scene.is_relative_to(ROOT) else str(scene),
            "source_scene_sha256": sha256(scene),
            "emitter_style": "volume",
            "generated_scene_sha256": variant_hash,
            "generator": "scripts/soft_volume_route_study.py",
            "generator_sha256": sha256(Path(__file__).resolve()),
            "candidate_disable_tile_lists": args.candidate_disable_tile_lists,
            "note": "Both paired variants use identical generated scene content. Deltas estimate run-to-run variation; stage medians characterize this style and are not optimization deltas.",
        }
        parity_dir = output / "fixed-tick-parity"
        parity_dir.mkdir(parents=True, exist_ok=True)
        parity_variants = {}
        for label, disable_tile_lists in (("tiled", False), ("exhaustive", True)):
            image = parity_dir / f"{label}.png"
            capture_command = [
                str(ROOT / "target/release/engine-lab"),
                "capture", "--scene", str(variant_scene), "--seed", str(args.seed),
                "--tick", "120", "--resolution", "640x360", "--scale", "1",
                "--output", str(image),
            ]
            if disable_tile_lists:
                capture_command.append("--disable-tile-lists")
            subprocess.run(capture_command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
            metadata = json.loads(image.with_suffix(".json").read_text())
            parity_variants[label] = {
                "image": str(image.relative_to(ROOT)) if image.is_relative_to(ROOT) else str(image),
                "pixel_sha256": pixel_sha256(image),
                "resolution": metadata["capabilities"]["resolution"],
                "adapter": metadata["capabilities"]["name"],
                "backend": metadata["capabilities"]["backend"],
                "tile_lists_enabled": metadata["capabilities"]["tile_lists"]["enabled"],
            }
        report["fixed_tick_tile_parity"] = {
            "tick": 120,
            "seed": args.seed,
            "resolution": [640, 360],
            "pixel_identical": parity_variants["tiled"]["pixel_sha256"] == parity_variants["exhaustive"]["pixel_sha256"],
            "variants": parity_variants,
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        baseline_run_path = output / "paired-runs" / "pair-01-baseline.engine.json"
        baseline_run = json.loads(baseline_run_path.read_text())
        binary_path = ROOT / "target/release/engine-lab"
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        output.mkdir(parents=True, exist_ok=True)
        summary = {
            "version": 1,
            "study": "O01 uninstrumented soft-volume route timing",
            "scene": str(scene.relative_to(ROOT)) if scene.is_relative_to(ROOT) else str(scene),
            "scene_sha256": sha256(scene),
            "generated_scene_sha256": variant_hash,
            "style": "volume",
            "route": args.route,
            "duration_seconds": args.duration,
            "warmup_seconds": args.warmup,
            "pairs": args.pairs,
            "seed": args.seed,
            "resolution": [640, 360],
            "host": {
                "adapter": baseline_run["capabilities"]["name"],
                "backend": baseline_run["capabilities"]["backend"],
                "native_window": False,
            },
            "git_revision": revision,
            "binary_sha256": sha256(binary_path),
            "runner_sha256": sha256(Path(__file__).resolve()),
            "source_fingerprints": {
                "engine_rust": tree_sha256(ROOT / "crates/engine/src"),
                "engine_lab_rust": tree_sha256(ROOT / "crates/engine-lab/src"),
                "renderer_shaders": tree_sha256(ROOT / "crates/engine/src/render/shaders"),
            },
            "instrumentation_enabled": False,
            "candidate_disable_tile_lists": args.candidate_disable_tile_lists,
            "comparison_report": str(report_path.relative_to(ROOT)) if report_path.is_relative_to(ROOT) else str(report_path),
            "comparison": report["comparison"],
            "fixed_tick_tile_parity": report["fixed_tick_tile_parity"],
            "measurement_overhead": report.get("measurement_overhead"),
            "scope": "Uninstrumented O01 GPU stage and whole-frame timings for the soft-volume style. Same-scene paired deltas are run-variance controls unless candidate_disable_tile_lists is true, in which case they compare tiled candidates with exhaustive evaluation. M1 Max/Metal only.",
            "reproduction": f"python3 scripts/soft_volume_route_study.py --output {args.output} --report {args.report} --duration {args.duration:g} --warmup {args.warmup:g} --pairs {args.pairs} --route {args.route} --seed {args.seed}" + (" --candidate-disable-tile-lists" if args.candidate_disable_tile_lists else ""),
        }
        summary_path = output / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        report_destination = (ROOT / args.report).resolve() if not args.report.is_absolute() else args.report
        report_destination.parent.mkdir(parents=True, exist_ok=True)
        report_destination.write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"summary": str(summary_path), "report": str(report_destination), "pairs": args.pairs, "style": "volume"}))
        if not report["fixed_tick_tile_parity"]["pixel_identical"]:
            raise SystemExit("tiled/exhaustive fixed-tick capture mismatch; inspect the report and captured images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
