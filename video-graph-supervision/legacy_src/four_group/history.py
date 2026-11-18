"""Read-only preselection audit; inventory alone is not evidence of model use."""
import json,re,os,hashlib
from pathlib import Path
from step_six.common import j,rows,filehash
from stsg_pilot.runtime import save
RX=re.compile(r'\bvideo_\d+\b')
def audit(pool,roots,out,extra=None):
 pool=Path(pool);out=Path(out);out.mkdir(parents=True,exist_ok=True);evidence=[];used={};used_hashes=set();failures=[]
 def ingest(p,kind):
  try:
   text=p.read_text();ids=sorted(set(RX.findall(text)))
   if not ids:return
   rec={'file':str(p),'sha256':filehash(p),'kind':kind,'video_ids':ids,'bytes':p.stat().st_size};evidence.append(rec)
   for vid in ids:used.setdefault(vid,[]).append({'file':str(p),'kind':kind,'source_sha256':rec['sha256']})
   # Hashes in actual calls/bindings are conservatively excluded if equal to a
   # source-file hash; pixel hashes will simply not match video hashes.
   used_hashes.update(re.findall(r'\b[0-9a-f]{64}\b',text))
  except Exception as e:failures.append({'file':str(p),'error':repr(e)})
 for root in roots:
  root=Path(root)
  for directory,dirs,files in os.walk(root):
   dirs[:]=[d for d in dirs if d not in ['request_cache','samples','candidate','requests','source','pixels','.git','__pycache__','selected_train','S1','S2','features'] and not d.startswith('models--')]
   for name in files:
    p=Path(directory)/name
    if name in ['requests.jsonl','requests_started.jsonl','frozen_videos.json','question_universe_frozen.json','BASE_VIDEO_INPUTS_FROZEN.json','VIDEO_INPUTS_FROZEN.json','P2_selected.json'] or ('frozen_inputs' in p.parts and name.endswith('.json')) or ('outputs' in p.parts and (name.endswith('.jsonl') or name.endswith('video_manifest.json'))):ingest(p,'model_call_or_frozen_generation_input')
 if extra:
  for f in extra:ingest(Path(f),'external_persisted_call_or_training_manifest')
 candidates=[];seen_pool={}
 for p in sorted(pool.glob('video_*.mp4'),key=lambda x:int(x.stem.split('_')[-1])):
  digest=filehash(p);why=used.get(p.stem,[]);state='EXCLUDE_USED_ID' if why else 'EXCLUDE_USED_FILE_HASH' if digest in used_hashes else 'NO_USE_FOUND_IN_AUDITED_RECORDS'
  duplicate=seen_pool.get(digest)
  if state=='NO_USE_FOUND_IN_AUDITED_RECORDS' and duplicate:state='EXCLUDE_DUPLICATE_POOL_FILE_HASH'
  seen_pool.setdefault(digest,p.stem)
  candidates.append({'duplicate_content_canonical_id':duplicate,'video_id':p.stem,'path':str(p),'sha256':digest,'bytes':p.stat().st_size,'history_status':state,'exclusion_evidence':why,'prior_use_certainty':'UNCERTAIN_OUTSIDE_AUDITED_RECORDS','strict_unseen_guarantee':False,'provenance_limit':'Audited persistent project calls/bindings only; pruned/removed historical jobs or model pretraining cannot be disproved.'})
 eligible=[x for x in candidates if x['history_status']=='NO_USE_FOUND_IN_AUDITED_RECORDS'];selected=eligible[:10]
 save(out/'HISTORY_EVIDENCE.json',evidence);save(out/'POOL_AUDIT.json',candidates);save(out/'SELECTION_FROZEN.json',{'requested':10,'selected':selected,'rule':'ascending numeric originalvideo ID among files with no use found by both ID/hash; no scene/output/quality screening; all selected remain denominator; no replacement','roots':[str(x) for x in roots],'read_failures':failures,'status':'ENGINEERING_DIAGNOSTIC_NOT_STRICT_HELDOUT','unread_or_removed_history':'uncertain; not claimed strict unseen','frozen_before_model_calls':True,'candidate_count':len(candidates),'eligible_count':len(eligible)});return selected
