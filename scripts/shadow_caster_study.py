#!/usr/bin/env python3
"""Compare cached and forced shadow redraws for deterministic caster poses."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
POSES = {
    "east": [5.0, 0.3, 0.0],
    "diagonal-east-north": [5.0, 0.3, 5.0],
    "north": [0.0, 0.3, 5.0],
    "west": [-5.0, 0.3, 0.0],
    "south": [0.0, 0.3, -5.0],
    "return-east": [5.0, 0.3, 0.0],
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/clearing.json")
    parser.add_argument("--camera", default="hero")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--object", default="fallen-log")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o02/moving-caster")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [str(args.binary), "serve", "--scene", str(args.scene), "--camera", args.camera, "--seed", str(args.seed)],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    counter = 0

    def request(method, **params):
        nonlocal counter
        counter += 1
        process.stdin.write(json.dumps({"id": counter, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        if response.get("id") != counter or "error" in response:
            raise RuntimeError(f"{method}: {response}")
        return response["result"]

    records = []
    try:
        request("reset", seed=args.seed)
        request("capture_frame", path=str((args.output / "initial.png").resolve()), scale=1)
        for name, position in POSES.items():
            request("set_object_transform", id=args.object, position=position)
            cached_path = args.output / f"{name}-cached.png"
            request("capture_frame", path=str(cached_path.resolve()), scale=1)
            cached_metrics = request("get_metrics")["frame"]
            request("set_shadow_cache", force_redraw=True)
            forced_path = args.output / f"{name}-forced.png"
            request("capture_frame", path=str(forced_path.resolve()), scale=1)
            forced_metrics = request("get_metrics")["frame"]
            request("set_shadow_cache", force_redraw=False)
            records.append({
                "pose": name,
                "position": position,
                "cached_sha256": sha256(cached_path),
                "forced_sha256": sha256(forced_path),
                "images_match": cached_path.read_bytes() == forced_path.read_bytes(),
                "cached": {key: cached_metrics.get(key) for key in (
                    "shadow_cache_hit", "shadow_redrawn", "shadow_maps_redrawn",
                    "shadow_dirty_faces", "shadow_dirty_reason", "cpu_shadow_encode_ms",
                )},
                "forced": {key: forced_metrics.get(key) for key in (
                    "shadow_cache_hit", "shadow_redrawn", "shadow_maps_redrawn",
                    "shadow_dirty_faces", "shadow_dirty_reason", "cpu_shadow_encode_ms",
                )},
            })
        request("capture_frame", path=str((args.output / "stable-cache-hit.png").resolve()), scale=1)
        stable = request("get_metrics")["frame"]
    finally:
        process.stdin.close()
        process.wait(timeout=30)

    report = {
        "scene": str(args.scene.relative_to(ROOT)) if args.scene.is_relative_to(ROOT) else str(args.scene),
        "camera": args.camera,
        "seed": args.seed,
        "tick": 0,
        "object": args.object,
        "face_order": ["sun", "+X", "-X", "+Y", "-Y", "+Z", "-Z"],
        "poses": records,
        "stable_cache_hit": {key: stable.get(key) for key in (
            "shadow_cache_hit", "shadow_redrawn", "shadow_maps_redrawn",
            "shadow_dirty_faces", "shadow_dirty_reason", "cpu_shadow_encode_ms",
        )},
    }
    report_path = args.output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "matches": all(item["images_match"] for item in records)}))


if __name__ == "__main__":
    main()
