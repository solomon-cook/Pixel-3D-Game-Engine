#!/usr/bin/env python3
"""Portable verification. --gpu exercises the real renderer and agent protocol."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
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
    run(sys.executable, "scripts/test_profile_compare.py")
    run(sys.executable, "scripts/test_geometry_scale_native_study.py")
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo/bin/cargo")
    for command in [("fmt", "--all", "--check"), ("clippy", "--workspace", "--all-targets", "--", "-D", "warnings"), ("test", "--workspace"), ("build", "--locked")]:
        run(cargo, *command)
    binary = ROOT / "target/debug" / ("engine-lab.exe" if os.name == "nt" else "engine-lab")
    run(binary, "validate")
    run(binary,"validate","assets/scenes/materials.json")
    description = json.loads(subprocess.check_output([binary, "describe"], cwd=ROOT))
    assert description["protocol_version"] == 1
    assert "set_simulation_batching" in description["commands"]
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
                batched_metrics = request("get_metrics")["result"]["frame"]
                tile_category_order = request("get_metrics")["result"]["capabilities"]["tile_lists"]["category_order"]
                assert tile_category_order == ["fire_primitives", "smoke_lobes", "point_lights", "particle_lights"]
                assert batched_metrics["cpu_steps_this_frame"] == 120
                assert batched_metrics["cpu_simulation_submissions_this_frame"] == 20
                first = request("capture_frame", path=str(temp / "first.png"), scale=1)
                assert first["result"]["tick"] == 120, first
                request("reset", seed=42)
                request("step", ticks=120)
                request("capture_frame", path=str(temp / "replay.png"), scale=1)
                assert (temp / "first.png").read_bytes() == (temp / "replay.png").read_bytes(), "same-device replay changed"
                # The optional O05 cache must allocate only while enabled and
                # disabling it must restore the direct-sampling reference.
                assert "result" in request(
                    "set_parameter",
                    path="render.experiments.smoke_absorption_cache",
                    value=True,
                )
                request("capture_frame", path=str(temp / "absorption-cached.png"), scale=1)
                cache_on = request("get_metrics")["result"]["capabilities"]["resource_inventory"]
                assert cache_on["smoke_absorption_cache_bytes"] > 0, "absorption cache did not allocate"
                assert "result" in request(
                    "set_parameter",
                    path="render.experiments.smoke_absorption_cache",
                    value=False,
                )
                request("capture_frame", path=str(temp / "absorption-disabled.png"), scale=1)
                cache_off = request("get_metrics")["result"]["capabilities"]["resource_inventory"]
                assert cache_off["smoke_absorption_cache_bytes"] == 0, "disabled absorption cache remains resident"
                assert (temp / "first.png").read_bytes() == (temp / "absorption-disabled.png").read_bytes(), "disabling absorption cache changed direct output"
                assert request("set_simulation_batching", enabled=False)["result"]["enabled"] is False
                before_serial = request("get_metrics")["result"]
                assert before_serial["simulation_batching_enabled"] is False
                request("reset", seed=42)
                request("step", ticks=120)
                serial_metrics = request("get_metrics")["result"]["frame"]
                assert serial_metrics["cpu_steps_this_frame"] - before_serial["frame"]["cpu_steps_this_frame"] == 120
                assert serial_metrics["cpu_simulation_submissions_this_frame"] - before_serial["frame"]["cpu_simulation_submissions_this_frame"] == 120
                request("capture_frame", path=str(temp / "unbatched.png"), scale=1)
                assert (temp / "first.png").read_bytes() == (temp / "unbatched.png").read_bytes(), "serial-submit baseline changed image"
                assert request("set_simulation_batching", enabled=True)["result"]["enabled"] is True
                assert "error" in request("set_simulation_batching", enabled=True, unknown=True)
                before_rebatched_metrics = request("get_metrics")["result"]["frame"]
                request("reset", seed=42)
                request("step", ticks=120)
                rebatched_metrics = request("get_metrics")["result"]["frame"]
                assert rebatched_metrics["cpu_steps_this_frame"] - before_rebatched_metrics["cpu_steps_this_frame"] == 120
                assert rebatched_metrics["cpu_simulation_submissions_this_frame"] - before_rebatched_metrics["cpu_simulation_submissions_this_frame"] == 20
                request("capture_frame", path=str(temp / "rebatched-after-toggle.png"), scale=1)
                assert (temp / "first.png").read_bytes() == (temp / "rebatched-after-toggle.png").read_bytes(), "batching toggle/reset changed replay image"
                assert request("set_tile_lists", enabled=True, force_overflow=True)["result"]["force_overflow"] is True
                request("capture_frame", path=str(temp / "forced-overflow.png"), scale=1)
                assert (temp / "first.png").read_bytes() == (temp / "forced-overflow.png").read_bytes(), "forced per-category tile fallback changed image"
                forced_overflow_metrics = request("get_metrics")["result"]["frame"]
                assert len(forced_overflow_metrics["tile_overflow_tiles"]) == 4
                assert all(count > 0 for count in forced_overflow_metrics["tile_overflow_tiles"]), "forced overflow did not reach every candidate category"
                request("set_tile_lists", enabled=True, force_overflow=False)
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
            # Timing must remain observational: disabling its query resources
            # preserves the selected fixed-tick image exactly.
            timing_disabled_image = temp / "timing-disabled.png"
            run(
                binary,
                "capture",
                "--scene",
                scene_path,
                "--camera",
                "hero",
                "--seed",
                "42",
                "--tick",
                "120",
                "--scale",
                "1",
                "--output",
                timing_disabled_image,
                "--disable-gpu-timing",
            )
            timed_metadata = json.loads((temp / "first.json").read_text())
            untimed_metadata = json.loads(timing_disabled_image.with_suffix(".json").read_text())
            assert untimed_metadata["capabilities"]["gpu_timestamps"] is False
            assert untimed_metadata["capabilities"]["resource_inventory"]["gpu_timestamp_query_set_count"] == 0
            expected_timed_query_sets = 9 if timed_metadata["capabilities"]["gpu_timestamps"] else 0
            assert timed_metadata["capabilities"]["resource_inventory"]["gpu_timestamp_query_set_count"] == expected_timed_query_sets
            assert (temp / "first.png").read_bytes() == timing_disabled_image.read_bytes(), "disabling GPU timing changed the fixed-tick image"

            # 60 ticks in one buffered sample intentionally exceeds the six
            # asynchronous compute-query slots. Samples must be skipped and
            # reported without blocking or losing route frames.
            saturation_report = temp / "query-slot-saturation.json"
            run(
                binary,
                "benchmark",
                "--mode",
                "buffered",
                "--duration",
                "1.1",
                "--warmup",
                "0",
                "--simulation-steps-per-frame",
                "60",
                "--output",
                saturation_report,
            )
            saturation = json.loads(saturation_report.read_text())
            rendered_samples = saturation["rendered_samples"]
            assert rendered_samples > 0
            assert len(saturation["samples"]) == rendered_samples, "buffered report lost submitted frames"
            assert saturation["duration_simulation_ticks"] == rendered_samples * 60
            assert [sample["tick"] for sample in saturation["samples"]] == [60, 120], (
                "buffered report lost or reordered fixed-tick route samples"
            )
            coverage = saturation["timing_coverage"]
            if saturation["capabilities"]["gpu_timestamps"]:
                expected_skipped = sum(
                    max(0, sample["simulation_steps_requested"] - 6)
                    for sample in saturation["samples"]
                )
                assert coverage["skipped_compute_samples"] >= expected_skipped, (
                    "compute query-slot exhaustion was not reported"
                )
            else:
                assert coverage["unavailable_reason"] == "adapter does not support TIMESTAMP_QUERY"
            fallback_image = temp / "forced-rgba16-fallback.png"
            run(binary, "capture", "--scene", scene_path, "--camera", "hero", "--seed", "42", "--tick", "120", "--scale", "1", "--output", fallback_image, "--force-rg16-fallback")
            fallback_metadata = json.loads(fallback_image.with_suffix(".json").read_text())
            fallback_inventory = fallback_metadata["capabilities"]["resource_inventory"]
            assert fallback_inventory["rg16_fallback_forced"] is True
            assert fallback_inventory["effect_depth_format"] == "Rgba16Float"
            assert fallback_inventory["smoke_volume_format"] == "Rgba16Float"
            assert (temp / "first.png").read_bytes() == fallback_image.read_bytes(), "RGBA16F fallback changed the fixed-tick image"
            dual_scene = ROOT / "assets/scenes/two-emitter-review.json"
            reversed_dual_scene = temp / "two-emitter-reversed.json"
            dual_definition = json.loads(dual_scene.read_text())
            dual_definition["emitters"].reverse()
            reversed_dual_scene.write_text(json.dumps(dual_definition))
            dual_images = {}
            for name, scene_arg, flags in [
                ("tiled", dual_scene, []),
                ("exhaustive", dual_scene, ["--disable-tile-lists"]),
                ("forced-overflow", dual_scene, ["--force-tile-overflow"]),
                ("reversed-order", reversed_dual_scene, []),
            ]:
                image = temp / f"dual-{name}.png"
                run(
                    binary,
                    "capture",
                    "--scene",
                    scene_arg,
                    "--camera",
                    "dual-wide",
                    "--seed",
                    "42",
                    "--tick",
                    "120",
                    "--scale",
                    "1",
                    "--output",
                    image,
                    *flags,
                )
                dual_images[name] = image.read_bytes()
            assert dual_images["tiled"] == dual_images["exhaustive"], (
                "two-emitter tiled output differs from exhaustive evaluation"
            )
            assert dual_images["tiled"] == dual_images["forced-overflow"], (
                "two-emitter forced fallback changed image"
            )
            assert dual_images["tiled"] == dual_images["reversed-order"], (
                "two-emitter output depends on scene array order"
            )
            dual_cache_images = {}
            dual_cache_bytes = {}
            dual_cache_source = ROOT / "assets/scenes/two-emitter-overflow-stress.json"
            for mode, enabled in (("direct", False), ("cache8", True)):
                definition = json.loads(dual_cache_source.read_text())
                definition["render"]["absorption_cache_resolution"] = 8
                definition["render"]["experiments"]["smoke_absorption_cache"] = enabled
                scene_variant = temp / f"dual-absorption-{mode}.json"
                scene_variant.write_text(json.dumps(definition))
                image_path = temp / f"dual-absorption-{mode}.png"
                run(
                    binary,
                    "capture",
                    "--scene",
                    scene_variant,
                    "--camera",
                    "dual-wide",
                    "--seed",
                    "42",
                    "--tick",
                    "300",
                    "--scale",
                    "1",
                    "--output",
                    image_path,
                )
                metadata = json.loads(image_path.with_suffix(".json").read_text())
                dual_cache_images[mode] = image_path.read_bytes()
                dual_cache_bytes[mode] = metadata["capabilities"]["resource_inventory"]["smoke_absorption_cache_bytes"]
                assert len(metadata["scene_definition"]["emitters"]) == 2
                assert metadata["metrics"]["smoke_absorption_cache_enabled"] is enabled
                assert dual_cache_bytes[mode] == (4096 if enabled else 0)
            assert dual_cache_images["direct"] == dual_cache_images["cache8"], (
                "two-emitter 8^3 absorption cache changed the matched fixed-tick image"
            )
    if args.gpu:
        run(sys.executable, ROOT / "scripts/verify_materials.py", "--binary", binary)
        run(sys.executable, ROOT / "scripts/verify_pixel_fire.py", "--binary", binary)
    if args.native:
        run(sys.executable, ROOT / "scripts/verify_native.py", "--binary", binary)
    print(json.dumps({"verified": True, "gpu": args.gpu,"native":args.native}))


if __name__ == "__main__":
    main()
