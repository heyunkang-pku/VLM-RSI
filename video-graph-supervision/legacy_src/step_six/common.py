import copy,hashlib,json,os,re,subprocess,time,unicodedata
from pathlib import Path
from stsg_pilot.runtime import save,append,emit
from step_review.program_adapter import h

def j(p):return json.loads(Path(p).read_text())
def rows(p):return [json.loads(x) for x in Path(p).read_text().splitlines()] if Path(p).exists() else []
def jl(p,x):Path(p).parent.mkdir(parents=True,exist_ok=True);Path(p).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in x))
def filehash(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def parsejson(s):
 s=s.strip()
 if s.startswith('```'):s=re.sub(r'^```(?:json)?\s*|\s*```$','',s)
 return json.loads(s)
def norm(x):
 if isinstance(x,list):return ' ; '.join(sorted(norm(v) for v in x))
 return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(x)).lower()).strip().rstrip(' .!?。！？')
def vote(samples,n=10):
 from collections import Counter
 valid=[norm(x['answer']) for x in samples if x.get('status')=='VALID' and norm(x.get('answer',''))];c=Counter(valid);rank=sorted(c.items(),key=lambda x:(-x[1],x[0]));tie=len(rank)>1 and rank[0][1]==rank[1][1];win=rank[0] if rank else (None,0)
 return {'status':'ANSWERED' if win[1]>n//2 and not tie else 'ABSTAIN','answer':win[0] if win[1]>n//2 and not tie else None,'votes':dict(c),'valid_samples':len(valid),'fixed_denominator':n,'tie':tie,'top_vote_count':win[1],'confidence':win[1]/n}
def choose_gpu(exclude=()):
 for line in subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines():
  i,m,u=[x.strip() for x in line.split(',')]
  if i not in exclude and float(m)>40000 and float(u)<5:return i
 raise RuntimeError('NO_IDLE_A40')
def absolute_media(m):
 m=copy.deepcopy(m)
 for f in [m['calibration_view']]+m['class_video_views']:f['file']=str(Path(m['_root'])/f['file'])
 m['_root']='/';return m

def make_runtime(cfg,root,phase,gpu):
 from step_native.checkpoint_runtime import CheckpointRuntime
 os.environ['CUDA_VISIBLE_DEVICES']=gpu;os.environ['SMOKE_DEADLINE']='inf';root=Path(root);root.mkdir(parents=True,exist_ok=True)
 c=dict(cfg,work_root=str(root),output_root=str(root),protocol_version=cfg['protocol_version']+':'+phase,request_namespace=phase+'_')
 save(root/'effective_config.json',c);return CheckpointRuntime(c,root/'runtime')
def ask(rt,media,prompt,role,owner,mode='text',cap=2048,temp=0,seed=2026110103):
 rt.mode=mode;r=rt.ask(media,[],prompt,role=role,seed=seed,temperature=temp,max_tokens=cap,owner=owner)
 if r['output_hit_cap']:raise ValueError('OUTPUT_TOKEN_CAP_HIT:'+r['request_id'])
 return r

def cost(root):
 root=Path(root);started={};done={}
 for f in root.rglob('requests_started.jsonl'):
  for r in rows(f):started[r['request_id']]=r
 for f in root.rglob('requests.jsonl'):
  for r in rows(f):done[r['request_id']]=r
 allocations=[j(p) for p in root.rglob('ALLOCATION.json')];return {'allocation_GPU_hours':sum(a['wall_seconds']/3600 for a in allocations),'attempted_calls':len(started),'completed_calls':sum(r.get('status')=='DONE' for r in done.values()),'failed_or_missing_calls':len(set(started)-{k for k,v in done.items() if v.get('status')=='DONE'}),'input_tokens':sum(r.get('input_tokens',0) for r in done.values()),'output_tokens':sum(r.get('output_tokens',0) for r in done.values()),'device_seconds':sum(r.get('model_device_wall_seconds',0) for r in done.values()),'device_GPU_hours':sum(r.get('model_device_wall_seconds',0) for r in done.values())/3600,'cost_currency':None,'cost_currency_reason':'user-owned server; no monetary tariff supplied','accuracy':'PENDING_INDEPENDENT_HUMAN'}

def allocation(rt,root):
 save(Path(root)/'ALLOCATION.json',{'gpu':rt.gpu,'wall_seconds':time.monotonic()-rt.started,'includes_model_loading':True,'model_load_seconds':rt.model_load_seconds,'model_calls':rt.calls-rt.initial_calls,'cache_hits':rt.cache_hits})
