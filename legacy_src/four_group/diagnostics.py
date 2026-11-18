"""Post-freeze yield/type/cost diagnostics, never selects or changes questions."""
import collections,re
from pathlib import Path
from step_six.common import j,rows
from stsg_pilot.runtime import save

def report(root):
 root=Path(root);selected=j(root/'selection/SELECTION_FROZEN.json')['selected'];srows=rows(root/'S_ALL_CANDIDATES.jsonl');prows=rows(root/'P_ALL_CANDIDATES.jsonl');qs=rows(root/'S_FROZEN_QA.jsonl')+rows(root/'P_FROZEN_QA.jsonl');prepared=j(root/'native/VIDEO_PREPARATION.json');states={}
 for p in (root/'native/frames').glob('*/*/STATE.json'):
  x=j(p);vid=x['scope'].split('/')[0];states.setdefault(vid,[]).append(x['state'])
 requests={}
 for p in root.rglob('requests.jsonl'):
  for r in rows(p):requests[r['request_id']]=r
 qcost=[]
 for q in qs:
  plan=q.get('plan_id');direct=[r for r in requests.values() if r.get('owner') in [q['question_id'],plan,'new:'+q['question_id']] or str(r.get('owner','')).startswith(q['question_id']+':')];qcost.append({'question_id':q['question_id'],'video_id':q['video_id'],'direct_model_calls':len(direct),'direct_input_tokens':sum(r.get('input_tokens',0) for r in direct),'direct_output_tokens':sum(r.get('output_tokens',0) for r in direct),'direct_device_seconds':sum(r.get('model_device_wall_seconds',0) for r in direct),'shared_native_construction_cost':'see per-video all calls; not silently allocated as direct question cost'})
 loss=[]
 for v in selected:
  vid=v['video_id'];ss=[x for x in srows if x['video_id']==vid];pp=[x for x in prows if x['video_id']==vid];qq=[x for x in qs if x['video_id']==vid];calls=[x for x in requests.values() if x.get('video_id')==vid]
  loss.append({'video_id':vid,'file_sha256':v['sha256'],'selected_denominator':1,'S1_status':next((x['status'] for x in prepared if x['video_id']==vid),'MISSING'),'keyframe_states':dict(collections.Counter(states.get(vid,[]))),'successful_graph_frame_count':sum(x in ['COMPLETED','PARTIAL'] for x in states.get(vid,[])),'S_attempts':len(ss),'S_attempt_statuses':dict(collections.Counter(x['status'] for x in ss)),'P_candidates':len(pp),'P_execution':dict(collections.Counter(x['execution']['status'] for x in pp)),'S_frozen':sum(x['route']=='S' for x in qq),'P_frozen':sum(x['route']=='P' for x in qq),'all_direct_and_shared_calls':len(calls),'device_seconds':sum(x.get('model_device_wall_seconds',0) for x in calls),'input_tokens':sum(x.get('input_tokens',0) for x in calls),'output_tokens':sum(x.get('output_tokens',0) for x in calls)})
 types=[]
 for q in qs:
  txt=q['question'].lower();typ=q.get('question_type','native_QRA');identity='same physical' in txt or 'identity' in txt or typ=='cross_frame_identity';action_order=bool(re.search(r'\b(before|after|first|last)\b',txt)) and any('motion'==e.get('kind') for e in q.get('path_edges',[]));times=[float(x) for x in re.findall(r'(\d+(?:\.\d+)?) seconds',txt)]
  types.append({'question_id':q['question_id'],'route':q['route'],'declared_type':typ,'coarse_text_type':'identity' if identity else 'action_order_candidate' if action_order else 'attribute_relation_or_static_observation','independent_temporal_necessity':'PENDING','public_time_tokens_seconds':times,'public_observation_span':max(times)-min(times) if len(times)>1 else 0 if times else None,'exact_question_duplicates_across_videos':sum(x['question'].strip().lower()==txt.strip() for x in qs),'risk_flags_are_not_filters':True})
 save(root/'VIDEO_YIELD_LOSS.json',loss);save(root/'QUESTION_TYPE_COVERAGE.json',types);save(root/'PER_QUESTION_DIRECT_COST.json',qcost)
 annotations=[str(p) for p in Path(selected[0]['path']).parent.parent.glob('*.json')] if selected else [];save(root/'GOLD_ALIGNMENT_AUDIT.json',{'searched':'selected pool parent top-level existing annotation JSON files','found_files':annotations,'matched_generated_question_gold_pairs':[],'accuracy':'PENDING_NO_ESTABLISHED_TASK_ENTITY_TIME_ALIGNMENT','no_correctness_inferred_from_agreement':True})
