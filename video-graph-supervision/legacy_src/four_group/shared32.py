"""Public32-first STEP adaptation; source of every visual observation frozen first."""
import argparse,copy,os,sys,subprocess,collections,concurrent.futures
from pathlib import Path
from step_six.common import *
from four_group import native_batch,routes_v2
from four_group.results import export_comparison
BASE=Path('/scratch/haozhe/.cache/vlm-rsi/four-group/step-four-group-unfiltered-route-comparison-old3/ae437383-088d-46f8-9570-0fe147b646c5')
def freeze_public(root):
 import shutil
 if (root/'PUBLIC32_FROZEN.json').exists():
  assert filehash(root/'PUBLIC32_FROZEN.json')==j(root/'PUBLIC32_HASH.json')['sha256'];return j(root/'PUBLIC32_FROZEN.json')
 media=copy.deepcopy(j(BASE/'VIDEO_INPUTS_FROZEN.json'));manifest={}
 for vid,m in media.items():
  fs=m['class_video_views'];assert len(fs)==32 and len({f['source_index'] for f in fs})==32
  for f in fs:
   src=Path(f['file']);assert filehash(src)==f['sha256'];dst=root/'public_pixels'/vid/src.name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst);f['file']=str(dst)
  m.update(_root='/',calibration_view=fs[0],public_frames=copy.deepcopy(fs),public32=True)
  manifest[vid]=m
 save(root/'PUBLIC32_FROZEN.json',manifest);save(root/'PUBLIC32_HASH.json',{'sha256':filehash(root/'PUBLIC32_FROZEN.json'),'baseline_source_sha256':filehash(BASE/'VIDEO_INPUTS_FROZEN.json'),'source':'old Solver32 before alignment; unchanged ordered pixel content'})
 return manifest

def prepare(cfg,root,selection):
 public=j(cfg['public_manifest']);tasks=[];records=[]
 for v in selection:
  vid=v['video_id'];m=public[vid];baseline=j(BASE/'native/videos'/vid/'S1/manifest.json');folder=root/'videos'/vid;folder.mkdir(parents=True,exist_ok=True);save(folder/'S1_BASELINE_READONLY.json',baseline)
  for frame in m['class_video_views']:
   clip=next(c for c in baseline['scenes'] if c['start_source_index']<=frame['source_index']<c['end_source_index_exclusive']);context=[f for f in m['class_video_views'] if clip['start_source_index']<=f['source_index']<clip['end_source_index_exclusive']];assert frame in context
   local=copy.deepcopy(m);local.update(calibration_view=frame,class_video_views=context,clip_id=clip['clip_id'],clip_intervals=[[context[0]['time_sec'],context[-1]['time_sec']]],public_frames=context)
   tasks.append({'scope':vid+'/'+frame['frame_id'],'folder':str(root/'frames'/vid/frame['frame_id']),'media':local,'candidate_existing':False})
  save(root/'frozen_inputs'/(vid+'.json'),{'all_tasks':[t for t in tasks if t['scope'].startswith(vid+'/')],'public_manifest_sha256':filehash(cfg['public_manifest']),'frozen_before_calls':True})
  records.append({'video_id':vid,'selected_keyframe_count':32,'status':'PUBLIC32_FROZEN','original_STEP_selection_preserved_separately':True})
 save(root/'VIDEO_PREPARATION.json',records);return tasks

def check_inputs(root,public,expect_frames):
 requests={}
 for p in root.rglob('requests.jsonl'):
  for r in rows(p):requests[r['request_id']]=r
 allowed={v:{f['frame_id']:(f['sha256'],f['time_sec']) for f in m['class_video_views']} for v,m in public.items()};violations=[]
 for r in requests.values():
  vid=r.get('video_id');seen=r.get('shown_frame_ids',[])
  for fid,h,t in zip(seen,r.get('frame_content_hashes',[]),r.get('actual_source_times_sec',[])):
   if vid not in allowed or allowed[vid].get(fid)!=(h,t):violations.append(r['request_id'])
  if r.get('input_mode')=='video' and len(seen)!=len(r.get('frame_content_hashes',[])):violations.append(r['request_id'])
 assert not violations,violations[:5]
 states=list((root/'native/frames').glob('*/*/STATE.json'));assert len(states)==expect_frames
 return {'visual_requests_checked':len(requests),'violations':violations,'frame_attempt_states':dict(collections.Counter(j(p)['state'] for p in states)),'all_frame_attempts_retained':len(states),'pixel_contract':'identical RGB PNG bytes, no resize for image/video; image/video temporal patching and Parser/Solver weight encoding differ; video odd count duplicate explicitly logged'}

def graph_qa(cfg,root,selection,public):
 from step_six.graph_routes import registry,clip_events
 n=root/'native';p3=n/'P3'/j(n/'STATE.json')['run'];graph=j(p3/'STSG_partial.json');pairs=j(p3/'PAIR_LEDGER.json');ledger=rows(n/'NATIVE_VERIFICATION_LEDGER.jsonl');tasks={}
 for f in (n/'frozen_inputs').glob('*.json'):
  for t in j(f)['all_tasks']:tasks[t['scope']]=t
 rt=make_runtime(cfg,root/'route_calls','shared32_QRA',choose_gpu())
 try:
  graph=clip_events(rt,root,graph,tasks,public);graph.update(graph_version='STEP-PUBLIC32-ADAPTATION-v1',public_manifest_sha256=filehash(cfg['public_manifest']));save(root/'GRAPH_SHARED_FROZEN.json',graph);save(root/'SOURCE_TEMPORAL_PAIRS.json',pairs);save(root/'SOURCE_NATIVE_LEDGER.json',ledger);facts=registry(ledger,pairs,graph,tasks);save(root/'FACT_REGISTRY.json',facts)
  with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
   future=pool.submit(routes_v2.p_route,root,graph,ledger,pairs,selection);sq=routes_v2.s_route(rt,root,graph,facts,public,selection);pq=future.result()
  jl(root/'SOLVER_QUESTIONS_ONLY.jsonl',[{k:q[k] for k in ['question_id','video_id','question','route']} for q in sq+pq]);save(root/'VIDEO_INPUTS_FROZEN.json',public);save(root/'FREEZE_MANIFEST.json',{n:filehash(root/n) for n in ['GRAPH_SHARED_FROZEN.json','S_FROZEN_QA.jsonl','P_FROZEN_QA.jsonl','SOLVER_QUESTIONS_ONLY.jsonl','VIDEO_INPUTS_FROZEN.json']})
 finally:allocation(rt,root/'route_calls')

def finalize(root,public):
 qs=rows(root/'S_FROZEN_QA.jsonl')+rows(root/'P_FROZEN_QA.jsonl');votes={}
 for p in root.glob('solver/shard_*/questions/*/VOTE.json'):
  v=j(p);votes[v['question_id']]=v
 assert len(votes)==len(qs)
 # Restore every output, including capped/format failures, from immutable raw receipts.
 req={r['owner']:r for p in root.glob('solver/shard_*/runtime/requests.jsonl') for r in rows(p)}
 for qid,v in votes.items():
  for s in v['samples']:
   r=req.get(qid+':'+str(s['sample_index']))
   if r:s.update(raw_response=r['raw_response'],actual_input_hashes=r['input_hashes'],shown_frame_ids=r['shown_frame_ids'],actual_pixel_hashes=r['frame_content_hashes'],actual_times_sec=r['actual_source_times_sec'])
 export_comparison(qs,votes,root/'four_groups','PUBLIC32_NEW_QUESTIONS_NOT_OLD53')
 graph=j(root/'GRAPH_SHARED_FROZEN.json');tax=[]
 for q in qs:
  identity=q.get('question_type')=='cross_frame_identity' and q.get('program',{}).get('op')=='identity';trace=q.get('program_read_trace',q.get('fact_ids'));tax.append({'question_id':q['question_id'],'route':q['route'],'type':'cross_time_identity' if identity else 'static_or_temporal_necessity_unresolved','necessary_frames':[q['program']['left'].rsplit('/',1)[0],q['program']['right'].rsplit('/',1)[0]] if identity else [],'identity_connection':q.get('program',{}).get('connection_id'),'fact_dependencies':trace,'time_intervals':q.get('event_context'),'temporal_truth':'not independently verified; timestamp alone never temporal','no_static_endpoints_as_action_proof':True})
 save(root/'TEMPORAL_QUESTION_DEPENDENCIES.json',tax);save(root/'UNSUPPORTED_TEMPORAL_TYPES.json',{'state_change_program':'not in existing deterministic grammar; no inferred state transitions','action_order_program':'motion affected-object binding and precise boundaries not established; retain failed candidates, no forced BEFORE','S_multi_time_necessity':'unresolved unless explicit dependency evidence; not counted as verified temporal'})
 selected=j(root/'selection/SELECTION_FROZEN.json')['selected'];loss=[]
 for v in selected:
  vid=v['video_id'];states=[j(p)['state'] for p in (root/'native/frames'/vid).glob('*/STATE.json')];ss=[r for r in rows(root/'S_ALL_CANDIDATES.jsonl') if r['video_id']==vid];pp=[r for r in rows(root/'P_ALL_CANDIDATES.jsonl') if r['video_id']==vid];loss.append({'video_id':vid,'public_frames':32,'frame_states':dict(collections.Counter(states)),'S_attempt_states':dict(collections.Counter(r['status'] for r in ss)),'P_candidate_public_failures':dict(collections.Counter(r.get('public_failure') or 'ELIGIBLE' for r in pp)),'S_frozen':sum(q['route']=='S' and q['video_id']==vid for q in qs),'P_frozen':sum(q['route']=='P' and q['video_id']==vid for q in qs)})
 save(root/'YIELD_LOSS.json',loss)
 for n,h in j(root/'FREEZE_MANIFEST.json').items():assert filehash(root/n)==h
 result={'questions':len(qs),'routes':j(root/'four_groups/SUMMARY.json'),'question_types':dict(collections.Counter(t['type'] for t in tax)),'motion_edges':len(graph['motion_edges']),'reference_edges':len(graph['reference_edges']),'pair_inputs':len(j(root/'SOURCE_TEMPORAL_PAIRS.json')),'cost':cost(root),'input_audit':check_inputs(root,public,32*len(public)),'truth':'PENDING_NO_ACCURACY','old_votes_reused':False};save(root/'SUMMARY.json',result);return result

def run_batch(cfg,root,selection,public):
 from four_group.pipeline import solver_stage
 root.mkdir(parents=True,exist_ok=True)
 if (root/'SUMMARY.json').exists():
  for n,h in j(root/'FREEZE_MANIFEST.json').items():assert filehash(root/n)==h
  emit('resume_completed_batch_no_calls',root=str(root));return j(root/'SUMMARY.json')
 c=dict(cfg,work_root=str(root));save(root/'effective_config.json',c);(root/'selection').mkdir(exist_ok=True);save(root/'selection/SELECTION_FROZEN.json',{'selected':selection});native_batch.prepare_batch=prepare
 if not (root/'native/STATE.json').exists():native_batch.execute(c,root/'native',selection)
 else:assert j(root/'native/STATE.json')['state']=='COMPLETED_NATIVE_PARTIAL'
 if not (root/'FREEZE_MANIFEST.json').exists():graph_qa(c,root,selection,public)
 solver_stage(c,root);result=finalize(root,public);emit('public32_batch_summary',root=str(root),**result);return result

def main():
 cfg=j('config/four_group.json');root=Path(cfg['public32_resume_root']) if cfg.get('public32_resume_root') else Path('/scratch/haozhe/.cache/vlm-rsi/public32')/os.environ['ORX_RUN_ID'];root.mkdir(parents=True,exist_ok=True);public=freeze_public(root);cfg.update(public_manifest=str(root/'PUBLIC32_FROZEN.json'),protocol_version='STEP-PUBLIC32-v1',source_commit=os.environ['ORX_COMMIT']);save(root/'effective_config.json',cfg);selection=sorted(j(BASE/'selection/SELECTION_FROZEN.json')['selected'],key=lambda v:int(v['video_id'].split('_')[-1]));save(root/'FROZEN_VIDEO_ORDER.json',selection)
 emit('public32_all_frozen',videos=10,frames=320,first_two=[v['video_id'] for v in selection[:2]])
 first=run_batch(cfg,root/'first2',selection[:2],{v['video_id']:public[v['video_id']] for v in selection[:2]});save(root/'FIRST2_ENGINEERING_CHECK.json',{'status':'PASS_INPUT_INVARIANTS','results':first,'does_not_require_positive_QA_or_identity_yield':True,'continue_remaining8':True})
 rest=run_batch(cfg,root/'remaining8',selection[2:],{v['video_id']:public[v['video_id']] for v in selection[2:]});save(root/'SUMMARY.json',{'first2':first,'remaining8':rest,'cost':cost(root),'old_results_readonly':True,'VQS_calls':0,'training':False});emit('public32_complete',root=str(root))
if __name__=='__main__':main()
