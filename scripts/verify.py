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
    run(binary,"validate","assets/scenes/materials.json")
    description = json.loads(subprocess.check_output([binary, "describe"], cwd=ROOT))
    assert description["protocol_version"] == 1
    if args.gpu:
        with tempfile.TemporaryDirectory(prefix="pixel-engine-check-") as temporary:
            temp = Path(temporary)
            shaders = temp / "shaders"
            shutil.copytree(ROOT / "crates/engine/src/render/shaders", shaders)
            # Add a disabled fill light to exercise multiple-source gradients
            # while preserving the reference fire's initial illumination.
            scene=json.loads((ROOT / "assets/scenes/clearing.json").read_text())
            scene["lights"].append({"id":"test-fill","kind":"point","position":[1.6,2.1,0.3],"color":[0.1,0.4,1.0],"intensity":0,"range":8})
            scene_path=temp / "scene.json"
            scene_path.write_text(json.dumps(scene))
            process = subprocess.Popen([binary, "serve", "--scene", scene_path, "--shaders", shaders], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
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
                request("capture_frame", path=str(temp / "local-light-before.png"), scale=1)
                assert "result" in request("set_parameter", path="lights.test-fill.intensity", value=8)
                request("capture_frame", path=str(temp / "local-light-after.png"), scale=1)
                assert (temp / "local-light-before.png").read_bytes() != (temp / "local-light-after.png").read_bytes(), "secondary point light has no visible effect"
                request("set_parameter", path="lights.test-fill.position", value=[-1.6,3.0,0.3])
                request("capture_frame", path=str(temp / "local-light-moved.png"), scale=1)
                assert (temp / "local-light-after.png").read_bytes() != (temp / "local-light-moved.png").read_bytes(), "local light gradient did not move"
                assert "error" in request("set_parameter", path="lights.test-fill.range", value=0)
                request("set_parameter", path="lights.test-fill.intensity", value=0)
                request("set_camera", id="fire-study")
                request("capture_frame", path=str(temp / "fire.png"), scale=1)
                metrics=request("get_metrics")["result"]["frame"]
                assert metrics["fire_primitives"] <= 256 and metrics["embers"] > 0
                assert "result" in request("set_parameter", path="effects.effect-campfire.fire.fragment_rate", value=0)
                assert "result" in request("set_parameter", path="effects.effect-campfire.fire.ember_rate", value=0)
                request("capture_frame", path=str(temp / "no-particles.png"), scale=1)
                metrics=request("get_metrics")["result"]["frame"]
                assert metrics["flame_fragments"] == 0 and metrics["embers"] == 0
                assert "error" in request("set_parameter", path="effects.effect-campfire.fire.motion_speed", value=0)
                request("set_parameter", path="effects.effect-campfire.palette.hot", value=[0.2,4,5])
                request("capture_frame", path=str(temp / "palette.png"), scale=1)
                assert (temp / "palette.png").read_bytes() != (temp / "no-particles.png").read_bytes(), "HDR palette did not reach renderer"
                request("set_parameter", path="effects.effect-campfire.palette.hot", value=[5,2.8,0.75])
                request("set_parameter", path="effects.effect-campfire.fire.fragment_rate", value=1.5)
                request("set_parameter", path="effects.effect-campfire.fire.ember_rate", value=4)
                request("set_parameter", path="emitters.campfire.effect_profile", value="effect-quiet")
                request("capture_frame", path=str(temp / "quiet.png"), scale=1)
                assert request("get_metrics")["result"]["capabilities"]["resolution"] == [640,360]
                request("set_parameter", path="emitters.campfire.effect_profile", value="effect-campfire")
                # Lights derived from moving particles must affect shading while
                # their own emitted glyphs/geometry stay unchanged.
                lit=request("inspect_effects")["result"]
                assert 0 < len(lit["particle_lights"]) <= 12
                request("capture_frame",path=str(temp / "particle-lit.png"),scale=1)
                assert "result" in request("set_parameter",path="effects.effect-campfire.fire.particle_lights",value=0)
                assert not request("inspect_effects")["result"]["particle_lights"]
                request("capture_frame",path=str(temp / "particle-unlit.png"),scale=1)
                assert (temp / "particle-lit.png").read_bytes() != (temp / "particle-unlit.png").read_bytes(), "moving emission sources did not affect shading"
                request("set_parameter",path="effects.effect-campfire.fire.particle_lights",value=12)
                assert "error" in request("set_parameter",path="effects.effect-campfire.fire.particle_lights",value=13)
                assert "error" in request("set_parameter",path="effects.effect-campfire.fire.branches",value=4)
                # Material-space breakup can be independently disabled.
                request("capture_frame", path=str(temp / "rough.png"), scale=1)
                assert "result" in request("set_parameter", path="effects.effect-campfire.fire.edge_breakup", value=0)
                request("set_parameter", path="effects.effect-campfire.fire.tip_breakup", value=0)
                request("capture_frame", path=str(temp / "smooth.png"), scale=1)
                assert (temp / "rough.png").read_bytes() != (temp / "smooth.png").read_bytes(), "flame breakup did not change coverage"
                request("set_parameter", path="effects.effect-campfire.fire.edge_breakup", value=0.5)
                request("set_parameter", path="effects.effect-campfire.fire.tip_breakup", value=0.8)
                # Exercise the same fire geometry in soft-volume treatment too.
                request("set_parameter", path="emitters.campfire.style", value="volume")
                request("capture_frame", path=str(temp / "soft-fire.png"), scale=1)
                request("set_parameter", path="emitters.campfire.style", value="ink")
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
                fire_shader=shaders / "fire.wgsl"
                working_fire=fire_shader.read_text()
                fire_shader.write_text("invalid fire shader")
                assert "error" in request("reload_shaders")
                request("capture_frame", path=str(temp / "fire-rollback.png"), scale=1)
                assert (temp / "replay.png").read_bytes() == (temp / "fire-rollback.png").read_bytes()
                fire_shader.write_text(working_fire)
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
    if args.gpu:
        import sys
        run(sys.executable, ROOT / "scripts/verify_materials.py", "--binary", binary)
        run(sys.executable, ROOT / "scripts/verify_pixel_fire.py", "--binary", binary)
    if args.native:
        import sys
        run(sys.executable, ROOT / "scripts/verify_native.py", "--binary", binary)
    print(json.dumps({"verified": True, "gpu": args.gpu,"native":args.native}))


if __name__ == "__main__":
    main()
