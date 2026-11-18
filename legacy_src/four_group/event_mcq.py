"""Graph-only full event QA generation; public32 MCQ Solver; data-only review."""
import os,sys,re,json,copy,random,collections,subprocess,difflib
from pathlib import Path
from step_six.common import *
from stsg_pilot.runtime import save,emit
BASE=Path('/scratch/haozhe/.cache/vlm-rsi/public32/2e2321e3-316b-447d-ad3f-57b47dfdaf22')
PROMPT='''Generate English event multiple-choice QA pairs only from the serialized spatiotemporal graph below. Generate at most four candidates, each with exactly four distinct options. Prefer ordering two events, what happened after an event, changes in the same object, or motion direction. Locate the question by actions/events, not exact public timestamps; keep timestamps only in internal evidence. Every answer must depend on relations between two or more moments. Skip single-time color/material questions. Check that the question/options do not reveal the correct answer. Do not supplement static questions to reach a count.
Only give a candidate answer if the graph explicitly supports the requested relation. Whole-clip start/end bounds are observation ranges, not event onsets/offsets. If records are holistic descriptions, affected objects unresolved, event order unknown, or evidence conflicting, report the concrete reason instead. Missing actions mean unknown, never evidence of absence. Do not upgrade usable_for_program_QA=false Motion records to bound event instances. Do not infer intermediate actions from static endpoints. For state change cite two different observed values of the same attribute on the same identity-linked object; for ordering cite two distinct bound event instances with nonoverlapping actual event bounds.
Return JSON {"candidates":[{"question":"English event question","options":["option1","option2","option3","option4"],"answer_index":0,"type":"event_order|event_after|state_change|motion_direction","event_or_action_edge_ids":[],"fact_ids":[],"identity_connection_ids":[],"evidence_frame_ids":[],"cross_frame_reason":"one sentence explaining which cross-frame relation determines the answer"}],"unanswerable":[{"type":"...","reason":"specific graph gap"}]}. Answer index must refer to your option list. Do not add graph/node IDs to the public question or options. No images are supplied to you. Graph facts can themselves be wrong; do not invent corrections.
'''
def similar(a,b):
 a=re.sub(r'[^a-z ]',' ',a.lower());b=re.sub(r'[^a-z ]',' ',b.lower());aa=set(a.split());bb=set(b.split());return a.strip()==b.strip() or len(aa&bb)/max(1,len(aa|bb))>=.8 or difflib.SequenceMatcher(None,a,b).ratio()>=.9

def validate(q,g,facts,pairs,frames,exclusions):
 try:
  assert q['type'] in ['event_order','event_after','state_change','motion_direction'],'NOT_EVENT_TYPE'
  assert len(q['options'])==4 and len({norm(x) for x in q['options']})==4,'OPTIONS_FORMAT'
  assert isinstance(q['answer_index'],int) and 0<=q['answer_index']<4,'ANSWER_INDEX'
  assert len(set(q['evidence_frame_ids']))>=2 and set(q['evidence_frame_ids'])<=frames,'FRAME_IDS'
  assert q['cross_frame_reason'].strip(),'CROSS_FRAME_REASON_MISSING'
  assert q['fact_ids'] and set(q['fact_ids'])<=facts.keys(),'FACT_IDS'
  assert not re.search(r'\b(?:src_\d+|o\d+|a\d+)\b|\d+(?:\.\d+)?\s*(?:seconds?|secs?)',q['question']),'PUBLIC_ID_OR_TIMESTAMP'
  assert not any(similar(q['question'],x) for x in exclusions),'EXACT_OR_NEAR_DUPLICATE'
  assert norm(q['options'][q['answer_index']]) not in norm(q['question']),'ANSWER_TEXT_IN_QUESTION'
  motions={m['id']:m for m in g['motion_edges']};events={e['id']:e for e in g.get('event_edges',[])};ids=q['event_or_action_edge_ids'];assert ids and all(i in motions or i in events for i in ids),'EVENT_EDGE_IDS'
  positive={r['id']:r for p in pairs for r in p.get('results',[]) if r['verdict']=='YES' and r['state'] in ['STATIC_MERGED','REFERENCE_CREATED','MOTION_EXTRACTED_NOT_INDEPENDENTLY_VALIDATED']}
  if q['type']=='state_change':
   ff=[facts[i] for i in q['fact_ids'] if facts[i]['kind']=='attribute'];assert len(ff)>=2,'TWO_OBSERVED_ATTRIBUTES_REQUIRED'
   found=False
   for a in ff:
    for b in ff:
     if a['scope']==b['scope'] or a['content']['type']!=b['content']['type'] or norm(a['content']['value'])==norm(b['content']['value']):continue
     left=a['scope']+'/'+a['parent_ids'][0];right=b['scope']+'/'+b['parent_ids'][0]
     for eid in q['identity_connection_ids']:
      edge=positive.get(eid)
      if edge and {left,right}=={edge['left'],edge['right']} and {a['scope'].split('/')[-1],b['scope'].split('/')[-1]}<=set(q['evidence_frame_ids']):found=True
   assert found,'STATE_CHANGE_IDENTITY_OR_VALUES_NOT_BOUND'
  else:
   selected=[motions.get(i,events.get(i)) for i in ids];assert all(x.get('usable_for_program_QA',False) and not x.get('affected_object_text_is_not_graph_reference',True) for x in selected),'EVENT_ENTITY_OR_INTERVAL_UNRESOLVED'
   if q['type'] in ['event_order','event_after']:
    assert len(set(ids))>=2,'TWO_DISTINCT_EVENTS_REQUIRED';ranges=[x.get('event_interval_sec') for x in selected];assert all(ranges),'NO_ACTUAL_EVENT_BOUNDS';assert any(a[1]<b[0] for a in ranges for b in ranges),'ORDER_NOT_ESTABLISHED'
  return None
 except (AssertionError,KeyError,TypeError,ValueError) as e:return str(e) or type(e).__name__

def compact(g,facts,pairs,vid):
 nodes=[{'id':k,'label':v['object']['label'],'classification':v['classification'],'frame_id':v['source_frame']['frame_id'],'time_sec':v['source_frame']['time_sec']} for k,v in g['source_nodes'].items() if k.startswith(vid+'/')];ff=[]
 for k,v in facts.items():
  if v.get('video_id')!=vid and not k.startswith(vid+'/'):continue
  c=v.get('content',{});content={a:c[a] for a in ['label','type','value','subject_id','predicate','object_id'] if a in c};ff.append({a:v.get(a) for a in ['id','kind','scope','time_sec','parent_ids']}|{'content':content})
 return {'objects':nodes,'facts':ff,'motion_edges':[x for x in g['motion_edges'] if x['left'].startswith(vid+'/')],'clip_observations':[x for x in g['event_edges'] if x['video_id']==vid],'identity_pair_ledger':[{'id':x['id'],'kind':x['kind'],'left_scope':x['left_scope'],'right_scope':x['right_scope'],'state':x['state'],'verdict_counts':dict(collections.Counter(r['verdict'] for r in x.get('results',[]))),'positive_or_conflicting_results':[{k:r.get(k) for k in ['id','left','right','verdict','state']} for r in x.get('results',[]) if r['verdict']=='YES' or 'CONFLICT' in r['state']]} for x in pairs if x['video_id']==vid]}

def main():
 cfg=j('config/four_group.json');cfg['protocol_version']='GRAPH-EVENT-MCQ-v1';root=Path('/scratch/haozhe/.cache/vlm-rsi/event-mcq')/os.environ['ORX_RUN_ID'];root.mkdir(parents=True);save(root/'effective_config.json',cfg);media=j(BASE/'PUBLIC32_FROZEN.json');exclusions=[];sources={};inputs={}
 for batch in ['first2','remaining8']:
  folder=BASE/batch;g=j(folder/'GRAPH_SHARED_FROZEN.json');facts=j(folder/'FACT_REGISTRY.json');pairs=j(folder/'SOURCE_TEMPORAL_PAIRS.json');exclusions += [q['question'] for q in rows(folder/'S_FROZEN_QA.jsonl')+rows(folder/'P_FROZEN_QA.jsonl')]
  for vid in media:
   if any(n.startswith(vid+'/') for n in g['source_nodes']):inputs[vid]=(g,facts,pairs)
  sources[batch]={n:filehash(folder/n) for n in ['GRAPH_SHARED_FROZEN.json','FACT_REGISTRY.json']}
 prior=Path('/scratch/haozhe/.cache/vlm-rsi/public32-followup/e02255a6-c5cd-4e51-a3ef-7a73aea422ab/FROZEN_ALL_QA.jsonl');exclusions += [q['question'] for q in rows(prior) if q.get('cohort')=='new_temporal']
 manual=Path('config/manual12_exclusions.json');manual_ready=manual.exists();manual_rows=j(manual) if manual_ready else [];exclusions += [x['question'] if isinstance(x,dict) else x for x in manual_rows];save(root/'EXCLUSIONS.json',{'texts':exclusions,'manual12_found':manual_ready,'manual_count':len(manual_rows),'strict_manual_exclusion_verified':manual_ready and len(manual_rows)==12})
 save(root/'SOURCE_HASHES.json',sources);save(root/'MEDIA_FROZEN.json',media);rt=make_runtime(cfg,root/'Questioner','graph_only_Questioner',choose_gpu());accepted=[];allrows=[];vidstats=[]
 try:
  for vid in sorted(media,key=lambda v:int(v.split('_')[-1])):
   if vid not in inputs:vidstats.append({'video_id':vid,'failure':'NO_GRAPH','retained_in_denominator':True});continue
   g,facts,pairs=inputs[vid];graph=compact(g,facts,pairs,vid);prompt=PROMPT+'Excluded development questions (do not reproduce these or near-paraphrases; their answers are not gold): '+json.dumps([x['question'] if isinstance(x,dict) else x for x in manual_rows],ensure_ascii=False)+'\nGraph: '+json.dumps(graph,ensure_ascii=False,separators=(',',':'));save(root/'graph_inputs'/(vid+'.json'),graph);(root/'prompts').mkdir(exist_ok=True);(root/'prompts'/(vid+'.txt')).write_text(prompt);rt.mode='text';row={'video_id':vid,'status':'FAILED','candidates':[]}
   try:
    result=rt.ask(media[vid],[],prompt,role='graph_event_QA',owner=vid,max_tokens=4096,temperature=0,seed=2026111401);row['raw_response']=result['raw_response'];assert not result['output_hit_cap'],'OUTPUT_TRUNCATED';reply=parsejson(result['raw_response']);row.update(status='COMPLETED',unanswerable=reply.get('unanswerable',[]));assert len(reply['candidates'])<=4,'CANDIDATE_CAP'
    for ix,q in enumerate(reply['candidates']):
     q=copy.deepcopy(q);reason=validate(q,g,{k:v for k,v in facts.items() if v.get('video_id')==vid or k.startswith(vid+'/')},pairs,{f['frame_id'] for f in media[vid]['class_video_views']},exclusions+[x['question'] for x in accepted]);q.update(video_id=vid,rejection_reason=reason,status='REJECTED' if reason else 'STRUCTURALLY_SUPPORTED')
     if not reason:
      answer=q['options'][q['answer_index']];order=list(range(4));random.Random(h([vid,ix,'option_seed_v1'])).shuffle(order);q['options']=[q['options'][i] for i in order];q['graph_answer']='ABCD'[q['options'].index(answer)];q['review_id']='event_'+h([vid,q])[:12];accepted.append(q)
     row['candidates'].append(q);allrows.append(q)
   except Exception as e:row['error']=repr(e)
   save(root/'generation'/(vid+'.json'),row);vidstats.append({'video_id':vid,'generation_status':row['status'],'candidate_count':len(row['candidates']),'accepted':sum(q.get('rejection_reason') is None for q in row['candidates']),'failure':row.get('error')})
 finally:allocation(rt,root/'Questioner')
 jl(root/'ALL_CANDIDATES.jsonl',allrows);save(root/'VIDEO_YIELD.json',vidstats)
 if accepted and not (manual_ready and len(manual_rows)==12):
  jl(root/'PROVISIONAL_QA_AWAITING_MANUAL_EXCLUSION.jsonl',accepted);save(root/'STATUS.json',{'stage':'AWAITING_MANUAL12_EXCLUSION_FILE','videos_attempted':len(vidstats),'voting_started':False});emit('event_mcq_waiting_manual_exclusions',root=str(root));return
 jl(root/'QA_FROZEN.jsonl',accepted);save(root/'FREEZE.json',{'QA_sha256':filehash(root/'QA_FROZEN.jsonl'),'media_sha256':filehash(root/'MEDIA_FROZEN.json')});emit('event_mcq_freeze',questions=len(accepted))
 votes=[]
 if accepted:
  solver=make_runtime(dict(cfg,model_path=cfg['solver_model_path'],model_revision=cfg['solver_model_revision']),root/'Solver','event_mcq_solver',choose_gpu())
  try:
   for q in accepted:
    samples=[]
    for i in range(10):
     s={'sample_index':i,'seed':20261101030+i,'status':'FAILED','answer':None}
     try:
      solver.mode='video';public=q['question']+'\n'+'\n'.join(f'{c}. {o}' for c,o in zip('ABCD',q['options']));r=solver.ask(media[q['video_id']],[], 'Choose the best option using the supplied video. Return JSON {"answer":"A|B|C|D"}; use null if evidence is insufficient.\n'+public,role='v4_event_mcq',owner=q['review_id']+':'+str(i),temperature=.7,max_tokens=2048,seed=s['seed']);s.update(raw_response=r['raw_response'],request_id=r['request_id']);assert not r['output_hit_cap'],'TRUNCATED';a=parsejson(r['raw_response']).get('answer');s.update(answer=a.strip().upper() if isinstance(a,str) else None,status='VALID' if isinstance(a,str) and a.strip().upper() in 'ABCD' and len(a.strip())==1 else 'ABSTAIN')
     except Exception as e:s['error']=repr(e)
     samples.append(s)
    from four_group.results import aggregate
    v=aggregate(samples);votes.append({'review_id':q['review_id'],'samples':samples,'vote':v,'graph_answer':q['graph_answer'],'exact_agreement':v['strict_majority_answer']==q['graph_answer'].lower() if v['strict_majority_status']=='ANSWERED' else None});jl(root/'VOTES.jsonl',votes)
  finally:allocation(solver,root/'Solver')
 jl(root/'REVIEW_NO_ANSWERS.jsonl',[{k:q[k] for k in ['review_id','video_id','question','options']}|{'frames':[{'frame_id':f['frame_id'],'file':f['file'],'time_sec':f['time_sec']} for f in media[q['video_id']]['class_video_views']]} for q in accepted]);save(root/'SUMMARY.json',{'videos':10,'questions':len(accepted),'types':dict(collections.Counter(q['type'] for q in accepted)),'strict_majority_answered':sum(v['vote']['strict_majority_status']=='ANSWERED' for v in votes),'exact_matches':sum(v['exact_agreement'] is True for v in votes),'accuracy':'NOT_EVALUATED','cost':cost(root),'manual12_exclusions_verified':manual_ready and len(manual_rows)==12});emit('event_mcq_complete',root=str(root))
if __name__=='__main__':main()
