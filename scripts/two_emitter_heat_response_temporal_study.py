#!/usr/bin/env python3
"""Compare source-one opaque heat response over the full dual-emitter camera route."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import subprocess
import shutil
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/two-emitter-review.json"
ROUTE_ID, CAMERA_ID = "clearing-orbit", "dual-wide"
SEED, START_TICK, RESPONSE = 42, 300, 0.8

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def image_metrics(image: Image.Image) -> dict:
    hist = image.histogram()[:768]
    channels = (hist[:256], hist[256:512], hist[512:768])
    pixels = image.width * image.height
    mae = sum(v * count for channel in channels for v, count in enumerate(channel)) / (pixels * 3)
    maximum = max((v for channel in channels for v, count in enumerate(channel) if count), default=0)
    changed = image.convert("L").point([0] + [1] * 255).histogram()[1]
    return {"mae_0_255": mae, "max_channel_error_0_255": maximum, "changed_pixels": changed, "pixels": pixels}

def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0

def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary",type=Path,default=ROOT/"target/release/engine-lab")
    ap.add_argument("--frames",type=int,default=2400)
    ap.add_argument("--stride",type=int,default=3)
    ap.add_argument("--output",type=Path,default=ROOT/"artifacts/multi-emitter/heat-response-moving-route")
    ap.add_argument("--report",type=Path,default=ROOT/"docs/measurements-multi-emitter-heat-response-temporal.json")
    a=ap.parse_args()
    if a.frames < 2 or a.stride < 1: ap.error("frames must be >=2 and stride >=1")
    binary,output,report_path=a.binary.resolve(),a.output.resolve(),a.report.resolve()
    output.mkdir(parents=True,exist_ok=True); report_path.parent.mkdir(parents=True,exist_ok=True)
    source=json.loads(SOURCE.read_text())
    route=next((r for r in source["routes"] if r["id"]==ROUTE_ID),None)
    camera=next((c for c in source["cameras"] if c["id"]==CAMERA_ID),None)
    if route is None or camera is None: ap.error("source scene is missing the named route or camera")
    variants={}
    for label,response in (("heat-off",0.0),("heat-on",RESPONSE)):
        scene=copy.deepcopy(source)
        if sorted(e["id"] for e in scene["emitters"]) != ["campfire","watchfire"]: ap.error("expected campfire and watchfire")
        for emitter in scene["emitters"]: emitter["enabled"] = emitter["id"]=="watchfire"
        material=next(m for m in scene["materials"] if m["id"]=="earth")
        material["heat_response"]=response
        scene_path=output/f"{label}.scene.json"
        scene_path.write_text(json.dumps(scene,indent=2)+"\n")
        subprocess.run([str(binary),"validate",str(scene_path)],cwd=ROOT,check=True,capture_output=True)
        seq_dir=output/label
        mode_frames=[]
        segment_records=[]
        for segment,start in enumerate(range(0,a.frames,600)):
            segment_frames=min(600,a.frames-start)
            segment_start_seconds=start*a.stride/60
            segment_dir=seq_dir/f"segment-{segment:02d}"
            cmd=["python3",str(ROOT/"scripts/capture_motion.py"),"--binary",str(binary),"--scene",str(scene_path),"--camera",CAMERA_ID,"--route",ROUTE_ID,"--route-start",str(segment_start_seconds),"--seed",str(SEED),"--profile","","--start-tick",str(START_TICK+start*a.stride),"--frames",str(segment_frames),"--stride",str(a.stride),"--output",str(segment_dir)]
            subprocess.run(cmd,cwd=ROOT,check=True)
            sequence=json.loads((segment_dir/"sequence.json").read_text())
            mode_frames.extend(sequence["frames"])
            segment_records.append({"route_start_seconds":segment_start_seconds,"start_tick":START_TICK+start*a.stride,"frames":segment_frames,"sequence":str((segment_dir/"sequence.json").relative_to(ROOT))})
        variants[label]={"frames":mode_frames,"segments":segment_records}
    off=variants["heat-off"]["frames"]; on=variants["heat-on"]["frames"]
    if len(off)!=len(on): raise RuntimeError("variant frame counts differ")
    per=[]; temporal=[]; counts_match=True; poses_match=True; device_set=set()
    prev_off=prev_on=None
    sample_indices=sorted(set((0,(a.frames-1)//4,(a.frames-1)//2,3*(a.frames-1)//4,a.frames-1)))
    samples=[]
    for i,(f0,f1) in enumerate(zip(off,on)):
        if f0["tick"]!=f1["tick"]: raise RuntimeError(f"frame {i} tick mismatch")
        if f0["metadata"] and f1["metadata"]:
            m0=json.loads(Path(f0["metadata"]).read_text()); m1=json.loads(Path(f1["metadata"]).read_text())
            poses_match &= m0["camera"]==m1["camera"]
            c0=m0["metrics"]; c1=m1["metrics"]
            counts_match &= all(c0.get(k)==c1.get(k) for k in ("fire_primitives","particle_lights","branch_segments_dropped","fire_segments_full"))
            device_set.add(m0["capabilities"].get("name")); device_set.add(m1["capabilities"].get("name"))
        im0=Image.open(f0["image"]).convert("RGB"); im1=Image.open(f1["image"]).convert("RGB")
        diff=ImageChops.difference(im1,im0)
        em=image_metrics(diff); per.append(em)
        if prev_off is not None:
            d0=ImageChops.difference(im0,prev_off); d1=ImageChops.difference(im1,prev_on)
            temporal.append(image_metrics(ImageChops.difference(d1,d0)))
        if i in sample_indices: samples.append((i,im0.copy(),im1.copy(),diff.copy()))
        prev_off,prev_on=im0,im1
    sheet=Image.new("RGB",(960,len(samples)*184),"#111")
    draw=ImageDraw.Draw(sheet)
    for row,(index,im0,im1,diff) in enumerate(samples):
        y=row*184
        for col,img in enumerate((im0,im1,diff.point(lambda x:min(255,x*5)))):
            sheet.paste(img.resize((320,180)),(col*320,y+4))
        draw.text((4,y+1),f"{index}: heat off",fill="white")
        draw.text((324,y+1),f"{index}: heat on",fill="white")
        draw.text((644,y+1),f"{index}: 5x diff",fill="white")
    sheet_path=output/"temporal-contact.png"; sheet.save(sheet_path)
    contact_report_path=report_path.with_name(report_path.stem+"-contact.png")
    if contact_report_path.resolve()!=sheet_path.resolve(): shutil.copy2(sheet_path,contact_report_path)
    errors=[x["mae_0_255"] for x in per]
    changes=[x["mae_0_255"] for x in temporal]
    report={"version":1,"date":"2026-10-18","study":"O05 source-one opaque heat-response full moving-route comparison","host":{"device":next((x for x in device_set if x),None),"backend":"Metal","native_window":False},"scene":str(SOURCE.relative_to(ROOT)),"scene_sha256":digest(SOURCE),"binary_sha256":digest(binary),"study_script_sha256":digest(Path(__file__)),"capture_script_sha256":digest(ROOT/"scripts/capture_motion.py"),"source_revision":subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip(),"emitters":{"enabled":["watchfire"],"disabled":["campfire"]},"material":"earth","heat_response":{"off":0.0,"on":RESPONSE},"seed":SEED,"camera":CAMERA_ID,"route":ROUTE_ID,"route_duration_seconds":(a.frames-1)*a.stride/60,"frames_per_variant":a.frames,"fps":60/a.stride,"start_tick":START_TICK,"end_tick":off[-1]["tick"],"resolution":[640,360],"checks":{"same_ticks":all(x["tick"]==y["tick"] for x,y in zip(off,on)),"same_camera_poses":poses_match,"fire_and_light_counts_match":counts_match,"source_isolation_configured":True},"heat_on_vs_off":{"frame_mae_mean":average(errors),"frame_mae_p95":sorted(errors)[math.ceil(.95*len(errors))-1],"max_channel_error":max(x["max_channel_error_0_255"] for x in per),"changed_pixels_mean":average([x["changed_pixels"] for x in per]),"changed_pixels_max":max(x["changed_pixels"] for x in per)},"temporal_change_difference":{"mae_mean":average(changes),"mae_p95":sorted(changes)[math.ceil(.95*len(changes))-1] if changes else 0.0,"max_channel_error":max((x["max_channel_error_0_255"] for x in temporal),default=0)},"contact_sheet":str(contact_report_path.relative_to(ROOT)) if contact_report_path.is_relative_to(ROOT) else str(contact_report_path),"contact_sheet_sha256":digest(contact_report_path),"sample_indices":sample_indices,"segments":variants["heat-off"]["segments"],"limitations":["Offscreen M1 Max/Metal route evidence only; no whole-frame performance conclusion, native playback or other-adapter acceptance.","Heat-response output indicates a designed gameplay cue and is not a calibrated temperature visualization.","Temporal image metrics compare heat-on and heat-off motion; they do not replace continuous playback review."]}
    report["all_parity_checks_passed"]=all(report["checks"].values())
    report_path.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"report":str(report_path),"checks":report["checks"],"frame_mae_mean":report["heat_on_vs_off"]["frame_mae_mean"],"temporal_mae_mean":report["temporal_change_difference"]["mae_mean"],"contact_sheet":str(sheet_path)},indent=2))
    return 0 if report["all_parity_checks_passed"] else 1
if __name__=="__main__": raise SystemExit(main())
