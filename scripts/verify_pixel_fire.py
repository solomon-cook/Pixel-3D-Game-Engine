#!/usr/bin/env python3
"""Verify solid colour coverage, shimmer and foreground protection on a real GPU."""
import argparse
import json
import os
from pathlib import Path
import struct
import shutil
import subprocess
import tempfile
import zlib

ROOT=Path(__file__).resolve().parents[1]


def pixels(path):
    """Read the engine's 8-bit RGB/RGBA PNGs using only the standard library."""
    data=path.read_bytes();offset=8;compressed=bytearray()
    while offset<len(data):
        count=struct.unpack_from('>I',data,offset)[0];kind=data[offset+4:offset+8];chunk=data[offset+8:offset+8+count];offset+=count+12
        if kind==b'IHDR':
            width,height,bits,color,_,_,interlace=struct.unpack('>IIBBBBB',chunk)
            assert bits==8 and color in (2,6) and interlace==0
        elif kind==b'IDAT':compressed.extend(chunk)
    channels=3 if color==2 else 4;stride=width*channels;raw=zlib.decompress(compressed);previous=bytearray(stride);result=[]
    for y in range(height):
        start=y*(stride+1);mode=raw[start];row=bytearray(raw[start+1:start+1+stride])
        for i in range(stride):
            a=row[i-channels] if i>=channels else 0;b=previous[i];c=previous[i-channels] if i>=channels else 0
            if mode==1:predict=a
            elif mode==2:predict=b
            elif mode==3:predict=(a+b)//2
            elif mode==4:
                p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c);predict=a if pa<=pb and pa<=pc else b if pb<=pc else c
            else:assert mode==0;predict=0
            row[i]=(row[i]+predict)&255
        result.extend(tuple(row[i:i+3]) for i in range(0,stride,channels));previous=row
    return width,height,result


def verify(binary):
    with tempfile.TemporaryDirectory(prefix='pixel-fire-') as tmp:
        temp=Path(tmp);shaders=temp/"shaders";shutil.copytree(ROOT/"crates/engine/src/render/shaders",shaders);scene=json.loads((ROOT/'assets/scenes/clearing.json').read_text())
        scene['environment'].update(sky_color=[0,0,0],horizon_color=[0,0,0],ambient=[0,0,0],fog_density=0,wind=[0,0,0])
        for light in scene['lights']:light['color']=[0,0,0]
        scene['render'].update(bloom_strength=0,palette_strength=0,dither_strength=0)
        scene['emitters'][0]['smoke_density']=0
        scene['cameras']=[dict(id='hero',position=[0,1.2,6],target=[0,1.2,0],projection=dict(kind='orthographic',height=3))]
        scene['routes']=[]
        scene['objects']=[dict(id='test-far',material='earth',geometry=dict(kind='cube'),position=[50,50,0],scale=[1,1,1])]
        profile=next(p for p in scene['effects'] if p['id']=='effect-campfire');profile['fire'].update(solid=True,heat_distortion=0,color_bands=4)
        def session(scene_path,callback):
            process=subprocess.Popen([str(binary),'serve','--scene',str(scene_path),'--shaders',str(shaders)],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True);counter=0
            def call(method,**params):
                nonlocal counter
                counter+=1;process.stdin.write(json.dumps(dict(id=counter,method=method,params=params))+'\n');process.stdin.flush()
                response=json.loads(process.stdout.readline());assert response['id']==counter,response;return response
            def capture(name):
                path=temp/(name+'.png');response=call('capture_frame',path=str(path),scale=1);assert 'result' in response,response;return pixels(path)
            try:callback(call,capture)
            finally:process.stdin.close();process.wait(timeout=30)
            assert process.returncode==0
        path=temp/'fire.json';path.write_text(json.dumps(scene))
        def coverage(call,capture):
            call('step',ticks=300);solid=capture('solid');count=len(set(solid[2]));assert 2<count<=5,('solid flame is not discrete',count)
            state=call('inspect_effects')['result']
            call('set_parameter',path='effects.effect-campfire.fire.solid',value=False)
            soft=capture('soft');assert len(set(soft[2]))>16,'soft alternative lost its gradients'
            assert state==call('inspect_effects')['result'],'presentation controls changed simulation/light state'
            call('set_parameter',path='effects.effect-campfire.fire.solid',value=True)
            call('set_parameter',path='effects.effect-campfire.fire.color_bands',value=2)
            assert len(set(capture('two-bands')[2]))<=3
            working=capture('working')
            shader=shaders/'post.wgsl';source=shader.read_text();shader.write_text('invalid pixel heat shader')
            assert 'error' in call('reload_shaders')
            assert working==capture('post-rollback'),'failed post reload replaced working pipelines'
            shader.write_text(source);assert 'result' in call('reload_shaders')
            for field,value in [('color_bands',1),('heat_distortion',5),('heat_distortion_height',0),('solid','yes')]:
                assert 'error' in call('set_parameter',path='effects.effect-campfire.fire.'+field,value=value)
        session(path,coverage)
        # A striped foreground board must stay intact while stripes behind the
        # hot-air column move. An orthographic camera gives an exact test ROI.
        scene['materials'] += [dict(id='test-white',color=[1,1,1],emission=1),dict(id='test-blue',color=[0,.1,.5],emission=1)]
        profile['fire']['emission']=0
        def box(id,material,position,scale):return dict(id=id,material=material,geometry=dict(kind='cube'),position=position,scale=scale)
        scene['objects']=[box('test-background','test-blue',[.5,1.5,-2],[4,3,.1])]
        for j in range(22):scene['objects'].append(box('test-back-stripe-'+str(j),'test-white',[-1.4+j*.17,1.5,-1.9],[.055,3,.1]))
        scene['objects'].append(box('test-foreground','test-blue',[-.5,1.8,2],[.7,1.3,.1]))
        for j in range(6):scene['objects'].append(box('test-front-stripe-'+str(j),'test-white',[-.8+j*.11,1.8,2.1],[.04,1.3,.1]))
        path.write_text(json.dumps(scene))
        def shimmer(call,capture):
            call('step',ticks=300);before=capture('no-heat')
            call('set_parameter',path='effects.effect-campfire.fire.heat_distortion',value=4)
            after=capture('heat');assert before!=after,'heat has no visible effect'
            width=before[0]
            for y in range(36,180):
                for x in range(224,296):assert before[2][y*width+x]==after[2][y*width+x],'heat distorted foreground geometry'
            assert after==capture('heat-replay'),'fixed-tick shimmer changed'
            call('set_parameter',path='effects.effect-campfire.fire.heat_distortion',value=0)
            assert before==capture('heat-restored'),'heat-off did not restore original pixels'
        session(path,shimmer)
    print(json.dumps(dict(pixel_fire_gpu_verified=True)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--binary',type=Path,default=ROOT/'target/debug'/('engine-lab.exe' if os.name=='nt' else 'engine-lab'))
    verify(parser.parse_args().binary.resolve())
