#!/usr/bin/env python3
"""Check shadow-cache invalidation for supported live edit classes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/clearing.json")
    parser.add_argument("--camera", default="hero")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o02/invalidation")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [str(args.binary), "serve", "--scene", str(args.scene), "--camera", args.camera,
         "--seed", str(args.seed)],
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

    def compare(label):
        cached_path = args.output / f"{label}-cached.png"
        request("capture_frame", path=str(cached_path.resolve()), scale=1)
        metrics = request("get_metrics")["frame"]
        request("set_shadow_cache", force_redraw=True)
        forced_path = args.output / f"{label}-forced.png"
        request("capture_frame", path=str(forced_path.resolve()), scale=1)
        forced_metrics = request("get_metrics")["frame"]
        request("set_shadow_cache", force_redraw=False)
        image = cached_path.read_bytes()
        return {
            "event": label,
            "images_match": image == forced_path.read_bytes(),
            "cached_sha256": hashlib.sha256(image).hexdigest(),
            "cached": {key: metrics.get(key) for key in (
                "shadow_cache_hit", "shadow_redrawn", "shadow_maps_redrawn",
                "shadow_dirty_faces", "shadow_dirty_reason", "cpu_shadow_encode_ms",
            )},
            "forced": {key: forced_metrics.get(key) for key in (
                "shadow_cache_hit", "shadow_maps_redrawn", "shadow_dirty_faces",
                "shadow_dirty_reason",
            )},
        }

    try:
        request("capture_frame", path=str((args.output / "initial.png").resolve()), scale=1)
        events = []
        edits = [
            ("material-shadow-class", "set_parameter", {
                "path": "materials.log.transmission", "value": 0.5,
            }),
            ("sun-projection", "set_parameter", {
                "path": "lights.sun.position", "value": [0.2, 0.55, -0.55],
            }),
            ("linked-fire-light-position", "set_parameter", {
                "path": "lights.fire-light.position", "value": [0.5, 0.5, 0.0],
            }),
            ("fire-light-range", "set_parameter", {
                "path": "lights.fire-light.range", "value": 18.0,
            }),
        ]
        for label, method, params in edits:
            request(method, **params)
            events.append(compare(label))
        request("step", ticks=30)
        request("reload_shaders")
        events.append(compare("successful-shader-reload"))
        request("reset", seed=args.seed)
        events.append(compare("reset"))
    finally:
        process.stdin.close()
        process.wait(timeout=30)

    report = {
        "scene": str(args.scene.relative_to(ROOT)) if args.scene.is_relative_to(ROOT) else str(args.scene),
        "camera": args.camera,
        "seed": args.seed,
        "resolution": [640, 360],
        "face_order": ["sun", "+X", "-X", "+Y", "-Y", "+Z", "-Z"],
        "events": events,
    }
    report_path = args.output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "matches": all(event["images_match"] for event in events)}))


if __name__ == "__main__":
    main()
