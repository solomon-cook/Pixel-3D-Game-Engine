#!/usr/bin/env python3
"""Capture baseline/variants and benchmark each with identical scene/route/seed."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--duration", type=float, default=120)
    args = parser.parse_args()
    destination = ROOT / "artifacts/experiments"
    destination.mkdir(parents=True, exist_ok=True)
    variants = ["baseline", "pixel_cluster_lighting", "stable_smoke_detail", "connected_motion"]
    for variant in variants:
        extra = [] if variant == "baseline" else ["--experiments", variant]
        for camera in ["hero", "smoke-close", "orthographic"]:
            subprocess.run([str(args.binary), "capture", "--camera", camera, "--tick", "300", "--output", str(destination / f"{variant}-{camera}.png"), *extra], cwd=ROOT, check=True)
        subprocess.run([str(args.binary), "benchmark", "--duration", str(args.duration), "--output", str(destination / f"{variant}-benchmark.json"), *extra], cwd=ROOT, check=True)
    summary = {variant: {key: json.loads((destination / f"{variant}-benchmark.json").read_text())[key] for key in ["frame_work", "cpu_encode", "gpu_render", "capabilities"]} for variant in variants}
    (destination / "summary.json").write_text(json.dumps({"variants": summary, "promotion": "pending visual review and cross-platform qualification"}, indent=2) + "\n")
    print(destination)


if __name__ == "__main__":
    main()
