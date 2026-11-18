"""Global FSG frequency + visual-presence verification BEFORE temporal merging.
Paper coverage and reconstructed prompt wording are explicit per ledger row.
No QA, program answers, VQS or G_raw.
"""
import copy,json,re,hashlib
from pathlib import Path
from stsg_pilot.runtime import save,append,emit
from .records import canon,plain

def status_graph(g):return g.get('prompt_chain_completed',False)
def valid_json(t):
 t=plain(t);return json.loads(t)
def verdict(t):
 v=t.strip().strip('[]\"\' .\n').upper();return v if v in ['YES','NO','UNCERTAIN'] else 'UNEXPECTED_OUTPUT'
def facts(g):
 parents={e['attribute_id']:e['subject_id'] for e in g['attribute_edges']};rows=[]
 for n in g['object_nodes']:rows.append({'id':n['id'],'type':'object','parents':[],'row':n})
 for n in g['attribute_nodes']:rows.append({'id':n['id'],'type':'attribute','parents':[parents[n['id']]],'row':n})
 for n in g['relation_edges']:rows.append({'id':n['id'],'type':'relation','parents':[n['subject_id'],n['object_id']],'row':n})
 return rows

def classify_correspondence(proposals):
 """A match is only provisional model evidence; enforce one-to-one uniqueness."""
 reverse={};out={}
 for oid,ids in proposals.items():
  if len(ids)==1:reverse.setdefault(ids[0],[]).append(oid)
 for oid,ids in proposals.items():out[oid]=ids[0] if len(ids)==1 and len(reverse.get(ids[0],[]))==1 else None
 return out

def sample_signature_set(g,typ):
 parents={e['attribute_id']:e['subject_id'] for e in g['attribute_edges']}
 if typ=='attribute':return {(parents[a['id']],canon(a['type']),canon(a['value'])) for a in g['attribute_nodes']}
 return {(e['subject_id'],canon(e['predicate']),e['object_id']) for e in g['relation_edges']}

def verify(rt,cfg,folder,g,media,samples,scope):
 folder.mkdir(parents=True,exist_ok=True);statefile=folder/'STATE.json';save(statefile,{'state':'RUNNING','scope':scope,'sample_denominator':len(samples)})
 N=cfg['sampling_replicas'];assert len(samples)==N;nodes={n['id']:n for n in g['object_nodes']};maps=[];alignment=[]
 for si,sample in enumerate(samples):
  if not sample['valid']:maps.append({});continue
  sg=sample['graph'];sn=sg['object_nodes'];proposals={}
  for node in g['object_nodes']:
   prompt='Compare two descriptions of object instances from independent parses of the SAME supplied keyframe. This is candidate correspondence, not external ground truth. Original: '+json.dumps({'id':node['id'],'description':node['referent']})+'. Sample candidates: '+json.dumps([{'id':x['id'],'description':x['referent']} for x in sn])+'. Identify the SAME physical instance only if its distinctive description is supported by the image. Same class alone is insufficient. If the original description contradicts the image, or multiple candidates could be the instance, leave unresolved. Return JSON {"matches":[sample IDs],"reason":"short reason"}; use [] for unresolved; list all duplicate candidates, never choose arbitrarily.'
   rt.mode='image';r=rt.ask(media,[],prompt,role='frequency_instance_correspondence',seed=cfg['seed'],max_tokens=256,temperature=0,owner=scope+':'+str(si)+':'+node['id'])
   try:
    j=valid_json(r['raw_response']);ids=j['matches'];assert isinstance(ids,list) and len(ids)==len(set(ids)) and all(x in {n['id'] for n in sn} for x in ids)
   except Exception:ids=[]
   proposals[node['id']]=ids;alignment.append({'scope':scope,'sample':si,'original_object':node['id'],'proposed_matches':ids,'request_id':r['request_id'],'source':'model-assisted candidate correspondence, NOT independent truth'})
  mapping=classify_correspondence(proposals);maps.append(mapping);save(folder/'alignment.json',alignment)
 rows=[];accepted={};byfacts={f['id']:f for f in facts(g)};aux_rows=[]
 for fact in facts(g):
  counts=[];unknown=[];row=fact['row'];typ=fact['type']
  for si,sample in enumerate(samples):
   if not sample['valid']:counts.append(False);unknown.append('INVALID_SAMPLE');continue
   mapping=maps[si];sg=sample['graph']
   if typ=='object':
    mid=mapping.get(row['id']);counts.append(mid is not None);unknown.append(None if mid is not None else 'INSTANCE_UNRESOLVED')
   else:
    mapped=[mapping.get(x) for x in fact['parents']]
    if any(x is None for x in mapped):counts.append(False);unknown.append('INSTANCE_UNRESOLVED');continue
    sig=(mapped[0],canon(row['type']),canon(row['value'])) if typ=='attribute' else (mapped[0],canon(row['predicate']),mapped[1])
    counts.append(sig in sample_signature_set(sg,typ));unknown.append(None)
  count=sum(counts);freqpass=count>=cfg['minimum_sample_occurrences'];parent_ok=all(accepted.get(x,False) for x in fact['parents'])
  entry={'scope':scope,'fact_id':fact['id'],'fact_type':typ,'parent_ids':fact['parents'],'source_request_ids':row.get('source_request_ids',[]),'source_keyframe':media['calibration_view'],'video_intervals':media.get('clip_intervals',[]),'candidate_content':row,'sample_ids':[x['sample_id'] for x in samples],'sample_valid':[x['valid'] for x in samples],'sample_occurrence':counts,'sample_unresolved_reason':unknown,'occurrences':count,'fixed_denominator':N,'frequency':count/N,'frequency_pass':freqpass,'sampling_incomplete':not all(x['valid'] for x in samples),'visual_verdict':None,'visual_request_id':None,'state':'NOT_STARTED','visual_prompt_basis':None,'parent_cascade':[],'classification_status':'not separately visually confirmed' if typ=='object' else None}
  if not parent_ok:entry.update(state='BLOCKED_PARENT',reason='required object rejected/unresolved',parent_cascade=[x for x in fact['parents'] if not accepted.get(x,False)])
  elif not freqpass:entry.update(state='UNRESOLVED_ALIGNMENT' if any(unknown) else 'FREQUENCY_REJECTED',reason='below fixed3/5; unresolved mappings not silently treated as known absence')
  else:
   if typ=='object':claim=row['referent'];basis='Supplement A.1 object+attribute composite existence example; native video modality'
   elif typ=='attribute':claim=nodes[fact['parents'][0]]['referent']+' whose '+row['type']+' is '+row['value'];basis='body Sec3.1 explicitly node/edge coverage; literal attribute wording is reconstruction, NOT an author-released prompt'
   else:claim=nodes[row['subject_id']]['referent']+' '+row['predicate']+' '+nodes[row['object_id']]['referent'];basis='body Sec3.1 explicitly node/edge coverage; literal relation wording is reconstruction, NOT an author-released prompt'
   prompt='For the given video, determine if ['+claim+'] truly exists in the given video. Just output Yes, No, or Uncertain.'
   rt.mode='video';r=rt.ask(media,[],prompt,role='native_presence_'+typ,seed=cfg['seed'],max_tokens=32,temperature=0,owner=scope+':'+fact['id']);v=verdict(r['raw_response']);entry.update(visual_verdict=v,visual_request_id=r['request_id'],visual_prompt_basis=basis,state='ACCEPTED' if v=='YES' else 'VISUAL_REJECTED' if v=='NO' else 'UNRESOLVED_VISUAL',raw_verdict=r['raw_response'])
  accepted[fact['id']]=entry['state']=='ACCEPTED'
  if typ=='object':
   clcounts=sum(sample['valid'] and maps[si].get(row['id']) is not None and next((n.get('classification') for n in sample['graph']['object_nodes'] if n['id']==maps[si].get(row['id'])),None)==row.get('classification') for si,sample in enumerate(samples))
   entry.update(classification=row.get('classification'),classification_occurrences=clcounts,classification_consistent=clcounts>=cfg['minimum_sample_occurrences'])
  rows.append(entry);save(folder/'ledger.json',rows);append(Path(cfg['work_root'])/'NATIVE_VERIFICATION_EVENTS.jsonl',entry)
 for i,claim in enumerate(g.get('unresolved_relation_claims',[])+g.get('postprocessing',{}).get('still_undecoded_raw_groups',[])):
  e={'scope':scope,'fact_id':'unresolved_'+str(i),'fact_type':'unresolved_relation_claim','candidate_content':claim,'state':'UNRESOLVED_PARSE_OR_ENDPOINT','visual_request_id':None,'frequency':None,'fixed_denominator':N,'reason':'No fact invented to fill missing endpoint or ambiguous tuple'}
  rows.append(e);append(Path(cfg['work_root'])/'NATIVE_VERIFICATION_EVENTS.jsonl',e)
 save(folder/'ledger.json',rows)
 # Known-case visibility is examined even when frequency rejects, but NOT relabelled main native acceptance.
 for node in g['object_nodes']:
  if accepted.get(node['id']):continue
  prompt='For the given video, determine if ['+node['referent']+'] truly exists in the given video. Just output Yes, No, or Uncertain.'
  rt.mode='video';r=rt.ask(media,[],prompt,role='diagnostic_presence_outside_frequency',seed=cfg['seed'],max_tokens=32,temperature=0,owner=scope+':'+node['id']);aux_rows.append({'scope':scope,'object_id':node['id'],'verdict':verdict(r['raw_response']),'request_id':r['request_id'],'scope_note':'diagnostic outside frequency gate, NOT a faithful main accepted fact and cannot override main status'})
 save(folder/'diagnostic_presence.json',aux_rows)
 vg=copy.deepcopy(g);vg['object_nodes']=[n for n in g['object_nodes'] if accepted[n['id']]];vg['attribute_nodes']=[a for a in g['attribute_nodes'] if accepted[a['id']]];vg['relation_edges']=[e for e in g['relation_edges'] if accepted[e['id']]];vg['attribute_edges']=[e for e in g['attribute_edges'] if accepted.get(e['attribute_id']) and accepted.get(e['subject_id'])];vg.update(native_verification_status='COMPLETED_WITH_EXPLICIT_PROMPT_RECONSTRUCTION',scope=scope,not_complete_G_step=True,verification_ledger_file=str(folder/'ledger.json'))
 save(folder/'FSG_verified.json',vg);save(folder/'post_snapshot.json',{'state':'COMPLETED' if all(x['valid'] for x in samples) else 'PARTIAL','candidate_sha256':hashlib.sha256(json.dumps(g,sort_keys=True).encode()).hexdigest(),'accepted_ids':[x for x in accepted if accepted[x]],'unavailable_ids':[x for x in accepted if not accepted[x]],'full_STSG':False})
 for typ in ['object','attribute','relation']:
  subset=[x for x in rows if x['fact_type']==typ];emit('native_verify_type',scope=scope,type=typ,candidates=len(subset),accepted=sum(x['state']=='ACCEPTED' for x in subset),states={st:sum(x['state']==st for x in subset) for st in sorted({x['state'] for x in subset})})
 save(statefile,{'state':'COMPLETED' if all(x['valid'] for x in samples) else 'PARTIAL','scope':scope,'candidate_facts':len(rows),'accepted':sum(accepted.values()),'independent_truth_available':False});return vg,rows
