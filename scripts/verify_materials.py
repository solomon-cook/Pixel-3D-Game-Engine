#!/usr/bin/env python3
"""Real GPU material/protocol checks; no image libraries or visual claims."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def verify(binary):
    with tempfile.TemporaryDirectory(prefix='pixel-materials-') as tmp:
        temp=Path(tmp)
        shutil.copytree(ROOT/'crates/engine/src/render/shaders',temp/'shaders')
        process=subprocess.Popen([str(binary),'serve','--scene',str(ROOT/'assets/scenes/materials.json'),'--shaders',str(temp/'shaders')],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        sequence=0
        def call(method,**params):
            nonlocal sequence
            sequence+=1
            process.stdin.write(json.dumps(dict(id=sequence,method=method,params=params))+'\n');process.stdin.flush()
            response=json.loads(process.stdout.readline())
            assert response['id']==sequence,response
            return response
        def capture(name):
            path=temp/(name+'.png')
            response=call('capture_frame',path=str(path),scale=1)
            assert 'result' in response,response
            return path.read_bytes()
        def set_value(path,value):
            response=call('set_parameter',path=path,value=value)
            assert 'result' in response,response
        try:
            call('step',ticks=120)
            first=capture('hero')
            call('reset',seed=42);call('step',ticks=120)
            assert first==capture('replay'),'material replay changed'
            for camera,edits in [
                ('metal-close',[('materials.chrome.metallic',0.),('materials.copper.roughness',.9),('render.reflection_steps',0)]),
                ('glass-close',[('materials.glass.transmission',0.),('materials.glass.ior',1.),('materials.glass.absorption',[4.,.1,.1])]),
                ('subsurface-close',[('materials.wax.subsurface',0.),('materials.wax.thickness',5.),('materials.wax.scatter_color',[1.,0.,0.])]),
            ]:
                call('set_camera',id=camera)
                for index,(path,value) in enumerate(edits):
                    section,material,*rest=path.split('.')
                    original=call('inspect_scene',section=section)['result']
                    if section=='materials': original=next(m for m in original if m['id']==material)[rest[0]]
                    else:original=original[material]
                    baseline=capture(camera+str(index)+'-before')
                    set_value(path,value)
                    changed=capture(camera+str(index)+'-after')
                    assert baseline!=changed,(path,'has no visible effect')
                    set_value(path,original)
                    assert baseline==capture(camera+str(index)+'-restored'),(path,'did not restore')
            for path,value in [('materials.glass.ior',.5),('materials.chrome.metallic',2),('materials.wax.thickness',-1),('render.reflection_steps',17)]:
                assert 'error' in call('set_parameter',path=path,value=value)
            call('set_camera',id='orthographic');capture('orthographic')
            call('set_camera',id='hero');working=capture('working')
            shader=temp/'shaders/optical.wgsl';source=shader.read_text();shader.write_text('invalid optical shader')
            assert 'error' in call('reload_shaders')
            assert working==capture('rollback'),'bad optical reload replaced working pipelines'
            shader.write_text(source);assert 'result' in call('reload_shaders')
            assert working==capture('reload'),'successful reload changed fixed-tick image'
            call('set_camera',id='glass-close')
            optical_direct=capture('optical-direct')
            set_value('render.experiments.optical_surface_reuse',True)
            optical_reuse=capture('optical-reuse')
            assert call('get_metrics')['result']['frame']['optical_surface_reuse_enabled'] is True
            assert optical_direct==optical_reuse,'optical surface reuse changed the matched glass image'
            set_value('render.experiments.optical_surface_reuse',False)
            assert optical_direct==capture('optical-direct-restored'),'disabling optical surface reuse did not restore direct output'
            assert call('get_metrics')['result']['capabilities']['resolution']==[640,360]
            assert call('get_metrics')['result']['capabilities']['transmission_layers']==1
        finally:
            process.stdin.close();process.wait(timeout=30)
        assert process.returncode==0
    print(json.dumps(dict(material_gpu_verified=True)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--binary',type=Path,default=ROOT/'target/debug'/('engine-lab.exe' if os.name=='nt' else 'engine-lab'))
    verify(parser.parse_args().binary.resolve())
