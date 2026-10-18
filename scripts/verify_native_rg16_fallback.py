#!/usr/bin/env python3
"""Verify native-window RGBA16F fallback setup and matched capture output."""

import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o08/rg16-fallback/native-window")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o08-rg16-native-fallback.json")
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    native_image = output / "native.png"
    headless_image = output / "headless.png"
    with (output / "native-stderr.log").open("w") as log:
        process = subprocess.Popen(
            [str(binary), "run", "--agent-stdio", "--force-rg16-fallback"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
        )
        sequence = 0

        def request(method: str, **params):
            nonlocal sequence
            sequence += 1
            process.stdin.write(json.dumps({"id": sequence, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            if response.get("id") != sequence or "result" not in response:
                raise RuntimeError(f"unexpected native response: {response}")
            return response["result"]

        try:
            metrics = request("get_metrics")
            capabilities = metrics["capabilities"]
            inventory = capabilities["resource_inventory"]
            if not inventory.get("rg16_fallback_forced"):
                raise RuntimeError("native renderer did not report forced fallback")
            if inventory["effect_depth_format"] != "Rgba16Float" or inventory["smoke_volume_format"] != "Rgba16Float":
                raise RuntimeError(f"native renderer did not select both fallback formats: {inventory}")
            request("step", ticks=120)
            capture = request("capture_frame", path=str(native_image), scale=1)
            if capture["tick"] != 120 or not native_image.is_file():
                raise RuntimeError(f"native capture did not complete at tick 120: {capture}")
            subprocess.run([
                str(binary), "capture", "--scene", "assets/scenes/clearing.json",
                "--camera", "hero", "--seed", "42", "--tick", "120",
                "--resolution", "640x360", "--scale", "1", "--force-rg16-fallback",
                "--output", str(headless_image),
            ], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
            parity = native_image.read_bytes() == headless_image.read_bytes()
            if not parity:
                raise RuntimeError("native and headless forced-fallback captures differ")
            request("shutdown")
            process.wait(timeout=20)
            if process.returncode != 0:
                raise RuntimeError(f"native renderer exited with status {process.returncode}")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            if process.stdin:
                process.stdin.close()
        report = {
            "native_window_verified": True,
            "adapter": capabilities["name"],
            "backend": capabilities["backend"],
            "seed": 42,
            "tick": capture["tick"],
            "resolution": capabilities["resolution"],
            "effect_depth_format": inventory["effect_depth_format"],
            "smoke_volume_format": inventory["smoke_volume_format"],
            "known_gpu_allocation_bytes": inventory["known_gpu_allocation_bytes"],
            "native_headless_png_identical": parity,
            "native_image": str(native_image.relative_to(ROOT)),
            "headless_image": str(headless_image.relative_to(ROOT)),
        }
        report_path = args.report.resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"report": str(report_path), "native_headless_png_identical": parity}))


if __name__ == "__main__":
    main()
