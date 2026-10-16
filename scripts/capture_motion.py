#!/usr/bin/env python3
"""Capture fixed-tick motion through the same agent API as still captures.

PNG frames and JSON provenance require only Python's standard library. Optional
--gif uses Pillow to create a small motion preview (not a seamless loop).
"""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, default=ROOT / 'target/release/engine-lab')
    parser.add_argument('--camera', default='fire-study')
    parser.add_argument('--profile', default='effect-campfire')
    parser.add_argument('--start-tick', type=int, default=300)
    parser.add_argument('--frames', type=int, default=120)
    parser.add_argument('--stride', type=int, default=3)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/fire-motion')
    parser.add_argument('--gif', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.frames <= 600 or not 1 <= args.stride <= 60 or not 0 <= args.start_tick <= 36000:
        parser.error('frames 1..600, stride 1..60, start-tick 0..36000')
    args.output.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen([str(args.binary), 'serve', '--camera', args.camera, '--effect-profile', args.profile], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
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
            path = args.output / f'{index:04}.png'
            frames.append(request('capture_frame', path=str(path.resolve()), scale=1))
        (args.output / 'sequence.json').write_text(json.dumps({'fps': 60 / args.stride, 'profile': args.profile, 'frames': frames}, indent=2) + '\n')
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
