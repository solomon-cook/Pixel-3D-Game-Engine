#!/usr/bin/env python3
"""Measure high screen coverage and maximum supported secondary lobes.

This is a single-emitter stress test, not evidence for arbitrary emitter counts.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, default=ROOT / 'target/release/engine-lab')
    parser.add_argument('--duration', type=float, default=120)
    args = parser.parse_args()
    scene = json.loads((ROOT / 'assets/scenes/clearing.json').read_text())
    scene['emitters'][0]['secondary_bubbles'] = 8
    scene['emitters'][0]['bubble_scale'] = 0.5
    scene['emitters'][0]['smoke_density'] = 8
    route = scene['routes'][0]
    route['id'] = 'smoke-stress'
    for keyframe in route['keyframes']:
        angle = keyframe['time'] / route['duration_seconds'] * math.tau
        keyframe['position'] = [math.cos(angle) * 2.8, 3.1, math.sin(angle) * 2.8]
        keyframe['target'] = [0, 3.0, 0]
    # Keep relative scene assets resolvable; always remove the transient scene.
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', prefix='.stress-', dir=ROOT / 'assets/scenes', delete=False) as file:
        json.dump(scene, file)
        scene_path = Path(file.name)
    try:
        subprocess.run([str(args.binary), 'benchmark', '--scene', str(scene_path), '--route', route['id'], '--duration', str(args.duration), '--output', str(ROOT / 'artifacts/smoke-stress-benchmark.json')], cwd=ROOT, check=True)
    finally:
        scene_path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
