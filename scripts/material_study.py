#!/usr/bin/env python3
"""Matched material captures, camera motion and optional 120-second route costs.

Uses only the standard library. --preview adds optional Pillow APNG output.
Reports distinguish complete material variants from isolated pass timings.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--binary',type=Path,default=ROOT/'target/release'/('engine-lab.exe' if os.name=='nt' else 'engine-lab'))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/material-study')
    parser.add_argument('--benchmark',action='store_true')
    parser.add_argument('--motion',action='store_true')
    parser.add_argument('--preview',action='store_true')
    args=parser.parse_args();args.binary=args.binary.resolve();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=True)
    source=json.loads((ROOT/'assets/scenes/materials.json').read_text())
    variants={'full':source,'environment-only':json.loads(json.dumps(source)),'diffuse-baseline':json.loads(json.dumps(source))}
    variants['environment-only']['render']['reflection_steps']=0
    for material in variants['diffuse-baseline']['materials']:
        material.update(metallic=0,reflectivity=0,transmission=0,subsurface=0)
    report={'version':1,'seed':42,'capture_tick':300,'comparison':'Same geometry, lights, simulation and selected pixel grid. Complete material modes, not isolated GPU pass timings. Offscreen unpaced; excludes native presentation/UI. GPU render timestamps exclude smoke compute.','variants':{},'source_hashes':{}}
    for path in [ROOT/'Cargo.lock',ROOT/'assets/scenes/materials.json',*sorted((ROOT/'crates').rglob('*.rs')),*sorted((ROOT/'crates').rglob('*.wgsl'))]:
        report['source_hashes'][str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name,scene in variants.items():
        directory=args.output/name;directory.mkdir(exist_ok=True)
        scene_path=directory/'scene.json';scene_path.write_text(json.dumps(scene,indent=2)+'\n')
        process=subprocess.Popen([str(args.binary),'serve','--scene',str(scene_path)],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        sequence=0
        def request(method,**params):
            nonlocal sequence
            sequence+=1;process.stdin.write(json.dumps(dict(id=sequence,method=method,params=params))+'\n');process.stdin.flush()
            response=json.loads(process.stdout.readline());assert response['id']==sequence,response
            if 'error' in response:raise RuntimeError(response)
            return response['result']
        try:
            request('step',ticks=300)
            captures=[]
            for camera in scene['cameras']:
                request('set_camera',id=camera['id'])
                captures.append(request('capture_frame',path=str(directory/(camera['id']+'.png')),scale=2))
            report['variants'][name]={'captures':captures,'capabilities':request('get_metrics')['capabilities']}
            if args.motion and name=='full':
                frames=[];motion=directory/'motion';motion.mkdir(exist_ok=True)
                for index in range(120):
                    f=index/119
                    camera=dict(id='motion-review',position=[8-15*f,7.6-2.1*f,14-f],target=[-.4,1,0],projection=dict(kind='perspective',fov_degrees=44))
                    request('set_camera',camera=camera)
                    if index:request('step',ticks=3)
                    frames.append(request('capture_frame',path=str(motion/f'{index:04}.png'),scale=1))
                (motion/'sequence.json').write_text(json.dumps(dict(fps=20,seamless=False,frames=frames),indent=2)+'\n')
                if args.preview:
                    from PIL import Image
                    images=[Image.open(f['image']).convert('RGB') for f in frames]
                    images[0].save(motion/'preview.png',save_all=True,append_images=images[1:],duration=50,loop=0)
                report['variants'][name]['motion']=str(motion/'sequence.json')
        finally:
            process.stdin.close();process.wait(timeout=30)
        if process.returncode:raise RuntimeError(f'{name} renderer exited {process.returncode}')
        if args.benchmark:
            output=directory/'benchmark.json'
            subprocess.run([str(args.binary),'benchmark','--scene',str(scene_path),'--route','material-orbit','--duration','120','--warmup','10','--output',str(output)],cwd=ROOT,check=True)
            measured=json.loads(output.read_text())
            report['variants'][name]['benchmark']={k:measured[k] for k in ['scope','seed','route_seconds','sample_hz','warmup_seconds','capabilities','frame_work','cpu_encode','simulation_cpu','gpu_render']}
            report['variants'][name]['benchmark']['raw_report']=str(output)
    path=args.output/'comparison.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(material_study=str(path),benchmarked=args.benchmark,motion=args.motion)))


if __name__=='__main__':main()
