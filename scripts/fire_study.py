#!/usr/bin/env python3
"""Matched flame structure / particle-light captures and optional route costs."""
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
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/fire-study')
    parser.add_argument('--benchmark',action='store_true')
    args=parser.parse_args();binary=args.binary.resolve();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    scene=json.loads((ROOT/'assets/scenes/clearing.json').read_text())
    report={'version':1,'seed':42,'tick':300,'comparison':'Same geometry, camera route, lights, pixel grid and simulation. Comparing rounded curves/branches and particle lighting, not isolated per-pass timings. GPU timestamps exclude smoke compute; offscreen unpaced, no presentation/UI.','source_hashes':{},'variants':{}}
    for path in [ROOT/'Cargo.lock',ROOT/'assets/scenes/clearing.json',*sorted((ROOT/'crates').rglob('*.rs')),*sorted((ROOT/'crates').rglob('*.wgsl'))]:
        report['source_hashes'][str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ['clustered-lit','clustered-unlit','long-curves-unlit']:
        variant=json.loads(json.dumps(scene))
        for profile in variant['effects']:
            if name!='clustered-lit':profile['fire']['particle_lights']=0
            if name=='long-curves-unlit':profile['fire'].update(lobe_roundness=0,branches=0)
        directory=output/name;directory.mkdir(exist_ok=True);path=directory/'scene.json';path.write_text(json.dumps(variant,indent=2)+'\n')
        captures=[]
        for camera in ['hero','fire-study','smoke-close','orthographic']:
            capture=directory/(camera+'.png')
            result=json.loads(subprocess.check_output([str(binary),'capture','--scene',str(path),'--camera',camera,'--seed','42','--tick','300','--scale','2','--output',str(capture)],cwd=ROOT))
            captures.append(result)
        report['variants'][name]={'captures':captures}
        if args.benchmark:
            measured=directory/'benchmark.json'
            subprocess.run([str(binary),'benchmark','--scene',str(path),'--route','clearing-orbit','--duration','120','--warmup','10','--output',str(measured)],cwd=ROOT,check=True)
            data=json.loads(measured.read_text());report['variants'][name]['benchmark']={key:data[key] for key in ['scope','seed','route_seconds','sample_hz','warmup_seconds','capabilities','frame_work','cpu_encode','simulation_cpu','gpu_render']}
    result=output/'comparison.json';result.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(dict(fire_study=str(result))))


if __name__=='__main__':main()
