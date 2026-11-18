"""Native STEP only: existing S1/A1 frequency+presence/static/Motion/Reference."""
import argparse,copy,json,os,sys,subprocess,time,traceback
from pathlib import Path
from step_six.common import j,rows,jl,choose_gpu,cost,allocation
from stsg_pilot.runtime import save,emit
from step_native.checkpoint_runtime import CheckpointRuntime
from step_native.frame_execution import process_frame,freeze_video_media
from step_native.splitting import prepare
from step_native.next_stage import collect

class BatchRuntime(CheckpointRuntime):
 def ask(self,media,ids,prompt,**kw):
  role=kw['role'];chain=role in ['scene_narrative','object_names'] or role.startswith(('instances_','attribute_narrative_','attributes_','relation_narrative_','relations_'))
  if chain:kw=dict(kw,max_tokens=8192 if self.mode=='image' else 4096)
  return super().ask(media,ids,prompt,**kw)

def prepare_batch(cfg,root,selection):
 tasks=[];videos=[]
 for rec in selection:
  vid=rec['video_id'];folder=root/'videos'/vid;folder.mkdir(parents=True,exist_ok=True);cc=dict(cfg,video={'video_id':vid,'source':'PerceptionTest','split':'train','path':rec['path'],'sha256':rec['sha256']})
  try:
   m=j(folder/'S1/manifest.json') if (folder/'S1/manifest.json').exists() else prepare(cc,folder)
   record={'video_id':vid,'folder':str(folder),'chosen_keyframes':m['selected_keyframe_source_indices'],'all_keyframes':m['selected_keyframe_source_indices'],'source_sha256':rec['sha256'],'partial_contiguous_clip_prefix_smoke':False};tt=freeze_video_media(cc,record,root);tasks+=tt;videos.append({**record,'status':'INPUTS_FROZEN','selected_keyframe_count':len(tt)})
  except Exception as e:
   videos.append({**rec,'status':'S1_FAILED','error':repr(e),'traceback':traceback.format_exc()});save(root/'frozen_inputs'/(vid+'.json'),{'all_tasks':[],'video_id':vid,'failure':repr(e)})
  save(root/'VIDEO_PREPARATION.json',videos)
 return tasks

def worker(cfg,index,gpu):
 root=Path(cfg['work_root']);out=root/'attempts'/os.environ['ORX_RUN_ID']/('gpu'+gpu)/('shard_'+str(index));out.mkdir(parents=True,exist_ok=True);os.environ['CUDA_VISIBLE_DEVICES']=gpu;os.environ['SMOKE_DEADLINE']='inf';c=dict(cfg,request_namespace='native_');rt=BatchRuntime(c,out)
 try:
  for t in j(root/f'shard_{index}.json'):
   try:process_frame(rt,dict(cfg,video=t['media']['video']),t)
   except Exception as e:save(Path(t['folder'])/'STATE.json',{'state':'FAILED','scope':t['scope'],'error':repr(e),'traceback':traceback.format_exc(),'continue_other_keyframes':True})
 finally:
  allocation(rt,out);a=j(out/'ALLOCATION.json');save(out/'allocation.json',{'gpu':gpu,'gpu_hours':a['wall_seconds']/3600,'worker_wall_seconds':a['wall_seconds'],'cache_hits':rt.cache_hits,'calls':rt.calls-rt.initial_calls})

def execute(cfg,root,selection):
 root=Path(root);root.mkdir(parents=True,exist_ok=True);c=dict(cfg,work_root=str(root),output_root=str(root),protocol_version='native-four-group-frozen-v1');save(root/'effective_config.json',c);tasks=prepare_batch(c,root,selection);save(root/'FROZEN_ALL_TASKS.json',tasks)
 gpus=[]
 for line in subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines():
  i,m,u=line.split(',')
  if float(m)>40000 and float(u)<5:gpus.append(i.strip())
 assert gpus,'NO_IDLE_A40';pp=[]
 for i,g in enumerate(gpus[:5]):
  shard=tasks[i::len(gpus[:5])]
  if not shard:continue
  save(root/f'shard_{i}.json',shard);pp.append((subprocess.Popen([sys.executable,'-m','four_group.native_batch','--config',str(root/'effective_config.json'),'--worker',str(i),'--gpu',g]),i))
 failures=[]
 for p,i in pp:
  if p.wait()!=0:failures.append({'shard':i,'returncode':p.returncode})
 for t in tasks:
  path=Path(t['folder'])/'STATE.json'
  if not path.exists():save(path,{'state':'FAILED','scope':t['scope'],'reason':'worker failed before frame execution'})
 collect(c,root);tc=dict(c,parent_work_root=str(root),protocol_version='native-four-group-temporal-v1',request_namespace='temporal_');save(root/'temporal_config.json',tc)
 subprocess.run([sys.executable,'-m','step_native.temporal','--config',str(root/'temporal_config.json')],check=True,env=dict(os.environ,CUDA_VISIBLE_DEVICES=''))
 p3=root/'P3'/os.environ['ORX_RUN_ID'];ts=j(p3/'summary.json');save(p3/'ALLOCATION.json',{'gpu':'native_temporal_worker','wall_seconds':ts['gpu_wall_seconds'],'includes_model_loading':True,'note':'temporal summary uses NativeRuntime.started set before model loading'})
 save(root/'STATE.json',{'state':'COMPLETED_NATIVE_PARTIAL','run':os.environ['ORX_RUN_ID'],'worker_failures':failures,'selected_videos':len(selection)});return root/'P3'/os.environ['ORX_RUN_ID']

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);ap.add_argument('--worker',type=int,required=True);ap.add_argument('--gpu',required=True);a=ap.parse_args();worker(j(a.config),a.worker,a.gpu)
if __name__=='__main__':main()
