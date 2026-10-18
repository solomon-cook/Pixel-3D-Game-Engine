#!/usr/bin/env python3
"""Measure O06 snapshot depth-guard changes on the optical motion route."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import statistics
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from optical_factorial_study import ROOT, ROUTE, variants

SOURCE_SHADER = ROOT / "crates/engine/src/render/shaders"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(binary: Path, scene: Path, shaders: Path, destination: Path,
            frames: int, stride: int, start_tick: int) -> dict:
    subprocess.run([
        "python3", str(ROOT / "scripts/capture_motion.py"),
        "--binary", str(binary), "--scene", str(scene), "--camera", "mixed-close",
        "--seed", "42", "--route", ROUTE, "--start-tick", str(start_tick),
        "--frames", str(frames), "--stride", str(stride), "--shaders", str(shaders),
        "--output", str(destination),
    ], cwd=ROOT, check=True)
    return json.loads((destination / "sequence.json").read_text())


def frame_error(base: Image.Image, candidate: Image.Image) -> tuple[float, int, int, tuple[int, int] | None]:
    difference = ImageChops.difference(base, candidate)
    channels = difference.split()
    histograms = [channel.histogram() for channel in channels]
    pixel_count = difference.width * difference.height
    mean = sum(value * count for hist in histograms for value, count in enumerate(hist)) / (pixel_count * 3)
    maximum = max((value for hist in histograms for value, count in enumerate(hist) if count), default=0)
    changed = 0
    peak_coordinate = None
    peak_value = -1
    for index, pixel in enumerate(difference.getdata()):
        value = max(pixel)
        if value:
            changed += 1
        if value > peak_value:
            peak_value = value
            peak_coordinate = (index % difference.width, index // difference.width)
    return mean, maximum, changed, peak_coordinate


def analyze(reference: dict, candidate: dict) -> tuple[dict, tuple[Image.Image, Image.Image, Image.Image], int]:
    base_frames, candidate_frames = reference["frames"], candidate["frames"]
    frame_errors, temporal_errors = [], []
    max_channel = max_changed = 0
    peak = (-1, -1, 0, None)
    state_match = True
    previous_base = previous_candidate = None
    peak_images = None
    peak_index = 0
    for index, (base_frame, frame) in enumerate(zip(base_frames, candidate_frames)):
        if base_frame["tick"] != frame["tick"] or base_frame["camera"] != frame["camera"]:
            raise RuntimeError(f"frame {index}: tick/camera mismatch")
        base_metadata = json.loads(Path(base_frame["metadata"]).read_text())
        metadata = json.loads(Path(frame["metadata"]).read_text())
        state_match &= all(
            base_metadata["metrics"].get(key) == metadata["metrics"].get(key)
            for key in ("fire_primitives_full", "fire_segments_full", "embers", "particle_lights", "flame_fragments")
        )
        base_image = Image.open(base_frame["image"]).convert("RGB")
        image = Image.open(frame["image"]).convert("RGB")
        mean, maximum, changed, coordinate = frame_error(base_image, image)
        frame_errors.append(mean)
        max_channel = max(max_channel, maximum)
        max_changed = max(max_changed, changed)
        if maximum > peak[0]:
            peak = (maximum, index, changed, coordinate)
            peak_images = (base_image.copy(), image.copy(), ImageChops.difference(base_image, image))
            peak_index = index
        if previous_base is not None:
            base_change = ImageChops.difference(base_image, previous_base)
            candidate_change = ImageChops.difference(image, previous_candidate)
            temporal_errors.append(frame_error(base_change, candidate_change)[0])
        previous_base, previous_candidate = base_image, image
    if len(base_frames) != len(candidate_frames):
        raise RuntimeError("frame counts differ")
    ordered_frame, ordered_temporal = sorted(frame_errors), sorted(temporal_errors)
    p95 = lambda values: values[int(0.95 * (len(values) - 1))]
    return ({
        "frame_count": len(candidate_frames),
        "effect_counts_match_every_frame": state_match,
        "frame_rgb_mae_mean": statistics.mean(frame_errors),
        "frame_rgb_mae_p95": p95(ordered_frame),
        "frame_rgb_mae_max": max(frame_errors),
        "temporal_change_magnitude_rgb_mae_mean": statistics.mean(temporal_errors),
        "temporal_change_magnitude_rgb_mae_p95": p95(ordered_temporal),
        "max_channel_difference": max_channel,
        "maximum_changed_pixels_per_frame": max_changed,
        "peak": {"channel_difference": peak[0], "frame_index": peak[1],
                 "tick": candidate_frames[peak[1]]["tick"], "changed_pixels": peak[2],
                 "coordinate_xy": list(peak[3]) if peak[3] else None},
    }, peak_images, peak_index)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o06-o08/temporal-depth-guard")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o06-temporal-depth-guard.json")
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--start-tick", type=int, default=300)
    args = parser.parse_args()
    if not 2 <= args.frames <= 600 or not 1 <= args.stride <= 60 or not 0 <= args.start_tick <= 36000:
        parser.error("frames must be 2..600, stride 1..60, and start-tick 0..36000")
    binary, output = args.binary.resolve(), args.output.resolve()
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)
    scenes = variants()
    scene_paths = {}
    for name in ("direct_copy_rgba16", "reuse_copy_rgba16"):
        path = output / "scenes" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(scenes[name], indent=2) + "\n")
        scene_paths[name] = path

    shader_current = output / "shaders-current"
    shader_tight = output / "shaders-very-tight"
    shader_exact = output / "shaders-exact-depth"
    shader_alphas = {limit: output / f"shaders-alpha-{limit:.2f}" for limit in (0.05, 0.10, 0.25)}
    shader_radiance = {limit: output / f"shaders-foreground-{limit:g}" for limit in (0.5, 2.0, 8.0)}
    shader_normals = {limit: output / f"shaders-normal-dot-{limit:.2f}" for limit in (0.90, 0.95, 0.99)}
    for path in (shader_current, shader_tight, shader_exact, *shader_alphas.values(), *shader_radiance.values(), *shader_normals.values()):
        if path.exists():
            shutil.rmtree(path)
        shutil.copytree(SOURCE_SHADER, path)
    shader_path = shader_tight / "optical.wgsl"
    shader = shader_path.read_text()
    needle = "max(0.002,expected_depth*0.0005)"
    if needle not in shader:
        raise RuntimeError("current O06 depth-guard pattern changed; update study before running")
    shader_path.write_text(shader.replace(needle, "max(0.0005,expected_depth*0.0001)"))
    exact_path = shader_exact / "optical.wgsl"
    exact_path.write_text(shader.replace(needle, "0."))
    alpha_condition = "if sampled_normal_depth.w>0. && abs(sampled_normal_depth.w-expected_depth)<=depth_tolerance {"
    base_shader = (SOURCE_SHADER / "optical.wgsl").read_text()
    if base_shader.count(alpha_condition) != 1:
        raise RuntimeError("O06 depth-match condition changed; update alpha study before running")
    for limit, directory in shader_alphas.items():
        path = directory / "optical.wgsl"
        path.write_text(base_shader.replace(
            alpha_condition,
            f"if sampled_normal_depth.w>0. && abs(sampled_normal_depth.w-expected_depth)<=depth_tolerance && foreground.a<={limit:.2f} {{",
        ))
    for limit, directory in shader_radiance.items():
        path = directory / "optical.wgsl"
        path.write_text(base_shader.replace(
            alpha_condition,
            "if sampled_normal_depth.w>0. && abs(sampled_normal_depth.w-expected_depth)<=depth_tolerance && "
            f"max(foreground.r,max(foreground.g,foreground.b))<={limit:.1f} {{",
        ))
    for limit, directory in shader_normals.items():
        path = directory / "optical.wgsl"
        path.write_text(base_shader.replace(
            alpha_condition,
            "if sampled_normal_depth.w>0. && abs(sampled_normal_depth.w-expected_depth)<=depth_tolerance && "
            f"dot(normalize(sampled_normal_depth.xyz),normalize(v.normal))>={limit:.2f} {{",
        ))

    direct_sequence = capture(binary, scene_paths["direct_copy_rgba16"], shader_current,
                              output / "frames-direct", args.frames, args.stride, args.start_tick)
    current_sequence = capture(binary, scene_paths["reuse_copy_rgba16"], shader_current,
                               output / "frames-current", args.frames, args.stride, args.start_tick)
    tight_sequence = capture(binary, scene_paths["reuse_copy_rgba16"], shader_tight,
                             output / "frames-very-tight", args.frames, args.stride, args.start_tick)
    exact_sequence = capture(binary, scene_paths["reuse_copy_rgba16"], shader_exact,
                             output / "frames-exact-depth", args.frames, args.stride, args.start_tick)
    current, _, _ = analyze(direct_sequence, current_sequence)
    tight, peak_images, peak_index = analyze(direct_sequence, tight_sequence)
    exact, _, _ = analyze(direct_sequence, exact_sequence)
    alpha_results = {}
    for limit, directory in shader_alphas.items():
        sequence = capture(binary, scene_paths["reuse_copy_rgba16"], directory,
                           output / f"frames-alpha-{limit:.2f}", args.frames, args.stride, args.start_tick)
        result, _, _ = analyze(direct_sequence, sequence)
        alpha_results[f"{limit:.2f}"] = result
    radiance_results = {}
    for limit, directory in shader_radiance.items():
        sequence = capture(binary, scene_paths["reuse_copy_rgba16"], directory,
                           output / f"frames-foreground-{limit:g}", args.frames, args.stride, args.start_tick)
        result, _, _ = analyze(direct_sequence, sequence)
        radiance_results[f"{limit:g}"] = result
    normal_results = {}
    for limit, directory in shader_normals.items():
        sequence = capture(binary, scene_paths["reuse_copy_rgba16"], directory,
                           output / f"frames-normal-dot-{limit:.2f}", args.frames, args.stride, args.start_tick)
        result, _, _ = analyze(direct_sequence, sequence)
        normal_results[f"{limit:.2f}"] = result
    sheet = Image.new("RGB", (1280, 380), (22, 22, 22))
    labels = ("direct RGBA16F", "very-tight reuse", "3x difference")
    for index, image in enumerate((peak_images[0], peak_images[1], peak_images[2].point(lambda c: min(255, c * 3)))):
        sheet.paste(image.resize((420, 236)), (index * 426, 24))
        ImageDraw.Draw(sheet).text((index * 426 + 4, 4), labels[index], fill="white")
    contact_path = output / "peak-frame-contact.png"
    sheet.save(contact_path)

    report = {
        "date": "2026-10-18",
        "workstream": "O06 moving-camera temporal depth-guard probe",
        "host": {"device": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "scene_source": "optical_factorial_study.mixed_scene with high-dynamic overrides",
        "scene_sha256": {name: sha256(path) for name, path in scene_paths.items()},
        "binary_sha256": sha256(binary),
        "capture_script_sha256": direct_sequence["capture_script_sha256"],
        "study_script_sha256": sha256(Path(__file__).resolve()),
        "shader_sha256": {
            "current": sha256(shader_current / "optical.wgsl"),
            "very_tight": sha256(shader_tight / "optical.wgsl"),
            "exact_depth": sha256(shader_exact / "optical.wgsl"),
            **{f"alpha_{limit:.2f}": sha256(path / "optical.wgsl") for limit, path in shader_alphas.items()},
            **{f"foreground_{limit:g}": sha256(path / "optical.wgsl") for limit, path in shader_radiance.items()},
            **{f"normal_dot_{limit:.2f}": sha256(path / "optical.wgsl") for limit, path in shader_normals.items()},
        },
        "route": ROUTE,
        "camera": "mixed-close",
        "resolution": [640, 360],
        "seed": 42,
        "start_tick": args.start_tick,
        "end_tick": direct_sequence["frames"][-1]["tick"],
        "frames": args.frames,
        "fps": 60 / args.stride,
        "guard_values": {"current": {"absolute_floor": 0.002, "relative_depth_tolerance": 0.0005},
                         "very_tight": {"absolute_floor": 0.0005, "relative_depth_tolerance": 0.0001},
                         "exact_depth": {"absolute_floor": 0.0, "relative_depth_tolerance": 0.0},
                         "foreground_alpha_maximum": [0.05, 0.10, 0.25],
                         "foreground_rgb_maximum": [0.5, 2.0, 8.0],
                         "surface_normal_dot_minimum": [0.90, 0.95, 0.99]},
        "current_guard": current,
        "very_tight_guard": tight,
        "exact_depth_guard": exact,
        "foreground_alpha_gates": alpha_results,
        "foreground_radiance_gates": radiance_results,
        "surface_normal_alignment_gates": normal_results,
        "strict_guard_reduced_total_pixel_error": tight["frame_rgb_mae_mean"] < current["frame_rgb_mae_mean"],
        "peak_frame_contact": {"path": str(contact_path.relative_to(ROOT)), "sha256": sha256(contact_path), "frame_index": peak_index},
        "interpretation": "Tighter and exact-depth, foreground-alpha, foreground-radiance, and surface-normal alignment guards are explicit fallback-to-direct conditions. This experiment measures image quality only and does not establish performance or promotion suitability.",
        "limitations": ["One offscreen M1 Max/Metal route; native-window and other-adapter checks remain open.",
                        "The fixed-camera experiment and this one orbit do not establish continuous human playback acceptance."],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "current_peak": current["peak"],
                      "very_tight_peak": tight["peak"],
                      "strict_guard_reduced_total_pixel_error": report["strict_guard_reduced_total_pixel_error"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
