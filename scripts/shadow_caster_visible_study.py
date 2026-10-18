#!/usr/bin/env python3
"""Compare shadow-cache parity while a caster remains in the camera view."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import select
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/clearing.json"
POSES = {
    "east": [5.0, 0.3, 0.0],
    "diagonal-east-north": [5.0, 0.3, 5.0],
    "north": [0.0, 0.3, 5.0],
    "west": [-5.0, 0.3, 0.0],
    "south": [0.0, 0.3, -5.0],
    "return-east": [5.0, 0.3, 0.0],
}
CAMERA = {
    "id": "shadow-caster-review",
    "position": [0.0, 9.0, 14.0],
    "target": [0.0, 0.4, 0.0],
    "projection": {"kind": "orthographic", "height": 14.0},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def revision() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def make_scene(output: Path) -> Path:
    scene = json.loads(SOURCE.read_text())
    scene["render"]["resolution"] = [640, 360]
    scene["cameras"] = [camera for camera in scene["cameras"] if camera["id"] != CAMERA["id"]]
    scene["cameras"].append(CAMERA)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "scene.json"
    path.write_text(json.dumps(scene, indent=2) + "\n")
    return path


def make_contact_sheet(captures: list[tuple[str, Path]], output: Path) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return
    thumb_w, thumb_h, label_h = 320, 180, 22
    columns = 3
    rows = (len(captures) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), "#20232a")
    draw = ImageDraw.Draw(sheet)
    for i, (label, path) in enumerate(captures):
        image = Image.open(path).convert("RGB").resize((thumb_w, thumb_h))
        x, y = (i % columns) * thumb_w, (i // columns) * (thumb_h + label_h)
        sheet.paste(image, (x, y))
        draw.text((x + 5, y + thumb_h + 3), label, fill="white")
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o02/visible-caster")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o02-visible-caster.json")
    parser.add_argument("--native", action="store_true", help="run the same captures through the native window agent session")
    args = parser.parse_args()
    binary, output, report_path = args.binary.resolve(), args.output.resolve(), args.report.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    scene_path = make_scene(output)
    command = [str(binary), "run", "--agent-stdio"] if args.native else [str(binary), "serve"]
    command += ["--scene", str(scene_path), "--camera", CAMERA["id"], "--seed", "42"]
    process = subprocess.Popen(
        command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL if args.native else None, text=True,
    )
    request_id = 0

    def request(method: str, **params):
        nonlocal request_id
        request_id += 1
        assert process.stdin and process.stdout
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        if args.native:
            ready, _, _ = select.select([process.stdout], [], [], 60)
            if not ready:
                raise TimeoutError(f"timed out waiting for {method} response")
        response = json.loads(process.stdout.readline())
        if response.get("id") != request_id or "error" in response:
            raise RuntimeError(f"{method}: {response}")
        return response["result"]

    records = []
    contact = []
    try:
        window = request("get_window") if args.native else None
        baseline_path = output / "initial-cached.png"
        request("capture_frame", path=str(baseline_path.resolve()), scale=1)
        baseline_metadata = json.loads(baseline_path.with_suffix(".json").read_text())
        baseline_metrics = baseline_metadata["metrics"]
        for name, position in POSES.items():
            request("set_object_transform", id="fallen-log", position=position)
            cached_path = output / f"{name}-cached.png"
            cached_result = request("capture_frame", path=str(cached_path.resolve()), scale=1)
            cached_metadata = json.loads(cached_path.with_suffix(".json").read_text())
            cached_metrics = cached_metadata["metrics"]

            request("set_shadow_cache", force_redraw=True)
            forced_path = output / f"{name}-forced.png"
            forced_result = request("capture_frame", path=str(forced_path.resolve()), scale=1)
            forced_metadata = json.loads(forced_path.with_suffix(".json").read_text())
            forced_metrics = forced_metadata["metrics"]
            request("set_shadow_cache", force_redraw=False)

            records.append({
                "pose": name,
                "position": position,
                "tick": cached_result["tick"],
                "cached_sha256": sha256(cached_path),
                "forced_sha256": sha256(forced_path),
                "images_match": cached_path.read_bytes() == forced_path.read_bytes(),
                "cached_shadow_maps_redrawn": None if args.native else cached_metrics["shadow_maps_redrawn"],
                "cached_dirty_faces": None if args.native else cached_metrics["shadow_dirty_faces"],
                "cached_dirty_reason": None if args.native else cached_metrics["shadow_dirty_reason"],
                "forced_shadow_maps_redrawn": None if args.native else forced_metrics["shadow_maps_redrawn"],
            })
            contact.extend([(f"{name} · cached", cached_path), (f"{name} · forced", forced_path)])
        if args.native:
            request("shutdown")
            process.wait(timeout=60)
    finally:
        if args.native and process.poll() is None:
            process.terminate()
            process.wait(timeout=60)
        elif not args.native:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=60)
    if process.returncode and not (args.native and process.returncode < 0):
        raise RuntimeError(f"serve exited {process.returncode}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    sheet_path = output / "contact-sheet.png"
    make_contact_sheet(contact, sheet_path)
    report = {
        "workstream": "O02 visible moving-caster shadow-cache image parity",
        "host": {"device": "Apple M1 Max", "backend": "Metal"},
        "render_mode": "native-window run --agent-stdio" if args.native else "headless serve",
        "native_window": window,
        "git_revision": revision(),
        "scene": "assets/scenes/clearing.json",
        "scene_sha256": sha256(scene_path),
        "renderer_source_sha256": sha256(ROOT / "crates/engine/src/render/mod.rs"),
        "study_script_sha256": sha256(Path(__file__).resolve()),
        "object": "fallen-log",
        "camera": CAMERA,
        "seed": 42,
        "resolution": [640, 360],
        "tick": 0,
        "method": "Six paused caster poses are captured in a wide orthographic camera that includes the moving log. Each cached image is paired with forced redraw at the same pose, seed, tick and camera.",
        "metrics_source": "metrics embedded in each capture sidecar, tied to that exact capture frame",
        "baseline": {
            "image_sha256": sha256(baseline_path),
            "shadow_maps_redrawn": baseline_metrics["shadow_maps_redrawn"],
            "dirty_reason": baseline_metrics["shadow_dirty_reason"],
        },
        "poses": records,
        "all_images_match": all(item["images_match"] for item in records),
        "contact_sheet": str(sheet_path.relative_to(ROOT)),
        "limitations": ["Discrete paused poses do not establish continuous visual quality or native-window behavior", "Only M1 Max/Metal is covered; DX12 and other adapters remain open", "The study moves one object, not a fire emitter or its light"],
    }
    if args.native:
        report["limitations"] = [
            "Discrete paused poses do not establish continuous visual quality.",
            "Native-window captures match forced redraw, but exact per-pose dirty masks are omitted because the live host may render between a transform request and a separate capture request; the headless study records those masks.",
            "Only M1 Max/Metal is covered; DX12 and other adapters remain open.",
            "The study moves one object, not a fire emitter or its light.",
        ]
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "poses": len(records), "all_images_match": report["all_images_match"], "contact_sheet": str(sheet_path)}))
    return 0 if report["all_images_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
