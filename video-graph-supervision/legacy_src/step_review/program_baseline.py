"""Freeze automatic program QA before isolated, sealed unadapted Base calls."""
import argparse,json,os,hashlib,time,subprocess,sys
from pathlib import Path
from stsg_pilot.runtime import save,emit,append
from stsg_pilot.media import sha_file
from step_native.checkpoint_runtime import CheckpointRuntime
from .program_adapter import main_candidates,execute,select,h
V1=Path('/scratch/haozhe/.cache/vlm-rsi/step-recovery/step-v1-bounded-truncation-recovery-with-immutab/V1')
def j(p):return json.loads(p.read_text())
def jsonl(p,rows):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
def freeze_media(root):
 from PIL import Image
 from transformers.models.qwen2_vl.image_processing_qwen2_vl import smart_resize
 pools={};meta={}
 for f in sorted((V1/'frozen_inputs').glob('*.json')):
  for task in j(f)['all_tasks']:
   m=task['media'];vid=m['video']['video_id'];meta[vid]=m;pool=pools.setdefault(vid,{})
   for q in [m['calibration_view']]+m['class_video_views']:
    # Prefer the existing video-sized view, otherwise resize the frozen image only.
    old=pool.get(q['source_index'])
    if old is None or q.get('resize_pixels_cap',999999)<old.get('resize_pixels_cap',999999):pool[q['source_index']]={**q,'file':str(Path(m['_root'])/q['file'])}
 result={}
 for vid,pool in sorted(pools.items()):
  ids=sorted(pool);n=min(32,len(ids));chosen=[ids[round(i*(len(ids)-1)/max(1,n-1))] for i in range(n)];frames=[]
  for ix in chosen:
   old=pool[ix];src=Path(old['file']);assert sha_file(src)==old['sha256'];dest=root/'inputs'/vid/(old['frame_id']+'.png');dest.parent.mkdir(parents=True,exist_ok=True)
   with Image.open(src) as im:
    rh,rw=smart_resize(im.height,im.width,factor=32,min_pixels=4096,max_pixels=50176);im.convert('RGB').resize((rw,rh),Image.Resampling.BICUBIC).save(dest)
   frames.append({**old,'file':str(dest),'sha256':sha_file(dest),'parent_pixel_sha256':old['sha256'],'resize_hw':[rh,rw]})
  m=meta[vid];result[vid]={'video':m['video'],'source_frames_decoded':m['source_frames_decoded'],'calibration_view':frames[0],'class_video_views':frames,'clip_intervals':[[0,max(x['time_sec'] for x in pool.values())]],'_root':str(root),'existing_frame_pool_size':len(pool),'selected_view_count':len(frames),'input_rule':'uniform chronological ranks of already frozen unique source frames; no source decode or graph facts in input'}
 save(root/'BASE_VIDEO_INPUTS_FROZEN.json',result);return result

def prepare(root):
 state=j(V1/'STATE.json');assert state['state']=='COMPLETED_V1'
 temporal=V1/'P3'/state['run'];graph=j(temporal/'STSG_partial.json');pairs=j(temporal/'PAIR_LEDGER.json');ledger=[json.loads(x) for x in (V1/'NATIVE_VERIFICATION_LEDGER.jsonl').read_text().splitlines()];candidates=main_candidates(graph,ledger,pairs,'V1')
 for x in candidates:
  x['execution']=execute(x,ledger,pairs,graph);times=[];entities=[]
  for d in x['dependencies']:
   if 'fact_key' not in d:continue
   scope,fid,_=d['fact_key'].rsplit('/',2);r=next(q for q in ledger if q['scope']==scope and q['fact_id']==fid);times.append(r['source_keyframe']['time_sec'])
   if r['fact_type']=='object':entities.append({'scope':scope,'fact_id':fid,'label':r['candidate_content']['label'],'referent':r['candidate_content']['referent']})
  x['time_range_sec']=[min(times),max(times)] if times else None;x['entity_references']=entities
 selected=select(candidates);assert all(x['execution']['status']=='ANSWERED' for x in selected)
 jsonl(root/'PROGRAM_CANDIDATE_POOL.jsonl',candidates);jsonl(root/'FROZEN_PROGRAM_QA.jsonl',selected)
 prompts=[{'question_id':q['question_id'],'video_id':q['video_id'],'question':q['question']} for q in selected];jsonl(root/'BASE_PROMPTS_ONLY.jsonl',prompts);freeze_media(root)
 save(root/'QUESTION_FREEZE_MANIFEST.json',{'graph_version':'V1','graph_sha256':sha_file(temporal/'STSG_partial.json'),'ledger_sha256':sha_file(V1/'NATIVE_VERIFICATION_LEDGER.jsonl'),'pairs_sha256':sha_file(temporal/'PAIR_LEDGER.json'),'rules_sha256':sha_file(Path('config/step_program_rules.json')),'candidate_pool_sha256':sha_file(root/'PROGRAM_CANDIDATE_POOL.jsonl'),'frozen_questions_sha256':sha_file(root/'FROZEN_PROGRAM_QA.jsonl'),'base_prompts_sha256':sha_file(root/'BASE_PROMPTS_ONLY.jsonl'),'base_inputs_sha256':sha_file(root/'BASE_VIDEO_INPUTS_FROZEN.json'),'frozen_before_Base_calls':True,'human_labels_read':False})
 from collections import Counter
 save(root/'PROGRAM_QA_YIELD.json',{'candidate_programs':len(candidates),'status_counts':dict(Counter(x['execution']['status'] for x in candidates)),'abstention_reasons':dict(Counter(x['execution'].get('reason') for x in candidates if x['execution']['status']=='ABSTAIN')),'selected_main':len(selected),'selected_types':dict(Counter(x['question_type'] for x in selected)),'by_video_selected':dict(Counter(x['video_id'] for x in selected)),'automatic_graph_not_human_corrected':True,'action_order_main':sum(x['question_type']=='motion_order_diagnostic' for x in selected),'selection_did_not_inspect_human_or_Base_answers':True});emit('program_question_freeze',**j(root/'PROGRAM_QA_YIELD.json'))

def base(cfg):
 root=Path(cfg['work_root']);os.environ['SMOKE_DEADLINE']='inf'
 for line in subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines():
  i,mem,u=line.split(',')
  if float(mem)>40000 and float(u)<5:os.environ['CUDA_VISIBLE_DEVICES']=i.strip();break
 else:raise RuntimeError('NO_IDLE_A40')
 # This process reads questions and media only, never graph, candidate answers or human labels.
 qs=[json.loads(x) for x in (root/'BASE_PROMPTS_ONLY.jsonl').read_text().splitlines()];media=j(root/'BASE_VIDEO_INPUTS_FROZEN.json');rt=CheckpointRuntime(cfg,root/'base_runtime');rt.mode='video';rows=[]
 try:
  for q in qs:
   prompt='Answer the following question directly using the supplied video. Give a concise answer; do not guess invisible facts. If the video does not support a unique answer, say uncertain.\nQuestion: '+q['question'];r=rt.ask(media[q['video_id']],[],prompt,role='unadapted_Base_direct_answer',seed=2026110102,max_tokens=256,temperature=0,owner=q['question_id']);row={'question_id':q['question_id'],'video_id':q['video_id'],'raw_answer':r['raw_response'],'request_id':r['request_id'],'model_kind':'unadapted pretrained instruction model, NOT Video-Zero checkpoint','model_revision':cfg['model_revision'],'output_hit_cap':r['output_hit_cap'],'human_comparison':'PENDING','sealed_before_human_labels':True};rows.append(row);jsonl(root/'BASE_SOLVER_OUTPUTS.jsonl',rows)
 finally:
  requests=[j(p) for p in (root/'request_cache').glob('*.json')];save(root/'BASE_COST.json',{'completed_calls':len(requests),'input_tokens':sum(x['input_tokens'] for x in requests),'output_tokens':sum(x['output_tokens'] for x in requests),'device_seconds':sum(x['model_device_wall_seconds'] for x in requests),'gpu_wall_seconds':time.monotonic()-rt.started,'gpu_hours':(time.monotonic()-rt.started)/3600,'accuracy':'PENDING_HUMAN'});emit('Base_sealed_summary',**j(root/'BASE_COST.json'))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--base-worker');a=ap.parse_args()
 if a.base_worker:base(j(Path(a.base_worker)));return
 root=V1/'program_QA'/os.environ['ORX_RUN_ID'];root.mkdir(parents=True);prepare(root);cfg=j(Path('config/step_next.json'));cfg.update(work_root=str(root),output_root=str(root),protocol_version='STEP-V1-BASE-DIRECT-v1',source_commit=os.environ['ORX_COMMIT'],request_timeout_seconds=420,stage='SEALED_UNADAPTED_BASE',training=False)
 save(root/'BASE_SOLVER_CONFIG.json',cfg);subprocess.run([sys.executable,'-m','step_review.program_baseline','--base-worker',str(root/'BASE_SOLVER_CONFIG.json')],check=True);save(root/'STATE.json',{'state':'COMPLETED','human_labels':'PENDING','run':os.environ['ORX_RUN_ID']})
if __name__=='__main__':main()
