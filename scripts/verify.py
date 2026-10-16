#!/usr/bin/env python3
"""Portable verification. --gpu exercises the real renderer and agent protocol."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    print("+", *map(str, args), flush=True)
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo/bin/cargo")
    for command in [("fmt", "--all", "--check"), ("clippy", "--workspace", "--all-targets", "--", "-D", "warnings"), ("test", "--workspace"), ("build", "--locked")]:
        run(cargo, *command)
    binary = ROOT / "target/debug" / ("engine-lab.exe" if os.name == "nt" else "engine-lab")
    run(binary, "validate")
    description = json.loads(subprocess.check_output([binary, "describe"], cwd=ROOT))
    assert description["protocol_version"] == 1
    if args.gpu:
        with tempfile.TemporaryDirectory(prefix="pixel-engine-check-") as temporary:
            temp = Path(temporary)
            shaders = temp / "shaders"
            shutil.copytree(ROOT / "crates/engine/src/render/shaders", shaders)
            process = subprocess.Popen([binary, "serve", "--shaders", shaders], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            counter = 0

            def request(method, **params):
                nonlocal counter
                counter += 1
                process.stdin.write(json.dumps({"id": counter, "method": method, "params": params}) + "\n")
                process.stdin.flush()
                response = json.loads(process.stdout.readline())
                assert response["id"] == counter, response
                return response

            try:
                assert "result" in request("inspect_scene")
                assert "error" in request("set_parameter", path="render.exposure", value=-2)
                assert "error" in request("set_camera", id="missing")
                assert "result" in request("step", ticks=120)
                first = request("capture_frame", path=str(temp / "first.png"), scale=1)
                assert first["result"]["tick"] == 120, first
                request("reset", seed=42)
                request("step", ticks=120)
                request("capture_frame", path=str(temp / "replay.png"), scale=1)
                assert (temp / "first.png").read_bytes() == (temp / "replay.png").read_bytes(), "same-device replay changed"
                # Shared smoke occlusion and internal emission must be visible,
                # reversible authoring operations at an identical simulation tick.
                request("set_camera", id="smoke-close")
                request("step", ticks=180)
                request("capture_frame", path=str(temp / "shadowed.png"), scale=1)
                assert "result" in request("set_parameter", path="emitters.campfire.self_shadow_strength", value=0)
                request("capture_frame", path=str(temp / "unshadowed.png"), scale=1)
                assert (temp / "shadowed.png").read_bytes() != (temp / "unshadowed.png").read_bytes(), "smoke occlusion has no visible effect"
                request("set_parameter", path="emitters.campfire.self_shadow_strength", value=0.9)
                request("set_parameter", path="emitters.campfire.internal_glow", value=1)
                request("capture_frame", path=str(temp / "emission.png"), scale=1)
                assert (temp / "emission.png").read_bytes() != (temp / "shadowed.png").read_bytes(), "internal smoke emission has no visible effect"
                assert "error" in request("set_parameter", path="emitters.campfire.self_shadow_strength", value=-1)
                request("set_parameter", path="emitters.campfire.internal_glow", value=0)
                request("set_camera", id="hero")
                request("reset", seed=42)
                request("step", ticks=120)
                shader_path = shaders / "world.wgsl"
                working = shader_path.read_text()
                shader_path.write_text("this is deliberately invalid WGSL")
                assert "error" in request("reload_shaders"), "invalid shader accepted"
                assert "result" in request("capture_frame", path=str(temp / "rollback.png"), scale=1)
                assert (temp / "replay.png").read_bytes() == (temp / "rollback.png").read_bytes(), "failed reload replaced working pipeline"
                shader_path.write_text(working)
                assert "result" in request("reload_shaders")
                assert "result" in request("set_camera", id="orthographic")
                assert "result" in request("capture_frame", path=str(temp / "ortho.png"), scale=1)
                assert "result" in request("get_metrics")
                process.stdin.write("not json\n")
                process.stdin.flush()
                assert json.loads(process.stdout.readline())["error"]["code"] == "parse_error"
            finally:
                process.stdin.close()
                process.wait(timeout=30)
            assert process.returncode == 0
    if args.native:
        import sys
        run(sys.executable, ROOT / "scripts/verify_native.py", "--binary", binary)
    print(json.dumps({"verified": True, "gpu": args.gpu,"native":args.native}))


if __name__ == "__main__":
    main()
