"""Tracked follow-up; never rebuilds graph or mutates old QA/votes."""
from pathlib import Path
import os,copy,subprocess,sys,csv,html,shutil,collections,json,re
from step_six.common import *
from four_group.followup import offline,relation
from four_group.routes import bounded
from step_six.graph_routes import REFINE
from step_six.rationale_recovery import raw_member
from four_group.results import export_comparison
BASE=Path('/scratch/haozhe/.cache/vlm-rsi/public32/2e2321e3-316b-447d-ad3f-57b47dfdaf22')
def generate(cfg,root,new,media):
 rt=make_runtime(cfg,root/'S_calls','new_temporal_S',choose_gpu());out=[];attempts=[]
 try:
  # Fixed two attempts/video, half positive/negative, independent of outputs.
  seeds=[]
  for vid in sorted({q['video_id'] for q in new}):
   for typ in ['identity_positive','identity_negative']:
    qq=sorted([q for q in new if q['video_id']==vid and q['question_type']==typ],key=lambda q:h(q['question_id']))
    if qq:seeds.append(qq[0])
  save(root/'S_PLANS_FROZEN.json',seeds)
  for q in seeds:
   row={'plan_id':q['question_id'],'video_id':q['video_id'],'question_type':q['question_type'],'dependencies':q['dependencies'],'status':'FAILED'}
   try:
    prompt='Generate a graph-guided QRA testing the physical identity of the two observed endpoints. Use the exact endpoints/times and explicit graph evidence given. Do not invent identity from class names or missing edges. No internal IDs in public question, no answer hint, no hidden facts. Return JSON {"Q":"public question","R":"evidence-grounded reasoning","A":"Yes or No"}.\n'+json.dumps(q,ensure_ascii=False)
    r,a=bounded(rt,media[q['video_id']],prompt,'graph_QRA',q['question_id']);iq=raw_member(r['raw_response'],'Q');ir=raw_member(r['raw_response'],'R');ia=raw_member(r['raw_response'],'A');rr,aa=bounded(rt,media[q['video_id']],REFINE.replace('[q]',iq).replace('[r]',ir).replace('[a]',ia),'supp_A2_refine',q['question_id']);fq=raw_member(rr['raw_response'],'Q');fa=raw_member(rr['raw_response'],'A');fr=raw_member(rr['raw_response'],'R')
    assert norm(fa) in ['yes','no'];import re
    original_times=[float(t) for t in re.findall(r'(\d+\.\d+) seconds',q['question'])];public_times=[float(t) for t in re.findall(r'\d+\.\d+',fq)];assert all(any(abs(t-x)<0.000002 for x in public_times) for t in original_times),'PUBLIC_TIME_SCOPE_CHANGED'
    assert not re.search(r'\b(?:o\d+|src_\d+|person\d+|table\d+)\b',fq)
    row.update(status='FROZEN',question_id='newS_'+h([q['question_id'],fq,fa])[:16],route='S',question=fq,answer=fa,rationale=fr,initial_raw=r['raw_response'],refined_raw=rr['raw_response'],initial_request=r['request_id'],refinement_request=rr['request_id'],source_program=q['program'],answer_changed=norm(ia)!=norm(fa));out.append(row.copy())
   except Exception as e:row['error']=repr(e)
   attempts.append(row);jl(root/'S_ALL_ATTEMPTS.jsonl',attempts)
  jl(root/'NEW_S_FROZEN.jsonl',out)
 finally:allocation(rt,root/'S_calls')
 return out

def vote_worker(cfg,root,index,count,gpu):
 from four_group.results import aggregate
 rt=make_runtime(dict(cfg,model_path=cfg['solver_model_path'],model_revision=cfg['solver_model_revision']),root/'votes'/str(index),'followup_votes'+str(index),gpu);rt.mode='video';media=j(root/'MEDIA.json')
 try:
  for q in rows(root/'PUBLIC_QUESTIONS_ONLY.jsonl')[index::count]:
   samples=[]
   for ix in range(10):
    s={'sample_index':ix,'seed':cfg['vote_seed']+ix,'status':'FAILED','answer':None}
    try:
     example='{"subject":"table","relation":"supports","object":"cup","answer":"The table supports the cup."}' if q['cohort']=='relation_rerun' else '{"answer":"Yes"}'
     prompt='Answer only using the supplied public32 video and question. Return JSON. Example syntax only (do not copy the example answer): '+example+'. For relation questions subject/object must follow the question direction, never return a bare preposition. If ambiguous use {"answer":null}.\nQuestion: '+q['question']
     r=rt.ask(media[q['video_id']],[],prompt,role='v4_followup_sample',owner=q['question_id']+':'+str(ix),max_tokens=2048,temperature=.7,seed=s['seed']);s.update(raw_response=r['raw_response'],request_id=r['request_id'],input_hashes=r['input_hashes'],frame_hashes=r['frame_content_hashes']);assert not r['output_hit_cap'],'TRUNCATED';a=parsejson(r['raw_response']).get('answer');s.update(answer=a,status='VALID' if isinstance(a,str) and norm(a) not in ['', 'unknown','uncertain','cannot determine','not sure'] else 'ABSTAIN')
     if q['cohort']=='relation_rerun' and a is not None:
      m=re.search(r'does the (.*?) have with the (.*?)\?',q['question']);triple,rule=relation(a,m[1],m[2]);s.update(triple=triple,parse_rule=rule)
      if not triple:s.update(status='UNRESOLVED',answer=None)
      else:s['answer']=triple[1]
    except Exception as e:s['error']=repr(e)
    samples.append(s)
   save(root/'votes'/str(index)/(q['question_id']+'.json'),{'question_id':q['question_id'],'samples':samples,'aggregate':aggregate(samples)})
 finally:allocation(rt,root/'votes'/str(index))

def main():
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--root');ap.add_argument('--worker',type=int);ap.add_argument('--count',type=int);ap.add_argument('--gpu');a=ap.parse_args();cfg=j('config/four_group.json');cfg['protocol_version']='PUBLIC32-FOLLOWUP-v1'
 if cfg.get('followup_finalize_root') and a.worker is None:return finish(Path(cfg['followup_finalize_root']))
 if a.worker is not None:return vote_worker(cfg,Path(a.root),a.worker,a.count,a.gpu)
 root=Path('/scratch/haozhe/.cache/vlm-rsi/public32-followup')/os.environ['ORX_RUN_ID'];root.mkdir(parents=True);save(root/'effective_config.json',cfg);old,new=offline(BASE,root/'offline');media=j(BASE/'PUBLIC32_FROZEN.json');save(root/'MEDIA.json',media);ss=generate(cfg,root,new,media);jl(root/'NEW_P_FROZEN.jsonl',new)
 scores=j(root/'offline/RELATION_COMPATIBLE_SCORES.json');ids={x['question_id'] for x in scores if not x['strict_majority']};rerun=[dict(q,cohort='relation_rerun') for q in old if q['question_id'] in ids];newall=[dict(q,cohort='new_temporal') for q in new+ss];questions=newall+rerun;jl(root/'FROZEN_ALL_QA.jsonl',questions);jl(root/'PUBLIC_QUESTIONS_ONLY.jsonl',[{k:q[k] for k in ['question_id','video_id','question','route','cohort']} for q in questions]);save(root/'FREEZE.json',{'hash':filehash(root/'FROZEN_ALL_QA.jsonl')})
 lines=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines();gpus=[l.split(',')[0].strip() for l in lines if float(l.split(',')[1])>40000 and float(l.split(',')[2])<5];assert gpus
 pp=[subprocess.Popen([sys.executable,'-m','four_group.followup_run','--root',str(root),'--worker',str(i),'--count',str(len(gpus)),'--gpu',g]) for i,g in enumerate(gpus)];assert all(p.wait()==0 for p in pp)
 finish(root)

def export_adapter(q):
 q=copy.deepcopy(q)
 if 'answer' not in q:q['answer']=q['candidate_answer']
 if q.get('dependencies') is not None:q['program_read_trace']=q['dependencies']
 return q

def finish(root):
 questions=rows(root/'FROZEN_ALL_QA.jsonl');assert filehash(root/'FROZEN_ALL_QA.jsonl')==j(root/'FREEZE.json')['hash']
 old=[]
 for batch in ['first2','remaining8']:old+=rows(BASE/batch/'four_groups/PER_QUESTION.jsonl')
 newall=[q for q in questions if q['cohort']=='new_temporal'];media=j(root/'MEDIA.json')
 vv={}
 for p in root.glob('votes/*/*.json'):
  v=j(p)
  if 'question_id' in v:vv[v['question_id']]=v
 for co in ['new_temporal','relation_rerun']:export_comparison([export_adapter(q) for q in questions if q['cohort']==co],vv,root/co,co)
 from four_group.independent_eval import export
 export(BASE,root,old,newall,media);assert filehash(root/'FROZEN_ALL_QA.jsonl')==j(root/'FREEZE.json')['hash'];save(root/'SUMMARY.json',{'offline':j(root/'offline/OFFLINE_SUMMARY.json'),'new_temporal':j(root/'new_temporal/SUMMARY.json'),'relation_rerun':j(root/'relation_rerun/SUMMARY.json'),'cost':cost(root),'correctness':'PENDING_INDEPENDENT_LABELS','VQS':False,'training':False});emit('followup_complete',root=str(root))
if __name__=='__main__':main()
