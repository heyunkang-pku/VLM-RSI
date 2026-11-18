"""Strict JSON contracts and deterministic graph QA. Python >=3.10, stdlib only.
No IO, model calls, imports of old engineering, CUDA, training or label readers.
Schema validation is semantic too: JSON Schema alone cannot check reference closure.
"""
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math

class ContractError(ValueError): pass

def require(ok, code):
    if not ok: raise ContractError(code)

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                                     ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def finite(x):
    return type(x) in (int,float) and math.isfinite(x)

def keys(value, required, optional=()):
    require(isinstance(value,dict),'EXPECTED_OBJECT')
    require(set(required)<=value.keys(),'MISSING_FIELDS')
    require(value.keys()<=set(required)|set(optional),'UNEXPECTED_FIELD')

def unique(items, code):
    require(len(items)==len(set(items)),code)

def named(items, field):
    require(isinstance(items,list),'EXPECTED_LIST')
    ids=[x[field] for x in items]
    require(all(isinstance(x,str) and x.strip() for x in ids),'EMPTY_ID')
    unique(ids,'DUPLICATE_ID')
    return dict(zip(ids,items))

def pts_seconds(pts,time_base,start_pts=0):
    require(type(pts) is int and type(start_pts) is int,'PTS_INTEGER_REQUIRED')
    try: tb=Fraction(time_base)
    except (ValueError,ZeroDivisionError,TypeError): raise ContractError('BAD_TIME_BASE')
    require(tb>0,'BAD_TIME_BASE')
    return Fraction(pts-start_pts)*tb

def sample_pts(pts,time_base,start_pts=0,cap=32):
    """Nearest actual PTS to uniform time targets; Gate A CPU index contract.
    Returns unique indices in presentation order. No decode, no index/FPS clock.
    This policy is not claimed identical to official torchvision sampling.
    """
    require(type(cap) is int and cap>0,'BAD_FRAME_CAP')
    require(bool(pts),'NO_PTS')
    seconds=[pts_seconds(p,time_base,start_pts) for p in pts]
    require(all(t>=0 for t in seconds),'NEGATIVE_PTS')
    require(all(a<b for a,b in zip(seconds,seconds[1:])),'NONUNIQUE_OR_UNSORTED_PTS')
    n=min(cap,len(pts))
    if n==1:return [pts[0]]
    targets=[seconds[0]+(seconds[-1]-seconds[0])*i/(n-1) for i in range(n)]
    selected={min(range(len(pts)),key=lambda i:(abs(seconds[i]-t),seconds[i])) for t in targets}
    return [pts[i] for i in sorted(selected)]

def interval(f,duration):
    lo,hi=f['start_sec_range'],f['end_sec_range']
    require(isinstance(lo,list) and isinstance(hi,list) and len(lo)==len(hi)==2,'BAD_INTERVAL')
    require(all(finite(x) for x in lo+hi),'NONFINITE_TIME')
    require(0<=lo[0]<=lo[1]<=hi[0]<=hi[1]<=duration,'BAD_INTERVAL')
    return lo,hi

def validate_graph(g):
    keys(g,['schema_version','video','clips','frames','parser_runs','facts'])
    require(g['schema_version']=='pilot-v1','SCHEMA_VERSION')
    v=g['video']; keys(v,['video_id','source_video_id','path','sha256','duration_sec','avg_fps',
                         'time_base','start_pts','source','split','license_status'])
    require(all(isinstance(v[k],str) and v[k] for k in ['video_id','source_video_id','path','source','split','license_status']),'VIDEO_METADATA')
    require(isinstance(v['sha256'],str) and len(v['sha256'])==64 and all(c in '0123456789abcdef' for c in v['sha256']),'VIDEO_HASH')
    require(finite(v['duration_sec']) and v['duration_sec']>0,'BAD_DURATION')
    try: require(Fraction(v['avg_fps'])>0,'BAD_FPS')
    except (ValueError,ZeroDivisionError,TypeError): raise ContractError('BAD_FPS')
    pts_seconds(0,v['time_base'],v['start_pts'])
    for c in g['clips']: keys(c,['clip_id','interval_sec','frame_ids','split_method'])
    for f in g['frames']: keys(f,['frame_id','clip_id','pts','time_sec','sha256','file'])
    for r in g['parser_runs']: keys(r,['parser_run_id','model_revision','prompt_hash','seed','frame_ids','sample_group'])
    for f in g['facts']:
        keys(f,['fact_id','kind','predicate','clip_ids','support_frame_ids','parser_run_id',
                'matched_parser_run_ids','start_sec_range','end_sec_range','depends_on'],
             ['subject_id','object_id','identity_status','attribute_value','node_type','identity_scope'])
    cs=named(g['clips'],'clip_id');fs=named(g['frames'],'frame_id');rs=named(g['parser_runs'],'parser_run_id');facts=named(g['facts'],'fact_id')
    require(bool(cs) and bool(fs) and bool(rs),'EMPTY_PROVENANCE')
    # Namespaces cannot collide, including motion / identity facts.
    unique(list(cs)+list(fs)+list(rs)+list(facts),'GLOBAL_ID_COLLISION')
    spans=[]
    for c in cs.values():
        require(len(c['interval_sec'])==2 and all(finite(x) for x in c['interval_sec']),'BAD_CLIP')
        a,b=c['interval_sec']; require(0<=a<b<=v['duration_sec'],'BAD_CLIP');spans.append((a,b))
        unique(c['frame_ids'],'DUPLICATE_FRAME_REFERENCE')
        require(set(c['frame_ids'])<=fs.keys(),'DANGLING_FRAME')
        require(all(fs[i]['clip_id']==c['clip_id'] for i in c['frame_ids']),'FRAME_CLIP_MISMATCH')
    spans.sort();require(all(a[1]<=b[0] for a,b in zip(spans,spans[1:])),'OVERLAPPING_CLIPS')
    for f in fs.values():
        require(f['clip_id'] in cs and f['frame_id'] in cs[f['clip_id']]['frame_ids'],'DANGLING_CLIP')
        sec=pts_seconds(f['pts'],v['time_base'],v['start_pts'])
        require(finite(f['time_sec']) and abs(float(sec)-f['time_sec'])<1e-9,'PTS_SECONDS_MISMATCH')
        a,b=cs[f['clip_id']]['interval_sec'];require(a<=sec<=b,'FRAME_OUTSIDE_CLIP')
        require(isinstance(f['sha256'],str) and len(f['sha256'])==64 and all(c in '0123456789abcdef' for c in f['sha256']),'FRAME_HASH')
    for r in rs.values():
        require(r['model_revision'] and r['prompt_hash'] and r['sample_group'] and type(r['seed']) is int,'RUN_PROVENANCE')
        unique(r['frame_ids'],'DUPLICATE_FRAME_REFERENCE');require(bool(r['frame_ids']) and set(r['frame_ids'])<=fs.keys(),'RUN_FRAMES')
    for f in facts.values():
        require(f['kind'] in ['object','attribute','relation','event','motion','identity'],'UNKNOWN_FACT_KIND')
        require(isinstance(f['predicate'],str) and f['predicate'].strip(),'EMPTY_PREDICATE')
        require(bool(f['clip_ids']) and set(f['clip_ids'])<=cs.keys(),'FACT_CLIPS')
        unique(f['clip_ids'],'DUPLICATE_CLIP_REFERENCE')
        require(bool(f['support_frame_ids']) and set(f['support_frame_ids'])<=fs.keys(),'FACT_SUPPORT')
        unique(f['support_frame_ids'],'DUPLICATE_FRAME_REFERENCE')
        require({fs[i]['clip_id'] for i in f['support_frame_ids']}==set(f['clip_ids']),'FACT_FRAME_CLIP_MISMATCH')
        require(f['parser_run_id'] in rs,'DANGLING_PARSER')
        require(set(f['support_frame_ids'])<=set(rs[f['parser_run_id']]['frame_ids']),'PARSER_DID_NOT_SEE_SUPPORT')
        lo,hi=interval(f,v['duration_sec'])
        require(min(cs[c]['interval_sec'][0] for c in f['clip_ids'])<=lo[0] and hi[1]<=max(cs[c]['interval_sec'][1] for c in f['clip_ids']),'FACT_OUTSIDE_CLIP')
        for fid in f['support_frame_ids']:
            require(lo[0]<=fs[fid]['time_sec']<=hi[1],'SUPPORT_OUTSIDE_FACT_INTERVAL')
        require(set(f['depends_on'])<=facts.keys(),'DANGLING_DEPENDENCY');unique(f['depends_on'],'DUPLICATE_DEPENDENCY')
        if f['kind']!='object':
            require(f.get('subject_id') in facts and facts[f['subject_id']]['kind']=='object','SUBJECT_NODE_REQUIRED')
        if f['kind']!='identity':
            require(len(f['clip_ids'])==1,'NONIDENTITY_FACT_MUST_BELONG_TO_ONE_CLIP')
            for field in ('subject_id','object_id'):
                if field in f:
                    require(f[field] in facts and set(facts[f[field]]['clip_ids'])<=set(f['clip_ids']),'CROSS_CLIP_REFERENT_WITHOUT_IDENTITY')
        if f['kind']=='object':
            require(f.get('node_type') in ['static','dynamic','unknown'],'OBJECT_NODE_TYPE')
            require(f.get('identity_scope','single_frame') in ['single_frame','tracked_entity'],'IDENTITY_SCOPE')
        if f['kind']=='attribute':
            require(isinstance(f.get('attribute_value'),str) and f['attribute_value'].strip(),'ATTRIBUTE_VALUE_REQUIRED')
        if f['kind'] in ['relation','identity']:
            require(f.get('object_id') in facts and facts[f['object_id']]['kind']=='object','OBJECT_NODE_REQUIRED')
        require(f['kind']=='identity' or 'identity_status' not in f,'IDENTITY_FIELD_SCOPE')
        if f['kind']=='identity':
            require(f.get('identity_status') in ['known','unknown'],'IDENTITY_UNCERTAINTY_REQUIRED')
            endpoints=[facts[f['subject_id']],facts[f['object_id']]]
            require(set(f['clip_ids'])==set(c for n in endpoints for c in n['clip_ids']),'IDENTITY_CLIPS')
        ids=f['matched_parser_run_ids'];unique(ids,'DUPLICATE_FREQUENCY_SAMPLE')
        require(f['parser_run_id'] in ids and set(ids)<=rs.keys(),'FREQUENCY_RUNS')
        r=rs[f['parser_run_id']]
        require(all(rs[i]['sample_group']==r['sample_group'] and rs[i]['frame_ids']==r['frame_ids'] for i in ids),'INCOMPARABLE_PARSE_SAMPLES')
    for i in facts: closure(facts,[i])
    return cs,fs,rs,facts

def direct_dependencies(f):
    return set(f['depends_on'])|{f[k] for k in ('subject_id','object_id') if k in f}

def closure(facts,roots):
    seen=set();active=set()
    def visit(i):
        require(i in facts,'DANGLING_DEPENDENCY');require(i not in active,'CYCLIC_DEPENDENCY')
        if i in seen:return
        active.add(i)
        for j in sorted(direct_dependencies(facts[i])): visit(j)
        active.remove(i);seen.add(i)
    for i in roots:visit(i)
    return sorted(seen)

def dependencies(g,program):
    _,_,_,facts=validate_graph(g)
    keys(program,['op','args','identity_fact_id'])
    require(program['op'] in ('BEFORE','WHICH_FIRST'),'UNSUPPORTED_OPEN_WORLD_OPERATION')
    require(isinstance(program['args'],list) and len(program['args'])==2 and program['args'][0]!=program['args'][1],'TWO_DISTINCT_EVENTS_REQUIRED')
    require(all(i in facts and facts[i]['kind'] in ['event','motion'] for i in program['args']),'EVENT_REQUIRED')
    a,b=[facts[i] for i in program['args']];link=program['identity_fact_id']
    if a['subject_id']==b['subject_id'] and link is None:
        track=facts[a['subject_id']]
        # A shared ID alone is not evidence: the track claim must cover both events.
        require(track.get('identity_scope')=='tracked_entity','SHARED_NODE_NOT_A_VERIFIED_TRACK')
        support=set(a['support_frame_ids'])|set(b['support_frame_ids'])
        require(support<=set(track['support_frame_ids']),'TRACK_MISSING_EVENT_SUPPORT')
        return closure(facts,program['args']+[track['fact_id']])
    require(link in facts and facts[link]['kind']=='identity','IDENTITY_PROOF_REQUIRED')
    f=facts[link]
    require({a['subject_id'],b['subject_id']}=={f['subject_id'],f['object_id']},'WRONG_IDENTITY_ENDPOINTS')
    return closure(facts,program['args']+[link])

def freeze_question(g,program,seed=20261030):
    require(type(seed) is int,'SEED_INTEGER_REQUIRED')
    deps=dependencies(g,program);facts={f['fact_id']:f for f in g['facts']};a,b=[facts[i] for i in program['args']]
    context=(f'For the entity described as "{facts[a["subject_id"]]["predicate"]}" in event A '
             f'and "{facts[b["subject_id"]]["predicate"]}" in event B, ')
    if program['op']=='BEFORE':
        question=context+f'did it complete "{a["predicate"]}" strictly before starting "{b["predicate"]}"?'
        answer_type='boolean'
    else:
        question=context+f'which event finished entirely before the other started? A: {a["predicate"]}; B: {b["predicate"]}.'
        answer_type='choice'
    row={'video_id':g['video']['video_id'],'source_video_id':g['video']['source_video_id'],
         'raw_graph_sha256':digest(g),'question':question,'answer_type':answer_type,
         'program':deepcopy(program),'required_fact_ids':deps,'seed':seed,
         'template_version':'strict-order-v2','template_family':'temporal_order',
         'identity_mode':'shared_track' if program['identity_fact_id'] is None else 'explicit_link',
         'cross_clip':len(set(a['clip_ids']+b['clip_ids']))>1,
         'logical_hop_count':2,'dependency_fact_count':len(deps),
         'candidate_generated_from_raw_graph':True}
    row['program_sha256']=digest(program);row['question_id']='q_'+digest(row)[:20]
    row['frozen_sha256']=digest(row)
    return row

def check_frozen(g,q):
    row=deepcopy(q);h=row.pop('frozen_sha256',None)
    require(digest(row)==h,'FROZEN_QUESTION_MUTATED')
    require(q['raw_graph_sha256']==digest(g),'RAW_GRAPH_MUTATED')
    require(q['program_sha256']==digest(q['program']),'PROGRAM_MUTATED')
    require(q['video_id']==g['video']['video_id'],'WRONG_VIDEO')
    require(q['required_fact_ids']==dependencies(g,q['program']),'DEPENDENCY_CLOSURE_MISMATCH')
    # Recompute full template, IDs, options; not just self-provided checksums.
    require(freeze_question(g,q['program'],q['seed'])==q,'NONCANONICAL_QUESTION')

def frequency(g,f):
    rs={r['parser_run_id']:r for r in g['parser_runs']};r=rs[f['parser_run_id']]
    n=sum(x['sample_group']==r['sample_group'] and x['frame_ids']==r['frame_ids'] for x in rs.values())
    return len(f['matched_parser_run_ids'])/n

def ledger_entry(g,fact_id,visual_verdict,checker_revision,checked_frames,*,
                 checker_run_id,raw_response,reason,cost_gpu_sec=0,tokens=0):
    _,_,_,facts=validate_graph(g);f=facts[fact_id]
    require(visual_verdict in ['yes','no','uncertain'],'VERDICT_ENUM')
    require(visual_verdict==parse_check_response(raw_response),'CHECKER_RESPONSE_VERDICT_MISMATCH')
    require(set(checked_frames)==set(f['support_frame_ids']),'CHECK_ALL_SUPPORT_FRAMES')
    require(checker_revision and checker_run_id and isinstance(raw_response,str) and isinstance(reason,str)
            and finite(cost_gpu_sec) and cost_gpu_sec>=0 and type(tokens) is int and tokens>=0,'CHECKER_PROVENANCE')
    return {'fact_id':fact_id,'raw_graph_sha256':digest(g),'fact_sha256':digest(f),
            'visual_verdict':visual_verdict,'checker_revision':checker_revision,
            'checked_frame_ids':list(checked_frames),'cost_gpu_sec':cost_gpu_sec,'tokens':tokens,
            'checker_run_id':checker_run_id,'raw_response':raw_response,'reason':reason,
            'checker_independence':'none','frequency':frequency(g,f),
            'frequency_matching':'exact canonical signature; same evidence sample group'}

def parse_check_response(raw_response):
    if not isinstance(raw_response,str):return 'uncertain'
    text=raw_response.strip().lower()
    return text if text in ['yes','no','uncertain'] else 'uncertain'

def verify_ledger(g,ledger):
    _,_,_,facts=validate_graph(g);byid={}
    for e in ledger:
        keys(e,['fact_id','raw_graph_sha256','fact_sha256','visual_verdict','checker_revision',
                'checked_frame_ids','cost_gpu_sec','tokens','checker_independence','frequency','frequency_matching',
                'checker_run_id','raw_response','reason'])
        i=e['fact_id'];require(i in facts,'DANGLING_LEDGER');require(i not in byid,'DUPLICATE_LEDGER')
        require(e['raw_graph_sha256']==digest(g) and e['fact_sha256']==digest(facts[i]),'STALE_LEDGER')
        rebuilt=ledger_entry(g,i,e['visual_verdict'],e['checker_revision'],e['checked_frame_ids'],
            checker_run_id=e['checker_run_id'],raw_response=e['raw_response'],reason=e['reason'],
            cost_gpu_sec=e['cost_gpu_sec'],tokens=e['tokens'])
        require(rebuilt==e,'LEDGER_PROVENANCE_MISMATCH');byid[i]=e
    return byid

def execute(g,q,*,method='B1',ledger=None,threshold=.75):
    trace=[]
    def result(status,answer=None,reason=None):
        return {'question_id':q.get('question_id'),'method':method,'status':status,'answer':answer,
                'reason':reason,'required_fact_ids':q.get('required_fact_ids',[]),'execution_trace':trace}
    try:
        require(method in ['B1','B2'],'METHOD_ENUM');require(finite(threshold) and 0<=threshold<=1,'BAD_THRESHOLD')
        check_frozen(g,q);facts={f['fact_id']:f for f in g['facts']}
        if method=='B2':
            byid=verify_ledger(g,ledger or [])
            for i in q['required_fact_ids']:
                e=byid.get(i)
                trace.append({'read_fact_id':i,'verification':e['visual_verdict'] if e else 'missing'})
                if not e or e['visual_verdict']!='yes' or e['frequency']<threshold:
                    return result('ABSTAIN',reason='REQUIRED_FACT_NOT_ACCEPTED:'+i)
        else: trace.extend({'read_fact_id':i,'verification':'unverified'} for i in q['required_fact_ids'])
        link=q['program']['identity_fact_id']
        if link is not None and facts[link]['identity_status']!='known':
            return result('ABSTAIN',reason='UNKNOWN_IDENTITY')
        a,b=[facts[i] for i in q['program']['args']]
        forward=a['end_sec_range'][1]<b['start_sec_range'][0]
        reverse=b['end_sec_range'][1]<a['start_sec_range'][0]
        trace.append({'order_test':'latest_end < earliest_start','forward':forward,'reverse':reverse})
        if not (forward or reverse):return result('ABSTAIN',reason='OVERLAPPING_OR_UNCERTAIN_ORDER')
        answer=('yes' if forward else 'no') if q['program']['op']=='BEFORE' else ('A' if forward else 'B')
        return result('ANSWERED',answer=answer)
    except (ContractError,KeyError,TypeError,ValueError,IndexError) as e:
        return result('ABSTAIN',reason='INVALID_CONTRACT:'+str(e))

def normalize_answer(text,answer_type):
    if not isinstance(text,str): return None
    x=text.strip().lower()
    if answer_type=='boolean':return {'yes':'yes','true':'yes','no':'no','false':'no'}.get(x)
    if answer_type=='choice':return {'a':'A','(a)':'A','a.':'A','b':'B','(b)':'B','b.':'B'}.get(x)
    raise ContractError('UNKNOWN_ANSWER_TYPE')

def majority_vote(question_id,texts,answer_type,threshold=.5):
    require(len(texts)==8,'EXPECTED_K8');require(finite(threshold) and .5<=threshold<=1,'BAD_THRESHOLD')
    normalized=[normalize_answer(t,answer_type) for t in texts];counts=Counter(x for x in normalized if x)
    winner=min(counts,key=lambda x:(-counts[x],x)) if counts else None
    fraction=counts[winner]/8 if winner else 0
    accepted=fraction>.5 and fraction>=threshold
    return {'question_id':question_id,'method':'B0','status':'ANSWERED' if accepted else 'ABSTAIN',
            'answer':winner if accepted else None,'vote_label':winner if accepted else None,
            'vote_fraction':fraction,'valid_rollout_count':sum(counts.values()),
            'invalid_format_count':normalized.count(None),'rollouts':list(texts),'normalized':normalized,
            'reason':None if accepted else 'NO_STRICT_MAJORITY_OR_THRESHOLD'}

def b0_payload(g,q):
    check_frozen(g,q)
    return {'video_id':q['video_id'],'frames':[{k:f[k] for k in ['frame_id','file','pts','time_sec','sha256']} for f in g['frames']],
            'question':q['question'],'answer_type':q['answer_type'],
            'format_instruction':'Reply only yes/no.' if q['answer_type']=='boolean' else 'Reply only A/B.'}

def checker_payload(g,fact_id):
    _,fs,_,facts=validate_graph(g);f=facts[fact_id]
    # Only a single atomic claim plus its referent descriptions, never question/program/answer/gold.
    refs={k:facts[f[k]]['predicate'] for k in ('subject_id','object_id') if k in f}
    claim={k:f[k] for k in ['kind','predicate','start_sec_range','end_sec_range']}
    claim.update({k:f[k] for k in ['attribute_value','node_type','identity_status','identity_scope'] if k in f})
    return {'video_id':g['video']['video_id'],'claim':claim,
            'referents':refs,'frames':[deepcopy(fs[i]) for i in f['support_frame_ids']],
            'instruction':('Verify this one claim, including its time evidence. '
                'For a tracked_entity object, YES requires the SAME PHYSICAL ENTITY across ALL supplied frames, '
                'not merely similar-looking objects in each frame. For an identity edge verify the two referents are the same entity. '
                'Reply yes/no/uncertain. No inference from missing facts.')}

def parser_payload(video,frames):
    # Reject labels/unapproved metadata, instead of forwarding an arbitrary manifest row.
    keys(video,['video_id','source_video_id','path','sha256','duration_sec','avg_fps','time_base','start_pts','source','split','license_status'])
    for f in frames:keys(f,['frame_id','clip_id','pts','time_sec','sha256','file'])
    return {'video':deepcopy(video),'frames':deepcopy(frames),'schema_version':'pilot-v1'}

def not_run_rows(questions):
    ids=[q['question_id'] for q in questions];unique(ids,'DUPLICATE_QUESTION_ID')
    return [{'question_id':i,'method':m,'status':'NOT_RUN','answer':None,'reason':'GATE_A_NO_INFERENCE'} for i in ids for m in ['B0','B1','B2']]
