"""Final bounded engineering variant. No new FSG calls; fixed temporal windows.
Actual scene clips remain unchanged. Window indices never enter question wording.
"""
from copy import deepcopy
from pathlib import Path
import json
from .core import keys,require,validate_graph
from .parsing import parse_json,make_clip_graph,attach_frequency,fact_signature
from .staged_parser import expand_fsg,expand_events,EVENT_SPEC,finish
from .runtime import save

WINDOW_SPEC='''You see ONLY a fixed temporal observation window from a longer video, not a new scene. Identify local concrete actions or visible state transitions IN THESE FRAMES. Localize distinct actions such as grasping, releasing, lifting, revealing or rotating when actually observed; do not collapse a sequence into one generic clip-long "moves" action. Do not invent transitions or force a minimum event count. Predicates must not contain numerical timestamps or ordinal hints like first/second. Use distinctive visible entities to distinguish actions when possible. Whole-clip object identities come from the frozen FSG below and remain hypotheses to be checked later.\n'''+EVENT_SPEC

def windows(frame_ids,count):
    require(len(frame_ids)>=count,'INSUFFICIENT_WINDOW_FRAMES')
    return [frame_ids[i*len(frame_ids)//count:(i+1)*len(frame_ids)//count] for i in range(count)]

def make_event_graph(base,record,run,window,index):
    g=deepcopy(base);g['parser_runs'].append(run);fs={f['frame_id']:f for f in g['frames']};facts={f['fact_id']:f for f in g['facts']}
    clip_id=window['clip_id'];prefix=clip_id+f'_w{index}_';new=[]
    for row in record['events']:
        keys(row,['id','kind','subject_id','predicate','frame_ids','start_sec_range','end_sec_range'])
        require(row['kind'] in ['event','motion'],'EVENT_KIND')
        require(isinstance(row['frame_ids'],list) and bool(row['frame_ids']) and set(row['frame_ids'])<=set(window['frame_ids']),'EVENT_WINDOW_SUPPORT')
        new.append({'fact_id':prefix+row['id'],'kind':row['kind'],'predicate':row['predicate'],'subject_id':clip_id+'_'+row['subject_id'],
                    'clip_ids':[clip_id],'support_frame_ids':row['frame_ids'],'parser_run_id':run['parser_run_id'],'matched_parser_run_ids':[run['parser_run_id']],
                    'start_sec_range':row['start_sec_range'],'end_sec_range':row['end_sec_range'],'depends_on':[]})
    for row in record['identities']:
        keys(row,['id','subject_id','object_id','identity_status','frame_ids'])
        ids=row['frame_ids']
        if isinstance(ids,str):require(ids in window['frame_ids'],'IDENTITY_WINDOW_SUPPORT');ids=[ids]
        require(isinstance(ids,list) and bool(ids) and set(ids)<=set(window['frame_ids']),'IDENTITY_WINDOW_SUPPORT')
        ts=[fs[i]['time_sec'] for i in ids]
        new.append({'fact_id':prefix+row['id'],'kind':'identity','predicate':'same physical entity','subject_id':clip_id+'_'+row['subject_id'],'object_id':clip_id+'_'+row['object_id'],
                    'identity_status':row['identity_status'],'clip_ids':[clip_id],'support_frame_ids':ids,'parser_run_id':run['parser_run_id'],'matched_parser_run_ids':[run['parser_run_id']],
                    'start_sec_range':[min(ts)]*2,'end_sec_range':[max(ts)]*2,'depends_on':[]})
    g['facts']+=new;validate_graph(g)
    return g,new

def windowed_parse_video(rt,media,folder,cfg):
    clips=[c for c in media['clips'] if c['frame_ids']];require(len(clips)==1,'SINGLE_SCENE_CACHE_ONLY')
    clip=clips[0];vid=media['video']['video_id'];source=Path(cfg['fsg_cache_root']);responses=[]
    for p in sorted(source.glob('worker*/requests.jsonl')):
        responses += [r for r in (json.loads(l) for l in p.read_text().splitlines()) if r['role']=='parser_fsg' and r['video_id']==vid and r['status']=='DONE']
    require(len(responses)==4,'CACHE_EXPECTS_EXACTLY_FOUR_FSG_RESPONSES')
    responses.sort(key=lambda r:r['seed']);fs={f['frame_id']:f for f in media['frames']}
    runs=[];samples={};first=None;first_record=None
    loss={'scene_count':media['scenes_detected'],'visible_clips':1,'parser_attempts':0,'parser_valid':0,'parser_failures':[],
          'fsg_cache_samples':4,'new_fsg_model_calls':0,'fsg_valid':0,'event_attempts':0,'event_valid':0,'windows':[],
          'bridge_attempts':0,'bridge_valid':0,'protocol':'cached-fsg-windowed-v3','actual_scene_count':1}
    reuse=[]
    for r in responses:
        require(r['model_revision']==cfg['model_revision'],'CACHE_MODEL_REVISION_MISMATCH')
        require(r['frame_content_hashes']==[fs[i]['sha256'] for i in r['shown_frame_ids']],'CACHE_FRAME_CONTENT_MISMATCH')
        require(set(r['shown_frame_ids'])==set(clip['frame_ids']),'CACHE_FRAME_SET_MISMATCH')
        run={'parser_run_id':r['request_id'],'model_revision':r['model_revision'],'prompt_hash':r['prompt_sha256'],'seed':r['seed'],'frame_ids':clip['frame_ids'],'sample_group':vid+':fsg-cache'}
        runs.append(run);reuse.append({'source_run_root':str(source),'source_request_id':r['request_id'],'role':'parser_fsg','model_calls_added':0})
        try:
            record=expand_fsg(parse_json(r['raw_response']),clip);g=make_clip_graph(media,clip,record,run);samples[run['parser_run_id']]=g;loss['fsg_valid']+=1
            if first is None:first=g;first_record=record
        except Exception as e:loss['parser_failures'].append({'run_id':r['request_id'],'error':'CACHED_FSG:'+str(e),'output_hit_cap':r['output_hit_cap']})
    save(folder/'fsg_cache_reuse.json',reuse);save(folder/'parser_loss.json',loss)
    require(first is not None,'NO_VALID_CACHED_FSG:'+vid)
    graph=attach_frequency(deepcopy(first),samples,runs)
    if not any(f['kind']=='object' for f in graph['facts']):return finish(graph,folder,cfg,loss)
    context=[{k:o[k] for k in ['id','description','node_type','identity_scope','frame_ids']} for o in first_record['objects']]
    for wi,ids in enumerate(windows(clip['frame_ids'],cfg['event_observation_windows'])):
        window=deepcopy(clip);window['frame_ids']=ids;group=vid+f':observation-window{wi}'
        winloss={'index':wi,'frame_ids':ids,'attempts':0,'valid':0,'selected_event_count':0,'true_scene_cut':False}
        wruns=[];sample_graphs={};sample_new={};selected=None
        prompt=WINDOW_SPEC+'\nFixed immutable local objects: '+json.dumps(context,separators=(',',':'))
        for k in range(4):
            r=rt.ask(media,ids,prompt,role='parser_events_window',seed=cfg['seed']+1000+wi*10+k,max_tokens=cfg['event_max_tokens'],temperature=.7,owner=group)
            run={'parser_run_id':r['request_id'],'model_revision':r['model_revision'],'prompt_hash':r['prompt_sha256'],'seed':r['seed'],'frame_ids':ids,'sample_group':group}
            wruns.append(run);loss['parser_attempts']+=1;loss['event_attempts']+=1;winloss['attempts']+=1
            try:
                record=expand_events(parse_json(r['raw_response']),media,window);g,new=make_event_graph(graph,record,run,window,wi)
                sample_graphs[run['parser_run_id']]=g;sample_new[run['parser_run_id']]=new
                loss['parser_valid']+=1;loss['event_valid']+=1;winloss['valid']+=1
                if selected is None:selected=run['parser_run_id']
            except Exception as e:loss['parser_failures'].append({'run_id':run['parser_run_id'],'error':f'WINDOW{wi}:'+str(e),'output_hit_cap':r['output_hit_cap']})
            save(folder/'parser_loss.json',loss)
        graph['parser_runs']+=wruns
        if selected is not None:
            tabs={rid:{fact_signature(sample_graphs[rid],f) for f in sample_new[rid]} for rid in sample_new}
            for f in sample_new[selected]:
                sig=fact_signature(sample_graphs[selected],f);f['matched_parser_run_ids']=[run['parser_run_id'] for run in wruns if sig in tabs.get(run['parser_run_id'],set())]
                graph['facts'].append(f)
            winloss['selected_event_count']=sum(f['kind'] in ['event','motion'] for f in sample_new[selected])
            winloss['selected_parser_run_id']=selected
        else:winloss['status']='NO_VALID_PARSE'
        loss['windows'].append(winloss);save(folder/'parser_loss.json',loss)
    return finish(graph,folder,cfg,loss)
