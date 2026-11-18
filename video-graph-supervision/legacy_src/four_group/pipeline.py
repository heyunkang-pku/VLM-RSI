"""Single tracked entry: old33 -> provenance freeze -> native batch -> 4groups.
No additional VQS verifier, main/aux necessity or uniqueness audit is imported.
"""
import argparse,copy,json,os,subprocess,sys,time,shutil
from pathlib import Path
from step_six.common import *
from stsg_pilot.runtime import save,emit
from .results import old33,export_comparison
from .history import audit
from . import native_batch
from .routes import s_route,p_route

def shared_media(cfg,root,selection):
 # Same preprocessing for S/P. No graph/answer enters this input builder.
 from PIL import Image
 from transformers.models.qwen2_vl.image_processing_qwen2_vl import smart_resize
 native=root/'native';result={}
 for v in selection:
  vid=v['video_id'];mfile=native/'videos'/vid/'S1/manifest.json'
  if not mfile.exists():continue
  s1=j(mfile);folder=mfile.parent.parent;clock=j(folder/'S1/frame_clock.json');n=min(32,len(clock));ids=sorted({round(i*(len(clock)-1)/max(1,n-1)) for i in range(n)});pool={f['source_index']:f for f in s1['frames']};needed=set(ids)-pool.keys()
  if needed:
   import av
   with av.open(v['path']) as c:
    for i,f in enumerate(c.decode(video=0)):
     if i not in needed:continue
     p=folder/'S1/source_frames'/f'src_{i:06d}.png';p.parent.mkdir(exist_ok=True);f.to_image().convert('RGB').save(p);pool[i]={**clock[i],'frame_id':f'src_{i:06d}','file':str(p),'sha256':filehash(p)}
  fs=[]
  for i in ids:
   f=pool[i];source=Path(f['file']) if Path(f['file']).is_absolute() else folder/f['file'];assert filehash(source)==f['sha256'];target=root/'inputs'/vid/(f['frame_id']+'.png');target.parent.mkdir(parents=True,exist_ok=True)
   with Image.open(source) as im:
    hh,ww=smart_resize(im.height,im.width,factor=32,min_pixels=4096,max_pixels=50176);im.convert('RGB').resize((ww,hh),Image.Resampling.BICUBIC).save(target)
   fs.append({**f,'file':str(target),'sha256':filehash(target),'parent_pixel_sha256':f['sha256']})
  result[vid]={'video':{'video_id':vid,'source_video_id':'PerceptionTest:'+vid,'avg_fps':s1['video']['avg_fps']},'calibration_view':fs[0],'class_video_views':fs,'source_frames_decoded':s1['source_frames_decoded'],'clip_intervals':[[0,s1['video']['duration_sec']]],'_root':str(root),'rule':'32 deterministic chronological source-frame ranks across whole frozen selected video; shared S/P; no answer/graph inputs'}
 save(root/'VIDEO_INPUTS_FROZEN.json',result);return result

def graph_questions(cfg,root,selection):
 from step_six.graph_routes import clip_events,registry
 nc=dict(cfg,work_root=str(root/'native'));state=j(root/'native/STATE.json');p3=root/'native/P3'/state['run'];graph=j(p3/'STSG_partial.json');pairs=j(p3/'PAIR_LEDGER.json');ledger=rows(root/'native/NATIVE_VERIFICATION_LEDGER.jsonl');tasks={}
 for p in (root/'native/frozen_inputs').glob('*.json'):
  for t in j(p).get('all_tasks',[]):tasks[t['scope']]=t
 media=shared_media(cfg,root,selection);rt=make_runtime(cfg,root/'route_calls','native_QRA',choose_gpu())
 try:
  graph=clip_events(rt,root,graph,tasks,media);graph['graph_version']='FOUR-GROUP-GRAPH-v1';save(root/'GRAPH_SHARED_FROZEN.json',graph);save(root/'SOURCE_NATIVE_LEDGER.json',ledger);save(root/'SOURCE_TEMPORAL_PAIRS.json',pairs);facts=registry(ledger,pairs,graph,tasks);save(root/'FACT_REGISTRY.json',facts)
  pq=p_route(root,graph,ledger,pairs,selection);sq=s_route(rt,root,graph,facts,media,selection)
  qs=sq+pq;jl(root/'SOLVER_QUESTIONS_ONLY.jsonl',[{k:q[k] for k in ['question_id','video_id','question','route']} for q in qs]);save(root/'FREEZE_MANIFEST.json',{n:filehash(root/n) for n in ['GRAPH_SHARED_FROZEN.json','S_FROZEN_QA.jsonl','P_FROZEN_QA.jsonl','SOLVER_QUESTIONS_ONLY.jsonl','VIDEO_INPUTS_FROZEN.json']});emit('four_group_question_freeze',S=len(sq),P=len(pq),video_denominator=len(selection))
 finally:allocation(rt,root/'route_calls');save(root/'ROUTE_COST.json',cost(root/'route_calls'))

def solver_stage(cfg,root):
 # Reuse isolated video+question-only Solver function. Never call its VQS path.
 lines=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines();gpus=[l.split(',')[0].strip() for l in lines if float(l.split(',')[1])>40000 and float(l.split(',')[2])<5];assert gpus,'NO_IDLE_A40';total=len(rows(root/'SOLVER_QUESTIONS_ONLY.jsonl'));gpus=gpus[:min(5,total)];pp=[]
 if not total:save(root/'SOLVER_FAILURES.json',[]);return
 for i,gpu in enumerate(gpus[:5]):pp.append((subprocess.Popen([sys.executable,'-m','four_group.pipeline','--worker','solver','--config',str(root/'effective_config.json'),'--index',str(i),'--count',str(len(gpus[:5])),'--gpu',gpu]),i))
 failures=[]
 for p,i in pp:
  if p.wait()!=0:failures.append({'shard':i,'returncode':p.returncode})
 save(root/'SOLVER_FAILURES.json',failures)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',default='config/four_group.json');ap.add_argument('--worker');ap.add_argument('--index',type=int,default=0);ap.add_argument('--count',type=int,default=1);ap.add_argument('--gpu');a=ap.parse_args();cfg=j(a.config)
 if a.worker:
  if a.worker=='solver':
   from .solver import solver_worker
   solver_worker(cfg,Path(cfg['work_root']),a.index,a.count,a.gpu)
  elif a.worker=='routes':graph_questions(cfg,Path(cfg['work_root']),j(Path(cfg['work_root'])/'selection/SELECTION_FROZEN.json')['selected'])
  return
 root=Path('/scratch/haozhe/.cache/vlm-rsi/four-group')/os.environ['ORX_EXPERIMENT']/os.environ['ORX_RUN_ID'];root.mkdir(parents=True);cfg.update(work_root=str(root),source_commit=os.environ['ORX_COMMIT']);save(root/'effective_config.json',cfg);print(json.dumps({'effective_config':cfg}),flush=True)
 old33(cfg['old33_root'],cfg['old33_original_root'],root/'old33');emit('old33_reconstructed_no_model_calls',questions=33,vote_draws=330)
 selected=audit(cfg['pool_root'],cfg['history_roots'],root/'selection',cfg.get('history_extra_files'));native_batch.execute(cfg,root/'native',selected)
 subprocess.run([sys.executable,'-m','four_group.pipeline','--worker','routes','--config',str(root/'effective_config.json')],check=True)
 solver_stage(cfg,root);qs=rows(root/'S_FROZEN_QA.jsonl')+rows(root/'P_FROZEN_QA.jsonl');votes={}
 for p in root.glob('solver/shard_*/questions/*/VOTE.json'):v=j(p);votes[v['question_id']]=v
 new=export_comparison(qs,votes,root/'new_batch','FIXED_PROTOCOL_ENGINEERING_BATCH_NOT_STRICT_HELDOUT')
 from .semantic_aux import execute as semantics
 om=j(Path(cfg['old33_root'])/'VIDEO_INPUTS_FROZEN.json');media={**om,**j(root/'VIDEO_INPUTS_FROZEN.json')};cfg2=dict(cfg,shared_media=media)
 semantics(cfg2,root,[('old33',r) for r in rows(root/'old33/PER_QUESTION.jsonl')]+[('new',r) for r in new],media)
 for n,digest in j(root/'FREEZE_MANIFEST.json').items():assert filehash(root/n)==digest
 from .diagnostics import report
 report(root)
 from .evidence import export as evidence_export
 evidence_export(cfg,root)
 summary={'old33':j(root/'old33/SUMMARY.json'),'new':j(root/'new_batch/SUMMARY.json'),'selected_video_denominator':len(selected),'native':j(root/'native/summary.json'),'cost_new':cost(root),'VQS_calls':0,'training':False,'correctness':'PENDING_UNLESS_EXPLICIT_GOLD_ALIGNMENT','selected_failed_videos_retained':True};save(root/'SUMMARY.json',summary);save(root/'STATE.json',{'state':'DONE','run':os.environ['ORX_RUN_ID']});emit('four_group_summary',**{k:v for k,v in summary.items() if k!='native'})
if __name__=='__main__':main()
