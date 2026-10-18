#!/usr/bin/env python3
"""Capture fixed-tick motion through the same agent API as still captures.

PNG frames and JSON provenance require only Python's standard library. Optional
--gif uses Pillow to create a small motion preview (not a seamless loop).
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def route_camera_at(route, base_camera, seconds):
    time = seconds % route['duration_seconds']
    keyframes = route['keyframes']
    index = max(0, min(len(keyframes) - 2, next(
        (i - 1 for i, keyframe in enumerate(keyframes) if keyframe['time'] > time),
        len(keyframes) - 2,
    )))
    first, second = keyframes[index:index + 2]
    span = second['time'] - first['time']
    amount = max(0.0, min(1.0, (time - first['time']) / span))
    return {
        **base_camera,
        'position': [a + (b - a) * amount for a, b in zip(first['position'], second['position'])],
        'target': [a + (b - a) * amount for a, b in zip(first['target'], second['target'])],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, default=ROOT / 'target/release/engine-lab')
    parser.add_argument('--shaders', type=Path, help='override WGSL shader directory for a renderer experiment')
    parser.add_argument('--camera', default='fire-study')
    parser.add_argument('--scene', type=Path, default=ROOT / 'assets/scenes/clearing.json')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--profile', default='effect-campfire')
    parser.add_argument('--experiments', help='comma-separated renderer experiments')
    parser.add_argument('--force-rg16-fallback', action='store_true', help='force the RGBA16F effect-target fallback')
    parser.add_argument('--route', help='camera route ID from the scene; updates the camera at every frame')
    parser.add_argument('--route-start', type=float, default=0, help='camera-route time in seconds at frame zero')
    parser.add_argument('--start-tick', type=int, default=300)
    parser.add_argument('--frames', type=int, default=120)
    parser.add_argument('--stride', type=int, default=3)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/fire-motion')
    parser.add_argument('--gif', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.frames <= 600 or not 1 <= args.stride <= 60 or not 0 <= args.start_tick <= 36000:
        parser.error('frames 1..600, stride 1..60, start-tick 0..36000')
    if not math.isfinite(args.route_start) or args.route_start < 0:
        parser.error('--route-start must be finite and nonnegative')
    if not args.scene.is_file():
        parser.error(f'scene does not exist: {args.scene}')
    args.scene = args.scene.resolve()
    args.binary = args.binary.resolve()
    if args.shaders:
        args.shaders = args.shaders.resolve()
        if not args.shaders.is_dir():
            parser.error(f'shader directory does not exist: {args.shaders}')
    scene = json.loads(args.scene.read_text())
    route = next((route for route in scene.get('routes', []) if route.get('id') == args.route), None) if args.route else None
    if args.route and route is None:
        parser.error(f"route '{args.route}' not found in scene")
    base_camera = next((camera for camera in scene.get('cameras', []) if camera.get('id') == args.camera), None)
    if base_camera is None:
        parser.error(f"camera '{args.camera}' not found in scene")
    args.output.mkdir(parents=True, exist_ok=True)
    command = [str(args.binary), 'serve', '--scene', str(args.scene.resolve()), '--seed', str(args.seed), '--camera', args.camera]
    if args.profile:
        command.extend(['--effect-profile', args.profile])
    if args.experiments:
        command.extend(['--experiments', args.experiments])
    if args.shaders:
        command.extend(['--shaders', str(args.shaders)])
    if args.force_rg16_fallback:
        command.append('--force-rg16-fallback')
    process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    counter = 0

    def request(method, **params):
        nonlocal counter
        counter += 1
        process.stdin.write(json.dumps({'id': counter, 'method': method, 'params': params}) + '\n')
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        if 'error' in response:
            raise RuntimeError(response)
        assert response['id'] == counter
        return response['result']

    frames = []
    try:
        request('step', ticks=args.start_tick)
        for index in range(args.frames):
            if index:
                request('step', ticks=args.stride)
            if route:
                camera = route_camera_at(route, base_camera, args.route_start + index * args.stride / 60)
                request('set_camera', camera=camera)
            path = args.output / f'{index:04}.png'
            frames.append(request('capture_frame', path=str(path.resolve()), scale=1))
        sequence = {
            'fps': 60 / args.stride,
            'camera': args.camera,
            'scene': str(args.scene.resolve()),
            'scene_sha256': hashlib.sha256(args.scene.read_bytes()).hexdigest(),
            'binary': str(args.binary),
            'binary_sha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(),
            'shaders': str(args.shaders) if args.shaders else None,
            'shader_sha256': hashlib.sha256((args.shaders / 'optical.wgsl').read_bytes()).hexdigest() if args.shaders and (args.shaders / 'optical.wgsl').is_file() else None,
            'capture_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'seed': args.seed,
            'profile': args.profile,
            'experiments': args.experiments,
            'force_rg16_fallback': args.force_rg16_fallback,
            'route': args.route,
            'route_start_seconds': args.route_start if route else None,
            'start_tick': args.start_tick,
            'frame_stride_ticks': args.stride,
            'frames': frames,
        }
        (args.output / 'sequence.json').write_text(json.dumps(sequence, indent=2) + '\n')
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    if args.gif:
        from PIL import Image
        images = [Image.open(frame['image']).convert('RGB') for frame in frames]
        # Fixed palette prevents an independent palette change on every frame.
        palette = images[0].quantize(colors=256)
        indexed = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
        indexed[0].save(args.output / 'preview.gif', save_all=True, append_images=indexed[1:], duration=round(args.stride / 60 * 1000 / 10) * 10, loop=0)
        # Full-colour APNG preserves the captured colours and exact frame period.
        images[0].save(args.output / 'preview.png', save_all=True, append_images=images[1:], duration=args.stride / 60 * 1000, loop=0)
    print(json.dumps({'sequence': str(args.output), 'frames': len(frames), 'fps': 60 / args.stride}))


if __name__ == '__main__':
    main()
