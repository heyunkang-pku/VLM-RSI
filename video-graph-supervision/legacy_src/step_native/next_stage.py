"""Tracked resumable P1/P2 run. P3 eligible tasks assessed after verified outputs."""
import argparse,copy,json,os,resource,subprocess,sys,time,traceback,shutil
from pathlib import Path
from stsg_pilot.runtime import save,emit
from stsg_pilot.media import sha_file
from .checkpoint_runtime import CheckpointRuntime
from .structure_scan import scan
from .frame_execution import process_frame,freeze_video_media

def gpu_worker(cfg,kind,index):
 root=Path(cfg['work_root']);attempt=root/'attempts'/os.environ['ORX_RUN_ID']/('gpu'+os.environ['CUDA_VISIBLE_DEVICES'])/(kind+'_'+str(index));attempt.mkdir(parents=True,exist_ok=True);started=time.monotonic();status='FAILED';rt=None
 try:
  rt=CheckpointRuntime(cfg,attempt)
  if kind=='base':
   old=Path(cfg['baseline_root']);assert sha_file(cfg['baseline_candidate_file'])==cfg['baseline_candidate_sha256'];media=json.loads((old/'S2/input_manifest.json').read_text());media.update(_root=str(old),clip_id='c0',clip_intervals=[[0,34.411]])
   task={'scope':'video_7793/src_000854','folder':str(root/'frames/video_7793/src_000854'),'media':media,'candidate_existing':True};save(root/'frozen_inputs/video_7793.json',task);process_frame(rt,cfg,task)
  else:
   selected=json.loads((root/'P2_selected.json').read_text());tasks=freeze_video_media(cfg,selected[index],root)
   for task in tasks:process_frame(rt,cfg,task)
  status='COMPLETED'
 except Exception as e:save(attempt/'failure.json',{'error':repr(e),'traceback':traceback.format_exc()});emit('worker_failed',kind=kind,error=repr(e));raise
 finally:save(attempt/'allocation.json',{'gpu':os.environ['CUDA_VISIBLE_DEVICES'],'status':status,'worker_wall_seconds':time.monotonic()-started,'gpu_hours':(time.monotonic()-started)/3600,'model_calls_current_attempt':rt.calls-rt.initial_calls if rt else 0,'cache_hits':rt.cache_hits if rt else 0,'rss_peak_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})

def collect(cfg,root):
 frames=[];ledger=[]
 for p in sorted((root/'frames').glob('*/*/STATE.json')):
  st=json.loads(p.read_text());frames.append(st);lp=p.parent/'verification/ledger.json'
  if lp.exists():ledger+=json.loads(lp.read_text())
 with (root/'NATIVE_VERIFICATION_LEDGER.jsonl').open('w') as f:
  for row in ledger:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 requests=[json.loads(p.read_text()) for p in (root/'request_cache').glob('*.json')];alloc=[json.loads(p.read_text()) for p in (root/'attempts').rglob('allocation.json')]
 missing_allocations=[str(p.relative_to(root)) for p in (root/'attempts').glob('*/*/*') if p.is_dir() and not (p/'allocation.json').exists()]
 stages={}
 for r in requests:
  st=r['role'];d=stages.setdefault(st,{'calls':0,'input_tokens':0,'output_tokens':0,'device_seconds':0});d['calls']+=1;d['input_tokens']+=r.get('input_tokens',0);d['output_tokens']+=r.get('output_tokens',0);d['device_seconds']+=r.get('model_device_wall_seconds',0)
 summary={'work_root':str(root),'frames':frames,'calls_distinct_recorded':len(requests),'allocations':alloc,'total_gpu_hours':sum(a['gpu_hours'] for a in alloc),'input_tokens':sum(r.get('input_tokens',0) for r in requests),'output_tokens':sum(r.get('output_tokens',0) for r in requests),'device_seconds':sum(r.get('model_device_wall_seconds',0) for r in requests),'calls_by_role':stages,'native_ledger_rows':len(ledger),'accepted_by_type':{t:sum(r.get('state')=='ACCEPTED' for r in ledger if r['fact_type']==t) for t in sorted({r['fact_type'] for r in ledger})},'training':False,'VQS_executed':False,'formal_B_comparison':False,'G_raw_created':False}
 summary.update(gpu_hours_is_lower_bound=bool(missing_allocations),missing_worker_allocation_records=missing_allocations)
 save(root/'summary.json',summary);emit('P1_P2_summary',**{k:v for k,v in summary.items() if k not in ['calls_by_role','allocations','frames']});return summary

def supervise(cfg):
 root=Path('/scratch/haozhe/.cache/vlm-rsi/step-next')/os.environ['ORX_EXPERIMENT']/cfg['protocol_version'];root.mkdir(parents=True,exist_ok=True);cfg=copy.deepcopy(cfg);cfg.update(work_root=str(root),output_root=str(root),source_commit=os.environ['ORX_COMMIT']);save(root/'effective_config.json',cfg);save(root/'STATE.json',{'state':'RUNNING','run':os.environ['ORX_RUN_ID'],'commit':os.environ['ORX_COMMIT']});os.environ['SMOKE_DEADLINE']='inf'
 scanp=subprocess.Popen([sys.executable,'-m','step_native.next_stage','--scan','--config',str(root/'effective_config.json')],env=dict(os.environ,CUDA_VISIBLE_DEVICES='')) if not (root/'P2_scan_done.json').exists() else None
 lines=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines();gpus=[l.split(',')[0].strip() for l in lines if float(l.split(',')[1])>40000 and float(l.split(',')[2])<5];assert gpus,'NO_IDLE_A40';gpus=gpus[:3];workers=[];queue=[('base',0)];supp_queued=False
 try:
  while queue or any(p.poll() is None for p,_,_,_ in workers) or not supp_queued:
   if (root/'P2_scan_done.json').exists() and not supp_queued:
    queue += [('supplement',i) for i in range(len(json.loads((root/'P2_selected.json').read_text())))];supp_queued=True
   if scanp is not None and scanp.poll() not in [None,0]:raise RuntimeError('CPU_SCAN_FAILED')
   busy={gpu for p,gpu,_,_ in workers if p.poll() is None}
   current_lines=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines()
   currently_idle={l.split(',')[0].strip() for l in current_lines if float(l.split(',')[1])>40000 and float(l.split(',')[2])<5}
   for gpu in gpus:
    if not queue or gpu in busy or gpu not in currently_idle:continue
    kind,index=queue.pop(0);env=dict(os.environ,CUDA_VISIBLE_DEVICES=gpu);start=time.time();p=subprocess.Popen([sys.executable,'-m','step_native.next_stage','--worker',kind,'--index',str(index),'--config',str(root/'effective_config.json')],env=env);workers.append((p,gpu,start,kind));emit('gpu_worker_started',gpu=gpu,kind=kind,index=index)
   for p,gpu,start,kind in workers:
    if p.poll() not in [None,0]:raise RuntimeError('WORKER_FAILED:'+gpu+':'+kind)
    if p.poll() is None:
     logs=root/'attempts'/os.environ['ORX_RUN_ID']/('gpu'+gpu);latest=max([start]+[f.stat().st_mtime for f in logs.rglob('requests*.jsonl')]);
     if time.time()-latest>cfg['guard_no_progress_seconds']:p.terminate();raise RuntimeError('STALLED_WORKER_NO_PROGRESS:'+gpu)
   time.sleep(5)
  if scanp is not None:assert scanp.wait()==0
  save(root/'STATE.json',{'state':'COMPLETED_P1_P2','run':os.environ['ORX_RUN_ID']})
 except Exception as e:save(root/'STATE.json',{'state':'FAILED_PARTIAL','error':repr(e),'traceback':traceback.format_exc()});raise
 finally:
  for p,_,_,_ in workers:
   if p.poll() is None:
    p.terminate()
    try:p.wait(timeout=10)
    except subprocess.TimeoutExpired:p.kill();p.wait()
  if scanp is not None and scanp.poll() is None:scanp.terminate();scanp.wait()
  collect(cfg,root)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);ap.add_argument('--worker');ap.add_argument('--index',type=int,default=0);ap.add_argument('--scan',action='store_true');a=ap.parse_args();cfg=json.loads(Path(a.config).read_text())
 if a.scan:scan(cfg,Path(cfg['work_root']))
 elif a.worker:gpu_worker(cfg,a.worker,a.index)
 else:supervise(cfg)
if __name__=='__main__':main()
