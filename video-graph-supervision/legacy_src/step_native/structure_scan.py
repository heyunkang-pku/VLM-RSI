"""CPU-only fixed numeric-ID prefix scan; outcomes never involve a model."""
import concurrent.futures,copy,json,time,traceback,os
from pathlib import Path
from stsg_pilot.runtime import save,emit
from stsg_pilot.media import sha_file
from .splitting import prepare

def scan_one(item):
    path,threshold,minframes=item;start=time.monotonic()
    try:
        import av,cv2
        from scenedetect.detectors import ContentDetector
        cv2.setNumThreads(1);det=ContentDetector(threshold=threshold,min_scene_len=minframes);cuts=[];n=0
        with av.open(path) as c:
            for n,frame in enumerate(c.decode(video=0)):cuts.extend(det.process_frame(n,cv2.resize(frame.to_ndarray(format='bgr24'),(320,180),interpolation=cv2.INTER_AREA)))
        n+=1;cuts.extend(det.post_process(n-1));cuts=sorted({x for x in cuts if 0<x<n})
        return {'video_id':Path(path).stem,'path':path,'decoded':True,'source_frames':n,'scene_count':len(cuts)+1,'keyframe_count_lower_bound':len(cuts)+1,'keyframe_count_inferred_if_single_scene':1 if not cuts else None,'cuts':cuts,'cpu_wall_seconds':time.monotonic()-start,'selection_rule':'scene_count>=2 implies >=2keyframes under frozen k mapping'}
    except Exception as e:return {'video_id':Path(path).stem,'path':path,'decoded':False,'error':repr(e),'cpu_wall_seconds':time.monotonic()-start}

def scan(cfg,root):
    pool=Path(cfg['pool_root']);paths=sorted(pool.glob('video_*.mp4'),key=lambda p:int(p.stem.split('_')[-1]));assert len(paths)==640,'FROZEN_POOL_SIZE_CHANGED'
    save(root/'P2_pool_manifest.json',{'ordered_paths':[str(p) for p in paths],'count':len(paths),'order':'numeric originalvideo ID ascending','exclude_supplement_base_video':'video_7793','frozen_before_any_supplement_model_calls':True})
    scanned=[];selected=[];eligible=[p for p in paths if p.stem!='video_7793']
    with concurrent.futures.ProcessPoolExecutor(max_workers=cfg['scan_workers']) as executor:
        for offset in range(0,len(eligible),cfg['scan_workers']):
            batch=eligible[offset:offset+cfg['scan_workers']];results=list(executor.map(scan_one,[(str(p),cfg['scene_threshold'],cfg['min_scene_frames']) for p in batch]))
            for r in results:
                r['selected']=False
                if r['decoded'] and r['scene_count']>=2 and len(selected)<cfg['max_supplement_videos']:
                    folder=root/'P2_videos'/r['video_id'];folder.mkdir(parents=True,exist_ok=True);cc=copy.deepcopy(cfg);cc['video']={'video_id':r['video_id'],'source':'PerceptionTest','split':'train','path':r['path'],'sha256':sha_file(r['path'])}
                    try:
                        manifest=prepare(cc,folder);r['keyframe_count']=len(manifest['selected_keyframe_source_indices']);r['keyframe_manifest']=str(folder/'S1/manifest.json')
                        if r['keyframe_count']>=2:
                            # Anomalous scale becomes an explicitly partial contiguous-prefix clip smoke.
                            allframes=manifest['selected_keyframe_source_indices'];chosen=allframes;partial=False
                            if len(allframes)>cfg['abnormal_keyframe_limit']:
                                chosen=[]
                                for scene in manifest['scenes']:
                                    here=[i for i in allframes if scene['start_source_index']<=i<scene['end_source_index_exclusive']]
                                    if chosen and len(chosen)+len(here)>cfg['abnormal_keyframe_limit']:break
                                    chosen+=here
                                    if len(chosen)>=2:break
                                partial=True
                            selected.append({'video_id':r['video_id'],'folder':str(folder),'source_sha256':cc['video']['sha256'],'all_keyframes':allframes,'chosen_keyframes':chosen,'partial_contiguous_clip_prefix_smoke':partial,'unprocessed_keyframe_count':len(allframes)-len(chosen),'manifest_sha256':sha_file(folder/'S1/manifest.json')});r['selected']=True;r['reason']='first structure-eligible in fixednumeric order'
                    except Exception as e:r['reason']='full_S1_FAILED:'+repr(e)
                elif not r['decoded']:r['reason']='DECODE_FAILED'
                elif r['scene_count']==1:r['reason']='single_scene_k1_no_multiple_keyframes'
                else:r['reason']='eligible_but_supplement_slots_filled'
                scanned.append(r)
            save(root/'P2_scan_results.json',scanned);save(root/'P2_selected.json',selected);emit('P2_scan_progress',scanned=len(scanned),selected=len(selected),pool=640)
            if len(selected)>=cfg['max_supplement_videos']:break
    save(root/'P2_scan_done.json',{'scanned':len(scanned),'pool_count':640,'selected':selected,'base_video_retained':'video_7793','unscanned_count':640-1-len(scanned),'base_already_measured':1})
