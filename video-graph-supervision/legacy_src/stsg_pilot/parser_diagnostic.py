"""Six matched, independent requests on frozen Gate B images. No decode or QA jobs."""
import argparse,copy,json,os,resource,shutil,subprocess,sys,time,traceback
from pathlib import Path
from .core import require
from .runtime import FrozenRuntime,save,emit
from .media import sha_file
from .parsing import parse_json,make_clip_graph
from .staged_parser import EVENT_SPEC,expand_events
from .candidates import generate_candidates

A_SPEC='''Using ONLY the actual supplied video frames, describe the concrete visible actions and state changes in chronological order. Refer to frame IDs where possible. Use ordinary free text. Do not output JSON, entity IDs, or precise temporal boundaries. Distinguish separate observable actions, without splitting one action into duplicate events. Do not guess hidden events, intentions, or what happened between unseen frames. If the input does not support an action, say so.'''
B_SPEC='''Using ONLY the actual supplied video frames, list concrete visible actions or state changes in chronological order. Return ONLY a JSON object with exactly the key "events" whose value is an array. Each entry has exactly: "action" (concrete action description), "subject" (visible subject description, NOT an entity ID), "evidence_frames" (a nonempty list of actual supplied frame IDs), "start_frame" (actual supplied frame ID for coarse start), "end_frame" (actual supplied frame ID for coarse end). Evidence frames must lie between start_frame and end_frame inclusive. Coarse boundaries describe the observed action, not hidden motion. Do not guess unseen events or split one action into duplicate events. No existing FSG IDs, identity links, or uncertainty boundary pairs are required. Empty events is allowed when evidence is insufficient. No markdown or explanation.'''

def objects_from_fsg(graph):
    return [{'id':f['fact_id'].removeprefix('c0_'),'description':f['predicate'],'node_type':f['node_type'],'identity_scope':f['identity_scope'],'frame_ids':f['support_frame_ids']} for f in graph['facts'] if f['kind']=='object']

def prompts(graph):
    return {'A':A_SPEC,'B':B_SPEC,'C':EVENT_SPEC+'\nExisting immutable local objects: '+json.dumps(objects_from_fsg(graph),separators=(',',':'))}

def analyze(response,media,graph):
    arm=response['condition'];text=response['raw_response'];result={'condition':arm,'video_id':response['video_id'],'nonempty_response':bool(text.strip()),'json_parsed':None,'schema_valid':None,'event_count':None,'visual_support':'REQUIRES_FRAME_REVIEW','entity_linkage':'REQUIRES_FRAME_REVIEW'}
    if arm=='A':return result
    try:
        record=parse_json(text);result['json_parsed']=True
        if isinstance(record,dict) and isinstance(record.get('events'),list):result['event_count']=len(record['events'])
        if arm=='B':
            require(set(record)=={'events'} and isinstance(record['events'],list),'B_TOP_LEVEL')
            frames={f['frame_id']:f['time_sec'] for f in media['frames']}
            for row in record['events']:
                require(set(row)=={'action','subject','evidence_frames','start_frame','end_frame'},'B_FIELDS')
                require(all(isinstance(row[k],str) and row[k].strip() for k in ['action','subject']),'B_DESCRIPTIONS')
                require(isinstance(row['evidence_frames'],list) and bool(row['evidence_frames']),'B_EVIDENCE_EMPTY')
                require(set(row['evidence_frames'])<=frames.keys() and row['start_frame'] in frames and row['end_frame'] in frames,'B_UNKNOWN_FRAME')
                require(frames[row['start_frame']]<=min(frames[f] for f in row['evidence_frames'])<=max(frames[f] for f in row['evidence_frames'])<=frames[row['end_frame']],'B_FRAME_ORDER')
            result['schema_valid']=True;result['minimal_record']=record
        else:
            clip=media['clips'][0];converted=expand_events(record,media,clip)
            base={'objects':objects_from_fsg(graph),'attributes':[],'relations':[],**converted}
            run={'parser_run_id':response['request_id'],'model_revision':response['model_revision'],'prompt_hash':response['prompt_sha256'],'seed':response['seed'],'frame_ids':clip['frame_ids'],'sample_group':'diagnostic_C'}
            g=make_clip_graph(media,clip,base,run);result['schema_valid']=True;result['converted_graph']=g
            result['structural_candidates']=generate_candidates(g,cap=100)
        return result
    except Exception as e:
        if result['json_parsed'] is None:result['json_parsed']=False
        result.update(schema_valid=False,error=str(e));return result

def worker(cfg):
    root=Path(cfg['output_root']);start=time.monotonic();rt=None;records=[]
    try:
        rt=FrozenRuntime(cfg,root/'worker')
        for vid in cfg['videos']:
            media=json.loads((root/'media'/f'{vid}.json').read_text());graph=json.loads((root/'fsg'/f'{vid}.json').read_text());hashes=[]
            for arm,prompt in prompts(graph).items():
                r=rt.ask(media,[f['frame_id'] for f in media['frames']],prompt,role='diagnostic_'+arm,seed=cfg['seed'],max_tokens=cfg['max_tokens'],temperature=0,owner=vid+':'+arm,parity=(rt.calls==0))
                r['condition']=arm;save(root/'responses'/f'{vid}_{arm}.json',r);records.append(r)
                hashes.append({k:r['input_hashes'][k] for k in ['pixel_values_videos','video_grid_thw']})
                save(root/'analysis'/f'{vid}_{arm}.json',analyze(r,media,graph))
            require(all(h==hashes[0] for h in hashes),'ARM_VISUAL_INPUT_MISMATCH')
            save(root/'visual_parity'/f'{vid}.json',{'passed':True,'condition_hashes':hashes,'frame_content_hashes':records[-1]['frame_content_hashes'],'frame_count':len(media['frames'])})
        require(rt.calls==6,'NOT_EXACTLY_SIX_REQUESTS')
        save(root/'completed.json',{'completed':True,'calls':rt.calls})
    except Exception as e:
        save(root/'failure.json',{'error':repr(e),'traceback':traceback.format_exc()});raise
    finally:
        save(root/'allocation.json',{'worker_wall_seconds':time.monotonic()-start,'allocated_gpu_hours':(time.monotonic()-start)/3600,'gpu':os.environ['CUDA_VISIBLE_DEVICES'],'model_loaded':rt is not None,'calls':rt.calls if rt else 0,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})

def supervise(cfg):
    root=Path('/scratch/haozhe/.cache/vlm-rsi/stsg-parser-diagnostic')/os.environ['ORX_RUN_ID'];root.mkdir(parents=True,exist_ok=False)
    cfg=copy.deepcopy(cfg);cfg.update(output_root=str(root),source_commit=os.environ['ORX_COMMIT'])
    require(list(cfg['videos'])==['video_7793','video_2495'] and cfg['worker_call_cap']==6 and cfg['temperature']==0,'DIAGNOSTIC_SCOPE')
    require(not any(cfg[k] for k in ['training','scaleup_authorized','reward_changes']),'FORBIDDEN_SCOPE')
    cache=Path(cfg['cache_root'])
    for vid,expected in cfg['videos'].items():
        mp=cache/'media'/f'{vid}.json';gp=cache/'videos'/vid/'raw_graph.json'
        require(sha_file(mp)==expected['media_sha256'] and sha_file(gp)==expected['fsg_sha256'],'FROZEN_METADATA_CHANGED')
        media=json.loads(mp.read_text());require(len(media['frames'])==32,'FROZEN_FRAME_COUNT_CHANGED')
        require(sha_file(media['video']['path'])==media['video']['sha256'],'VIDEO_HASH_CHANGED')
        for f in media['frames']:
            require(sha_file(cache/f['file'])==f['sha256'],'FROZEN_FRAME_CHANGED')
            target=root/f['file'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(cache/f['file'],target)
        save(root/'media'/f'{vid}.json',media);save(root/'fsg'/f'{vid}.json',json.loads(gp.read_text()))
    lines=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines()
    free=[l.split(',')[0].strip() for l in lines if float(l.split(',')[1])>40000 and float(l.split(',')[2])<5];require(bool(free),'NO_IDLE_A40')
    cfg['gpu_id']=free[0];save(root/'effective_config.json',cfg);emit('parser_diagnostic_start',config=cfg)
    env=dict(os.environ,CUDA_VISIBLE_DEVICES=free[0],SMOKE_DEADLINE=str(time.time()+cfg['wall_seconds']))
    p=subprocess.Popen([sys.executable,'-m','stsg_pilot.parser_diagnostic','--worker','--config',str(root/'effective_config.json')],env=env)
    try:
        p.wait(timeout=cfg['wall_seconds']);require(p.returncode==0,'DIAGNOSTIC_WORKER_FAILED')
    finally:
        if p.poll() is None:
            p.terminate()
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        responses=[json.loads(f.read_text()) for f in sorted((root/'responses').glob('*.json'))]
        alloc=json.loads((root/'allocation.json').read_text()) if (root/'allocation.json').exists() else {'allocated_gpu_hours':cfg['wall_seconds']/3600,'allocation_record_missing':True}
        summary={'output_root':str(root),'run_id':os.environ['ORX_RUN_ID'],'source_commit':os.environ['ORX_COMMIT'],'completed':(root/'completed.json').exists(),'generation_calls_completed':len(responses),'max_generation_calls':6,'input_tokens':sum(r['input_tokens'] for r in responses),'output_tokens':sum(r['output_tokens'] for r in responses),'model_device_wall_seconds':sum(r['model_device_wall_seconds'] for r in responses),**alloc,'peak_allocated_bytes':max([r['peak_allocated_bytes'] for r in responses],default=0),'peak_reserved_bytes':max([r['peak_reserved_bytes'] for r in responses],default=0),'training':False,'b0_b1_b2_executed':False,'new_frame_sampling':False}
        save(root/'summary.json',summary);emit('parser_diagnostic_summary',**summary)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);ap.add_argument('--worker',action='store_true');a=ap.parse_args();cfg=json.loads(Path(a.config).read_text())
    (worker if a.worker else supervise)(cfg)
if __name__=='__main__':main()
