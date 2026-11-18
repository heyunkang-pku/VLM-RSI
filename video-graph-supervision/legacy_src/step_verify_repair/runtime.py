"""Exact old-check reuse and bounded greedy requests with complete evidence export."""
import copy,json
from pathlib import Path
from step_native.checkpoint_runtime import CheckpointRuntime
from step_native.recovery import formatted_prompt
from step_six.common import h,save,append,absolute_media
from stsg_pilot.media import sha_file

def semantic_key(rev,mode,prompt,seed,temp,hashes):return h([rev,mode,prompt,seed,temp,hashes])
class RepairRuntime(CheckpointRuntime):
 def __init__(self,cfg,out):
  super().__init__(cfg,out);self.old={};self.old_capped={}
  for folder in cfg['reuse_call_roots']:
   for p in (Path(folder)/'request_cache').glob('*.json'):
    r=json.loads(p.read_text())
    if r.get('status')!='DONE':continue
    k=semantic_key(r['model_revision'],r['input_mode'],r['prompt'],r['seed'],r['temperature'],r.get('frame_content_hashes',[]))
    if r.get('output_hit_cap'):self.old_capped.setdefault((k,r['max_new_tokens']),(r,str(p)))
    else:self.old.setdefault(k,(r,str(p)))
 def ask(self,media,frame_ids,prompt,**kw):
  shown=[media['calibration_view']] if self.mode=='image' else media['class_video_views'] if self.mode=='video' else [];hashes=[x['sha256'] for x in shown]
  for frame in shown:assert sha_file(Path(media['_root'])/frame['file'])==frame['sha256'],'FROZEN_PIXEL_MUTATED'
  if self.mode=='video' and len(hashes)%2:hashes.append(hashes[-1])
  key=semantic_key(self.cfg['model_revision'],self.mode,formatted_prompt(media,self.mode,prompt),kw['seed'],kw.get('temperature',0),hashes)
  if key in self.old:
   r,src=self.old[key];self.cache_hits+=1;append(Path(self.cfg['work_root'])/'OLD_CHECK_REUSE.jsonl',{'request_id':r['request_id'],'source':src,'semantic_key':key,'policy':'identical revision/greedy prompt/seed/pixel hashes/time-prefixed prompt; completed EOS reply, old output cap not hit'});save(Path(self.cfg['work_root'])/'reused_requests'/(r['request_id']+'.json'),r);return copy.deepcopy(r)
  if (key,kw['max_tokens']) in self.old_capped:
   r,src=self.old_capped[(key,kw['max_tokens'])];self.cache_hits+=1;append(Path(self.cfg['work_root'])/'CAPPED_FAILURE_REUSE.jsonl',{'request_id':r['request_id'],'source':src,'semantic_key':key,'cap':kw['max_tokens'],'policy':'reuse identical known truncation as FAILED evidence only; never parse/accept prefix'});save(Path(self.cfg['work_root'])/'reused_requests'/(r['request_id']+'.json'),r);return copy.deepcopy(r)
  return super().ask(media,frame_ids,prompt,**kw)

def atom_media(atom,facts,media,pair_inputs):
 f=facts[atom['evidence_fact_id']]
 if f.get('pair_id') in pair_inputs:
  m=absolute_media(pair_inputs[f['pair_id']]);m['calibration_view']=m['class_video_views'][0];return m,'video'
 if atom['kind'] in ['motion','identity','time'] or f.get('verification_mode')=='video' or atom.get('evidence_scope') in ['interval','full_clip']:
  m=copy.deepcopy(media[f['video_id']]);return m,'video'
 # A static requirement spanning multiple observations must not be proved by
 # silently showing just a single selected frame.
 scopes={facts[x].get('scope') for x in atom['fact_ids'] if x in facts and facts[x].get('scope')}
 if len(scopes)>1:raise ValueError('MULTI_OBSERVATION_FACT_NEEDS_EXPLICIT_TEMPORAL_GROUNDING')
 return copy.deepcopy(f['media']),'image'
