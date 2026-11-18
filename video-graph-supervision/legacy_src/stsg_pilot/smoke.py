"""Five frozen videos only. Parse/freeze barrier precedes every B0/Checker request."""
import argparse,copy,datetime,json,os,shutil,signal,subprocess,sys,time,traceback
from pathlib import Path
from .core import *
from .candidates import generate_candidates
from .controls import matched_controls
from .media import prepare_media,sha_file
from .parsing import PARSER_SPEC,BRIDGE_SPEC,parse_json,make_clip_graph,attach_frequency
from .runtime import FrozenRuntime,save,append,emit

def valid_schema(g):
    from jsonschema import Draft202012Validator
    Draft202012Validator(json.loads(Path('schemas/raw_graph.schema.json').read_text())).validate(g)
    validate_graph(g)

def make_run(response,frames,group):
    return {'parser_run_id':response['request_id'],'model_revision':response['model_revision'],
            'prompt_hash':response['prompt_sha256'],'seed':response['seed'],'frame_ids':frames,'sample_group':group}

def parse_video(rt,media,folder,cfg):
    clips=[c for c in media['clips'] if c['frame_ids']]
    require(0<len(clips)<=cfg['max_clips'],'SCENE_BUDGET_EXCEEDED')
    roots=[];loss={'scene_count':media['scenes_detected'],'visible_clips':len(clips),'parser_attempts':0,'parser_valid':0,'parser_failures':[],'bridge_attempts':0,'bridge_valid':0}
    for ci,clip in enumerate(clips):
        group=media['video']['video_id']+':'+clip['clip_id'];runs=[];samples={};first=None
        prompt=PARSER_SPEC+'\nClip bounds: '+json.dumps(clip['interval_sec'])
        for k in range(cfg['parser_samples']):
            response=rt.ask(media,clip['frame_ids'],prompt,role='parser',seed=cfg['seed']+ci*10+k,max_tokens=cfg['parser_max_tokens'],temperature=.7,owner=group)
            run=make_run(response,clip['frame_ids'],group);runs.append(run);loss['parser_attempts']+=1
            try:
                record=parse_json(response['raw_response']);g=make_clip_graph(media,clip,record,run);valid_schema(g)
                samples[run['parser_run_id']]=g;loss['parser_valid']+=1
                if first is None:first=g
            except Exception as e:
                loss['parser_failures'].append({'run_id':run['parser_run_id'],'error':str(e),'output_hit_cap':response['output_hit_cap']})
            save(folder/'parser_loss.json',loss)
        require(first is not None,'NO_STRUCTURALLY_VALID_PARSE:'+group)
        roots.append(attach_frequency(copy.deepcopy(first),samples,runs))
    graph={'schema_version':'pilot-v1','video':copy.deepcopy(media['video']),'frames':copy.deepcopy(media['frames']),
           'clips':copy.deepcopy(clips),'parser_runs':[r for g in roots for r in g['parser_runs']],
           'facts':[f for g in roots for f in g['facts']]}
    # Bridge only existing original local nodes; never update root entities/events.
    for ci,(left,right) in enumerate(zip(roots,roots[1:])):
        objects=[f for g in [left,right] for f in g['facts'] if f['kind']=='object']
        if not objects:continue
        frame_ids=[f['frame_id'] for f in media['frames'] if f['clip_id'] in [left['clips'][0]['clip_id'],right['clips'][0]['clip_id']]]
        group=media['video']['video_id']+f':bridge{ci}';runs=[];samples={};first=None
        prompt=BRIDGE_SPEC+'\nExisting objects: '+json.dumps([{k:o[k] for k in ['fact_id','predicate','clip_ids','support_frame_ids']} for o in objects])
        for k in range(cfg['parser_samples']):
            response=rt.ask(media,frame_ids,prompt,role='bridge_parser',seed=cfg['seed']+100+ci*10+k,max_tokens=cfg['parser_max_tokens'],temperature=.7,owner=group)
            run=make_run(response,frame_ids,group);runs.append(run);loss['bridge_attempts']+=1
            try:
                record=parse_json(response['raw_response']);keys(record,['identities']);new=[];facts={f['fact_id']:f for f in graph['facts']};fs={f['frame_id']:f for f in media['frames']}
                for i in record['identities']:
                    keys(i,['id','subject_id','object_id','identity_status','frame_ids']);require(i['subject_id'] in facts and i['object_id'] in facts,'BRIDGE_UNKNOWN_NODE')
                    a,b=facts[i['subject_id']],facts[i['object_id']];require(a['kind']==b['kind']=='object','BRIDGE_OBJECT_REQUIRED')
                    require(a['clip_ids']!=b['clip_ids'],'BRIDGE_MUST_CROSS_CLIPS')
                    require(set(i['frame_ids'])<=set(frame_ids) and bool(i['frame_ids']),'BRIDGE_FRAMES');times=[fs[f]['time_sec'] for f in i['frame_ids']]
                    new.append({'fact_id':f'bridge{ci}_'+i['id'],'kind':'identity','predicate':'same physical entity','clip_ids':sorted(set(a['clip_ids']+b['clip_ids'])),
                                'support_frame_ids':i['frame_ids'],'parser_run_id':run['parser_run_id'],'matched_parser_run_ids':[run['parser_run_id']],
                                'start_sec_range':[min(times)]*2,'end_sec_range':[max(times)]*2,'depends_on':[],
                                'subject_id':i['subject_id'],'object_id':i['object_id'],'identity_status':i['identity_status']})
                candidate=copy.deepcopy(graph);candidate['parser_runs'].append(run);candidate['facts']+=new;valid_schema(candidate)
                # attach_frequency over whole graph would mix pre-existing sample groups; retain only bridge facts for matching.
                samples[run['parser_run_id']]=candidate;loss['bridge_valid']+=1
                if first is None:first=(candidate,new)
            except Exception as e:loss['parser_failures'].append({'run_id':run['parser_run_id'],'error':'BRIDGE:'+str(e),'output_hit_cap':response['output_hit_cap']})
            save(folder/'parser_loss.json',loss)
        graph['parser_runs']+=runs
        if first is not None:
            from .parsing import fact_signature
            for f in first[1]:
                sig=fact_signature(first[0],f)
                f['matched_parser_run_ids']=[rid for rid,g in samples.items() if any(x['parser_run_id']==rid and fact_signature(g,x)==sig for x in g['facts'])]
                graph['facts'].append(f)
    require(len(graph['facts'])<=cfg['max_facts'],'RAW_GRAPH_FACT_BUDGET_EXCEEDED')
    valid_schema(graph);save(folder/'raw_graph.json',graph)
    qs=generate_candidates(graph,seed=cfg['seed'],cap=cfg['max_questions_per_video'])
    save(folder/'locked_candidates.json',qs);save(folder/'parser_loss.json',loss)
    return graph,qs

def verify_select_b1(graph,q,b1,ledger,cfg):
    expected=execute(graph,q,method='B1');require(expected==b1,'B1_RESULT_MUTATED')
    gate=execute(graph,q,method='B2',ledger=ledger,threshold=cfg['frequency_threshold'])
    if gate['status']=='ANSWERED':
        require(b1['status']=='ANSWERED' and gate['answer']==b1['answer'],'SELECTIVE_VERIFICATION_CHANGED_ANSWER')
        gate['answer']=b1['answer']  # Existing B1 label only. No new answer generator.
    gate['function']='Selective Verification';gate['b1_answer']=b1['answer']
    return gate

def evaluate_video(rt,media,folder,cfg,graph,qs):
    questions=qs['questions'];ids=[f['frame_id'] for f in media['frames']]
    b1=[execute(graph,q,method='B1') for q in questions];save(folder/'b1_program.json',b1)
    b0=[{'question_id':q['question_id'],'method':'B0','status':'NOT_RUN','answer':None,'reason':'PENDING'} for q in questions]
    b2=[{'question_id':q['question_id'],'method':'B2','status':'NOT_RUN','answer':None,'reason':'PENDING'} for q in questions]
    save(folder/'b0_votes.json',b0);save(folder/'b2_selective.json',b2)
    for j,q in enumerate(questions):
        payload=b0_payload(graph,q);texts=[]
        for k in range(8):
            response=rt.ask(media,ids,payload['question']+'\n'+payload['format_instruction'],role='B0',seed=cfg['seed']+10+k,max_tokens=cfg['b0_max_tokens'],temperature=.7,owner=q['question_id'])
            texts.append(response['raw_response']);b0[j]['partial_rollouts']=list(texts);save(folder/'b0_votes.json',b0)
        b0[j]=majority_vote(q['question_id'],texts,q['answer_type']);save(folder/'b0_votes.json',b0)
    needed=sorted(set(i for q in questions for i in q['required_fact_ids']));ledger=[]
    for i in needed:
        payload=checker_payload(graph,i)
        prompt=json.dumps({k:v for k,v in payload.items() if k!='frames'},ensure_ascii=False)
        shown=[f['frame_id'] for f in payload['frames']]
        response=rt.ask(media,shown,prompt,role='checker',seed=cfg['seed'],max_tokens=cfg['checker_max_tokens'],owner=i)
        verdict=parse_check_response(response['raw_response'])
        ledger.append(ledger_entry(graph,i,verdict,cfg['model_revision'],shown,checker_run_id=response['request_id'],raw_response=response['raw_response'],reason='strict atomic visual/identity/time response; non-enum is uncertain',cost_gpu_sec=response['model_device_wall_seconds'],tokens=response['input_tokens']+response['output_tokens']))
        save(folder/'checker_ledger.json',ledger)
    for j,(q,a) in enumerate(zip(questions,b1)):
        b2[j]=verify_select_b1(graph,q,a,ledger,cfg)
    save(folder/'b2_selective.json',b2);save(folder/'checker_ledger.json',ledger)
    require(digest(graph)==qs['raw_graph_sha256'],'GRAPH_CHANGED_AFTER_VERIFICATION')
    return {'N':len(questions),'B0_answered':sum(r['status']=='ANSWERED' for r in b0),'B1_answered':sum(r['status']=='ANSWERED' for r in b1),'B2_answered':sum(r['status']=='ANSWERED' for r in b2),'checker_claims':len(ledger),'graph_unchanged':True}

def worker(cfg,index,gpu):
    root=Path(cfg['output_root']);work=root/f'worker{index}';work.mkdir(exist_ok=True);start=time.monotonic();rt=None
    try:
        rt=FrozenRuntime(cfg,work)
        if index==0:
            media=json.loads((root/'media'/f'{cfg["videos"][0]["video_id"]}.json').read_text())
            response=rt.ask(media,[f['frame_id'] for f in media['frames']], 'Describe only the visible actions in this video in one short sentence. This is a runtime check; do not generate QA.',role='preflight',seed=cfg['seed'],max_tokens=64,parity=True)
            require(response['output_tokens']>0,'EMPTY_SINGLE_REQUEST')
            save(root/'preflight_passed.json',{'media_decode_parity':media['decode_parity_passed'],'encoded_replay_passed':True,'single_request':response,'model_load_passed':True})
        assignments=[v for j,v in enumerate(cfg['videos']) if j%cfg['gpu_count']==index]
        for v in assignments:
            folder=root/'videos'/v['video_id'];folder.mkdir(parents=True,exist_ok=True)
            media=json.loads((root/'media'/f'{v["video_id"]}.json').read_text())
            status={'video_id':v['video_id'],'stage':'PARSE','status':'RUNNING'};save(folder/'status.json',status)
            try:
                if cfg.get('protocol')=='cached-fsg-windowed-events-v3':
                    from .windowed_parser import windowed_parse_video
                    graph,qs=windowed_parse_video(rt,media,folder,cfg)
                elif cfg.get('protocol')=='purpose-separated-compact-parser-v2':
                    from .staged_parser import staged_parse_video
                    graph,qs=staged_parse_video(rt,media,folder,cfg)
                else:graph,qs=parse_video(rt,media,folder,cfg)
                status.update(stage='FROZEN_CANDIDATES',status='PARSED',facts=len(graph['facts']),N=len(qs['questions']),graph_sha256=digest(graph),questions_sha256=qs['question_set_sha256'])
            except Exception as e:status.update(stage='PARSE',status='FAILED',error=repr(e));emit('video_parse_failed',video=v['video_id'],error=repr(e))
            save(folder/'status.json',status)
        save(root/f'parse_done_worker{index}.json',{'gpu':gpu,'calls':rt.calls})
        while not (root/'question_universe_frozen.json').exists():
            require(time.time()<rt.deadline-15,'BUDGET_WAITING_FOR_QSET');time.sleep(1)
        universe=json.loads((root/'question_universe_frozen.json').read_text())
        for v in assignments:
            folder=root/'videos'/v['video_id'];status=json.loads((folder/'status.json').read_text())
            if status['status']!='PARSED':continue
            graph=json.loads((folder/'raw_graph.json').read_text());qs=json.loads((folder/'locked_candidates.json').read_text())
            require({q['question_id'] for q in qs['questions']}<={q['question_id'] for q in universe['questions']},'GLOBAL_QSET_MISMATCH')
            try:
                summary=evaluate_video(rt,json.loads((root/'media'/f'{v["video_id"]}.json').read_text()),folder,cfg,graph,qs)
                status.update(stage='COMPLETE',status='DONE',summary=summary)
            except Exception as e:status.update(stage='EVALUATION',status='PARTIAL',error=repr(e));emit('video_evaluation_partial',video=v['video_id'],error=repr(e))
            save(folder/'status.json',status)
    except Exception as e:
        save(work/'fatal.json',{'error':repr(e),'traceback':traceback.format_exc()});emit('worker_failed',index=index,error=repr(e));raise
    finally:
        import resource
        save(work/'allocation.json',{'gpu':gpu,'worker_wall_seconds':time.monotonic()-start,'model_loaded':rt is not None,'model_calls':rt.calls if rt else None,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})

def collect(root,cfg):
    statuses=[];questions=[];graphs={};rows={m:[] for m in ['B0','B1','B2']}
    for v in cfg['videos']:
        folder=root/'videos'/v['video_id']
        statuses.append(json.loads((folder/'status.json').read_text()) if (folder/'status.json').exists() else {'video_id':v['video_id'],'status':'NOT_RUN','stage':'PREPARATION'})
        if not (folder/'locked_candidates.json').exists():continue
        qs=json.loads((folder/'locked_candidates.json').read_text());questions+=qs['questions'];graphs[v['video_id']]=json.loads((folder/'raw_graph.json').read_text())
        for method,name in [('B0','b0_votes.json'),('B1','b1_program.json'),('B2','b2_selective.json')]:
            actual=json.loads((folder/name).read_text()) if (folder/name).exists() else []
            byid={r['question_id']:r for r in actual}
            for q in qs['questions']:rows[method].append(byid.get(q['question_id'],{'question_id':q['question_id'],'method':method,'status':'NOT_RUN','answer':None,'reason':'RUN_INCOMPLETE'}))
    save(root/'video_statuses.json',statuses);save(root/'all_questions.json',questions)
    for m,r in rows.items():save(root/f'{m}_all_questions.json',r)
    completed=all(r['status']!='NOT_RUN' for m in rows.values() for r in m)
    controls=matched_controls(questions,rows['B1'],rows['B2'],graphs,seed=cfg['selection_control_seed']) if completed else {'status':'NOT_RUN','reason':'Cannot match full-universe coverage with incomplete outputs','model_calls_added':0}
    save(root/'matched_coverage_controls.json',controls)
    requests=[];alloc=[]
    for p in sorted(root.glob('worker*/requests.jsonl')):requests += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    for p in sorted(root.glob('worker*/allocation.json')):alloc.append(json.loads(p.read_text()))
    summary={'stage':'GATE_B_FIVE_VIDEO_SMOKE','frozen_video_count':5,'videos_with_graph':len(graphs),'videos_with_candidate':sum(bool(json.loads((root/'videos'/vid/'locked_candidates.json').read_text())['questions']) for vid in graphs),
             'candidate_N':len(questions),'method_counts':{m:{s:sum(r['status']==s for r in rr) for s in ['ANSWERED','ABSTAIN','NOT_RUN']} for m,rr in rows.items()},
             'calls_by_role':dict(__import__('collections').Counter(r['role'] for r in requests)),'request_count':len(requests),'input_tokens':sum(r.get('input_tokens',0) for r in requests),'output_tokens':sum(r.get('output_tokens',0) for r in requests),
             'model_device_wall_seconds':sum(r.get('model_device_wall_seconds',0) for r in requests),'worker_allocated_gpu_hours':sum(a['worker_wall_seconds'] for a in alloc)/3600,
             'peak_allocated_bytes':max((r.get('peak_allocated_bytes',0) for r in requests),default=0),'peak_reserved_bytes':max((r.get('peak_reserved_bytes',0) for r in requests),default=0),
             'independent_gold':False,'precision':None,'correct_yield':None,'training_updates':0,'model_download_bytes':0,'old_engine_imports':False,'controls_model_calls':0,'all_locked_outputs_completed':completed}
    save(root/'summary.json',summary);emit('gate_b_summary',**summary)

def supervise(cfg):
    manifest=json.loads(Path(cfg['frozen_video_manifest']).read_text());require(len(manifest['selected'])==cfg['max_videos']==5,'FIVE_VIDEO_SCOPE_ONLY')
    root=Path('/scratch/haozhe/.cache/vlm-rsi/stsg-gate-b')/os.environ['ORX_RUN_ID'];root.mkdir(parents=True,exist_ok=False)
    cfg=copy.deepcopy(cfg);cfg['output_root']=str(root);cfg['videos']=[dict(v,video_id=Path(v['path']).stem) for v in manifest['selected']]
    cfg['manifest_sha256']=sha_file(cfg['frozen_video_manifest']);cfg['source_commit']=os.environ.get('ORX_COMMIT')
    geometry=json.loads((Path(cfg['model_path'])/'preprocessor_config.json').read_text())
    cfg['visual_resize_factor']=geometry['patch_size']*geometry['merge_size']
    save(root/'frozen_videos.json',manifest)
    # All media identities frozen before decode, model load or outputs.
    emit('gate_b_start',output_root=str(root),config=cfg)
    require(shutil.disk_usage('/scratch/haozhe').free>cfg['disk_reserve_bytes'],'INSUFFICIENT_DISK_RESERVE')
    gpu_lines=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True).splitlines()
    free=[line.split(',')[0].strip() for line in gpu_lines if float(line.split(',')[1])>40000 and float(line.split(',')[2])<5]
    require(bool(free),'NO_FREE_A40');gpus=free[:cfg['max_gpus']];cfg['gpu_count']=len(gpus);cfg['gpu_ids']=gpus
    save(root/'effective_config.json',cfg);os.environ['SMOKE_DEADLINE']=str(time.time()+cfg['wall_seconds']);deadline=float(os.environ['SMOKE_DEADLINE']);processes=[]
    try:
        for v in cfg['videos']:
            if cfg.get('reuse_media_root'):
                old=Path(cfg['reuse_media_root']);media=json.loads((old/'media'/f'{v["video_id"]}.json').read_text())
                require(sha_file(v['path'])==v['sha256']==media['video']['sha256'],'CACHED_MEDIA_SOURCE_CHANGED')
                for f in media['frames']:
                    require(sha_file(old/f['file'])==f['sha256'],'CACHED_FRAME_CHANGED')
                    target=root/f['file'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old/f['file'],target)
            else:media=prepare_media(v,root,resize_factor=cfg['visual_resize_factor'])
            save(root/'media'/f'{v["video_id"]}.json',media);emit('media_prepared',video=v['video_id'],frames=len(media['frames']),clips=len(media['clips']),decode_parity=media['decode_parity_passed'])
        # Exercise the actual Processor on CPU before occupying a GPU or loading weights.
        import torch
        from transformers import AutoProcessor
        encoder=object.__new__(FrozenRuntime);encoder.cfg=cfg;encoder.torch=torch
        encoder.processor=AutoProcessor.from_pretrained(cfg['model_path'],local_files_only=True)
        first=json.loads((root/'media'/f'{cfg["videos"][0]["video_id"]}.json').read_text())
        x,a=encoder.encode(first,[f['frame_id'] for f in first['frames']],'CPU processor parity check.')
        y,b=encoder.encode(first,[f['frame_id'] for f in first['frames']],'CPU processor parity check.')
        require(a['input_hashes']==b['input_hashes'],'CPU_ENCODE_REPLAY_MISMATCH')
        save(root/'cpu_processor_preflight.json',{'passed':True,'weights_loaded':False,**a})
        del x,y,encoder
        emit('cpu_processor_preflight_passed',resize_factor=cfg['visual_resize_factor'])
        def launch(i):
            env=dict(os.environ,CUDA_VISIBLE_DEVICES=gpus[i]);p=subprocess.Popen([sys.executable,'-m','stsg_pilot.smoke','--worker',str(i),'--config',str(root/'effective_config.json')],env=env);processes.append(p)
        launch(0)
        while not (root/'preflight_passed.json').exists():
            require(processes[0].poll() is None,'PREFLIGHT_PROCESS_FAILED');require(time.time()<deadline,'PREFLIGHT_TIMEOUT');time.sleep(1)
        emit('minimal_preflight_passed')
        for i in range(1,len(gpus)):launch(i)
        while not all((root/f'parse_done_worker{i}.json').exists() for i in range(len(gpus))):
            require(all(p.poll() is None or p.returncode==0 for p in processes),'PARSER_WORKER_FAILED');require(time.time()<deadline,'PARSE_TIMEOUT');time.sleep(1)
        questions=[]
        for v in cfg['videos']:
            p=root/'videos'/v['video_id']/'locked_candidates.json'
            if p.exists():questions+=json.loads(p.read_text())['questions']
        save(root/'question_universe_frozen.json',{'questions':questions,'question_set_sha256':digest(questions),'manifest_sha256':cfg['manifest_sha256'],'frozen_before_b0_checker':True})
        emit('global_question_universe_frozen',N=len(questions),sha256=digest(questions))
        while any(p.poll() is None for p in processes):
            require(time.time()<deadline,'WALL_BUDGET_REACHED')
            require(sum(p.stat().st_size for p in root.rglob('*') if p.is_file())<=cfg['storage_cap_bytes'],'STORAGE_BUDGET_REACHED')
            time.sleep(3)
        require(all(p.returncode==0 for p in processes),'EVALUATION_WORKER_FAILED')
    except Exception as e:
        save(root/'supervisor_failure.json',{'error':repr(e),'traceback':traceback.format_exc()});emit('supervisor_stopped',error=repr(e));raise
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        collect(root,cfg)
        Path('outputs').mkdir(exist_ok=True)
        save(Path('outputs')/(os.environ['ORX_RUN_ID']+'.json'),{'durable_output_root':str(root),'summary':json.loads((root/'summary.json').read_text())})

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',default='config/gate_b.json');ap.add_argument('--worker',type=int);a=ap.parse_args();cfg=json.loads(Path(a.config).read_text())
    require(not cfg['training'] and not cfg['reward_changes'] and not cfg['scaleup_authorized'],'FORBIDDEN_SCOPE')
    if a.worker is None:supervise(cfg)
    else:worker(cfg,a.worker,os.environ['CUDA_VISIBLE_DEVICES'])
if __name__=='__main__':main()
