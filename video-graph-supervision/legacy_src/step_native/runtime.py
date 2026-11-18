"""General inference wrapper only, reusing frozen model loading/cost accounting.
No legacy FSG/Event Parser, program generator or checker is imported or called.
"""
import hashlib
from fractions import Fraction
from pathlib import Path
from stsg_pilot.runtime import FrozenRuntime
from stsg_pilot.media import sha_file

class NativeRuntime(FrozenRuntime):
    def encode(self,media,frame_ids,prompt):
        import numpy as np
        from PIL import Image
        torch=self.torch;mode=self.mode;kwargs={};shown=[];hashes=[];source_pts=[]
        if mode=='image':shown=[media['calibration_view']]
        elif mode=='video':shown=media['class_video_views']
        content=[]
        if mode in ['image','video']:
            frames=[]
            for f in shown:
                path=Path(self.cfg['output_root'])/f['file'];assert sha_file(path)==f['sha256']
                with Image.open(path) as im:frames.append(np.asarray(im.convert('RGB')).copy())
                hashes.append(f['sha256']);source_pts.append(f['time_sec'])
            content.append({'type':mode})
            if mode=='image':kwargs={'images':[Image.fromarray(frames[0])],'do_resize':False}
            else:
                if len(frames)%2:frames.append(frames[-1]);shown=shown+[shown[-1]];hashes.append(hashes[-1]);source_pts.append(source_pts[-1])
                metadata={'fps':float(Fraction(media['video']['avg_fps'])),'frames_indices':[f['source_index'] for f in shown],'total_num_frames':media['source_frames_decoded']}
                kwargs={'videos':[torch.stack([torch.from_numpy(a).permute(2,0,1) for a in frames])],'video_metadata':[metadata],'do_resize':False,'do_sample_frames':False}
        content.append({'type':'text','text':prompt});messages=[{'role':'user','content':content}]
        text=self.processor.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
        inputs=self.processor(text=[text],return_tensors='pt',**kwargs);hs={};shapes={}
        for k,v in inputs.items():
            if torch.is_tensor(v):hs[k]=hashlib.sha256(v.contiguous().view(torch.uint8).numpy().tobytes()).hexdigest();shapes[k]=list(v.shape)
        return inputs,{'input_mode':mode,'input_hashes':hs,'input_shapes':shapes,'shown_frame_ids':[f['frame_id'] for f in shown],'frame_content_hashes':hashes,'actual_source_times_sec':source_pts,'actual_visual_files':[f['file'] for f in shown],'prompt':prompt,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'chat_text_sha256':hashlib.sha256(text.encode()).hexdigest(),'chat_template_rendered':text}
