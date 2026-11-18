"""Frozen offline Qwen3-VL backend, shared cached video frames for all roles."""
import datetime,hashlib,json,os,time
from pathlib import Path
from fractions import Fraction
from .core import require,digest
from .media import sha_file,check_geometry

def save(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False));tmp.replace(p)
def append(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a') as f:f.write(json.dumps(value,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
def emit(event,**kw):print(json.dumps({'event':event,**kw},ensure_ascii=False),flush=True)

def configure_threads(torch):
    torch.set_num_threads(2)
    # PyTorch permits setting interop threads only once per process.
    if torch.get_num_interop_threads()!=1:
        torch.set_num_interop_threads(1)

class FrozenRuntime:
    def __init__(self,cfg,out):
        import torch,transformers,importlib.metadata
        from transformers import AutoProcessor,Qwen3VLForConditionalGeneration
        self.torch=torch;self.cfg=cfg;self.out=Path(out);self.calls=0;self.started=time.monotonic()
        self.deadline=float(os.environ['SMOKE_DEADLINE']);self.gpu=os.environ['CUDA_VISIBLE_DEVICES']
        configure_threads(torch)
        require(torch.__version__=='2.5.1+cu124' and transformers.__version__=='4.57.0','RUNTIME_VERSION_CHANGED')
        require(torch.cuda.get_device_properties(0).total_memory>=40*1024**3,'GPU_TOO_SMALL')
        torch.cuda.set_per_process_memory_fraction(.80,0)
        start=time.monotonic();self.processor=AutoProcessor.from_pretrained(cfg['model_path'],local_files_only=True)
        self.model=Qwen3VLForConditionalGeneration.from_pretrained(cfg['model_path'],local_files_only=True,torch_dtype=torch.bfloat16,attn_implementation='sdpa',device_map={'':'cuda:0'}).eval()
        require(all(not p.requires_grad or p.grad is None for p in self.model.parameters()),'UNEXPECTED_MODEL_GRAD')
        for p in self.model.parameters():p.requires_grad_(False)
        self.model_load_seconds=time.monotonic()-start
        save(self.out/'runtime.json',{'model_path':cfg['model_path'],'revision':cfg['model_revision'],'gpu':self.gpu,'torch':torch.__version__,'transformers':transformers.__version__,'cuda_device':torch.cuda.get_device_name(0),'load_seconds':self.model_load_seconds,
            'packages':{x:importlib.metadata.version(x) for x in ['torch','transformers','torchvision','numpy','av','Pillow','qwen-vl-utils','scenedetect','opencv-python-headless','jsonschema']},'checkpoint_config_sha256':sha_file(Path(cfg['model_path'])/'config.json'),'training':False})
        emit('model_loaded',gpu=self.gpu,seconds=self.model_load_seconds)
    def encode(self,media,frame_ids,prompt):
        import numpy as np
        from PIL import Image
        torch=self.torch;fs={f['frame_id']:f for f in media['frames']}
        require(bool(frame_ids) and len(frame_ids)<=32 and set(frame_ids)<=fs.keys(),'MODEL_FRAME_BUDGET_OR_UNKNOWN_FRAME')
        ordered=sorted(set(frame_ids),key=lambda i:fs[i]['pts'])
        shown=ordered+([ordered[-1]] if len(ordered)%2 else [])
        frames=[]
        for i in shown:
            f=fs[i];path=Path(self.cfg['output_root'])/f['file']
            require(sha_file(path)==f['sha256'],'CACHED_FRAME_MUTATED')
            with Image.open(path) as im:frames.append(torch.from_numpy(np.asarray(im.convert('RGB')).copy()).permute(2,0,1))
        check_geometry(frames[0].shape[-2],frames[0].shape[-1],self.processor.video_processor.patch_size,self.processor.video_processor.merge_size)
        clock=[{'frame_id':i,'global_seconds':fs[i]['time_sec']} for i in shown]
        prompt='Actual frame clock in supplied order (authoritative global seconds; native average-FPS timestamps may differ): '+json.dumps(clock)+'\n'+prompt
        messages=[{'role':'user','content':[{'type':'video'},{'type':'text','text':prompt}]}]
        text=self.processor.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
        metadata={'fps':float(Fraction(media['video']['avg_fps'])),'frames_indices':[media['source_frame_indices'][i] for i in shown],'total_num_frames':media['total_source_frames']}
        inputs=self.processor(text=[text],videos=[torch.stack(frames)],video_metadata=[metadata],return_tensors='pt',do_resize=False,do_sample_frames=False)
        hashes={};shapes={}
        for k,v in inputs.items():
            if torch.is_tensor(v):
                hashes[k]=hashlib.sha256(v.contiguous().view(torch.uint8).numpy().tobytes()).hexdigest();shapes[k]=list(v.shape)
        return inputs,{'input_hashes':hashes,'input_shapes':shapes,'shown_frame_ids':shown,'frame_content_hashes':[fs[i]['sha256'] for i in shown],'prompt':prompt,'prompt_sha256':digest(prompt),'video_metadata':metadata}
    def ask(self,media,frame_ids,prompt,*,role,seed,max_tokens,temperature=0,owner=None,parity=False):
        require(time.time()<self.deadline-15,'BUDGET_DEADLINE_REACHED')
        require(self.calls<self.cfg['worker_call_cap'],'WORKER_CALL_CAP')
        torch=self.torch;begin=time.monotonic();inputs,meta=self.encode(media,frame_ids,prompt)
        if parity:
            again,check=self.encode(media,frame_ids,prompt)
            require(meta['input_hashes']==check['input_hashes'],'ENCODE_REPLAY_MISMATCH')
            del again
        self.calls+=1;request_id=f'{self.cfg.get("request_namespace","")}{os.environ["ORX_RUN_ID"][:8]}_gpu{self.gpu}_request{self.calls:04d}'
        record={'request_id':request_id,'role':role,'owner':owner,'video_id':media['video']['video_id'],'source_video_id':media['video']['source_video_id'],
                'seed':seed,'max_new_tokens':max_tokens,'temperature':temperature,'top_p':.9 if temperature else None,'model_revision':self.cfg['model_revision'],'gpu':self.gpu,
                'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),**meta}
        append(self.out/'requests_started.jsonl',record)
        torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
        torch.cuda.reset_peak_memory_stats();torch.cuda.synchronize();gpu_start=time.monotonic()
        try:
            device_inputs={k:v.to('cuda') if torch.is_tensor(v) else v for k,v in inputs.items()}
            kwargs={'max_new_tokens':max_tokens,'do_sample':temperature>0,'use_cache':True}
            if temperature:kwargs.update(temperature=temperature,top_p=.9,top_k=0)
            with torch.inference_mode():output=self.model.generate(**device_inputs,**kwargs)
            torch.cuda.synchronize();elapsed=time.monotonic()-gpu_start
            ids=output[0,inputs['input_ids'].shape[1]:];text=self.processor.decode(ids,skip_special_tokens=True)
            record.update(status='DONE',raw_response=text,input_tokens=int(inputs['input_ids'].shape[1]),output_tokens=len(ids),output_hit_cap=len(ids)>=max_tokens,
                          model_device_wall_seconds=elapsed,total_request_wall_seconds=time.monotonic()-begin,peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved(),encoded_replay_passed=True if parity else None)
            append(self.out/'requests.jsonl',record);emit('request_done',gpu=self.gpu,request=request_id,role=role,video=record['video_id'],tokens=len(ids),seconds=round(elapsed,2))
            del output,device_inputs,inputs;return record
        except Exception as e:
            record.update(status='FAILED',error=repr(e),model_device_wall_seconds=time.monotonic()-gpu_start,total_request_wall_seconds=time.monotonic()-begin)
            append(self.out/'requests.jsonl',record);raise
