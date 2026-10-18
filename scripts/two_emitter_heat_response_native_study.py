#!/usr/bin/env python3
"""Compare secondary-emitter heat response at focused native-window orbit poses."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import select
import subprocess

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/scenes/two-emitter-review.json"
POSES = {
    "near-east": [-3.0, 1.7, 2.8],
    "east": [-0.2, 1.7, 0.0],
    "near-west": [-3.0, 1.7, -2.8],
    "west": [-5.8, 1.7, 0.0],
    "return-east": [-3.0, 1.7, 2.8],
}
TARGET = [-3.0, 0.3, 0.0]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(a: Path, b: Path) -> dict:
    with Image.open(a) as image:
        first = image.convert("RGB")
    with Image.open(b) as image:
        second = image.convert("RGB")
    diff = ImageChops.difference(first, second)
    pixels = list(diff.getdata())
    return {
        "changed_pixels": sum(any(pixel) for pixel in pixels),
        "total_pixels": first.width * first.height,
        "mean_absolute_channel_error": sum(sum(pixel) for pixel in pixels) / (3 * len(pixels)),
        "max_channel_error": max(max(pixel) for pixel in pixels),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/multi-emitter/heat-native")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-multi-emitter-heat-response-native.json")
    parser.add_argument("--tick", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    binary = args.binary.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "-p", "engine-lab"], cwd=ROOT, check=True)
    output, report_path = args.output.resolve(), args.report.resolve()
    output.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [str(binary), "run", "--agent-stdio", "--paused", "--scene", str(SCENE),
         "--camera", "dual-wide", "--seed", str(args.seed)],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    request_id = 0

    def request(method: str, **params):
        nonlocal request_id
        request_id += 1
        if process.poll() is not None or process.stdin is None or process.stdout is None:
            raise RuntimeError(f"native session exited before {method}")
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], 60)
        if not ready:
            raise TimeoutError(f"timed out waiting for {method}")
        response = json.loads(process.stdout.readline())
        if response.get("id") != request_id or response.get("error"):
            raise RuntimeError(f"{method}: {response}")
        return response["result"]

    records = []
    captures = []
    try:
        request("step", ticks=args.tick)
        window = request("get_window")
        for name, position in POSES.items():
            camera = {"id": f"heat-native-{name}", "position": position, "target": TARGET,
                      "projection": {"kind": "perspective", "fov_degrees": 48.0}}
            request("set_camera", camera=camera)
            pair = {}
            for label, response in (("off", 0.0), ("on", 0.8)):
                request("set_parameter", path="materials.earth.heat_response", value=response)
                path = (output / f"{name}-{label}.png").resolve()
                result = request("capture_frame", path=str(path), scale=1)
                metadata = json.loads(path.with_suffix(".json").read_text())
                pair[label] = {"path": path, "tick": result["tick"], "sha256": sha256(path),
                               "camera": metadata["camera"], "resolution": metadata["capabilities"]["resolution"]}
                captures.append((f"{name} / heat {label}", path))
            error = compare(pair["off"]["path"], pair["on"]["path"])
            records.append({"pose": name, "position": position, "target": TARGET,
                            "tick": pair["off"]["tick"], "heat_off_sha256": pair["off"]["sha256"],
                            "heat_on_sha256": pair["on"]["sha256"], "heat_on_off": error,
                            "off_on_images_differ": pair["off"]["sha256"] != pair["on"]["sha256"]})
        request("set_parameter", path="materials.earth.heat_response", value=0.0)
        request("shutdown")
        process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=30)

    sheet = Image.new("RGB", (960, ((len(captures) + 1) // 2) * 206), "#20232a")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(sheet)
    for index, (label, path) in enumerate(captures):
        thumb = Image.open(path).convert("RGB").resize((480, 180))
        x, y = (index % 2) * 480, (index // 2) * 206
        sheet.paste(thumb, (x, y))
        draw.text((x + 6, y + 184), label, fill="white")
    contact_path = report_path.with_name(report_path.stem + "-contact.png")
    contact_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(contact_path)
    metadata = json.loads((Path(captures[0][1]).with_suffix(".json")).read_text())
    report = {
        "version": 1,
        "study": "O05 source-one opaque heat-response focused native-window captures",
        "host": {"device": metadata["capabilities"]["name"], "backend": metadata["capabilities"]["backend"],
                 "native_window": True, "window": window},
        "scene": str(SCENE.relative_to(ROOT)), "scene_sha256": sha256(SCENE),
        "binary_sha256": sha256(binary), "script_sha256": sha256(Path(__file__).resolve()),
        "seed": args.seed, "tick": args.tick, "material": "earth", "heat_response": {"off": 0.0, "on": 0.8},
        "camera_mode": "runtime native camera matching the five focused watchfire-orbit checkpoints",
        "resolution": [640, 360], "poses": records,
        "all_ticks_match": all(row["tick"] == args.tick for row in records),
        "all_focused_poses_show_heat_difference": all(row["off_on_images_differ"] and row["heat_on_off"]["changed_pixels"] > 0 for row in records),
        "contact_sheet": str(contact_path.relative_to(ROOT)), "contact_sheet_sha256": sha256(contact_path),
        "limitations": ["Five paused native-window checkpoints at one tick do not establish continuous playback or visual acceptance.",
                        "M1 Max/Metal only; DX12 and other-adapter behavior remain open.",
                        "Image differences demonstrate the cue contribution, not a performance improvement or calibrated temperature."],
    }
    report["all_checks_passed"] = report["all_ticks_match"] and report["all_focused_poses_show_heat_difference"]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "all_checks_passed": report["all_checks_passed"],
                      "changed_pixels": {row["pose"]: row["heat_on_off"]["changed_pixels"] for row in records},
                      "contact_sheet": str(contact_path)}, indent=2))
    return 0 if report["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
