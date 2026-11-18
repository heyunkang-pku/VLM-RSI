"""Explicit multi-time engineering adaptation, preserves STEP-S1 baseline."""
import os,copy,sys,subprocess,shutil,time
from pathlib import Path
from step_six.common import *
from four_group import native_batch,pipeline,routes_v2
BASE=Path('/scratch/haozhe/.cache/vlm-rsi/four-group/step-four-group-unfiltered-route-comparison-old3/ae437383-088d-46f8-9570-0fe147b646c5')
def multi_indices(s1):
 extra={round(c['start_source_index']+i*(c['end_source_index_exclusive']-c['start_source_index']-1)/3) for c in s1['scenes'] for i in range(4)}
 return sorted(set(s1['selected_keyframe_source_indices'])|extra)
def prepare_engineering(cfg,folder):
 vid=cfg['video']['video_id'];source=BASE/'native/videos'/vid/'S1';shutil.copytree(source,folder/'S1',dirs_exist_ok=True);s1=j(folder/'S1/manifest.json');save(folder/'S1/STEP_BASELINE_MANIFEST_UNCHANGED.json',s1)
 new=multi_indices(s1);old=s1['selected_keyframe_source_indices'];s1.update(selected_keyframe_source_indices=new,engineering_adaptation='four equally spaced source-index times per native scene UNION original keyframes; no model-dependent replacement',STEP_baseline_selected_keyframes=old)
 save(folder/'S1/manifest.json',s1);return s1

def main():
 # Reserve GPUs only after paired53 finishes; waits do not launch inference.
 cfg=j('config/four_group.json');root=Path('/scratch/haozhe/.cache/vlm-rsi/multitime-engineering')/os.environ['ORX_RUN_ID'];root.mkdir(parents=True,exist_ok=True);cfg.update(work_root=str(root),protocol_version='MULTITIME-ENGINEERING-v1',extra_VQS_enabled=False)
 selected=j(BASE/'selection/SELECTION_FROZEN.json')['selected'];(root/'selection').mkdir(exist_ok=True);save(root/'selection/SELECTION_FROZEN.json',j(BASE/'selection/SELECTION_FROZEN.json'));save(root/'effective_config.json',cfg)
 # Freeze all per-scene times before any model request.
 plans=[]
 for v in selected:
  m=j(BASE/'native/videos'/v['video_id']/'S1/manifest.json');plans.append({'video_id':v['video_id'],'baseline_indices':m['selected_keyframe_source_indices'],'engineering_indices':multi_indices(m),'no_true_identity_assumed':True})
 save(root/'MULTITIME_PLAN_FROZEN.json',plans);emit('engineering_multitime_plan_frozen',videos=len(plans),frames=sum(len(p['engineering_indices']) for p in plans))
 # Baseline input alignment has priority. Wait for its supervisor status file,
 # rather than occupying GPUs with a competing experiment.
 from pathlib import Path as P
 gate=P('/scratch/haozhe/.orx/runs/d0bf4ad8-1db1-4229-ba08-47f4368c8fd9')
 # Persistent alignment SUMMARY is authoritative; no monitor-status guess.
 align=P('/scratch/haozhe/.cache/vlm-rsi/input-alignment/d0bf4ad8-1db1-4229-ba08-47f4368c8fd9/SUMMARY.json')
 while not align.exists():
  emit('engineering_waiting_for_alignment');time.sleep(30)
 native_batch.prepare=prepare_engineering
 original_prepare=native_batch.prepare_batch
 def reuse_prepare(c,nroot,selection):
  tasks=original_prepare(c,nroot,selection);reused=[]
  for t in tasks:
   source=BASE/'native/frames'/t['scope'];ip=source/'input_manifest.json'
   if not ip.exists() or not (source/'verification/STATE.json').exists():continue
   previous=j(ip);current=t['media'];finger=lambda m:[m['calibration_view']['sha256']]+[f['sha256'] for f in m['class_video_views']]
   if finger(previous)!=finger(current):continue
   shutil.copytree(source,Path(t['folder']),dirs_exist_ok=True);reused.append({'scope':t['scope'],'source':str(source),'actual_input_hashes_equal':True,'input_manifest_sha256':filehash(ip),'old_partial_retained':j(source/'STATE.json')})
  save(nroot/'REUSED_BASELINE_FRAMES.json',reused);return tasks
 native_batch.prepare_batch=reuse_prepare
 native_batch.execute(cfg,root/'native',selected)
 pipeline.s_route=routes_v2.s_route;pipeline.p_route=routes_v2.p_route;pipeline.graph_questions(cfg,root,selected)
 summary={'phase':'NEW_GRAPH_AND_QA_V2_FROZEN','engineering_adaptation':True,'not_official_STEP_sampling':True,'videos':len(selected),'S_questions':len(rows(root/'S_FROZEN_QA.jsonl')),'P_questions':len(rows(root/'P_FROZEN_QA.jsonl')),'cost':cost(root),'VQS_calls':0,'training':False,'old53_unchanged':True,'next':'new questions frozen; separate paired public input/voting rules required before any comparison to old53'};save(root/'SUMMARY.json',summary);emit('multitime_engineering_summary',**summary)
if __name__=='__main__':main()
