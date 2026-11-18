"""Single-keyframe native A.1 prompt chain. No events, no merging, no QA."""
import copy,hashlib,json,time,re
from pathlib import Path
from stsg_pilot.runtime import save,emit
from stsg_pilot.media import sha_file
from .runtime import NativeRuntime
from . import prompts as P,records as R

def prepare_inputs(cfg,root,s1):
    from PIL import Image
    from transformers.models.qwen2_vl.image_processing_qwen2_vl import smart_resize
    cal=s1['calibration_source_index'];source=next(f for f in s1['frames'] if f['source_index']==cal)
    video=s1['video'];media={'video':{'video_id':video['video_id'],'source_video_id':'PerceptionTest:'+video['video_id'],'avg_fps':video['avg_fps']},'source_frames_decoded':s1['source_frames_decoded']}
    def resize(f,mode,cap):
        im=Image.open(root/f['file']).convert('RGB');h,w=smart_resize(im.height,im.width,factor=32,min_pixels=4096,max_pixels=cap)
        file=f'S2/model_inputs/{mode}_{f["source_index"]:06d}.png';target=root/file;target.parent.mkdir(parents=True,exist_ok=True);im.resize((w,h),Image.Resampling.BICUBIC).save(target)
        return {**f,'file':file,'sha256':sha_file(target),'source_file':f['file'],'source_sha256':f['sha256'],'resize_hw':[h,w],'resize_pixels_cap':cap}
    media['calibration_view']=resize(source,'image',200704)
    media['class_video_views']=[resize(f,'video',50176) for f in s1['frames'] if f['class_video_context']]
    save(root/'S2/input_manifest.json',media);return media

def run_chain(cfg,root,rt=None,media=None):
    if media is None:
        s1=json.loads((root/'S1/manifest.json').read_text());media=prepare_inputs(cfg,root,s1)
    out=root/'S2';out.mkdir(parents=True,exist_ok=True)
    rt=rt or NativeRuntime(cfg,out/'worker');calls_at_start=rt.calls;g={'schema':'STEP-FSG-reimplementation-v1','video_id':cfg['video']['video_id'],'source_keyframe':media['calibration_view'],'object_nodes':[],'attribute_nodes':[],'attribute_edges':[],'relation_edges':[],'unresolved_relation_claims':[],'native_verification_status':'UNVERIFIED_CANDIDATE'};errors=[];calls=[]
    def call(role,mode,prompt,depends=()):
        rt.mode=mode;r=rt.ask(media,[],prompt,role=role,seed=cfg['seed'],max_tokens=cfg['max_tokens'],temperature=cfg.get('chain_temperature',0),owner=role,parity=(rt.calls==0));calls.append(r)
        r['depends_on_request_ids']=list(depends);save(out/'requests'/f'{rt.calls:03d}_{role}.json',r)
        if r['output_hit_cap']:raise RuntimeError('OUTPUT_TOKEN_CAP_HIT:'+role)
        return r
    def extract(role,template,narrative,referent,depends):
        prompt=template.format(narrative=narrative,referent=referent)
        if not cfg.get('sentencewise_overflow_recovery'):return [call(role,'text',prompt,depends)]
        # Preserve the actual failed full-sentence response, then reapply the same
        # supplementary extraction task to literal sentence spans; no invented facts.
        try:return [call(role,'text',prompt,depends)]
        except RuntimeError as e:
            if not str(e).startswith('OUTPUT_TOKEN_CAP_HIT:'):raise
        parts=[x.strip() for x in re.split(r'(?<=[.!?])\s+|\n+',narrative) if x.strip()]
        if len(parts)<2 or len(parts)>24:raise RuntimeError('OUTPUT_TOKEN_CAP_HIT:UNSPLITTABLE:'+role)
        save(out/'sentence_recovery'/f'{role}.json',{'source_narrative':narrative,'literal_chunks':parts,'assumption':'same Supplement extraction task per literal sentence; all chunks required'})
        return [call(role+'_sentence_'+str(i),'text',template.format(narrative=x,referent=referent),depends) for i,x in enumerate(parts)]
    def checkpoint():
        save(out/'FSG_candidate_partial.json',g);save(out/'parsing_issues.json',errors)
    def issue(role,e,response):errors.append({'stage':role,'error':str(e),'request_id':response['request_id'],'raw_response_retained':True})
    try:
        narrative=call('scene_narrative','image',P.NARRATIVE)
        obj=call('object_names','text',P.OBJECTS.format(narrative=narrative['raw_response']),[narrative['request_id']]);labels=R.object_classes(obj['raw_response']);save(out/'object_classes.json',labels)
        for ci,label in enumerate(labels):
            ins=call(f'instances_{ci}','image',P.INSTANCES.format(label=label),[obj['request_id']]);rows=R.instances(ins['raw_response'],label)
            for row in rows:
                nid=f'o{len(g["object_nodes"]):03d}';ref=row['instance_name']+', '+row['distinctive_description']
                g['object_nodes'].append({'id':nid,'label':label,'referent':ref,**row,'source_keyframe_id':media['calibration_view']['frame_id'],'source_request_ids':[obj['request_id'],ins['request_id']],'classification':None,'cross_frame_identity':'NOT_ASSESSED','verification':'NOT_RUN'})
            checkpoint()
        for node in g['object_nodes']:
            nid=node['id'];dep=[node['source_request_ids'][-1]]
            cl=call(f'classify_{nid}','video',P.CLASSIFY.format(referent=node['referent']),dep)
            try:node['classification']=R.classification(cl['raw_response']);node['classification_request_id']=cl['request_id']
            except Exception as e:issue('classification',e,cl)
            desc=call(f'attribute_narrative_{nid}','image',P.ATTR_NARRATIVE.format(referent=node['referent']),dep)
            attr_responses=extract(f'attributes_{nid}',P.ATTR_EXTRACT,desc['raw_response'],node['referent'],[desc['request_id']])
            for attrs in attr_responses:
                try:
                    for a in R.attributes(attrs['raw_response']):
                        aid=f'a{len(g["attribute_nodes"]):03d}';g['attribute_nodes'].append({'id':aid,**a,'source_keyframe_id':media['calibration_view']['frame_id'],'source_request_ids':[desc['request_id'],attrs['request_id']],'verification':'NOT_RUN'})
                        g['attribute_edges'].append({'id':'has_'+aid,'subject_id':nid,'attribute_id':aid,'source_request_ids':[desc['request_id'],attrs['request_id']]})
                except Exception as e:issue('attributes',e,attrs)
            checkpoint()
        for node in g['object_nodes']:
            others=[x['referent'] for x in g['object_nodes'] if x['id']!=node['id']]
            if not others:continue
            d=call(f'relation_narrative_{node["id"]}','image',P.REL_NARRATIVE.format(referent=node['referent'],others=', '.join(others)),node['source_request_ids'])
            rel_responses=extract(f'relations_{node["id"]}',P.REL_EXTRACT,d['raw_response'],node['referent'],[d['request_id']])
            for r in rel_responses:
                try:
                    parsed,bad=R.triples_with_issues(r['raw_response'])
                    for badrow in bad:g['unresolved_relation_claims'].append({**badrow,'status':'UNRESOLVED_SYNTAX','requested_subject_id':node['id'],'source_request_ids':[d['request_id'],r['request_id']]})
                    for triplet in parsed:
                        candidates=R.target_candidates(triplet['object'],g['object_nodes']);claim={**triplet,'requested_subject_id':node['id'],'subject_binding':'task-scoped requested instance, not crossframe identity','target_candidates':candidates,'source_request_ids':[d['request_id'],r['request_id']],'source_keyframe_id':media['calibration_view']['frame_id'],'verification':'NOT_RUN'}
                        subject_candidates=R.target_candidates(triplet['subject'],g['object_nodes'])
                        claim['subject_candidates']=subject_candidates
                        if len(subject_candidates)==1 and subject_candidates[0]==node['id'] and len(candidates)==1:g['relation_edges'].append({'id':f'r{len(g["relation_edges"]):03d}','subject_id':node['id'],'object_id':candidates[0],**claim})
                        else:g['unresolved_relation_claims'].append({**claim,'status':'UNRESOLVED_OR_MISMATCHED_SUBJECT' if subject_candidates!=[node['id']] else ('UNRESOLVED_TARGET' if not candidates else 'AMBIGUOUS_TARGET')})
                except Exception as e:issue('relations',e,r)
            checkpoint()
        g['prompt_chain_completed']=True
        g['decoding_issues']=errors
    finally:
        checkpoint();save(out/'FSG_pre_native_verification.json',g)
        save(out/'chain_summary.json',{'full_chain_completed':g.get('prompt_chain_completed',False),'calls':rt.calls-calls_at_start,'objects':len(g['object_nodes']),'attributes':len(g['attribute_nodes']),'relations_resolved':len(g['relation_edges']),'relations_unresolved':len(g['unresolved_relation_claims']),'parsing_issues':len(errors),'native_verification_calls':0,'new_events':0,'B0_B4_calls':0})
        emit('S2_chain_complete',**json.loads((out/'chain_summary.json').read_text()))
    return g
