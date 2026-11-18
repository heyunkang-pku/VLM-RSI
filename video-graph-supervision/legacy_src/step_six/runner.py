"""Fixed-run-contract entry for small three-video, two-route six-group pilot."""
import argparse,copy,json,os,subprocess,sys,time,traceback
from pathlib import Path
from collections import Counter
from .common import *
from .graph_routes import load_source,clip_events,registry,s_route,p_route
from .verification import verify_question

def stage_graph(cfg,root):
 if cfg.get('resume_six_root'):
  from .rationale_recovery import stage_recovery
  return stage_recovery(cfg,root)
 gpu=choose_gpu();rt=make_runtime(cfg,root/'graph_qra_calls','qra',gpu)
 try:
  src,graph,pairs,ledger,tasks=load_source(cfg)
  # The already-frozen common video input manifests, NOT a new decode/sample.
  media={k:absolute_media(v) for k,v in j(cfg['shared_video_inputs']).items()};save(root/'VIDEO_INPUTS_FROZEN.json',media)
  graph=clip_events(rt,root,graph,tasks,media);save(root/'SOURCE_NATIVE_LEDGER.json',ledger);save(root/'SOURCE_TEMPORAL_PAIRS.json',pairs)
  facts=registry(ledger,pairs,graph,tasks);save(root/'FACT_REGISTRY.json',facts)
  p=p_route(root,graph,ledger,pairs);s=s_route(rt,root,graph,facts,media)
  questions=s+p
  jl(root/'SOLVER_QUESTIONS_ONLY.jsonl',[{k:q[k] for k in ['question_id','video_id','question','route']} for q in questions])
  manifest={'graph_sha256':filehash(root/'GRAPH_SHARED_FROZEN.json'),'S_bank_sha256':filehash(root/'S_FROZEN_QA.jsonl'),'P_bank_sha256':filehash(root/'P_FROZEN_QA.jsonl'),'solver_questions_sha256':filehash(root/'SOLVER_QUESTIONS_ONLY.jsonl'),'input_manifest_sha256':filehash(root/'VIDEO_INPUTS_FROZEN.json'),'native_ledger_sha256':filehash(root/'SOURCE_NATIVE_LEDGER.json'),'frozen_after_native_refinement_and_program_execution':True,'frozen_before_solver_and_VQS':True,'human_labels_read':False,'run':os.environ['ORX_RUN_ID'],'source_commit':os.environ['ORX_COMMIT']}
  save(root/'QUESTION_FREEZE_MANIFEST.json',manifest);save(root/'STAGE_GRAPH_STATE.json',{'state':'DONE','S':len(s),'P':len(p)});emit('question_banks_frozen',S=len(s),P=len(p))
 finally:allocation(rt,root/'graph_qra_calls');save(root/'GRAPH_QRA_COST.json',cost(root/'graph_qra_calls'))

def solver_worker(cfg,root,index,count,gpu):
 # Input isolation: this function reads ONLY public questions, input manifests
 # and decoding config. No graph, candidate answer, rationale, or program read.
 done=set(j(root/'REUSED_COMPLETED_QUESTION_IDS.json')) if (root/'REUSED_COMPLETED_QUESTION_IDS.json').exists() else set();qc=[q for q in rows(root/'SOLVER_QUESTIONS_ONLY.jsonl') if q['question_id'] not in done][index::count];media=j(root/'VIDEO_INPUTS_FROZEN.json');sc=dict(cfg,model_path=cfg['solver_model_path'],model_revision=cfg['solver_model_revision']);work=root/'solver'/('shard_'+str(index));rt=make_runtime(sc,work,'solver'+str(index),gpu);rt.mode='video'
 try:
  for q in qc:
   results=[];out=work/'questions'/q['question_id'];out.mkdir(parents=True,exist_ok=True)
   for ix in range(cfg['vote_samples']):
    p=out/(str(ix)+'.json')
    if p.exists():sample=j(p)
    else:
     sample={'question_id':q['question_id'],'sample_index':ix,'seed':cfg['vote_seed']+ix,'status':'FAILED','answer':None}
     try:
      prompt='Answer the question using only the supplied video and question. Return JSON {"answer":"concise answer"}. If the video does not support an unambiguous answer, return {"answer":null}. Do not guess invisible facts.\nQuestion: '+q['question']
      r=ask(rt,media[q['video_id']],prompt,'VideoZero_v4_majority_sample',q['question_id']+':'+str(ix),'video',cfg['vote_max_tokens'],cfg['vote_temperature'],cfg['vote_seed']+ix);parsed=parsejson(r['raw_response']);a=parsed.get('answer');sample.update(status='VALID' if isinstance(a,(str,list)) and bool(norm(a)) and norm(a) not in ['uncertain','unknown','cannot determine','not sure'] else 'ABSTAIN',answer=a,request_id=r['request_id'],raw_response=r['raw_response'])
     except Exception as e:sample['error']=repr(e)
     save(p,sample)
    results.append(sample)
   aggregate={'question_id':q['question_id'],'route':q['route'],'group':q['route']+'0',**vote(results,cfg['vote_samples']),'samples':results};save(out/'VOTE.json',aggregate);emit('majority_vote_complete',question=q['question_id'],status=aggregate['status'],votes=aggregate['top_vote_count'])
 finally:allocation(rt,work);save(work/'COST.json',cost(work))

def vqs_worker(cfg,root,gpu):
 facts=j(root/'FACT_REGISTRY.json');media=j(root/'VIDEO_INPUTS_FROZEN.json');qs=rows(root/'S_FROZEN_QA.jsonl')+rows(root/'P_FROZEN_QA.jsonl');work=root/'vqs';rt=make_runtime(cfg,work,'vqs',gpu);result=rows(work/'RESULTS.jsonl');done={r['question_id'] for r in result};qs=[q for q in qs if q['question_id'] not in done]
 try:
  for q in qs:
   r=verify_question(rt,q,facts,media,work);result.append(r);jl(work/'RESULTS.jsonl',result);emit('VQS_question_complete',question=q['question_id'],status=r['status'])
 finally:allocation(rt,work);save(work/'COST.json',cost(work))

def finalize(root,cfg,failures):
 manifest=j(root/'QUESTION_FREEZE_MANIFEST.json')
 for key,file in [('graph_sha256','GRAPH_SHARED_FROZEN.json'),('S_bank_sha256','S_FROZEN_QA.jsonl'),('P_bank_sha256','P_FROZEN_QA.jsonl'),('solver_questions_sha256','SOLVER_QUESTIONS_ONLY.jsonl'),('input_manifest_sha256','VIDEO_INPUTS_FROZEN.json')]:assert manifest[key]==filehash(root/file),'FROZEN_INPUT_MUTATION:'+file
 qs=rows(root/'S_FROZEN_QA.jsonl')+rows(root/'P_FROZEN_QA.jsonl');vqs={q['question_id']:q for q in rows(root/'vqs/RESULTS.jsonl')};votes={}
 for p in (root/'solver').glob('shard_*/questions/*/VOTE.json'):v=j(p);votes[v['question_id']]=v
 results=[];blind=[]
 for q in qs:
  qid=q['question_id'];route=q['route'];v=votes.get(qid);check=vqs.get(qid)
  results += [{'question_id':qid,'group':route+'0','question':q['question'],'status':v['status'] if v else 'NOT_COMPLETED','answer':v['answer'] if v else None,'vote':v,'human_accuracy':'PENDING'},{'question_id':qid,'group':route+'1','question':q['question'],'status':'FROZEN_ANSWER','answer':q['answer'],'source':'STEP_native_QRA' if route=='S' else 'deterministic_program','human_accuracy':'PENDING'},{'question_id':qid,'group':route+'2','question':q['question'],'status':check['status'] if check else 'NOT_COMPLETED','answer':q['answer'] if check and check['status']=='ACCEPT' else None,'frozen_source_answer':q['answer'],'candidate_answer_modified':False,'verification':check,'human_accuracy':'PENDING'}]
  blind.append({'review_id':'review_'+h([qid,'stage1'])[:12],'video_id':q['video_id'],'question_id':qid,'question':q['question'],'answerability':'PENDING','independent_answer':'','evidence_frame_ids':[],'time_evidence':'','notes':''})
 jl(root/'SIX_GROUP_RESULTS.jsonl',results);jl(root/'BLIND_STAGE1/questions.jsonl',blind)
 # Separate sealed stage2 packet: no group names visible; fixed deterministic shuffle.
 import random
 packets=[]
 for q in qs:
  options=[{'blind_answer_id':h([q['question_id'],r['group']])[:12],'answer':r['answer']} for r in results if r['question_id']==q['question_id']];random.Random(h(q['question_id'])).shuffle(options);packets.append({'question_id':q['question_id'],'anonymous_outputs':options,'correctness':'PENDING','instruction':'Only after independent Stage1 response; labels absent, missing outputs remain null.'})
 jl(root/'BLIND_STAGE2_SEALED/anonymous_answers.jsonl',packets)
 metrics={}
 for g in ['S0','S1','S2','P0','P1','P2']:
  rr=[r for r in results if r['group']==g];metrics[g]={'questions':len(rr),'statuses':dict(Counter(r['status'] for r in rr)),'non_abstained':sum(r['answer'] is not None for r in rr),'accuracy':'PENDING'}
 agreement={}
 for route in ['S','P']:
  subset=[q for q in qs if q['route']==route];both=[q for q in subset if votes.get(q['question_id'],{}).get('status')=='ANSWERED'];agreement[route]={'vote_answered_denominator':len(both),'normalized_exact_matches':sum(norm(votes[q['question_id']]['answer'])==norm(q['answer']) for q in both),'metric':'answer agreement only, NOT accuracy'}
 sc=rows(root/'S_ALL_CANDIDATES.jsonl');pc=rows(root/'P_ALL_CANDIDATES.jsonl');graph=j(root/'GRAPH_SHARED_FROZEN.json');summary={'groups':metrics,'agreement':agreement,'yield':{'videos':3,'frozen_keyframes':40,'S_plans':len(sc),'S_generation_statuses':dict(Counter(x['status'] for x in sc)),'S_frozen':sum(q['route']=='S' for q in qs),'P_candidates':len(pc),'P_execution_statuses':dict(Counter(x['execution']['status'] for x in pc)),'P_frozen':sum(q['route']=='P' for q in qs),'event_edges':len(graph['event_edges']),'motion_edges':len(graph['motion_edges']),'reference_edges':len(graph['reference_edges']),'static_identity_groups':len(graph['static_identity_groups'])},'worker_failures':failures,'total_new_cost':cost(root),'graph_status':'PARTIAL','human_metrics':'PENDING','training':False,'new_reward':False,'weights_updated':False}
 save(root/'YIELD_COST_SUMMARY.json',summary);save(root/'STATE.json',{'state':'COMPLETED_WITH_PARTIALS' if failures else 'COMPLETED','run':os.environ['ORX_RUN_ID'],'summary':summary});emit('six_group_summary',**summary)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',default='config/step_six.json');ap.add_argument('--stage',choices=['graph','solver','vqs']);ap.add_argument('--index',type=int,default=0);ap.add_argument('--count',type=int,default=1);ap.add_argument('--gpu');a=ap.parse_args();cfg=j(a.config)
 if a.stage:
  root=Path(cfg['work_root'])
  if a.stage=='graph':stage_graph(cfg,root)
  elif a.stage=='solver':solver_worker(cfg,root,a.index,a.count,a.gpu)
  else:vqs_worker(cfg,root,a.gpu)
  return
 root=Path('/scratch/haozhe/.cache/vlm-rsi/step-six')/os.environ['ORX_EXPERIMENT']/os.environ['ORX_RUN_ID'];root.mkdir(parents=True);cfg.update(work_root=str(root),source_commit=os.environ['ORX_COMMIT']);cp=root/'effective_config.json';save(cp,cfg);print(json.dumps({'effective_config':cfg}),flush=True)
 # Automatic dependency barrier: CPU-only, no human-label wait. Only start
 # after native verification AND temporal merging have committed the V2 state.
 while True:
  sp=Path(cfg['graph_source'])/'STATE.json'
  if sp.exists():
   st=j(sp)
   if st.get('state')=='COMPLETED_V1' and st.get('version')=='V2':break
  emit('waiting_for_V2_graph_completion',source=cfg['graph_source']);time.sleep(30)
 if cfg.get('resume_six_root'):
  while not (Path(cfg['resume_six_root'])/'STATE.json').exists():
   emit('waiting_for_original_P_results',source=cfg['resume_six_root']);time.sleep(30)
 # Graph extraction runs as a separate process, so CUDA/model state is released
 # before v4 Solver and original 4B checker are placed on independent cards.
 subprocess.run([sys.executable,'-m','step_six.runner','--config',str(cp),'--stage','graph'],check=True)
 gpus=[]
 for line in subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines():
  i,m,u=line.split(',')
  if float(m)>40000 and float(u)<5:gpus.append(i.strip())
 assert gpus,'NO_IDLE_A40';failures=[];processes=[]
 if len(gpus)==1:
  for stage in ['vqs','solver']:
   p=subprocess.run([sys.executable,'-m','step_six.runner','--config',str(cp),'--stage',stage,'--gpu',gpus[0]])
   if p.returncode:failures.append({'stage':stage,'returncode':p.returncode})
 else:
  jobs=[('vqs',0,1,gpus[0])]+[('solver',i,len(gpus)-1,g) for i,g in enumerate(gpus[1:])]
  for stage,ix,n,gpu in jobs:
   cmd=[sys.executable,'-m','step_six.runner','--config',str(cp),'--stage',stage,'--gpu',gpu,'--index',str(ix),'--count',str(n)];p=subprocess.Popen(cmd);processes.append((p,stage,ix))
  for p,stage,ix in processes:
   rc=p.wait()
   if rc:failures.append({'stage':stage,'index':ix,'returncode':rc})
 finalize(root,cfg,failures)
if __name__=='__main__':main()
