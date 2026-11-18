"""Lossless structured-R adapter. No new initial QRA draws or graph changes."""
import copy,json,re,shutil
from pathlib import Path
from .common import *
from .graph_routes import REFINE

def raw_member(text,key):
 """Extract the exact JSON value span, retaining duplicate nested member text."""
 text=text.strip()
 if text.startswith('```'):text=re.sub(r'^```(?:json)?\s*|\s*```$','',text)
 decoder=json.JSONDecoder();i=0
 while i<len(text) and text[i].isspace():i+=1
 if text[i]!='{':raise ValueError('TOP_LEVEL_QRA_NOT_OBJECT')
 i+=1;found=[]
 while True:
  while i<len(text) and text[i].isspace():i+=1
  if text[i]=='}':break
  name,end=decoder.raw_decode(text,i);i=end
  while text[i].isspace():i+=1
  if text[i]!=':':raise ValueError('JSON_MEMBER_COLON')
  i+=1
  while text[i].isspace():i+=1
  start=i;value,end=decoder.raw_decode(text,i)
  if name==key:found.append((value,text[start:end]))
  i=end
  while i<len(text) and text[i].isspace():i+=1
  if text[i]=='}':break
  if text[i]!=',':raise ValueError('JSON_MEMBER_COMMA')
  i+=1
 if len(found)!=1:raise ValueError('MISSING_OR_DUPLICATE_TOP_LEVEL_'+key)
 value,span=found[0]
 if isinstance(value,str):
  if not value.strip():raise ValueError('EMPTY_'+key)
  return value
 if key=='R' and isinstance(value,(dict,list)) and value:return span
 raise ValueError('UNSUPPORTED_'+key+'_TYPE')

def stage_recovery(cfg,root):
 parent=Path(cfg['resume_six_root']);root.mkdir(parents=True,exist_ok=True)
 names=['GRAPH_SHARED_FROZEN.json','FACT_REGISTRY.json','SOURCE_NATIVE_LEDGER.json','SOURCE_TEMPORAL_PAIRS.json','VIDEO_INPUTS_FROZEN.json','P_ALL_CANDIDATES.jsonl','P_FROZEN_QA.jsonl','S_PATH_PLANS_FROZEN.json']
 for name in names:shutil.copy2(parent/name,root/name)
 # Preserve all original outputs in their own immutable parent directory. Copy
 # vote receipts only, not historical GPU allocation/raw-call logs as new cost.
 for p in (parent/'solver').glob('shard_*/questions/*'):
  target=root/'solver'/p.relative_to(parent/'solver');target.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(p,target)
 old_s=rows(parent/'S_FROZEN_QA.jsonl');oldmap={q['plan_id']:q for q in old_s};reuse_ids={q['question_id'] for q in old_s+rows(parent/'P_FROZEN_QA.jsonl')}
 vr=[r for r in rows(parent/'vqs/RESULTS.jsonl') if r['question_id'] in reuse_ids];jl(root/'vqs/RESULTS.jsonl',vr)
 for q in vr:
  src=parent/'vqs/per_question'/(q['question_id']+'.json')
  if src.exists():dest=root/'vqs/per_question'/src.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
 jl(root/'vqs/CHECKER_LEDGER.jsonl',[r for r in rows(parent/'vqs/CHECKER_LEDGER.jsonl') if r['question_id'] in reuse_ids])
 solver_completed={j(p)['question_id'] for p in (parent/'solver').glob('shard_*/questions/*/VOTE.json')};save(root/'REUSED_COMPLETED_QUESTION_IDS.json',sorted(solver_completed));save(root/'REUSE_PROVENANCE.json',{'parent_root':str(parent),'graph_sha256':filehash(root/'GRAPH_SHARED_FROZEN.json'),'P_bank_sha256':filehash(root/'P_FROZEN_QA.jsonl'),'parent_summary':j(parent/'YIELD_COST_SUMMARY.json'),'all_initial_S_draws_reused':True,'no_new_initial_sampling_or_graph_calls':True,'historical_raw_calls_remain_parent_stage':True,'original_failed_candidate_records':str(parent/'S_ALL_CANDIDATES.jsonl')})
 media=j(root/'VIDEO_INPUTS_FROZEN.json');plans=j(root/'S_PATH_PLANS_FROZEN.json');initial={r['owner']:r for r in rows(parent/'graph_qra_calls/runtime/requests.jsonl') if r['role']=='native_graph_path_initial_QRA'};rt=make_runtime(cfg,root/'graph_qra_calls','qra_recovery',choose_gpu());allrows=[];bank=[]
 try:
  for p in plans:
   if p['plan_id'] in oldmap:row=copy.deepcopy(oldmap[p['plan_id']]);row['reused_frozen_from_parent']=True
   else:
    row={**p,'route':'S','graph_sha256':filehash(root/'GRAPH_SHARED_FROZEN.json'),'parent_initial_generation_reused':True}
    if p['status']=='PLANNED':
     try:
      r=initial[p['plan_id']];assert not r['output_hit_cap'];raw=parsejson(r['raw_response']);Q=raw_member(r['raw_response'],'Q');R=raw_member(r['raw_response'],'R');A=raw_member(r['raw_response'],'A');assert set(raw.get('used_fact_ids',[]))<=set(p['fact_ids'])
      prompt=REFINE.replace('[q]',Q).replace('[r]',R).replace('[a]',A)
      refined=ask(rt,media[p['video_id']],prompt,'native_supp_A2_QRA_refinement',p['plan_id']);final=parsejson(refined['raw_response']);fq=raw_member(refined['raw_response'],'Q');fr=raw_member(refined['raw_response'],'R');fa=raw_member(refined['raw_response'],'A')
      row.update(status='FROZEN',question_id='S_'+h([p['plan_id'],final])[:16],question=fq,rationale=fr,answer=fa,initial_QRA=raw,initial_raw_QRA=r['raw_response'],initial_rationale_lossless_text=R,initial_request_id=r['request_id'],refinement_request_id=refined['request_id'],refinement_raw_QRA=refined['raw_response'],answer_changed_during_native_refinement=A!=fa,dependencies_status='AWAITING_POST_FREEZE_VQS_EXTRACTION',time_range_sec=p['event_context']['observation_interval_sec'] if p['event_context'] else None)
     except Exception as e:row.update(status='GENERATION_FAILED',error=repr(e))
   save(root/'S_candidates'/(p['plan_id']+'.json'),row);allrows.append(row)
   if row['status']=='FROZEN':bank.append(row)
  jl(root/'S_ALL_CANDIDATES.jsonl',allrows);jl(root/'S_FROZEN_QA.jsonl',bank)
  qs=bank+rows(root/'P_FROZEN_QA.jsonl');jl(root/'SOLVER_QUESTIONS_ONLY.jsonl',[{k:q[k] for k in ['question_id','video_id','question','route']} for q in qs])
  manifest={k:filehash(root/f) for k,f in [('graph_sha256','GRAPH_SHARED_FROZEN.json'),('S_bank_sha256','S_FROZEN_QA.jsonl'),('P_bank_sha256','P_FROZEN_QA.jsonl'),('solver_questions_sha256','SOLVER_QUESTIONS_ONLY.jsonl'),('input_manifest_sha256','VIDEO_INPUTS_FROZEN.json'),('native_ledger_sha256','SOURCE_NATIVE_LEDGER.json')]};manifest.update(frozen_after_native_refinement_and_program_execution=True,frozen_before_solver_and_VQS=True,parent_root=str(parent),human_labels_read=False,run=os.environ['ORX_RUN_ID'],source_commit=os.environ['ORX_COMMIT']);save(root/'QUESTION_FREEZE_MANIFEST.json',manifest);emit('question_banks_frozen',S=len(bank),P=len(qs)-len(bank),graph_reused=True)
 finally:allocation(rt,root/'graph_qra_calls');save(root/'GRAPH_QRA_COST.json',cost(root/'graph_qra_calls'))
