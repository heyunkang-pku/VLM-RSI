"""V2 native extraction recovery; no legacy Event Parser."""
import copy,json,hashlib
from pathlib import Path
from .checkpoint_runtime import CheckpointRuntime
from .recovery import digest,formatted_prompt,RecoveryGenerationFailure
from stsg_pilot.runtime import save,append

def semantic(mode,prompt,seed,temp,hashes):
 return digest([mode,prompt,seed,temp,hashes])
class V2Runtime(CheckpointRuntime):
 def __init__(self,cfg,out):
  super().__init__(cfg,out);self.old={};self.in_chain=False
  src=Path(cfg['v0_root'])
  for folder in ['referenced_requests','request_cache']:
   for p in (src/folder).glob('*.json'):
    r=json.loads(p.read_text())
    if r.get('status')!='DONE':continue
    k=semantic(r.get('input_mode'),r['prompt'],r['seed'],r['temperature'],r.get('frame_content_hashes',[]));prior=self.old.get(k)
    if prior is None or (prior['output_hit_cap'] and not r['output_hit_cap']):self.old[k]=r
 def begin_chain(self,key):self.in_chain=True;self.chain_key=key;self.invalidated=False;self.lineage=[]
 def begin_verify(self,key):self.in_chain=False;self.chain_key=key;self.invalidated=True;self.lineage=[]
 def ask(self,media,frame_ids,prompt,**kw):
  shown=[media['calibration_view']] if self.mode=='image' else media['class_video_views'] if self.mode=='video' else []
  hashes=[f['sha256'] for f in shown]
  if self.mode=='video' and len(hashes)%2:hashes=hashes+[hashes[-1]]
  k=semantic(self.mode,formatted_prompt(media,self.mode,prompt),kw['seed'],kw.get('temperature',0),hashes);old=self.old.get(k)
  if self.in_chain and not self.invalidated and old:
   self.cache_hits+=1;r=copy.deepcopy(old);self.lineage.append(r['request_id'])
   append(Path(self.cfg['work_root'])/'REUSE_LEDGER.jsonl',{'chain':self.chain_key,'request_id':r['request_id'],'origin':'V1','truncated':r['output_hit_cap']})
   save(Path(self.cfg['work_root'])/'referenced_requests'/(r['request_id']+'.json'),r)
   if r['output_hit_cap']:
    self.invalidated=True
    if self.mode=='text':return r # native helper splits the actual narrative
   else:return r
  self.invalidated=True;original=self.protocol;self.protocol=original+':'+digest([self.chain_key,self.lineage])
  # A single bounded request. No repeated stochastic search or changed video pool.
  cap=kw['max_tokens']
  if self.in_chain and not kw['role'].startswith('classify_'):cap=8192 if self.mode=='image' else 4096
  try:
   try:r=super().ask(media,frame_ids,prompt,**dict(kw,max_tokens=cap))
   except TimeoutError as e:raise RecoveryGenerationFailure('V2_REQUEST_TIMEOUT_NO_RETRY') from e
   self.lineage.append(r['request_id']);save(Path(self.cfg['work_root'])/'referenced_requests'/(r['request_id']+'.json'),r);return r
  finally:self.protocol=original
