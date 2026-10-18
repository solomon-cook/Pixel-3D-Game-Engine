#!/usr/bin/env python3
"""Verify lazy optical snapshot allocation in a paused native Session."""

from __future__ import annotations

import argparse
import hashlib
import json
import select
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display_path(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/materials.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o08/lazy-optical-native")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o08-lazy-optical-native.json")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    binary, source = args.binary.resolve(), args.scene.resolve()
    output, report_path = args.output.resolve(), args.report.resolve()
    if not binary.is_file() or not source.is_file():
        parser.error("binary and source scene must exist")

    output.mkdir(parents=True, exist_ok=True)
    scene = json.loads(source.read_text())
    away = next((camera for camera in scene.get("cameras", []) if camera.get("id") == "away"), None)
    if away is None:
        away = {
            "id": "away",
            "position": [8.0, 7.6, 14.0],
            "target": [20.0, 10.0, 25.0],
            "projection": {"kind": "perspective", "fov_degrees": 44.0},
        }
        scene.setdefault("cameras", []).append(away)
    generated_scene = output / "materials-away.json"
    generated_scene.write_text(json.dumps(scene, indent=2) + "\n")
    subprocess.run([str(binary), "validate", str(generated_scene)], cwd=ROOT, check=True, stdout=subprocess.PIPE)

    process = subprocess.Popen(
        [str(binary), "run", "--agent-stdio", "--paused", "--scene", str(generated_scene),
         "--camera", "away", "--seed", str(args.seed)],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    request_id = 0

    def request(method: str, **params):
        nonlocal request_id
        request_id += 1
        if process.poll() is not None or not process.stdin or not process.stdout:
            raise RuntimeError(f"native Session exited before {method}")
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], 90)
        if not ready:
            raise TimeoutError(f"timed out waiting for native {method}")
        response = json.loads(process.stdout.readline())
        if response.get("id") != request_id or response.get("error"):
            raise RuntimeError(f"{method}: {response}")
        return response["result"]

    captures = {}
    window = None
    try:
        window = request("get_window")
        request("set_parameter", path="materials.chalk.reflectivity", value=0.3)
        for label, camera in (("edited_offscreen", "away"), ("first_visible", "hero"),
                              ("turned_away", "away"), ("visible_again", "hero")):
            request("set_camera", id=camera)
            image_path = output / f"{label}.png"
            result = request("capture_frame", path=str(image_path.resolve()), scale=1)
            metadata_path = image_path.with_suffix(".json")
            metadata = json.loads(metadata_path.read_text())
            inventory = metadata["capabilities"]["resource_inventory"]
            metrics = metadata["metrics"]
            captures[label] = {
                "camera": camera,
                "tick": result["tick"],
                "image": display_path(image_path),
                "image_sha256": sha256(image_path),
                "snapshot_bytes": inventory["optical_snapshot_bytes"],
                "known_gpu_allocation_bytes": inventory["known_gpu_allocation_bytes"],
                "optical_draw_batches": metrics["optical_draw_batches"],
                "optical_resolve_timed": "optical_resolve" in metrics.get("gpu_passes_ms", {}),
            }
        request("shutdown")
        process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=30)

    edited = captures["edited_offscreen"]
    first_visible = captures["first_visible"]
    turned_away = captures["turned_away"]
    visible_again = captures["visible_again"]
    report = {
        "version": 1,
        "workstream": "O08 native lazy optical HDR snapshot lifecycle",
        "host": {"adapter": metadata["capabilities"].get("name"),
                 "backend": metadata["capabilities"].get("backend"), "native_window": True, "window": window},
        "scene": str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source),
        "scene_sha256": sha256(source),
        "generated_scene": display_path(generated_scene),
        "generated_scene_sha256": sha256(generated_scene),
        "binary_sha256": sha256(binary),
        "render_source_sha256": sha256(ROOT / "crates/engine/src/render/mod.rs"),
        "session_source_sha256": sha256(ROOT / "crates/engine/src/session.rs"),
        "seed": args.seed,
        "resolution": metadata["capabilities"].get("resolution"),
        "edit": {"path": "materials.chalk.reflectivity", "value": 0.3},
        "captures": captures,
        "checks": {
            "offscreen_edit_keeps_snapshot_unallocated": edited["snapshot_bytes"] == 0 and edited["optical_draw_batches"] == 0,
            "offscreen_states_skip_optical_timestamp": not edited["optical_resolve_timed"] and not turned_away["optical_resolve_timed"],
            "first_visible_batch_allocates_once": first_visible["snapshot_bytes"] == 1843200 and first_visible["optical_draw_batches"] > 0,
            "first_visible_frame_includes_resolve_timestamp": first_visible["optical_resolve_timed"],
            "turning_away_skips_optical_batch_but_retains_snapshot": turned_away["snapshot_bytes"] == 1843200 and turned_away["optical_draw_batches"] == 0,
            "revisiting_visible_geometry_does_not_duplicate_allocation": visible_again["snapshot_bytes"] == first_visible["snapshot_bytes"] and visible_again["known_gpu_allocation_bytes"] == first_visible["known_gpu_allocation_bytes"],
            "allocation_increase_is_one_snapshot": first_visible["known_gpu_allocation_bytes"] - edited["known_gpu_allocation_bytes"] == 1843200,
            "repeated_paused_camera_captures_are_identical": edited["image_sha256"] == turned_away["image_sha256"] and first_visible["image_sha256"] == visible_again["image_sha256"],
        },
        "limitations": [
            "One paused native-window Session on Apple M1 Max/Metal; this checks Session/resource lifecycle, not continuous timing.",
            "This is camera-frustum visibility, not occlusion detection; DX12 and other adapters remain unqualified.",
        ],
    }
    report["all_checks_passed"] = all(report["checks"].values())
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "checks": report["checks"], "all_checks_passed": report["all_checks_passed"]}, indent=2))
    return 0 if report["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
