"""V1 bounded output-length recovery, immutable V0, same method and inputs."""
import argparse,copy,hashlib,json,os,shutil,subprocess,sys,time,traceback
from pathlib import Path
from stsg_pilot.runtime import save,append,emit
from .checkpoint_runtime import CheckpointRuntime
from .calibration import run_chain
from .native_verification import verify
from .next_stage import collect
from .frame_execution import candidate_output_failure

def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
class RecoveryGenerationFailure(RuntimeError):pass
def failure_signature(mode,prompt,kw,hashes):
 return digest({'mode':mode,'prompt':prompt,'seed':kw['seed'],'temperature':kw.get('temperature',0),'cap':kw['max_tokens'],'pixel_files':hashes})

def formatted_prompt(media,mode,prompt):
 if mode=='video':return 'Authoritative source PTS times (seconds), in supplied video order: '+json.dumps([{'frame_id':f['frame_id'],'source_seconds':f['time_sec']} for f in media['class_video_views']])+'. Clip intervals: '+json.dumps(media.get('clip_intervals',[]))+'.\n'+prompt
 return prompt

def import_terminal_failures(root):
 for p in root.glob('attempts/*/*/*/requests.jsonl'):
  for line in p.read_text().splitlines():
   r=json.loads(line)
   if r.get('status')=='FAILED' and 'SINGLE_REQUEST_TIMEOUT' in r.get('error',''):
    kw={'seed':r['seed'],'temperature':r['temperature'],'max_tokens':r['max_new_tokens']};key=failure_signature(r['input_mode'],r['prompt'],kw,r['frame_content_hashes']);save(root/'terminal_request_failures'/(key+'.json'),{'request_id':r['request_id'],'source_log':str(p),'reason':'previous timed-out attempt is terminal, do not regenerate','cap':r['max_new_tokens']})
def v0_key(cfg,media,mode,prompt,kw):
 shown=[media['calibration_view']] if mode=='image' else media['class_video_views'] if mode=='video' else []
 if mode=='video':prompt='Authoritative source PTS times (seconds), in supplied video order: '+json.dumps([{'frame_id':f['frame_id'],'source_seconds':f['time_sec']} for f in shown])+'. Clip intervals: '+json.dumps(media.get('clip_intervals',[]))+'.\n'+prompt
 key={'protocol':'step-next-v1','revision':cfg['model_revision'],'mode':mode,'prompt':prompt,'seed':kw['seed'],'temperature':kw.get('temperature',0),'max_tokens':kw['max_tokens'],'pixel_files':[f['sha256'] for f in shown],'times':[f['time_sec'] for f in shown],'video_fps':media['video']['avg_fps'],'total_frames':media['source_frames_decoded']}
 # V0 used default ensure_ascii=True.
 return hashlib.sha256(json.dumps(key,sort_keys=True).encode()).hexdigest()

class RecoveryRuntime(CheckpointRuntime):
 def begin_chain(self,key):self.in_chain=True;self.chain_key=key;self.invalidated=False;self.lineage=[]
 def begin_verify(self,key):self.in_chain=False;self.chain_key=key;self.lineage=[];self.invalidated=True
 def ask(self,media,frame_ids,prompt,**kw):
  old=Path(self.cfg['v0_root'])/'request_cache'/(v0_key(self.cfg,media,self.mode,prompt,kw)+'.json');oldr=json.loads(old.read_text()) if old.exists() else None
  if self.in_chain and not self.invalidated and oldr and oldr['status']=='DONE' and not oldr['output_hit_cap']:
   self.cache_hits+=1;r=copy.deepcopy(oldr);self.lineage.append(r['request_id']);append(Path(self.cfg['work_root'])/'REUSE_LEDGER.jsonl',{'chain':self.chain_key,'request_id':r['request_id'],'origin':'V0','source_cache_sha256':hashlib.sha256(old.read_bytes()).hexdigest(),'reason':'same frozen input/prompt/seed; no recovered upstream yet'});save(Path(self.cfg['work_root'])/'referenced_requests'/(r['request_id']+'.json'),r);return r
  # Conservatively invalidate the whole remaining chain suffix after a changed upstream.
  self.invalidated=True;original_protocol=self.protocol;self.protocol=original_protocol+':'+digest({'stage':self.chain_key,'upstream_request_ids':self.lineage})
  if self.in_chain and not kw['role'].startswith('classify_'):caps=[2048,4096]
  else:caps=[kw['max_tokens']]
  try:
   for attempt,cap in enumerate(caps):
    args=dict(kw,max_tokens=cap);shown=[media['calibration_view']] if self.mode=='image' else media['class_video_views'] if self.mode=='video' else [];fp=failure_signature(self.mode,formatted_prompt(media,self.mode,prompt),args,[f['sha256'] for f in shown]);terminal=Path(self.cfg['work_root'])/'terminal_request_failures'/(fp+'.json')
    if terminal.exists():raise RecoveryGenerationFailure('RECOVERY_TERMINAL_FAILURE_RETAINED:'+terminal.read_text())
    try:r=super().ask(media,frame_ids,prompt,**args)
    except TimeoutError as e:
     save(terminal,{'chain':self.chain_key,'cap':cap,'error':repr(e),'reason':'terminal request failure; no retry or further escalation'});raise RecoveryGenerationFailure('RECOVERY_TERMINAL_REQUEST_TIMEOUT:'+str(cap)) from e
    append(Path(self.cfg['work_root'])/'RECOVERY_CALL_LEDGER.jsonl',{'chain':self.chain_key,'request_id':r['request_id'],'role':r['role'],'cap':cap,'attempt':attempt,'old_request_id':oldr['request_id'] if oldr else None,'old_was_truncated':oldr.get('output_hit_cap') if oldr else None,'output_hit_cap':r['output_hit_cap'],'dependency_policy':'all remaining chain suffix invalidated; raw V0 never changed','old_input_hashes':oldr.get('input_hashes') if oldr else None,'new_input_hashes':r['input_hashes']});save(Path(self.cfg['work_root'])/'referenced_requests'/(r['request_id']+'.json'),r)
    if not r['output_hit_cap']:break
  finally:self.protocol=original_protocol
  self.lineage.append(r['request_id']);return r

def freeze(cfg,root):
 src=Path(cfg['v0_root']);tasks=[]
 for p in sorted((src/'frozen_inputs').glob('*.json')):
  j=json.loads(p.read_text());tasks+=j.get('all_tasks',[j] if 'scope' in j else [])
 allnew=[];affected=[]
 for old in tasks:
  t=copy.deepcopy(old);folder=root/'frames'/old['scope'];oldfolder=Path(old['folder']);t.update(folder=str(folder),v0_folder=str(oldfolder));oldstate=json.loads((oldfolder/'STATE.json').read_text());t['v0_state']=oldstate['state'];allnew.append(t)
  if oldstate['state']=='COMPLETED':
   if not folder.exists():shutil.copytree(oldfolder,folder)
  else:affected.append(t)
 for v in sorted({t['media']['video']['video_id'] for t in allnew}):save(root/'frozen_inputs'/(v+'.json'),{'all_tasks':[t for t in allnew if t['media']['video']['video_id']==v],'version':cfg.get('graph_version','V1'),'V0_input_binding_preserved':True})
 save(root/'FROZEN_RECOVERY_SCOPE.json',{'all_keyframes':len(allnew),'affected_keyframes':affected,'unaffected_frames_reused':[t['scope'] for t in allnew if t['v0_state']=='COMPLETED'],'policy':'recover six candidate chains +30invalid samples +30unstarted samples; fixed seeds/5denominator; nontruncated prefixes reused; descendant suffix invalidated; same prompts/pixels/revision/sampling/matching'});return affected

def process(rt,cfg,t):
 folder=Path(t['folder']);old=Path(t['v0_folder']);state=folder/'STATE.json';folder.mkdir(parents=True,exist_ok=True)
 if state.exists() and json.loads(state.read_text())['state'] in ['COMPLETED','PARTIAL','CANDIDATE_UNAVAILABLE']:return
 save(state,{'state':'RUNNING','scope':t['scope'],'version':cfg.get('graph_version','V1')});media=t['media'];save(folder/'input_manifest.json',media);cc=dict(cfg,video=media['video'])
 cp=folder/'candidate/FSG_frozen.json';oldcp=old/'candidate/FSG_frozen.json'
 if cp.exists():g=json.loads(cp.read_text())
 elif oldcp.exists():g=json.loads(oldcp.read_text());save(cp,g)
 else:
  rt.begin_chain(t['scope']+':candidate')
  try:g=run_chain(dict(cc,seed=cfg['candidate_seed'],chain_temperature=0),folder/'candidate',rt,media);save(cp,g)
  except Exception as e:
   if not candidate_output_failure(e) and not isinstance(e,RecoveryGenerationFailure):raise
   save(state,{'state':'CANDIDATE_UNAVAILABLE','scope':t['scope'],'version':cfg.get('graph_version','V1'),'error':repr(e),'reason':'bounded recovery exhausted; retain keyframe denominator'});return
 samples=[]
 for i,seed in enumerate(cfg['sampling_seeds']):
  sp=folder/'samples'/str(i);receipt=sp/'RECEIPT.json';oldreceipt=old/'samples'/str(i)/'RECEIPT.json'
  if receipt.exists():s=json.loads(receipt.read_text())
  elif oldreceipt.exists() and json.loads(oldreceipt.read_text())['valid'] and t['v0_state']!='CANDIDATE_UNAVAILABLE':
   s=json.loads(oldreceipt.read_text());s.update(reused_from_version=cfg.get('baseline_version','V0'));save(receipt,s)
  else:
   rt.begin_chain(t['scope']+':seed'+str(seed))
   try:sg=run_chain(dict(cc,seed=seed,chain_temperature=cfg['sampling_temperature']),sp,rt,media);s={'sample_id':t['scope']+':seed'+str(seed),'seed':seed,'valid':bool(sg.get('prompt_chain_completed')),'graph':sg,'version':cfg.get('graph_version','V1')}
   except Exception as e:
    if not candidate_output_failure(e) and not isinstance(e,RecoveryGenerationFailure):raise
    s={'sample_id':t['scope']+':seed'+str(seed),'seed':seed,'valid':False,'error':repr(e),'version':cfg.get('graph_version','V1'),'traceback':traceback.format_exc()}
   save(receipt,s)
  samples.append(s);emit('V1_sample_completed',scope=t['scope'],seed=seed,valid=s['valid'],reused=s.get('reused_from_version'))
 rt.begin_verify(t['scope']+':verification:'+digest({'g':g,'samples':samples}));vg,ledger=verify(rt,cfg,folder/'verification',g,media,samples,t['scope']);save(state,{'state':'COMPLETED' if all(x['valid'] for x in samples) else 'PARTIAL','scope':t['scope'],'version':cfg.get('graph_version','V1'),'valid_samples':sum(x['valid'] for x in samples),'fixed_denominator':5,'candidate_objects':len(g['object_nodes']),'available_objects':len(vg['object_nodes'])})

def worker(cfg,index):
 root=Path(cfg['work_root']);out=root/'attempts'/os.environ['ORX_RUN_ID']/('gpu'+os.environ['CUDA_VISIBLE_DEVICES'])/('shard_'+str(index));start=time.monotonic();rt=None
 try:
  rt=(__import__('step_native.v2_recovery',fromlist=['V2Runtime']).V2Runtime if cfg.get('graph_version')=='V2' else RecoveryRuntime)(cfg,out);tasks=json.loads((root/f'shard_{index}.json').read_text())
  for t in tasks:process(rt,cfg,t)
 finally:save(out/'allocation.json',{'gpu':os.environ['CUDA_VISIBLE_DEVICES'],'gpu_hours':(time.monotonic()-start)/3600,'worker_wall_seconds':time.monotonic()-start,'model_calls_current_attempt':rt.calls-rt.initial_calls if rt else 0,'cache_hits':rt.cache_hits if rt else 0})

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);ap.add_argument('--worker',type=int);a=ap.parse_args();cfg=json.loads(Path(a.config).read_text());os.environ['SMOKE_DEADLINE']='inf'
 if a.worker is not None:worker(cfg,a.worker);return
 root=Path('/scratch/haozhe/.cache/vlm-rsi/step-recovery')/os.environ['ORX_EXPERIMENT']/cfg.get('graph_version','V1');root.mkdir(parents=True,exist_ok=True);cfg.update(work_root=str(root),output_root=str(root),source_commit=os.environ['ORX_COMMIT']);save(root/'effective_config.json',cfg);import_terminal_failures(root);tasks=freeze(cfg,root);gpus=[]
 for line in subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines():
  i,m,u=line.split(',')
  if float(m)>40000 and float(u)<5:gpus.append(i.strip())
 assert gpus,'NO_IDLE_A40';gpus=gpus[:5];processes=[];save(root/'STATE.json',{'state':'RUNNING','version':cfg.get('graph_version','V1'),'run':os.environ['ORX_RUN_ID']})
 try:
  for index,gpu in enumerate(gpus):
   shard=tasks[index::len(gpus)]
   if not shard:continue
   save(root/f'shard_{index}.json',shard);p=subprocess.Popen([sys.executable,'-m','step_native.recovery','--config',str(root/'effective_config.json'),'--worker',str(index)],env=dict(os.environ,CUDA_VISIBLE_DEVICES=gpu));processes.append((p,gpu,time.time()))
  while any(p.poll() is None for p,_,_ in processes):
   for p,gpu,started in processes:
    if p.poll() not in [None,0]:raise RuntimeError('V1_WORKER_FAILED:'+gpu)
    if p.poll() is None:
     last=max([started]+[f.stat().st_mtime for f in (root/'attempts'/os.environ['ORX_RUN_ID']/('gpu'+gpu)).rglob('requests*.jsonl')])
     if time.time()-last>cfg['guard_no_progress_seconds']:raise RuntimeError('V1_NO_PROGRESS:'+gpu)
   time.sleep(5)
  for p,_,_ in processes:assert p.wait()==0
  save(root/'STATE.json',{'state':'COMPLETED_FSG','version':cfg.get('graph_version','V1')});collect(cfg,root)
  tc=dict(cfg,parent_work_root=str(root),protocol_version='step-temporal-'+cfg.get('graph_version','V1'),request_namespace='temporal_');save(root/'temporal_config.json',tc);subprocess.run([sys.executable,'-m','step_native.temporal','--config',str(root/'temporal_config.json')],check=True,env=dict(os.environ,CUDA_VISIBLE_DEVICES=''))
  save(root/'STATE.json',{'state':'COMPLETED_V1','version':cfg.get('graph_version','V1'),'run':os.environ['ORX_RUN_ID']})
 finally:
  for p,_,_ in processes:
   if p.poll() is None:p.terminate();p.wait(timeout=20)
  collect(cfg,root)
if __name__=='__main__':main()
