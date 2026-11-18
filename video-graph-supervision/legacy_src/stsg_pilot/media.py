"""Bounded PyAV decoding; actual PTS index and scene detection, no full RGB retention."""
import hashlib,json,math
from pathlib import Path
from fractions import Fraction
from .core import require,sample_pts,digest

def sha_file(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def check_geometry(height,width,patch_size,merge_size):
    factor=patch_size*merge_size
    require(height%factor==0 and width%factor==0,'CHECKPOINT_PATCH_ALIGNMENT')

def prepare_media(row,out,resize_factor=32):
    import av
    import numpy as np
    from PIL import Image
    from scenedetect.detectors import ContentDetector
    from qwen_vl_utils.vision_process import smart_resize
    path=row['path'];require(sha_file(path)==row['sha256'],'MEDIA_HASH_MISMATCH')
    vid=Path(path).stem;folder=Path(out)/'frames'/vid;folder.mkdir(parents=True,exist_ok=True)
    detector=ContentDetector(threshold=27.0,min_scene_len=15)
    pts=[];cuts=[]
    with av.open(path) as c:
        s=c.streams.video[0];tb=str(s.time_base);fps=str(s.average_rate);start=int(s.start_time or 0)
        duration=float(c.duration/av.time_base) if c.duration else float(s.duration*s.time_base)
        h,w=smart_resize(s.height,s.width,factor=resize_factor,min_pixels=4*resize_factor**2,max_pixels=50176)
        check_geometry(h,w,resize_factor,1)
        for i,frame in enumerate(c.decode(video=0)):
            require(frame.pts is not None,'MISSING_PTS')
            if frame.pts<start:continue
            pts.append((int(frame.pts),i))
            # Scene detection sees the full stream, only one small RGB image at a time.
            small=np.asarray(frame.to_image().resize((160,90)))[:,:,::-1].copy()
            cuts.extend(detector.process_frame(i,small))
    # Duplicate PTS are forbidden instead of silently changing clock conventions.
    require(len({p for p,i in pts})==len(pts),'DUPLICATE_PTS')
    pts.sort();clock={p:float(Fraction(p-start)*Fraction(tb)) for p,i in pts};index={p:i for p,i in pts}
    times={i:clock[p] for p,i in pts};cut_times=sorted({times[i] for i in cuts if i in times and 0<times[i]<duration})
    boundaries=[0.]+cut_times+[duration]
    clips=[{'clip_id':f'c{i}','interval_sec':[a,b],'frame_ids':[],'split_method':'PySceneDetect.ContentDetector threshold27 min15 fullstream160x90'} for i,(a,b) in enumerate(zip(boundaries,boundaries[1:]))]
    count=min(32,max(2,int(duration*2)));count-=count%2
    chosen=sample_pts([p for p,i in pts],tb,start,count)
    if len(chosen)%2:chosen=chosen[:-2]+chosen[-1:]
    want=set(chosen);raw={}
    with av.open(path) as c:
        for frame in c.decode(video=0):
            if frame.pts in want:
                raw[int(frame.pts)]=frame.to_image().convert('RGB').resize((w,h),Image.Resampling.BICUBIC)
    require(set(raw)==want,'SECOND_PASS_PTS_MISMATCH')
    # Independent third streaming pass validates the actual resized pixels, not just IDs.
    expected={p:hashlib.sha256(raw[p].tobytes()).hexdigest() for p in chosen};again={}
    with av.open(path) as c:
        for frame in c.decode(video=0):
            if frame.pts in want:
                im=frame.to_image().convert('RGB').resize((w,h),Image.Resampling.BICUBIC)
                again[int(frame.pts)]=hashlib.sha256(im.tobytes()).hexdigest()
    require(expected==again,'INDEPENDENT_DECODE_RGB_MISMATCH')
    frames=[]
    for j,p in enumerate(chosen):
        sec=clock[p];ci=min(next((i for i,b in enumerate(boundaries[1:]) if sec<b),len(clips)-1),len(clips)-1)
        fid=f'f{j:03d}';file=folder/(fid+'.png');raw[p].save(file)
        f={'frame_id':fid,'clip_id':clips[ci]['clip_id'],'pts':p,'time_sec':sec,'sha256':sha_file(file),'file':str(file.relative_to(out))}
        frames.append(f);clips[ci]['frame_ids'].append(fid)
    video={'video_id':vid,'source_video_id':'PerceptionTest:'+vid,'path':path,'sha256':row['sha256'],'duration_sec':duration,'avg_fps':fps,'time_base':tb,'start_pts':start,'source':'PerceptionTest','split':'train','license_status':'official README non-software CC-BY-4.0'}
    return {'video':video,'frames':frames,'clips':clips,'source_frame_indices':{f'f{j:03d}':index[p] for j,p in enumerate(chosen)},'total_source_frames':len(pts),'resize_hw':[h,w],
            'sampling':'PTS-nearest uniform time,2fps cap32,even; same cached frames available to all roles',
            'independent_decode_pixel_hashes':expected,'decode_parity_passed':expected==again,
            'native_average_fps_clock_max_error_seconds':max(abs(index[p]/float(Fraction(fps))-clock[p]) for p in chosen),
            'source_pts_sha256':digest(pts),'scenes_detected':len(clips),'scenes_without_sampled_frames':sum(not c['frame_ids'] for c in clips)}
