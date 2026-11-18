"""Tracked S1 CPU then one-keyframe S2, no native verification without approval."""
import argparse,copy,json,os,resource,subprocess,sys,time,traceback
from pathlib import Path
from stsg_pilot.runtime import save,emit
from .splitting import prepare

def worker(cfg):
    root=Path(cfg['output_root']);start=time.monotonic();status='FAILED'
    try:
        from .calibration import run_chain
        run_chain(cfg,root);status='COMPLETED'
    except Exception as e:
        save(root/'S2/failure.json',{'error':repr(e),'traceback':traceback.format_exc()});emit('S2_stopped',error=repr(e));raise
    finally:save(root/'S2/allocation.json',{'status':status,'gpu':os.environ['CUDA_VISIBLE_DEVICES'],'worker_wall_seconds':time.monotonic()-start,'allocated_gpu_hours':(time.monotonic()-start)/3600,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})

def supervise(cfg):
    assert cfg['video']['video_id']=='video_7793' and cfg['wall_seconds']+cfg['kill_grace_seconds']<=900
    assert not any(cfg[k] for k in ['training','scaleup_authorized','reward_changes'])
    root=Path('/scratch/haozhe/.cache/vlm-rsi/step-native-s1-s2')/os.environ['ORX_RUN_ID'];root.mkdir(parents=True,exist_ok=False)
    cfg=copy.deepcopy(cfg);cfg.update(output_root=str(root),source_commit=os.environ['ORX_COMMIT']);save(root/'effective_config.json',cfg)
    start=time.monotonic();prepare(cfg,root);assert time.monotonic()-start<cfg['cpu_wall_seconds'],'S1_CPU_BUDGET_EXCEEDED'
    lines=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines()
    free=[l.split(',')[0].strip() for l in lines if float(l.split(',')[1])>40000 and float(l.split(',')[2])<5];assert free,'NO_IDLE_A40'
    cfg['gpu_id']=free[0];save(root/'effective_config.json',cfg);emit('S2_start',config=cfg)
    env=dict(os.environ,CUDA_VISIBLE_DEVICES=free[0],SMOKE_DEADLINE=str(time.time()+cfg['wall_seconds']))
    p=subprocess.Popen([sys.executable,'-m','step_native.run','--worker','--config',str(root/'effective_config.json')],env=env);allocated_start=time.monotonic()
    try:
        p.wait(timeout=cfg['wall_seconds'])
    except subprocess.TimeoutExpired:
        save(root/'S2/budget_stop.json',{'reason':'0.25GPUh hard budget','worker_seconds_cap':cfg['wall_seconds']});p.terminate()
        try:p.wait(timeout=cfg['kill_grace_seconds'])
        except subprocess.TimeoutExpired:p.kill();p.wait()
    finally:
        elapsed=time.monotonic()-allocated_start
        responses=[];f=root/'S2/worker/requests.jsonl'
        if f.exists():responses=[json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        chain=json.loads((root/'S2/chain_summary.json').read_text()) if (root/'S2/chain_summary.json').exists() else {'full_chain_completed':False}
        summary={'run_id':os.environ['ORX_RUN_ID'],'source_commit':os.environ['ORX_COMMIT'],'output_root':str(root),'S1':json.loads((root/'S1/manifest.json').read_text()),'S2':chain,'worker_returncode':p.returncode,'allocated_gpu_seconds_including_setup_process_exit':elapsed,'allocated_gpu_hours':elapsed/3600,'device_call_seconds':sum(r.get('model_device_wall_seconds',0) for r in responses),'completed_model_calls':sum(r.get('status')=='DONE' for r in responses),'failed_model_calls':sum(r.get('status')=='FAILED' for r in responses),'input_tokens':sum(r.get('input_tokens',0) for r in responses),'output_tokens':sum(r.get('output_tokens',0) for r in responses),'peak_allocated_bytes':max([r.get('peak_allocated_bytes',0) for r in responses],default=0),'peak_reserved_bytes':max([r.get('peak_reserved_bytes',0) for r in responses],default=0),'native_verification_calls':0,'B0_B4_calls':0,'training':False}
        save(root/'summary.json',summary);emit('STEP_S1_S2_summary',**{k:v for k,v in summary.items() if k!='S1'})
    assert p.returncode==0,'S2_INCOMPLETE_SEE_PARTIAL_OUTPUTS'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);ap.add_argument('--worker',action='store_true');a=ap.parse_args();cfg=json.loads(Path(a.config).read_text());(worker if a.worker else supervise)(cfg)
if __name__=='__main__':main()
