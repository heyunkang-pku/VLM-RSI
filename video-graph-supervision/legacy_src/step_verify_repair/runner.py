"""Only verification changes; graph,33QA, answers, votes and baseline immutable."""
import argparse,copy,json,os,shutil,subprocess,sys,time
from pathlib import Path
from collections import Counter
from step_six.common import *
from step_native.native_verification import verdict
from .dependencies import p_dependencies
from .semantic import bounded_call
from .semantic_v2 import s_dependencies
from .gates_v2 import p_annotations,evidence_preflight,decide_status
from .facets_v3 import p_main,s_main
from .runtime import RepairRuntime,atom_media

FILES=['GRAPH_SHARED_FROZEN.json','FACT_REGISTRY.json','SOURCE_NATIVE_LEDGER.json','SOURCE_TEMPORAL_PAIRS.json','VIDEO_INPUTS_FROZEN.json','S_FROZEN_QA.jsonl','P_FROZEN_QA.jsonl','SIX_GROUP_RESULTS.jsonl','YIELD_COST_SUMMARY.json','QUESTION_FREEZE_MANIFEST.json']
def freeze(cfg,root):
 src=Path(cfg['baseline_root']);dest=root/'frozen';dest.mkdir(parents=True,exist_ok=True);manifest=[]
 for name in FILES:
  target=dest/name
  if not target.exists():shutil.copy2(src/name,target)
  assert filehash(src/name)==filehash(target);manifest.append({'file':str(target.relative_to(root)),'sha256':filehash(target),'source':str(src/name)})
 for p in (src/'solver').glob('shard_*/questions/*/VOTE.json'):
  destp=dest/p.relative_to(src);destp.parent.mkdir(parents=True,exist_ok=True)
  if not destp.exists():shutil.copy2(p,destp)
  manifest.append({'file':str(destp.relative_to(root)),'sha256':filehash(destp),'source':str(p)})
 for name in ['RESULTS.jsonl','CHECKER_LEDGER.jsonl']:
  destp=dest/'baseline_vqs'/name;destp.parent.mkdir(parents=True,exist_ok=True)
  if not destp.exists():shutil.copy2(src/'vqs'/name,destp)
  manifest.append({'file':str(destp.relative_to(root)),'sha256':filehash(destp),'source':str(src/'vqs'/name)})
 prev=Path(cfg['previous_repair_root'])
 for name in ['REPAIRED_CHECK_RESULTS.jsonl','DERIVATIVE_SIX_GROUP_RESULTS.jsonl','SUMMARY.json']:
  destp=dest/'previous_repair'/name;destp.parent.mkdir(parents=True,exist_ok=True)
  if not destp.exists():shutil.copy2(prev/name,destp)
  assert filehash(destp)==cfg['expected_previous_sha256'][name]
  manifest.append({'file':str(destp.relative_to(root)),'sha256':filehash(destp),'source':str(prev/name)})
 # Ensure actual immutable files match the reviewed artifact, not merely a new
 # hash computed after unobserved mutation on the server.
 for name,expected in cfg['expected_baseline_sha256'].items():assert filehash(dest/name)==expected,'BASELINE_CHANGED:'+name
 qs=rows(dest/'S_FROZEN_QA.jsonl')+rows(dest/'P_FROZEN_QA.jsonl');assert len(qs)==33
 save(root/'FROZEN_BASELINE_MANIFEST.json',manifest);return qs

def pair_contexts(cfg):
 out={}
 for p in Path(cfg['temporal_root']).glob('pair_inputs/*.json'):
  m=j(p); # pair ID is encoded in the filename and in corresponding ledger
  out[p.stem]=m
 return out

def worker(cfg,index,gpu):
 root=Path(cfg['work_root']);work=root/'workers'/('shard_'+str(index));work.mkdir(parents=True,exist_ok=True);os.environ['CUDA_VISIBLE_DEVICES']=gpu;os.environ['SMOKE_DEADLINE']='inf'
 c=dict(cfg,work_root=str(work),output_root=str(work),protocol_version=cfg['protocol_version']+':checker',request_namespace='repair'+str(index)+'_');rt=RepairRuntime(c,work/'runtime');frozen=root/'frozen';facts=j(frozen/'FACT_REGISTRY.json');media=j(frozen/'VIDEO_INPUTS_FROZEN.json');graph=j(frozen/'GRAPH_SHARED_FROZEN.json');ledger=j(frozen/'SOURCE_NATIVE_LEDGER.json');pairs=j(frozen/'SOURCE_TEMPORAL_PAIRS.json');allpairs=pair_contexts(cfg);pairmap={f['pair_id']:allpairs[f['pair_id'].replace('/','_')] for f in facts.values() if f.get('pair_id') and f['pair_id'].replace('/','_') in allpairs};old={x['question_id']:x for x in rows(frozen/'previous_repair/REPAIRED_CHECK_RESULTS.jsonl')}
 try:
  for q in j(root/f'shard_{index}.json'):
   out=root/'questions'/(q['question_id']+'.json')
   if out.exists():continue
   before=h(q);result={'question_id':q['question_id'],'route':q['route'],'frozen_answer':q['answer'],'accepted_answer':None,'baseline_status':old[q['question_id']]['status'],'checks':[],'status':'UNRESOLVED','human_truth':'PENDING','NO_is_independent_truth':False}
   try:
    dep=p_main(q,facts,ledger,pairs,graph) if q['route']=='P' else s_main(rt,q,facts,media);result['dependencies']=dep;save(root/'dependencies'/(q['question_id']+'.json'),dep)
    prepared=[];preflights=[]
    for atom in dep['atoms']:
     try:
      m,mode=atom_media(atom,facts,media,pairmap);pre=evidence_preflight(atom,q,facts,m,mode);prepared.append((m,mode))
     except Exception as e:pre={'sufficient':False,'issues':['INPUT_GROUNDING_ERROR'],'error':repr(e)};prepared.append((None,None))
     preflights.append(pre)
    result['evidence_preflights']=preflights
    result['previous_checks_diagnostic_only']=old[q['question_id']].get('checks',[])
    gate=decide_status(dep,preflights,[])
    for atom_index,a in enumerate(dep['atoms']):
     rec={**a,'verdict':'UNRESOLVED','evidence_preflight':preflights[atom_index]}
     if gate in ['UNRESOLVED_DEPENDENCY_BEFORE_VISUAL','UNRESOLVED_EVIDENCE_BEFORE_VISUAL']:
      rec.update(verdict='NOT_RUN_PRECHECK',skip_reason=gate);result['checks'].append(rec);append(work/'CHECKER_LEDGER.jsonl',{'question_id':q['question_id'],**rec});continue
     try:
      m,mode=prepared[atom_index]
      prompt=a['claim']+'\nLooking only at the '+('image' if mode=='image' else 'supplied video frames and their authoritative times')+', is that statement true? Answer with one word, YES or NO.'
      r,attempts=bounded_call(rt,m,prompt,'question_conditioned_required_fact',q['question_id']+':'+a['requirement_id'],mode,(32,64));v=verdict(r['raw_response']);rec.update(verdict=v,raw_response=r['raw_response'],request_id=r['request_id'],attempts=attempts,actual_input={'mode':mode,'visual_root':r['visual_root'],'files':r.get('actual_visual_files'),'frame_ids':r.get('shown_frame_ids'),'times_sec':r.get('actual_source_times_sec'),'frame_content_hashes':r['frame_content_hashes'],'tensor_hashes':r['input_hashes'],'tensor_shapes':r['input_shapes'],'prompt':r['prompt'],'model_revision':r['model_revision']},fact_ERROR_attribution='MODEL_NO_PENDING_VISUAL_REVIEW' if v=='NO' else 'NOT_INDEPENDENTLY_EVALUATED')
      if a['kind'] in ['identity','motion','time'] and mode=='image':rec.update(verdict='UNRESOLVED',grounding_error='TEMPORAL_FACT_WITH_SINGLE_IMAGE')
     except Exception as e:rec['error']=repr(e)
     result['checks'].append(rec);append(work/'CHECKER_LEDGER.jsonl',{'question_id':q['question_id'],**rec})
    result['status']=decide_status(dep,preflights,result['checks'])
    result['main_verification_scope']=dep.get('main_acceptance_scope','positive fact verification')
    result['reasoning_review']=dep.get('reasoning_review')
    result['question_ambiguity']=dep.get('question_ambiguity')
    result['answer_completeness']=dep.get('answer_completeness')
    if result['status']=='ACCEPT':result['accepted_answer']=q['answer']
    result['positive_claims_verification']={'all_necessary_positive_claims_YES':bool(result['checks']) and all(x['verdict']=='YES' for x in result['checks']),'prior_positive_results_diagnostic_only':True,'answer_exhaustiveness':dep.get('relation_completeness',{})}
   except Exception as e:result.update(status='UNRESOLVED_IMPLEMENTATION_OR_OUTPUT',error=repr(e))
   assert h(q)==before;save(out,result);emit('verification_repair_question_complete',question=q['question_id'],before=result['baseline_status'],after=result['status'])
 finally:allocation(rt,work);save(work/'COST.json',cost(work))

def finalize(cfg,root,failures):
 qs=rows(root/'frozen/S_FROZEN_QA.jsonl')+rows(root/'frozen/P_FROZEN_QA.jsonl');old={x['question_id']:x for x in rows(root/'frozen/previous_repair/REPAIRED_CHECK_RESULTS.jsonl')};new=[j(root/'questions'/(q['question_id']+'.json')) for q in qs if (root/'questions'/(q['question_id']+'.json')).exists()];jl(root/'REPAIRED_CHECK_RESULTS.jsonl',new);changes=[]
 for n in new:
  o=old[n['question_id']];changes.append({'question_id':n['question_id'],'route':n['route'],'before':o['status'],'after':n['status'],'before_unresolved':o.get('dependencies',{}).get('unresolved',[]),'after_unresolved':n.get('dependencies',{}).get('unresolved',[]),'before_error':o.get('error'),'after_error':n.get('error'),'before_NO_claims':[c['claim'] for c in o.get('checks',[]) if c['verdict']=='NO'],'evidence_preflights':n.get('evidence_preflights',[]),'referring_bindings':n.get('dependencies',{}).get('referring_bindings',[]),'relation_completeness':n.get('dependencies',{}).get('relation_completeness',{}),'after_necessary_NO_claims':[{'claim':c['claim'],'reason':c['reason'],'requirement_id':c['requirement_id']} for c in n['checks'] if c['verdict']=='NO'],'background_assumptions':n.get('dependencies',{}).get('background_assumptions',[]),'NO_truth_status':'PENDING_VISUAL_REVIEW_NOT_CONFIRMED_ERROR'})
 jl(root/'BEFORE_AFTER_REASONS.jsonl',changes)
 for rec in j(root/'FROZEN_BASELINE_MANIFEST.json'):assert filehash(root/rec['file'])==rec['sha256'];assert filehash(Path(rec['source']))==rec['sha256']
 # Original six-group scores are not overwritten. The derivative view modifies
 # only S2/P2 acceptance fields, retaining exact question/source answer bytes.
 m={x['question_id']:x for x in new};out=[]
 for row in rows(root/'frozen/previous_repair/DERIVATIVE_SIX_GROUP_RESULTS.jsonl'):
  row=copy.deepcopy(row)
  if row['group'] in ['S2','P2'] and row['question_id'] in m:
   rr=m[row['question_id']];row.update(status=rr['status'],answer=rr['accepted_answer'],verification=rr,verification_version=cfg['protocol_version'])
  out.append(row)
 jl(root/'DERIVATIVE_SIX_GROUP_RESULTS.jsonl',out)
 summary={'frozen_questions':len(qs),'completed_verifications':len(new),'groups':{route:{'before':dict(Counter(x['status'] for x in old.values() if x['route']==route)),'after':dict(Counter(x['status'] for x in new if x['route']==route))} for route in ['S','P']},'votes_reused':330,'new_solver_calls':0,'new_graph_calls':0,'baseline_files_and_answers_unchanged':True,'cost':cost(root),'worker_failures':failures,'human_accuracy':'PENDING','fact_error_truth':'NO requires independent visual review, not established by checker verdict'}
 save(root/'SUMMARY.json',summary);save(root/'STATE.json',{'state':'DONE_WITH_PARTIALS' if failures or len(new)!=33 else 'DONE','run':os.environ['ORX_RUN_ID']});emit('verification_repair_summary',**summary)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',default='config/step_verify_repair.json');ap.add_argument('--worker',type=int);ap.add_argument('--gpu');a=ap.parse_args();cfg=j(a.config)
 if a.worker is not None:worker(cfg,a.worker,a.gpu);return
 root=Path('/scratch/haozhe/.cache/vlm-rsi/verification-repair')/os.environ['ORX_EXPERIMENT']/os.environ['ORX_RUN_ID'];root.mkdir(parents=True);cfg.update(work_root=str(root),source_commit=os.environ['ORX_COMMIT']);save(root/'effective_config.json',cfg);qs=freeze(cfg,root);print(json.dumps({'effective_config':cfg,'frozen_questions':len(qs)}),flush=True);gpus=[]
 for line in subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines():
  i,m,u=line.split(',')
  if float(m)>40000 and float(u)<5:gpus.append(i.strip())
 assert gpus,'NO_IDLE_A40';pp=[];failures=[]
 for index,gpu in enumerate(gpus[:5]):
  save(root/f'shard_{index}.json',qs[index::len(gpus[:5])]);cmd=[sys.executable,'-m','step_verify_repair.runner','--config',str(root/'effective_config.json'),'--worker',str(index),'--gpu',gpu];pp.append((subprocess.Popen(cmd),index))
 for p,index in pp:
  code=p.wait()
  if code:failures.append({'shard':index,'exit_code':code})
 finalize(cfg,root,failures)
if __name__=='__main__':main()
