"""STEP S1: PySceneDetect + Song et al. [42] §3.2 clustering/stillness.

HSV/Scharr hist layout follows Hecate hist_opencv.hpp (Apache2, Yahoo2016).
Explicit paper-level reimplementation, not a bit-exact Hecate pipeline.
"""
import hashlib,json,time,resource
from pathlib import Path
from fractions import Fraction
from stsg_pilot.runtime import save,emit
from stsg_pilot.media import sha_file

def feature_2220(bgr):
    import cv2,numpy as np
    color=[];edges=[];h,w=bgr.shape[:2]
    for cells in [1,2]:
        for x in range(cells):
            for y in range(cells):
                patch=bgr[y*(h//cells):(y+1)*(h//cells),x*(w//cells):(x+1)*(w//cells)]
                hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
                for ch in range(3):
                    hist=cv2.calcHist([hsv],[ch],None,[128],[0,256]);color.append(cv2.normalize(hist,None).ravel())
                gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY);gx=cv2.Scharr(gray,cv2.CV_32F,1,0);gy=cv2.Scharr(gray,cv2.CV_32F,0,1)
                ori=(np.degrees(np.arctan2(gy,gx))%180).astype('float32');mag=cv2.magnitude(gx,gy)
                for a,nb,rng in [(ori,30,[0,180]),(mag,30,[0,256])]:
                    hist=cv2.calcHist([a],[0],None,[nb],rng);edges.append(cv2.normalize(hist,None).ravel())
    f=np.concatenate(color+edges).astype('float32');assert f.shape==(2220,) and np.isfinite(f).all();return f

def select_subshots(labels,scene_ranges,ssd):
    """No forced number of keyframes: preserve contiguous label runs per scene."""
    results=[]
    for ci,(a,b) in enumerate(scene_ranges):
        start=a
        for j in range(a+1,b+1):
            if j==b or labels[j]!=labels[start]:
                eligible=[k for k in range(start,j) if ssd[k] is not None]
                if not eligible:eligible=list(range(start,j))
                k=min(eligible,key=lambda i:(float('inf') if ssd[i] is None else ssd[i],i))
                results.append({'clip_id':f'c{ci}','source_start_index':start,'source_end_index_exclusive':j,'cluster_id':int(labels[start]),'selected_source_index':k,'ssd':ssd[k],'selection':'minimum predecessor SSD; earliest-index tie break','degenerate_singleton_no_predecessor':ssd[k] is None})
                start=j
    return results

def prepare(cfg,root):
    import av,cv2,numpy as np
    from scenedetect.detectors import ContentDetector
    start=time.monotonic();v=cfg['video'];assert sha_file(v['path'])==v['sha256'];cv2.setNumThreads(1)
    detector=ContentDetector(threshold=cfg['scene_threshold'],min_scene_len=cfg['min_scene_frames'])
    cuts=[];clock=[];feats=[];ssds=[];prev=None;hw=cfg['analysis_hw']
    with av.open(v['path']) as c:
        stream=c.streams.video[0];tb=str(stream.time_base);p0=int(stream.start_time or 0);fps=str(stream.average_rate);duration=float(c.duration/av.time_base)
        for index,frame in enumerate(c.decode(video=0)):
            assert frame.pts is not None
            bgr=cv2.resize(frame.to_ndarray(format='bgr24'),(hw[1],hw[0]),interpolation=cv2.INTER_AREA)
            cuts.extend(detector.process_frame(index,bgr));feats.append(feature_2220(bgr));f=bgr.astype('float32')
            ssds.append(None if prev is None else float(np.mean((f-prev)**2,dtype=np.float64)))
            prev=f;clock.append({'source_index':index,'pts':int(frame.pts),'time_sec':float(Fraction(frame.pts-p0)*Fraction(tb))})
            if index%300==0:emit('S1_decode_progress',frames=index+1)
    cuts.extend(detector.post_process(len(clock)-1));assert all(a['pts']<b['pts'] for a,b in zip(clock,clock[1:]))
    bounds=[0]+sorted(set(i for i in cuts if 0<i<len(clock)))+[len(clock)];ranges=list(zip(bounds,bounds[1:]));features=np.stack(feats)
    k=min(len(ranges),len(clock));cv2.setRNGSeed(cfg['kmeans_seed'])
    compact,labels,centers=cv2.kmeans(features,k,None,(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_MAX_ITER,cfg['kmeans_max_iter'],cfg['kmeans_epsilon']),cfg['kmeans_attempts'],cv2.KMEANS_PP_CENTERS)
    labels=labels[:,0].tolist();subshots=select_subshots(labels,ranges,ssds)
    selected=sorted({r['selected_source_index'] for r in subshots});calibration=selected[0]
    # Video classification input only; not a second keyframe algorithm or extra FSG frame.
    context=sorted({round(i*(len(clock)-1)/(min(cfg['class_video_frame_cap'],len(clock))-1)) for i in range(min(cfg['class_video_frame_cap'],len(clock)))})
    (root/'S1').mkdir(exist_ok=True);np.savez_compressed(root/'S1/features_and_clustering.npz',features=features,labels=np.array(labels),centers=centers,ssd=np.array([np.nan if s is None else s for s in ssds]))
    save(root/'S1/frame_clock.json',clock);manifest=[];wanted=set(selected+context)
    with av.open(v['path']) as c:
        for index,frame in enumerate(c.decode(video=0)):
            if index not in wanted:continue
            assert frame.pts==clock[index]['pts'];file=f'S1/source_frames/src_{index:06d}.png';target=root/file;target.parent.mkdir(parents=True,exist_ok=True);frame.to_image().convert('RGB').save(target)
            manifest.append({**clock[index],'frame_id':f'src_{index:06d}','file':file,'sha256':sha_file(target),'selected_keyframe':index in selected,'class_video_context':index in context})
    scenes=[{'clip_id':f'c{i}','start_source_index':a,'end_source_index_exclusive':b,'start_sec':clock[a]['time_sec'],'end_sec':clock[b]['time_sec'] if b<len(clock) else duration} for i,(a,b) in enumerate(ranges)]
    result={'video':{**v,'avg_fps':fps,'time_base':tb,'start_pts':p0,'duration_sec':duration},'source_frames_decoded':len(clock),'scenes':scenes,'cluster_count':k,'feature_dim':2220,'kmeans_compactness':float(compact),'subshots':subshots,'selected_keyframe_source_indices':selected,'calibration_source_index':calibration,'video_context_source_indices':context,'frames':manifest,'CPU_seconds':time.monotonic()-start,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'selection_frozen_before_model':True,'new_frame_version_preserves_legacy':True}
    save(root/'S1/manifest.json',result);emit('S1_complete',video=v['video_id'],scenes=len(scenes),keyframes=len(selected),calibration_index=calibration,cpu_seconds=result['CPU_seconds']);return result
