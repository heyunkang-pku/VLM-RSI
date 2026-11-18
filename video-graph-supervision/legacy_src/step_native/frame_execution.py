"""Freeze clip-local inputs, execute native FSG replicates, verify globally."""
import copy,json,traceback
from pathlib import Path
from stsg_pilot.runtime import save,emit
from stsg_pilot.media import sha_file
from .calibration import prepare_inputs,run_chain
from .native_verification import verify

def candidate_output_failure(error):
 """Only declared model-output failures are local; runtime faults still abort."""
 return (isinstance(error,RuntimeError) and str(error).startswith('OUTPUT_TOKEN_CAP_HIT:')) or (isinstance(error,ValueError) and str(error) in {'OBJECT_LIST_NOT_RECOGNIZED','EMPTY_OBJECT_CLASS','INSTANCE_QUANTITY_NOT_RECOGNIZED','INSTANCE_ROWS_QUANTITY_MISMATCH'})

def freeze_video_media(cfg,video_record,root):
 import av
 folder=Path(video_record['folder']);s1=json.loads((folder/'S1/manifest.json').read_text());clock=json.loads((folder/'S1/frame_clock.json').read_text());sources={f['source_index']:f for f in s1['frames']};tasks=[]
 for index in video_record['chosen_keyframes']:
  clip=next(c for c in s1['scenes'] if c['start_source_index']<=index<c['end_source_index_exclusive']);a,b=clip['start_source_index'],clip['end_source_index_exclusive'];n=min(cfg['class_video_frame_cap'],b-a);context=sorted({round(a+i*(b-a-1)/max(1,n-1)) for i in range(n)});missing=set(context+[index])-sources.keys()
  if missing:
   with av.open(s1['video']['path']) as c:
    for i,frame in enumerate(c.decode(video=0)):
     if i not in missing:continue
     record=clock[i];assert frame.pts==record['pts'];file=f'S1/source_frames/src_{i:06d}.png';dest=folder/file;dest.parent.mkdir(parents=True,exist_ok=True);frame.to_image().convert('RGB').save(dest);sources[i]={**record,'frame_id':f'src_{i:06d}','file':file,'sha256':sha_file(dest)}
  local=copy.deepcopy(s1);local['calibration_source_index']=index;local['frames']=[dict(sources[i],class_video_context=i in context,selected_keyframe=i==index) for i in sorted(set(context+[index]))];media=prepare_inputs(cfg,folder,local);media.update(_root=str(folder),clip_id=clip['clip_id'],clip_intervals=[[clip['start_sec'],clip['end_sec']]])
  task={'scope':s1['video']['video_id']+'/'+media['calibration_view']['frame_id'],'folder':str(root/'frames'/s1['video']['video_id']/media['calibration_view']['frame_id']),'media':media,'candidate_existing':False};tasks.append(task)
 save(root/'frozen_inputs'/f'{s1["video"]["video_id"]}.json',{'video_hash':s1['video']['sha256'],'selection_record':video_record,'all_tasks':tasks,'frozen_before_video_model_calls':True});return tasks

def process_frame(rt,cfg,task):
 folder=Path(task['folder']);folder.mkdir(parents=True,exist_ok=True);state=folder/'STATE.json'
 if state.exists() and json.loads(state.read_text())['state']=='CANDIDATE_UNAVAILABLE':
  emit('frame_resume_candidate_unavailable',scope=task['scope']);return
 if (folder/'verification/STATE.json').exists() and json.loads((folder/'verification/STATE.json').read_text())['state'] in ['COMPLETED','PARTIAL']:
  emit('frame_resume_completed',scope=task['scope']);return
 save(state,{'state':'RUNNING','scope':task['scope'],'candidate_existing':task['candidate_existing']});media=task['media'];save(folder/'input_manifest.json',media)
 try:
  if task['candidate_existing']:g=json.loads(Path(cfg['baseline_candidate_file']).read_text());save(folder/'candidate/FSG_frozen.json',g)
  else:
   frozen=folder/'candidate/FSG_frozen.json'
   if frozen.exists():g=json.loads(frozen.read_text())
   else:
    cc=dict(cfg,seed=cfg['candidate_seed'],chain_temperature=0)
    try:g=run_chain(cc,folder/'candidate',rt,media)
    except Exception as e:
     if not candidate_output_failure(e):raise
     save(state,{'state':'CANDIDATE_UNAVAILABLE','scope':task['scope'],'stage':'candidate_chain','error':repr(e),'traceback':traceback.format_exc(),'retained_in_keyframe_denominator':True,'resampling':False,'retry_count':0,'native_verification':'NOT_APPLICABLE_INCOMPLETE_CANDIDATE'})
     emit('candidate_output_unavailable',scope=task['scope'],error=repr(e));return
    save(frozen,g)
  samples=[]
  for i,seed in enumerate(cfg['sampling_seeds']):
   sp=folder/'samples'/str(i);receipt=sp/'RECEIPT.json'
   if receipt.exists():sample=json.loads(receipt.read_text())
   else:
    cc=dict(cfg,seed=seed,chain_temperature=cfg['sampling_temperature'])
    try:sg=run_chain(cc,sp,rt,media);sample={'sample_id':task['scope']+':seed'+str(seed),'seed':seed,'valid':bool(sg.get('prompt_chain_completed')),'graph':sg}
    except Exception as e:sample={'sample_id':task['scope']+':seed'+str(seed),'seed':seed,'valid':False,'error':repr(e),'traceback':traceback.format_exc()}
    save(receipt,sample)
   samples.append(sample);emit('sample_completed',scope=task['scope'],sample=i,valid=sample['valid'])
  vg,ledger=verify(rt,cfg,folder/'verification',g,media,samples,task['scope']);save(state,{'state':'COMPLETED' if all(x['valid'] for x in samples) else 'PARTIAL','scope':task['scope'],'valid_samples':sum(x['valid'] for x in samples),'fixed_denominator':cfg['sampling_replicas'],'candidate_objects':len(g['object_nodes']),'available_objects':len(vg['object_nodes'])})
 except Exception as e:save(state,{'state':'FAILED','scope':task['scope'],'error':repr(e),'traceback':traceback.format_exc()});raise
