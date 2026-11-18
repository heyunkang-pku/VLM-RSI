"""Cache identical requests, not sampled evidence; seeds and actual pixels are keys."""
import copy,hashlib,json,os,signal,time
from pathlib import Path
from .runtime import NativeRuntime
from stsg_pilot.runtime import save,append,emit
class CheckpointRuntime(NativeRuntime):
    def __init__(self,cfg,out):
        super().__init__(cfg,out);self.cache=Path(cfg['work_root'])/'request_cache';self.cache.mkdir(exist_ok=True);self.cache_hits=0;self.protocol=cfg['protocol_version']
        prefix=cfg.get('request_namespace','')+os.environ['ORX_RUN_ID'][:8]+'_gpu'+self.gpu+'_request'
        seen=[json.loads(f.read_text()).get('request_id','') for f in self.cache.glob('*.json')]
        self.calls=max([int(x[len(prefix):]) for x in seen if x.startswith(prefix)]+[0]);self.initial_calls=self.calls
    def ask(self,media,frame_ids,prompt,**kw):
        mode=self.mode;shown=([media['calibration_view']] if mode=='image' else media['class_video_views'] if mode=='video' else [])
        if media.get('public32') and mode=='image':
            prompt='Public source frame '+shown[0]['frame_id']+' at PTS seconds '+str(shown[0]['time_sec'])+'.\n'+prompt
        if mode=='video':
            prompt='Authoritative source PTS times (seconds), in supplied video order: '+json.dumps([{'frame_id':f['frame_id'],'source_seconds':f['time_sec']} for f in shown])+'. Clip intervals: '+json.dumps(media.get('clip_intervals',[]))+'.\n'+prompt
        key={'protocol':self.protocol,'revision':self.cfg['model_revision'],'mode':mode,'prompt':prompt,'seed':kw['seed'],'temperature':kw.get('temperature',0),'max_tokens':kw['max_tokens'],'pixel_files':[f['sha256'] for f in shown],'times':[f['time_sec'] for f in shown],'video_fps':media['video']['avg_fps'],'total_frames':media['source_frames_decoded']}
        digest=hashlib.sha256(json.dumps(key,sort_keys=True).encode()).hexdigest();target=self.cache/(digest+'.json')
        if target.exists():
            r=json.loads(target.read_text());assert r['status']=='DONE';self.cache_hits+=1;return copy.deepcopy(r)
        self.cfg['output_root']=media['_root'];begin=time.time()
        def timeout(sig,frame):raise TimeoutError('SINGLE_REQUEST_TIMEOUT')
        signal.signal(signal.SIGALRM,timeout);signal.alarm(self.cfg['request_timeout_seconds'])
        try:r=super().ask(media,frame_ids,prompt,**kw)
        finally:signal.alarm(0)
        r.update(visual_root=media['_root'],source_commit=os.environ['ORX_COMMIT'],request_cache_key=digest,request_duration_including_encoding=time.time()-begin)
        if r['status']=='DONE':save(target,r)
        append(Path(self.cfg['work_root'])/'completed_requests_index.jsonl',{'request_id':r['request_id'],'cache_file':str(target),'role':r['role'],'source_commit':r['source_commit']})
        return copy.deepcopy(r)
