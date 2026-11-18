"""Conditional STEP A.1 temporal modules; no legacy parser, QA or VQS.
Pair enumeration, clip context and ambiguity guards are explicit reconstruction.
"""
import argparse,copy,json,os,re,time,resource
from pathlib import Path
from stsg_pilot.runtime import save,emit
from stsg_pilot.media import sha_file
from .checkpoint_runtime import CheckpointRuntime
from .native_verification import verdict

IDENTITY="For the given video, determine if [{left}] in the first half and [{right}] in the second half are the same object. Just output 'Yes' or 'No'."
BRIDGE="For the given video, determine if [{left}] in the first clip and [{right}] in the second clip are the same object. Just output 'Yes' or 'No'."
ACTION="Given the same object [{left}] in the first half video and [{right}] in the second half video, describe the action of this object in the video."
EXTRACT_ACTION='''For the given sentence, the task is to extract meaningful action for the given object. The action should be described using a verb or verb phrase. Let's take a few examples to understand how to extract.
Question: Given the sentence “The man walked on the street,” extract meaningful action for the object “man”.
Answer: [“action”:“walking on the street”]
Question: Given the sentence “The cat jumped on the bed,” extract meaningful action for the object “cat”.
Answer: [“action”:“jumping on the bed”]
Question: Given the sentence “The dog chased the ball in the park,” extract meaningful action for the object “dog”.
Answer: [“action”:“chasing the ball in the park”]
Please answer the following question.
Question: Given the sentence “[{narrative}],” extract meaningful action for the object “[{label}]”.
Answer:'''
EXTRACT_PREDICATE='''For the given action, extract the predicate and object. The predicate is a verb or verb phrase, and the object is the entity or noun that is affected by the action. Let's take a few examples to understand how to extract.
Question: Given the action “walking”, extract the predicate and object.
Answer: [“predicate”:“walking”, “object”:“None”]
Question: Given the action “jumping on the bed”, extract the predicate and object.
Answer: [“predicate”:“jumping on”, “object”:“bed”]
Question: Given the action “sitting on the chair”, extract the predicate and object.
Answer: [“predicate”:“sitting on”, “object”:“chair”]
Please answer the following question.
Question: Given the action “[{action}]”, extract the predicate and object.
Answer:'''

def text_field(text,key):
 values=re.findall('["“]'+key+r'["”]\s*:\s*["“]([^"”]+)["”]',text)
 if len(values)!=1 or not values[0].strip():raise ValueError('AMBIGUOUS_OR_MISSING_'+key)
 return values[0].strip()

def unique_yes(rows):
 """Keep only one-to-one yes mappings, never choose among duplicate instances."""
 yes=[r for r in rows if r['verdict']=='YES'];a={};b={}
 for r in yes:a[r['left']]=a.get(r['left'],0)+1;b[r['right']]=b.get(r['right'],0)+1
 return {r['id'] for r in yes if a[r['left']]==b[r['right']]==1}

def static_union(nodes,pairs):
 parent={n:n for n in nodes};members={n:{n} for n in nodes};rejected=[]
 def find(n):
  while parent[n]!=n:n=parent[n]
  return n
 for pid,a,b in pairs:
  a,b=find(a),find(b)
  if a==b:continue
  frames_a={nodes[x]['scope'] for x in members[a]};frames_b={nodes[x]['scope'] for x in members[b]}
  if frames_a&frames_b:rejected.append(pid);continue
  parent[b]=a;members[a]|=members.pop(b)
 return [sorted(x) for x in members.values()],rejected

def freeze(cfg,root):
 src=Path(cfg['parent_work_root']);alltasks=[]
 for p in sorted((src/'frozen_inputs').glob('*.json')):
  j=json.loads(p.read_text());alltasks+=j.get('all_tasks',[j] if 'scope' in j else [])
 nodes={};tasks={};plans=[];frames=[]
 for task in alltasks:
  scope=task['scope'];tasks[scope]=task;folder=Path(task['folder']);m=task['media'];lp=folder/'verification/ledger.json';accepted=[]
  if lp.exists():
   for row in json.loads(lp.read_text()):
    if row['fact_type']=='object' and row['state']=='ACCEPTED' and row.get('classification_consistent') and row.get('classification') in ['static','dynamic']:
     q=scope+'/'+row['fact_id'];nodes[q]={'id':q,'scope':scope,'clip_id':m['clip_id'],'source_frame':m['calibration_view'],'object':row['candidate_content'],'classification':row['classification'],'ledger':str(lp),'ledger_sha256':sha_file(lp),'sampling_incomplete':row.get('sampling_incomplete',False)};accepted.append(q)
  frames.append({'scope':scope,'video_id':m['video']['video_id'],'clip_id':m['clip_id'],'source_index':m['calibration_view']['source_index'],'objects':accepted,'frame_state':json.loads((folder/'STATE.json').read_text())['state']})
 for vid in sorted({x['video_id'] for x in frames}):
  ordered=sorted([x for x in frames if x['video_id']==vid],key=lambda x:x['source_index'])
  for a,b in zip(ordered,ordered[1:]):
   kind='within_clip' if a['clip_id']==b['clip_id'] else 'cross_clip'
   row={'id':vid+'/'+a['scope'].split('/')[-1]+'__'+b['scope'].split('/')[-1],'video_id':vid,'kind':kind,'left_scope':a['scope'],'right_scope':b['scope'],'left_objects':a['objects'],'right_objects':b['objects'],'state':'ELIGIBLE' if a['objects'] and b['objects'] else 'NO_ELIGIBLE_ENDPOINTS','identity_candidates':[]}
   for l in a['objects']:
    for r in b['objects']:row['identity_candidates'].append({'id':row['id']+'/'+l.split('/')[-1]+'__'+r.split('/')[-1],'left':l,'right':r})
   plans.append(row)
 save(root/'FROZEN_PLAN.json',{'parent_source_root':str(src),'nodes':nodes,'frames':frames,'pairs':plans,'tasks':tasks,'pair_rule':'consecutive originally selected keyframes; adjacent clip boundary only, no skipping failed endpoints; full cartesian accepted classified instances; no class-name identity heuristic','frozen_before_calls':True});return nodes,tasks,plans

def context(root,taska,taskb,pid):
 ma,mb=taska['media'],taskb['media']
 if ma.get('public32'):
  left,right=ma['calibration_view'],mb['calibration_view'];fs=sorted({f['source_index']:f for f in ma['public_frames']+mb['public_frames']}.values(),key=lambda f:f['source_index']);a=next(i for i,f in enumerate(fs) if f['source_index']==left['source_index']);b=next(i for i,f in enumerate(fs) if f['source_index']==right['source_index']);chosen=fs[max(0,a-1):min(len(fs),b+2)];media=copy.deepcopy(ma);media.update(class_video_views=chosen,clip_intervals=[[chosen[0]['time_sec'],chosen[-1]['time_sec']]],identity_endpoint_frame_ids=[left['frame_id'],right['frame_id']]);save(root/'pair_inputs'/(pid.replace('/','_')+'.json'),media);return media
 from PIL import Image
 from transformers.models.qwen2_vl.image_processing_qwen2_vl import smart_resize
 left=ma['calibration_view'];right=mb['calibration_view'];lo,hi=left['time_sec'],right['time_sec'];pool={}
 for m in [ma,mb]:
  for f in m['class_video_views']:
   if lo<=f['time_sec']<=hi:pool[f['source_index']]={**f,'file':str(Path(m['_root'])/f['file'])}
 for m,f in [(ma,left),(mb,right)]:
  p=root/'inputs'/('video_'+m['video']['video_id']+'_'+f['frame_id']+'.png');p.parent.mkdir(parents=True,exist_ok=True)
  if not p.exists():
   with Image.open(Path(m['_root'])/f['file']) as im:
    h,w=smart_resize(im.height,im.width,factor=32,min_pixels=4096,max_pixels=50176);im.convert('RGB').resize((w,h),Image.Resampling.BICUBIC).save(p)
  pool[f['source_index']]={**f,'file':str(p),'sha256':sha_file(p),'resize_pixels_cap':50176}
 mids=sorted(i for i in pool if i not in [left['source_index'],right['source_index']]);k=min(14,len(mids));chosen=sorted({left['source_index'],right['source_index']}|{mids[round(i*(len(mids)-1)/max(1,k-1))] for i in range(k)})
 media=copy.deepcopy(ma);media.update(_root=str(root),class_video_views=[pool[i] for i in chosen],clip_intervals=ma['clip_intervals'] if ma['clip_id']==mb['clip_id'] else ma['clip_intervals']+mb['clip_intervals']);save(root/'pair_inputs'/(pid.replace('/','_')+'.json'),media);return media


def graph_view(tasks,groups):
 canonical={n:members[0] for members in groups for n in members};objs={};attrs=[];has=[];rels=[];snapshots=[]
 for scope,task in tasks.items():
  path=Path(task['folder'])/'verification/FSG_verified.json'
  if not path.exists():continue
  g=json.loads(path.read_text());snapshots.append({'scope':scope,'path':str(path),'sha256':sha_file(path),'effective_video_id':task['media']['video']['video_id'],'source_video_id_annotation':g.get('video_id')})
  def objid(local):
   qualified=scope+'/'+local;return canonical.get(qualified,qualified)
  for o in g['object_nodes']:
   q=scope+'/'+o['id'];c=objid(o['id']);n=objs.setdefault(c,{'id':c,'member_source_ids':[],'source_objects':[]})
   n['member_source_ids'].append(q);n['source_objects'].append(o)
  for a in g['attribute_nodes']:attrs.append({**a,'id':scope+'/'+a['id'],'source_scope':scope,'effective_verification':'ACCEPTED','original_verification_annotation':a.get('verification')})
  for e in g['attribute_edges']:has.append({**e,'id':scope+'/'+e['id'],'subject_id':objid(e['subject_id']),'attribute_id':scope+'/'+e['attribute_id'],'source_scope':scope})
  for e in g['relation_edges']:rels.append({**e,'id':scope+'/'+e['id'],'subject_id':objid(e['subject_id']),'object_id':objid(e['object_id']),'source_scope':scope,'effective_verification':'ACCEPTED','original_verification_annotation':e.get('verification')})
 assert all(e['subject_id'] in objs and e['object_id'] in objs for e in rels)
 assert all(e['subject_id'] in objs and e['attribute_id'] in {a['id'] for a in attrs} for e in has)
 return {'object_nodes':list(objs.values()),'attribute_nodes':attrs,'attribute_edges':has,'relation_edges':rels,'source_snapshots':snapshots,'canonical_object_ids':canonical,'conflicting_attributes_preserved':True}

def execute(cfg,root):
 nodes,tasks,plans=freeze(cfg,root);rt=CheckpointRuntime(cfg,root/'runtime');results=[];statics=[];motions=[];refs=[];begin=time.monotonic()
 try:
  for plan in plans:
   if plan['state']!='ELIGIBLE':results.append(plan);save(root/'PAIR_LEDGER.json',results);continue
   media=context(root,tasks[plan['left_scope']],tasks[plan['right_scope']],plan['id']);rows=[]
   def call(role,mode,prompt,owner):
    rt.mode=mode;r=rt.ask(media,[],prompt,role=role,seed=cfg['seed'],temperature=0,max_tokens=cfg['max_tokens'],owner=owner)
    if r['output_hit_cap']:raise ValueError('OUTPUT_TOKEN_CAP_HIT:'+role)
    return r
   for pair in plan['identity_candidates']:
    ln,rn=nodes[pair['left']],nodes[pair['right']];template=IDENTITY if plan['kind']=='within_clip' else BRIDGE
    try:
     r=call('native_temporal_identity_'+plan['kind'],'video',template.format(left=ln['object']['referent'],right=rn['object']['referent']),pair['id']);rows.append({**pair,'verdict':verdict(r['raw_response']),'identity_request_id':r['request_id'],'classification_left':ln['classification'],'classification_right':rn['classification']})
    except (ValueError,TimeoutError) as e:
     rows.append({**pair,'verdict':'UNCERTAIN','identity_request_id':None,'classification_left':ln['classification'],'classification_right':rn['classification'],'failure':repr(e)})
   allowed=unique_yes(rows)
   for row in rows:
    row['state']='IDENTITY_REJECTED' if row['verdict']=='NO' else 'UNRESOLVED_IDENTITY'
    if row['id'] not in allowed:continue
    if plan['kind']=='cross_clip':row['state']='REFERENCE_CREATED';refs.append({**row,'type':'Reference','source':row['left'],'target':row['right'],'independent_truth':'NOT_EVALUATED'});continue
    if row['classification_left']!=row['classification_right']:row['state']='UNRESOLVED_CLASSIFICATION_CONFLICT';continue
    if row['classification_left']=='static':row['state']='STATIC_MERGE_PROPOSED';statics.append((row['id'],row['left'],row['right']));continue
    ln,rn=nodes[row['left']],nodes[row['right']]
    if media.get('public32') and len({f['source_index'] for f in media['class_video_views']})<3:
     row['state']='UNRESOLVED_MOTION_INSUFFICIENT_MULTIFRAME_EVIDENCE';continue
    try:
     d=call('native_motion_description','video',ACTION.format(left=ln['object']['referent'],right=rn['object']['referent']),row['id'])
     a=call('native_motion_action','text',EXTRACT_ACTION.format(narrative=d['raw_response'],label=ln['object']['label']),row['id']);action=text_field(a['raw_response'],'action')
     p=call('native_motion_predicate','text',EXTRACT_PREDICATE.format(action=action),row['id']);predicate=text_field(p['raw_response'],'predicate');affected=text_field(p['raw_response'],'object')
     row.update(state='MOTION_EXTRACTED_NOT_INDEPENDENTLY_VALIDATED',action=action,predicate=predicate,affected_object_text=affected,source_request_ids=[d['request_id'],a['request_id'],p['request_id']]);motions.append({**row,'type':'Motion','source':row['left'],'target':row['right'],'observation_interval_sec':[media['class_video_views'][0]['time_sec'],media['class_video_views'][-1]['time_sec']],'necessary_source_frames':[f['frame_id'] for f in media['class_video_views']],'identity_endpoint_frames':[ln['source_frame']['frame_id'],rn['source_frame']['frame_id']],'time_interpretation':'endpoint observation interval, not event boundary annotation','affected_object_text_is_not_graph_reference':True,'post_motion_native_verification':'NOT_EXECUTED_NO_DISCLOSED_SEPARATE_STAGE','usable_for_program_QA':False})
    except (ValueError,TimeoutError) as e:row.update(state='UNRESOLVED_MOTION_OUTPUT',error=str(e))
   results.append({**plan,'results':rows});save(root/'PAIR_LEDGER.json',results);emit('temporal_pair_completed',pair=plan['id'],states={s:sum(x['state']==s for x in rows) for s in {x['state'] for x in rows}})
  groups,rejected=static_union(nodes,statics)
  for p in results:
   for r in p.get('results',[]):
    if r['state']=='STATIC_MERGE_PROPOSED':r['state']='UNRESOLVED_TRANSITIVE_IDENTITY_CONFLICT' if r['id'] in rejected else 'STATIC_MERGED'
  save(root/'PAIR_LEDGER.json',results);save(root/'STSG_partial.json',{'status':'PARTIAL','merged_fsg_view':graph_view(tasks,groups),'source_nodes':nodes,'static_identity_groups':groups,'static_proposals_rejected':rejected,'static_group_fact_preservation':'All original objects, attributes and spatial edges retained at source FSG paths and IDs; conflicts NOT overwritten','motion_edges':motions,'reference_edges':refs,'missing_modules':['clip Event Edge topology/prompt underdetermined','independent temporal fact validation'],'complete_G_step':False,'QA_executed':False})
 finally:
  requests=[json.loads(p.read_text()) for p in (root/'request_cache').glob('*.json')];save(root/'summary.json',{'calls':len(requests),'input_tokens':sum(r['input_tokens'] for r in requests),'output_tokens':sum(r['output_tokens'] for r in requests),'device_seconds':sum(r['model_device_wall_seconds'] for r in requests),'gpu_wall_seconds':time.monotonic()-rt.started,'gpu_hours':(time.monotonic()-rt.started)/3600,'cpu_user_seconds':resource.getrusage(resource.RUSAGE_SELF).ru_utime,'pairs_planned':len(plans),'pairs_processed':len(results),'motion_edges_extracted':len(motions),'reference_edges':len(refs),'static_proposals':len(statics),'training':False});emit('P3_summary',**json.loads((root/'summary.json').read_text()))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);a=ap.parse_args();cfg=json.loads(Path(a.config).read_text());root=Path(cfg['parent_work_root'])/'P3'/os.environ['ORX_RUN_ID'];root.mkdir(parents=True);cfg.update(work_root=str(root),output_root=str(root),source_commit=os.environ['ORX_COMMIT']);save(root/'effective_config.json',cfg);os.environ['SMOKE_DEADLINE']='inf'
 import subprocess
 for line in subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines():
  i,mem,u=line.split(',')
  if float(mem)>40000 and float(u)<5:os.environ['CUDA_VISIBLE_DEVICES']=i.strip();break
 else:raise RuntimeError('NO_IDLE_A40')
 execute(cfg,root)
if __name__=='__main__':main()
