"""Native STEP graph-path QRA and isolated deterministic program route."""
import copy,json,random
from pathlib import Path
from .common import *
from step_review.program_adapter import main_candidates,execute,select
REFINE='I have the question “[q]”, the rationale “[r]”, and the answer “[a]” about the video. Due to template generation, these may contain grammatical errors, logical inconsistencies, or unclear semantics. Please correct them and return the improved version in JSON format : {"Q":"question","R":"rationale","A":"answer"}'

def load_source(cfg):
 src=Path(cfg['graph_source']);state=j(src/'STATE.json');assert state['state'].startswith('COMPLETED'),state
 p3=src/'P3'/state['run'];g=j(p3/'STSG_partial.json');pairs=j(p3/'PAIR_LEDGER.json');ledger=rows(src/'NATIVE_VERIFICATION_LEDGER.jsonl');tasks={}
 for f in sorted((src/'frozen_inputs').glob('*.json')):
  for t in j(f)['all_tasks']:tasks[t['scope']]=t
 return src,g,pairs,ledger,tasks

def clip_events(rt,root,graph,tasks,media):
 groups={}
 for t in tasks.values():groups.setdefault((t['media']['video']['video_id'],t['media']['clip_id']),[]).append(t)
 events=[];anchors=[]
 for (vid,cid),tt in sorted(groups.items()):
  eid='event_'+h([vid,cid])[:12];out=root/'events'/(eid+'.json')
  if out.exists():row=j(out)
  else:
   # Only existing frozen visual inputs; restrict by the original S1 clip interval.
   interval=tt[0]['media']['clip_intervals'][0];lo,hi=interval;m=copy.deepcopy(media[vid]);fs=[f for f in m['class_video_views'] if lo<=f['time_sec']<=hi]
   # Include selected frozen keyframes where common video ranks omit a short clip.
   if not fs:fs=[absolute_media(t['media'])['calibration_view'] for t in sorted(tt,key=lambda t:t['media']['calibration_view']['time_sec'])]
   m['class_video_views']=fs;m['clip_intervals']=[interval]
   row={'id':eid,'type':'Event','video_id':vid,'clip_id':cid,'source':eid+'_start','target':eid+'_end','observation_interval_sec':interval,'input_frame_ids':[f['frame_id'] for f in fs],'time_semantics':'S1 clip observation bounds, not precise action/gold interval','topology_status':'RECONSTRUCTION_ASSUMPTION_CLIP_BOUNDARY_ANCHORS','independent_truth':'PENDING','native_post_event_verification':'NOT_DISCLOSED_NOT_INVENTED'}
   try:
    r=ask(rt,m,'Describe the events in this video clip, providing a holistic description of the clip. Describe only observable events; do not infer hidden actions.','native_clip_holistic_description',eid,'video',1024)
    row.update(status='EXTRACTED_UNVERIFIED',description=r['raw_response'],source_request_ids=[r['request_id']])
   except Exception as e:row.update(status='UNRESOLVED',error=repr(e),description=None,source_request_ids=[])
   save(out,row)
  events.append(row);anchors += [{'id':row['source'],'type':'ClipBoundary','time_sec':row['observation_interval_sec'][0]},{'id':row['target'],'type':'ClipBoundary','time_sec':row['observation_interval_sec'][1]}]
 graph=copy.deepcopy(graph);graph.update(event_edges=events,clip_boundary_nodes=anchors,graph_version='V2-six-v1',complete_G_step=False,status='PARTIAL',event_topology_assumption=True,missing_modules=['independent fact truth','author-undisclosed exact event topology/prompt','author-undisclosed QA sampling/template details']);save(root/'GRAPH_SHARED_FROZEN.json',graph);return graph

def fact_id(r):return r['scope']+'/'+r['fact_id']
def registry(ledger,pairs,graph,tasks):
 byid={fact_id(r):r for r in ledger if r['state']=='ACCEPTED'};facts={}
 def ref(scope,oid):
  o=byid.get(scope+'/'+oid);return o['candidate_content']['referent'] if o else None
 for fid,r in byid.items():
  c=r['candidate_content'];scope=r['scope'];typ=r['fact_type'];parents=[scope+'/'+x for x in r['parent_ids']];t=r['source_keyframe']['time_sec'];claim=None
  if typ=='object':claim='The '+c['referent']+' is visible in this frame.'
  elif typ=='attribute' and ref(scope,r['parent_ids'][0]):claim='The '+ref(scope,r['parent_ids'][0])+' has '+c['type'].replace('_',' ')+' '+c['value']+'.'
  elif typ=='relation' and ref(scope,c['subject_id']) and ref(scope,c['object_id']):claim='The '+ref(scope,c['subject_id'])+' '+c['predicate']+' the '+ref(scope,c['object_id'])+'.'
  if claim:facts[fid]={'id':fid,'kind':typ,'claim':claim,'scope':scope,'video_id':scope.split('/')[0],'time_sec':t,'parent_ids':parents,'content':c,'native_ledger':r,'media':absolute_media(tasks[scope]['media']),'verification_mode':'image','graph_fact_sha256':h(r)}
 for pair in pairs:
  for r in pair.get('results',[]):
   if r['state'] not in ['STATIC_MERGED','REFERENCE_CREATED','MOTION_EXTRACTED_NOT_INDEPENDENTLY_VALIDATED']:continue
   a,b=facts.get(r['left']),facts.get(r['right'])
   if not a or not b:continue
   typ='identity';claim='The '+a['content']['referent']+f' at {a["time_sec"]:.6f} seconds and the '+b['content']['referent']+f' at {b["time_sec"]:.6f} seconds are the same physical object.'
   facts[r['id']]={'id':r['id'],'kind':typ,'claim':claim,'video_id':pair['video_id'],'parent_ids':[r['left'],r['right']],'content':r,'verification_mode':'video','pair_id':pair['id'],'graph_fact_sha256':h(r)}
 for r in graph['motion_edges']:
  facts['motion:'+r['id']]={'id':'motion:'+r['id'],'kind':'motion','claim':r.get('action',''),'video_id':r['source'].split('/')[0],'parent_ids':[r['source'],r['target']],'content':r,'verification_mode':'video','unresolved_reason':'affected object binding and precise action boundaries not independently established','graph_fact_sha256':h(r)}
 for r in graph['event_edges']:
  facts[r['id']]={'id':r['id'],'kind':'event','claim':r['description'],'video_id':r['video_id'],'parent_ids':[],'content':r,'verification_mode':'video','graph_fact_sha256':h(r),'unresolved_reason':'holistic description is not a complete atomization; clip bounds are observation bounds'}
 return facts

def path_plans(graph,facts,seed=2026110103):
 # STEP main Sec3.2 Q/A-frontier expansion. Non-disclosed tie-breaking,
 # N and per-video trial count fixed here; no solver answer is consulted.
 adjacency={};edges=[]
 def add(a,b,ids,kind):
  if a not in facts or b not in facts:return
  e={'a':a,'b':b,'fact_ids':ids,'kind':kind};edges.append(e);adjacency.setdefault(a,[]).append(e);adjacency.setdefault(b,[]).append(e)
 for f in facts.values():
  if f['kind']=='attribute' and f['parent_ids']:add(f['parent_ids'][0],f['id'],[f['parent_ids'][0],f['id']],'attribute')
  elif f['kind']=='relation' and len(f['parent_ids'])==2:add(*f['parent_ids'],f['parent_ids']+[f['id']],'relation')
  elif f['kind']=='identity' and len(f['parent_ids'])==2:add(*f['parent_ids'],f['parent_ids']+[f['id']],'identity')
 rng=random.Random(seed);plans=[]
 for vid in sorted({x['video_id'] for x in facts.values()}):
  eligible=[e for e in edges if facts[e['a']]['video_id']==vid];rng.shuffle(eligible)
  for ix in range(4):
   pid='s_plan_'+h([vid,ix,seed])[:12]
   if ix>=len(eligible):plans.append({'plan_id':pid,'video_id':vid,'status':'NO_CONNECTED_PAIR'});continue
   initial=eligible[ix];qset={initial['a']};aset={initial['b']};chosen=[initial];steps=[]
   for n in range(3):
    expandable=[q for q in sorted(qset) if any((e['b'] if e['a']==q else e['a']) not in aset for e in adjacency.get(q,[]))]
    if not expandable:break
    q=rng.choice(expandable);qset.remove(q);aset.add(q);opened=[]
    for e in adjacency[q]:
     other=e['b'] if e['a']==q else e['a']
     if other not in aset:
      qset.add(other);opened.append(other)
      if e not in chosen:chosen.append(e)
    steps.append({'expanded_Q_node':q,'moved_to_A':q,'opened_neighbor_nodes':opened,'Q':sorted(qset),'A':sorted(aset)})
   dep=sorted({fid for e in chosen for fid in e['fact_ids']});times=[facts[f]['time_sec'] for f in dep if 'time_sec' in facts[f]];events=[e for e in graph['event_edges'] if e['video_id']==vid and e['description'] and min(times)>=e['observation_interval_sec'][0] and max(times)<=e['observation_interval_sec'][1]]
   plans.append({'plan_id':pid,'video_id':vid,'status':'PLANNED','initial_pair':initial,'expansion_steps':steps,'path_edges':chosen,'fact_ids':dep,'event_context':rng.choice(events) if events else None,'initial_Q_nodes':[initial['a']],'initial_A_nodes':[initial['b']],'max_expansion_steps':3})
 return plans

def s_route(rt,root,graph,facts,media):
 plans=path_plans(graph,facts);save(root/'S_PATH_PLANS_FROZEN.json',plans);candidates=[];frozen=[]
 for p in plans:
  out=root/'S_candidates'/(p['plan_id']+'.json')
  if out.exists():row=j(out)
  else:
   row={**p,'route':'S','graph_sha256':filehash(root/'GRAPH_SHARED_FROZEN.json')}
   if p['status']=='PLANNED':
    try:
     path=[{k:v for k,v in facts[x].items() if k in ['id','kind','claim','time_sec','parent_ids']} for x in p['fact_ids']]
     # Native graph-guided QRA initial-template wording not published. Keep graph
     # path sampling/iterative subquestions, then exact Supplement refinement.
     prompt='Generate one compositional video question, explicit step-by-step rationale as subquestion/answer pairs, and its answer from this connected graph reasoning path. Use the initial Q/A node pair as the initial subquestion/answer, and incorporate the recorded frontier expansions in order. Use only supplied graph facts. Do not invent actions, identity, ordering, counts or absent facts. Apply the supplied clip time range as temporal context when present. Do not answer from external knowledge. Return JSON {"Q":"question","R":"explicit subquestion and answer reasoning","A":"concise answer","used_fact_ids":["IDs"]}.\n'+json.dumps({'path':path,'initial_pair':p['initial_pair'],'expansions':p['expansion_steps'],'event_context':p['event_context']},ensure_ascii=False)
     initial=ask(rt,media[p['video_id']],prompt,'native_graph_path_initial_QRA',p['plan_id']);raw=parsejson(initial['raw_response']);assert all(isinstance(raw.get(k),str) and raw[k].strip() for k in ['Q','R','A']);assert set(raw.get('used_fact_ids',[]))<=set(p['fact_ids'])
     refine=REFINE.replace('[q]',raw['Q']).replace('[r]',raw['R']).replace('[a]',raw['A']);r=ask(rt,media[p['video_id']],refine,'native_supp_A2_QRA_refinement',p['plan_id']);final=parsejson(r['raw_response']);assert all(isinstance(final.get(k),str) and final[k].strip() for k in ['Q','R','A'])
     row.update(status='FROZEN',question_id='S_'+h([p['plan_id'],final])[:16],question=final['Q'],rationale=final['R'],answer=final['A'],initial_QRA=raw,initial_request_id=initial['request_id'],refinement_request_id=r['request_id'],answer_changed_during_native_refinement=raw['A']!=final['A'],dependencies_status='AWAITING_POST_FREEZE_VQS_EXTRACTION',time_range_sec=p['event_context']['observation_interval_sec'] if p['event_context'] else None)
    except Exception as e:row.update(status='GENERATION_FAILED',error=repr(e))
   save(out,row)
  candidates.append(row)
  if row['status']=='FROZEN':frozen.append(row)
 jl(root/'S_ALL_CANDIDATES.jsonl',candidates);jl(root/'S_FROZEN_QA.jsonl',frozen);return frozen

def p_route(root,graph,ledger,pairs):
 candidates=main_candidates(graph,ledger,pairs,'V2-six-v1')
 for q in candidates:q['execution']=execute(q,ledger,pairs,graph)
 selected=select(candidates);frozen=[]
 for q in selected:
  if q['execution']['status']!='ANSWERED':continue
  deps=[d['fact_key'].rsplit('/',1)[0] if 'fact_key' in d else d['connection_key'].rsplit('/',1)[0] for d in q['dependencies']]
  scopes={d.rsplit('/',1)[0] for d in deps if '/src_' in d and not '__' in d};lookup=[r for r in ledger if r['scope'] in scopes and r['fact_type']=='object' and r['state']=='ACCEPTED']
  # Record the exact scope/class lookup universe used by unique(), plus all
  # target fact reads and temporal connection reads. The open-world uniqueness
  # claim is additionally checked against pixels by VQS, never inferred true.
  trace={'value_and_parent_fact_ids':deps,'scope_object_lookup_rows':[{'id':r['scope']+'/'+r['fact_id'],'content_sha256':h(r),'label':r['candidate_content']['label']} for r in lookup],'source_ledger_sha256':h(ledger),'source_pairs_sha256':h(pairs),'source_graph_sha256':h(graph),'operations':['select ACCEPTED scope/type index','bind object label and uniqueness','read matching attribute/relation or explicit identity connection','execute frozen op'],'scope_completeness':'automatic graph partial; visual uniqueness constraint required'}
  q=copy.deepcopy(q);q.update(route='P',answer=q['execution']['answer'],fact_ids=sorted(set(deps+[x['id'] for x in trace['scope_object_lookup_rows']])),program_read_trace=trace,graph_sha256=filehash(root/'GRAPH_SHARED_FROZEN.json'),time_range_sec=None);frozen.append(q)
 jl(root/'P_ALL_CANDIDATES.jsonl',candidates);jl(root/'P_FROZEN_QA.jsonl',frozen);return frozen
