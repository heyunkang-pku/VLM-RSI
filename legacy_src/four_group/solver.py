"""Isolated unchanged10draw VideoZero-v4 adapter; no verifier imports."""
from .results import *
from step_six.common import *
def solver_worker(cfg,root,index,count,gpu):
 # Input isolation: this function reads ONLY public questions, input manifests
 # and decoding config. No graph, candidate answer, rationale, or program read.
 done=set(j(root/'REUSED_COMPLETED_QUESTION_IDS.json')) if (root/'REUSED_COMPLETED_QUESTION_IDS.json').exists() else set();qc=[q for q in rows(root/'SOLVER_QUESTIONS_ONLY.jsonl') if q['question_id'] not in done][index::count];media=j(root/'VIDEO_INPUTS_FROZEN.json');sc=dict(cfg,model_path=cfg['solver_model_path'],model_revision=cfg['solver_model_revision']);work=root/'solver'/('shard_'+str(index));rt=make_runtime(sc,work,'solver'+str(index),gpu);rt.mode='video'
 try:
  for q in qc:
   results=[];out=work/'questions'/q['question_id'];out.mkdir(parents=True,exist_ok=True)
   for ix in range(cfg['vote_samples']):
    p=out/(str(ix)+'.json')
    if p.exists():sample=j(p)
    else:
     sample={'question_id':q['question_id'],'sample_index':ix,'seed':cfg['vote_seed']+ix,'status':'FAILED','answer':None}
     try:
      prompt='Answer the question using only the supplied video and question. Return JSON {"answer":"concise answer"}. If the video does not support an unambiguous answer, return {"answer":null}. Do not guess invisible facts.\nQuestion: '+q['question']
      if media[q['video_id']].get('public32'):
       prompt='Use only the public video frames and question. Return JSON {"answer":"concise answer"}; use null when unsupported or ambiguous. Attribute answers must name only the requested value. For spatial/contact relation questions also return nonempty string fields subject, relation, object in the requested direction and make answer a complete subject-relation-object clause. Do not emit a bare preposition.\nQuestion: '+q['question']
      r=ask(rt,media[q['video_id']],prompt,'VideoZero_v4_majority_sample',q['question_id']+':'+str(ix),'video',cfg['vote_max_tokens'],cfg['vote_temperature'],cfg['vote_seed']+ix);sample.update(raw_response=r['raw_response'],request_id=r['request_id']);parsed=parsejson(r['raw_response']);a=parsed.get('answer')
      if media[q['video_id']].get('public32') and ('spatial or contact relationship' in q['question'].lower()) and a is not None:
       assert all(isinstance(parsed.get(k),str) and parsed[k].strip() for k in ['subject','relation','object']),'RELATION_FORMAT_MISSING_DIRECTION_FIELDS'
       sample['direction_fields']={k:parsed[k] for k in ['subject','relation','object']}
      sample.update(status='VALID' if isinstance(a,(str,list)) and bool(norm(a)) and norm(a) not in ['uncertain','unknown','cannot determine','not sure'] else 'ABSTAIN',answer=a,request_id=r['request_id'],raw_response=r['raw_response'])
     except Exception as e:sample['error']=repr(e)
     save(p,sample)
    results.append(sample)
   aggregate={'question_id':q['question_id'],'route':q['route'],'group':q['route']+'0',**vote(results,cfg['vote_samples']),'samples':results};save(out/'VOTE.json',aggregate);emit('majority_vote_complete',question=q['question_id'],status=aggregate['status'],votes=aggregate['top_vote_count'])
 finally:allocation(rt,work);save(work/'COST.json',cost(work))

