"""Purpose-separated STEP-style parsing. Same frames; no QA/checker outputs as inputs.

Explicit ALL is a model claim of visibility/identity at every supplied clip frame,
not inference of unobserved facts. Frame ranges are mapped through actual PTS.
"""
from copy import deepcopy
from .core import keys,require,validate_graph
from .parsing import parse_json,make_clip_graph,attach_frequency
from .runtime import save

FSG_SPEC='''Build a compact scene record ONLY from the supplied real video frames.
Return JSON with exactly objects, attributes, relations arrays. No events, questions or answers yet.
Objects have id, description, node_type, identity_scope, frame_ids. Use separate IDs and distinctive descriptions for separate physical instances (three cups are three objects). node_type must be exactly "static", "dynamic", or "unknown". identity_scope must be exactly "tracked_entity" or "single_frame". tracked_entity asserts the SAME physical instance across its declared frames; a shared class label is not proof of identity.
frame_ids may be the string "ALL" ONLY if that claim is visible in EVERY supplied clip frame; otherwise list actual frame IDs. ALL is an explicit visual assertion that will later be checked on ALL frames. Never use ALL just to save space when visibility or identity is uncertain.
Attributes have id, subject_id, predicate, value, frame_ids; relations have id, subject_id, object_id, predicate, frame_ids. All references must point to existing object IDs. Use 1-2 supporting frames for individual attributes/relations, not repeated long frame lists. At most8 objects and16 attributes/relations combined; whole graph hard limit64 facts. Use compact JSON, no markdown, no explanations. Do not invent entities or relationships; [] is allowed when no evidence.
Example of FORMAT ONLY (replace descriptions and IDs by actual observations): {"objects":[{"id":"o1","description":"distinctive visible entity","node_type":"dynamic","identity_scope":"tracked_entity","frame_ids":"ALL"}],"attributes":[],"relations":[]}'''

EVENT_SPEC='''Identify observable temporal events of the EXISTING immutable entities below, using ONLY the supplied video frames. Return JSON with exactly events and identities arrays. Do not rewrite objects, create new object IDs, questions, answers, or generic causal explanations.
Each event entry must have id, kind, subject_id, predicate, frame_ids, start_frame_range, end_frame_range. kind must be the single string "event" or the single string "motion"; never output a list or a string containing |. subject_id must be an existing LOCAL object ID. predicate describes a concise concrete action. frame_ids lists 1-4 actual frames showing the action.
start_frame_range is a pair of actual frame IDs bracketing the earliest/latest plausible onset; end_frame_range similarly brackets termination. Repeating a frame ID means a point estimate; preserve uncertainty rather than forcing point estimates. These ranges will be converted to exact global seconds by a deterministic actual-PTS lookup. Require start_earliest <= start_latest <= end_earliest <= end_latest, and all supporting frames lie within the outer bounds. No numeric time guesses.
Identity entries, only for DIFFERENT existing local nodes, have id, subject_id, object_id, identity_status, frame_ids. identity_status must be exactly "known" or "unknown"; known asserts SAME physical entity, not same appearance. A shared tracked_entity node needs no redundant identity edge.
Return at most6 observable events. Empty arrays are allowed when evidence is insufficient. Output compact JSON with no markdown. Do not repair missing information by guessing.'''

def expand_fsg(record,clip):
    keys(record,['objects','attributes','relations'])
    record=deepcopy(record)
    for rows in record.values():
        require(isinstance(rows,list),'ARRAY_REQUIRED')
        for row in rows:
            if row.get('frame_ids')=='ALL':row['frame_ids']=list(clip['frame_ids'])
            elif isinstance(row.get('frame_ids'),str):
                require(row['frame_ids'] in clip['frame_ids'],'UNKNOWN_SCALAR_FRAME_ID')
                row['frame_ids']=[row['frame_ids']]
    record.update(events=[],identities=[])
    return record

def expand_events(record,media,clip):
    keys(record,['events','identities']);record=deepcopy(record)
    frames={f['frame_id']:f for f in media['frames'] if f['frame_id'] in clip['frame_ids']}
    for row in record['events']:
        keys(row,['id','kind','subject_id','predicate','frame_ids','start_frame_range','end_frame_range'])
        if isinstance(row['frame_ids'],str):
            require(row['frame_ids'] in frames,'UNKNOWN_SCALAR_FRAME_ID')
            row['frame_ids']=[row['frame_ids']]
        for key,out in [('start_frame_range','start_sec_range'),('end_frame_range','end_sec_range')]:
            pair=row.pop(key);require(isinstance(pair,list) and len(pair)==2 and set(pair)<=frames.keys(),'UNKNOWN_EVENT_BOUNDARY_FRAME')
            row[out]=[frames[i]['time_sec'] for i in pair]
    return record

def staged_parse_video(rt,media,folder,cfg):
    # Gate B same-five corpus is single scene in the measured parent. Multi-clip
    # remains an explicit stop here, rather than pretend untested bridging works.
    clips=[c for c in media['clips'] if c['frame_ids']]
    require(len(clips)==1,'STAGED_SMOKE_EXPECTS_FROZEN_SINGLE_SCENE_INPUT')
    clip=clips[0];vid=media['video']['video_id'];runs=[];samples={};first=None;first_record=None
    loss={'scene_count':media['scenes_detected'],'visible_clips':1,'parser_attempts':0,'parser_valid':0,'parser_failures':[],
          'fsg_attempts':0,'fsg_valid':0,'event_attempts':0,'event_valid':0,'bridge_attempts':0,'bridge_valid':0,'protocol':'staged-v2'}
    def make_run(response,group):
        return {'parser_run_id':response['request_id'],'model_revision':response['model_revision'],'prompt_hash':response['prompt_sha256'],
                'seed':response['seed'],'frame_ids':clip['frame_ids'],'sample_group':group}
    for k in range(4):
        response=rt.ask(media,clip['frame_ids'],FSG_SPEC,role='parser_fsg',seed=cfg['seed']+k,max_tokens=cfg['object_max_tokens'],temperature=.7,owner=vid+':fsg')
        run=make_run(response,vid+':fsg');runs.append(run);loss['parser_attempts']+=1;loss['fsg_attempts']+=1
        try:
            record=expand_fsg(parse_json(response['raw_response']),clip);g=make_clip_graph(media,clip,record,run)
            samples[run['parser_run_id']]=g;loss['parser_valid']+=1;loss['fsg_valid']+=1
            if first is None:first=g;first_record=record
        except Exception as e:loss['parser_failures'].append({'run_id':run['parser_run_id'],'error':'FSG:'+str(e),'output_hit_cap':response['output_hit_cap']})
        save(folder/'parser_loss.json',loss)
    require(first is not None,'NO_STRUCTURALLY_VALID_FSG:'+vid)
    fsg=attach_frequency(deepcopy(first),samples,runs)
    # Do not replace an empty first valid FSG by a more productive later sample.
    if not any(f['kind']=='object' for f in fsg['facts']):return finish(fsg,folder,cfg,loss)
    event_runs=[];event_samples={};event_root=None
    import json
    context=[{k:o[k] for k in ['id','description','node_type','identity_scope','frame_ids']} for o in first_record['objects']]
    prompt=EVENT_SPEC+'\nExisting immutable local objects: '+json.dumps(context,separators=(',',':'))
    for k in range(4):
        response=rt.ask(media,clip['frame_ids'],prompt,role='parser_events',seed=cfg['seed']+1000+k,max_tokens=cfg['event_max_tokens'],temperature=.7,owner=vid+':events')
        run=make_run(response,vid+':events');event_runs.append(run);loss['parser_attempts']+=1;loss['event_attempts']+=1
        try:
            events=expand_events(parse_json(response['raw_response']),media,clip);record=deepcopy(first_record);record.update(events)
            g=make_clip_graph(media,clip,record,run);event_samples[run['parser_run_id']]=g;loss['parser_valid']+=1;loss['event_valid']+=1
            if event_root is None:event_root=g
        except Exception as e:loss['parser_failures'].append({'run_id':run['parser_run_id'],'error':'EVENTS:'+str(e),'output_hit_cap':response['output_hit_cap']})
        save(folder/'parser_loss.json',loss)
    graph=deepcopy(fsg);graph['parser_runs']+=event_runs
    if event_root is not None:
        e=attach_frequency(deepcopy(event_root),event_samples,event_runs)
        graph['facts'] += [f for f in e['facts'] if f['kind'] in ['event','motion','identity']]
    else:loss['event_phase_status']='NO_VALID_EVENT_RECORD_FSG_RETAINED'
    return finish(graph,folder,cfg,loss)

def finish(graph,folder,cfg,loss):
    from .smoke import valid_schema
    from .candidates import generate_candidates
    require(len(graph['facts'])<=cfg['max_facts'],'RAW_GRAPH_FACT_BUDGET_EXCEEDED');valid_schema(graph)
    save(folder/'raw_graph.json',graph);qs=generate_candidates(graph,seed=cfg['seed'],cap=cfg['max_questions_per_video'])
    save(folder/'locked_candidates.json',qs);save(folder/'parser_loss.json',loss)
    return graph,qs
