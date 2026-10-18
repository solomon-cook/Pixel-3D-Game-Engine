#!/usr/bin/env python3
"""Run a sustained paired projected-fire-detail LOD study for one scene profile."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, default=Path("assets/scenes/projected-detail-motion-review.json"))
    parser.add_argument("--route", default="projected-detail-review-orbit")
    parser.add_argument("--camera", default="hero")
    parser.add_argument("--profile", choices=("campfire", "quiet", "bonfire"), default="campfire")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration", type=float, default=120.)
    parser.add_argument("--warmup", type=float, default=10.)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("artifacts/o04/campfire-sustained"))
    args = parser.parse_args()
    if args.duration <= 0 or args.warmup < 0 or args.pairs < 1:
        parser.error("duration/pairs must be positive and warmup cannot be negative")

    source = args.scene if args.scene.is_absolute() else ROOT / args.scene
    output = args.output if args.output.is_absolute() else ROOT / args.output
    scene_dir = output / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)
    original = json.loads(source.read_text())
    effect_profile = f"effect-{args.profile}"
    if not any(effect.get("id") == effect_profile for effect in original.get("effects", [])):
        parser.error(f"scene does not define profile {effect_profile!r}")
    names = {}
    for mode, enabled in (("baseline", False), ("candidate", True)):
        scene = json.loads(json.dumps(original))
        scene.setdefault("render", {}).setdefault("experiments", {})["projected_detail_lod"] = enabled
        if len(scene.get("emitters", [])) != 1:
            parser.error("this study expects the planned single-emitter profile scene")
        scene["emitters"][0]["effect_profile"] = effect_profile
        path = scene_dir / f"{mode}.json"
        path.write_text(json.dumps(scene, indent=2) + "\n")
        names[mode] = path

    binary = ROOT / "target/release/engine-lab"
    subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    for mode, path in names.items():
        subprocess.run([str(binary), "validate", str(path)], cwd=ROOT, check=True, stdout=subprocess.PIPE)
    output.mkdir(parents=True, exist_ok=True)
    comparison = output / "comparison.json"
    command = [
        "python3", str(ROOT / "scripts/profile_compare.py"),
        "--baseline", str(names["baseline"]),
        "--candidate", str(names["candidate"]),
        "--route", args.route,
        "--camera", args.camera,
        "--seed", str(args.seed),
        "--resolution", "640x360",
        "--duration", str(args.duration),
        "--warmup", str(args.warmup),
        "--pairs", str(args.pairs),
        "--output", str(output),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    report = json.loads(comparison.read_text())
    report["o04_study"] = {
        "source_scene": str(source.relative_to(ROOT)),
        "scene_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "baseline_lod": False,
        "candidate_lod": True,
        "profile_ids": [effect_profile],
        "selected_profile": effect_profile,
        "route": args.route,
        "camera": args.camera,
        "seed": args.seed,
        "resolution": [640, 360],
        "duration_seconds_per_run": args.duration,
        "warmup_seconds": args.warmup,
        "pairs": args.pairs,
    }
    comparison.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(comparison), "profile_ids": report["o04_study"]["profile_ids"]}))


if __name__ == "__main__":
    main()
