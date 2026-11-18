"""Frozen unfiltered routes. Only syntax/references/execution gate publication."""
import copy,json,re
from pathlib import Path
from step_six.common import *
from step_six.graph_routes import path_plans,REFINE
from step_six.rationale_recovery import raw_member

def bounded(rt,m,prompt,role,owner,mode='text',caps=(2048,4096),seed=2026110201):
 attempts=[]
 for cap in caps:
  rt.mode=mode;r=rt.ask(m,[],prompt,role=role,owner=owner,seed=seed,max_tokens=cap,temperature=0);attempts.append({'request_id':r['request_id'],'cap':cap,'truncated':r['output_hit_cap']})
  if not r['output_hit_cap']:return r,attempts
 raise ValueError('FIXED_OUTPUT_CAP_EXHAUSTED:'+json.dumps(attempts))

def s_route(rt,root,graph,facts,media,selected):
 plans=path_plans(graph,facts,2026110201);by={(p['video_id'],i):p for v in selected for i,p in enumerate([p for p in plans if p['video_id']==v['video_id']])}
 # path_plans omits videos with zero facts; explicitly retain four failure slots.
 frozen=[];allrows=[];seen=set()
 for v in selected:
  pp=[p for p in plans if p['video_id']==v['video_id']]
  for i in range(4):
   p=pp[i] if i<len(pp) else {'plan_id':'s_plan_'+h([v['video_id'],i,2026110201])[:12],'video_id':v['video_id'],'status':'NO_CONNECTED_PAIR'};path=root/'S_candidates'/(p['plan_id']+'.json')
   if path.exists():row=j(path)
   else:
    row={**p,'route':'S','graph_sha256':filehash(root/'GRAPH_SHARED_FROZEN.json')}
    if p['status']=='PLANNED':
     try:
      evidence=[{k:val for k,val in facts[x].items() if k in ['id','kind','claim','time_sec','parent_ids']} for x in p['fact_ids']]
      prompt='Generate one compositional video question, explicit step-by-step rationale as subquestion/answer pairs, and its answer from this connected graph reasoning path. Use the initial Q/A node pair as the initial subquestion/answer, and incorporate the recorded frontier expansions in order. Use only supplied graph facts. Do not invent actions, identity, ordering, counts or absent facts. Apply the supplied clip time range as temporal context when present. Return JSON {"Q":"question","R":"explicit subquestion and answer reasoning","A":"concise answer","used_fact_ids":["IDs"]}.\n'+json.dumps({'path':evidence,'initial_pair':p['initial_pair'],'expansions':p['expansion_steps'],'event_context':p.get('event_context')},ensure_ascii=False)
      r,attempts=bounded(rt,media[v['video_id']],prompt,'native_graph_path_initial_QRA',p['plan_id']);initial=parsejson(r['raw_response']);Q=raw_member(r['raw_response'],'Q');R=raw_member(r['raw_response'],'R');A=raw_member(r['raw_response'],'A');assert set(initial.get('used_fact_ids',[]))<=set(p['fact_ids'])
      row.update(initial_raw_QRA=r['raw_response'],initial_QRA=initial,initial_request_id=r['request_id'],initial_attempts=attempts)
      rr,aa=bounded(rt,media[v['video_id']],REFINE.replace('[q]',Q).replace('[r]',R).replace('[a]',A),'native_supp_A2_QRA_refinement',p['plan_id']);final=parsejson(rr['raw_response']);fq=raw_member(rr['raw_response'],'Q');fr=raw_member(rr['raw_response'],'R');fa=raw_member(rr['raw_response'],'A');key=norm(fq)
      row.update(question_id='S_'+h([p['plan_id'],final])[:16],question=fq,rationale=fr,answer=fa,refinement_raw_QRA=rr['raw_response'],refinement_request_id=rr['request_id'],refinement_attempts=aa,question_changed=Q!=fq,answer_changed=A!=fa,time_tokens_before=re.findall(r'\d+(?:\.\d+)?',Q),time_tokens_after=re.findall(r'\d+(?:\.\d+)?',fq),status='DUPLICATE_QUESTION' if (v['video_id'],key) in seen else 'FROZEN')
     except Exception as e:row.update(status='GENERATION_FAILED',error=repr(e))
    save(path,row)
   allrows.append(row)
   if row.get('question'):seen.add((v['video_id'],norm(row['question'])))
   if row['status']=='FROZEN':frozen.append(row)
 jl(root/'S_ALL_CANDIDATES.jsonl',allrows);jl(root/'S_FROZEN_QA.jsonl',frozen);return frozen

def p_route(root,graph,ledger,pairs,selected):
 # Reuse native candidate enumeration as a syntax generator only. Override
 # historical uniqueness/content-quality status; actual replay decides execution.
 from step_review.program_adapter import main_candidates,execute
 candidates=[];contexts={};enumeration_errors=[]
 for video in selected:
  vid=video['video_id'];lv=[r for r in ledger if r['scope'].startswith(vid+'/')];pv=[p for p in pairs if p.get('video_id')==vid];contexts[vid]=(lv,pv)
  try:candidates += [q for q in main_candidates(graph,lv,pv,'FOUR-GROUP-GRAPH-v1') if q['video_id']==vid]
  except Exception as e:enumeration_errors.append({'video_id':vid,'error':repr(e)})
 save(root/'P_ENUMERATION_FAILURES.json',enumeration_errors)
 by={(r['scope'],r['fact_id']):r for r in ledger if r['state']=='ACCEPTED'}
 for q in candidates:
  q['historical_adapter_status_diagnostic_only']=q['status'];q['historical_adapter_reason_diagnostic_only']=q['abstention_reason'];q['status']='EXECUTABLE';q['abstention_reason']=None
  p=q['program']
  if p['op']=='motion_before':q.update(status='ABSTAIN',abstention_reason='MOTION_OBJECT_AND_TIME_BINDING_NOT_ESTABLISHED')
  if p['op']=='identity':
   valid=any(r['id']==p['connection_id'] and r['state'] in ['STATIC_MERGED','REFERENCE_CREATED'] for pair in pairs for r in pair.get('results',[]))
   if not valid:q.update(status='ABSTAIN',abstention_reason='NO_NATIVE_IDENTITY_BINDING')
  lv,pv=contexts[q['video_id']];q['execution']=execute(q,lv,pv,graph);q.update(route='P',answer=q['execution'].get('answer'),graph_sha256=filehash(root/'GRAPH_SHARED_FROZEN.json'))
  deps=[d['fact_key'].rsplit('/',1)[0] if 'fact_key' in d else d['connection_key'].rsplit('/',1)[0] if 'connection_key' in d else d.get('motion_key','').rsplit('/',1)[0] for d in q['dependencies'] if d]
  q['fact_ids']=deps;q['program_read_trace']={'value_fact_ids':deps,'video_source_ledger_hash':h(lv),'scope_lookup_rows':[{'fact_id':s+'/'+fid,'class':r['candidate_content']['label']} for (s,fid),r in by.items() if s==p['scope'] and r['fact_type']=='object'],'graph_hash':h(graph),'pairs_hash':h(pv),'operation':p,'truth_interpretation':'program over partial graph, not visual truth','no_extra_global_uniqueness_filter':True}
 chosen=[]
 for v in selected:
  for typ in ['attribute','spatial_relation','cross_frame_identity']:
   eligible=[q for q in candidates if q['video_id']==v['video_id'] and q['question_type']==typ and q['execution']['status']=='ANSWERED'];chosen+=sorted(eligible,key=lambda q:h([2026110201,q['question_id']]))[:2]
 jl(root/'P_ALL_CANDIDATES.jsonl',candidates);jl(root/'P_FROZEN_QA.jsonl',chosen);return chosen
