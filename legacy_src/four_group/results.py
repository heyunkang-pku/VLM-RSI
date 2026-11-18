import json,re,collections,csv,copy
from pathlib import Path
from step_six.common import norm,j,rows,jl,filehash
from stsg_pilot.runtime import save

def aggregate(samples,n=10):
 counts=collections.Counter(norm(s['answer']) for s in samples if s.get('status')=='VALID' and s.get('answer') is not None and norm(s['answer']));rank=sorted(counts.items(),key=lambda kv:(-kv[1],kv[0]));top=rank[0][1] if rank else 0;winners=[a for a,c in rank if c==top];tie=len(winners)>1;strict=top>n/2 and not tie
 return {'votes':dict(counts),'ranked_votes':rank,'plurality_candidates':winners,'plurality_answer':winners[0] if len(winners)==1 else None,'top_vote_count':top,'top_vote_fraction':top/n,'tie':tie,'no_valid_answer':not rank,'strict_majority_status':'ANSWERED' if strict else 'ABSTAIN','strict_majority_answer':winners[0] if strict else None,'strict_abstention_reason':None if strict else ('NO_VALID_ANSWER' if not rank else 'TOP_VOTE_TIE' if tie else 'NO_STRICT_MAJORITY'),'fixed_denominator':n,'valid_samples':sum(counts.values()),'sample_status_counts':dict(collections.Counter(s.get('status','MISSING') for s in samples))}

def risks(q):
 text=q['question'];return {'internal_ids':re.findall(r'\b\w+\d+\b',text),'whole_clip_assertion':bool(re.search(r'throughout|entire|consistently',text+' '+str(q.get('answer')),re.I)),'set_answer':isinstance(q.get('answer'),list),'generic_referent':bool(re.search(r'\b(surface|object|thing|item)\b',text,re.I)),'flags_are_diagnostics_not_filters':True}

def export_comparison(qs,votes,out,split):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);records=[];groups=[]
 for q in qs:
  v=votes.get(q['question_id']);samples=v.get('samples',[]) if v else [];assert not samples or len(samples)==10
  agg=aggregate(samples);record={'question_id':q['question_id'],'video_id':q['video_id'],'route':q['route'],'question':q['question'],'candidate_answer':q['answer'],'candidate_raw_source':q.get('refinement_request_id','deterministic_program'),'rationale':q.get('rationale'),'program':q.get('program'),'dependencies':q.get('program_read_trace',q.get('fact_ids')),'split':split,'vote':agg,'samples':samples,'candidate_normalized':norm(q['answer']),'plurality_exact_equal':norm(q['answer'])==agg['plurality_answer'] if agg['plurality_answer'] is not None else None,'strict_exact_equal':norm(q['answer'])==agg['strict_majority_answer'] if agg['strict_majority_answer'] is not None else None,'risk_flags':risks(q),'accuracy':'PENDING_NO_MATCHED_GOLD','semantic_aux':'PENDING'};records.append(record)
  groups+=[{'group':q['route']+'0','question_id':q['question_id'],'question':q['question'],'plurality':agg['plurality_answer'],'plurality_candidates':agg['plurality_candidates'],'strict_majority':agg['strict_majority_answer'],'vote':agg},{'group':q['route']+'1','question_id':q['question_id'],'question':q['question'],'answer':q['answer'],'meaning':'native generated/refined answer' if q['route']=='S' else 'program result conditional on automatic graph, NOT visual truth'}]
 jl(out/'PER_QUESTION.jsonl',records);jl(out/'FOUR_GROUP_RESULTS.jsonl',groups)
 with (out/'COMPARISON.csv').open('w',encoding='utf-8-sig',newline='') as fp:
  names=['question_id','video_id','route','question','candidate_answer','plurality_candidates','top_vote_count','votes','strict_majority_answer','strict_abstention_reason','plurality_exact_equal','strict_exact_equal'];w=csv.DictWriter(fp,fieldnames=names);w.writeheader()
  for r in records:w.writerow({k:json.dumps(r.get(k,r['vote'].get(k)),ensure_ascii=False) for k in names})
 summary={}
 for route in ['S','P']:
  rr=[x for x in records if x['route']==route];summary[route]={'questions':len(rr),'ties':sum(x['vote']['tie'] for x in rr),'no_valid':sum(x['vote']['no_valid_answer'] for x in rr),'strict_answered':sum(x['vote']['strict_majority_status']=='ANSWERED' for x in rr),'plurality_comparable':sum(x['plurality_exact_equal'] is not None for x in rr),'plurality_exact_matches':sum(x['plurality_exact_equal'] is True for x in rr),'strict_comparable':sum(x['strict_exact_equal'] is not None for x in rr),'strict_exact_matches':sum(x['strict_exact_equal'] is True for x in rr),'top_fraction_distribution':[x['vote']['top_vote_fraction'] for x in rr]}
 save(out/'SUMMARY.json',{'split':split,'routes':summary,'vote_draws':sum(len(x['samples']) for x in records),'accuracy':'PENDING','agreement_is_not_accuracy':True});return records

def old33(source,original,out):
 source=Path(source);original=Path(original);out=Path(out);out.mkdir(parents=True,exist_ok=True)
 qs=rows(source/'S_FROZEN_QA.jsonl')+rows(source/'P_FROZEN_QA.jsonl');assert len(qs)==33;votes={};raw={}
 for folder in [original,source]:
  for p in folder.glob('solver/shard_*/runtime/requests.jsonl'):
   for r in rows(p):
    if r['role']=='VideoZero_v4_majority_sample':raw[r['owner']]=r
 for p in source.glob('solver/shard_*/questions/*/VOTE.json'):
  v=j(p)
  for s in v['samples']:
   owner=v['question_id']+':'+str(s['sample_index']);r=raw.get(owner)
   if r:
    assert r['model_revision']=='9b5f72f0afab975893cec22fcbff9e8619a2851f/v4';s['raw_response']=r.get('raw_response');s['output_hit_cap']=r.get('output_hit_cap');s['actual_input_hashes']=r.get('input_hashes');s['actual_pixel_hashes']=r.get('frame_content_hashes');s['actual_times_sec']=r.get('actual_source_times_sec');s['original_request_id']=r['request_id'];s['revision']=r['model_revision']
   else:raise ValueError('OLD_RAW_CALL_NOT_FOUND:'+owner)
  votes[v['question_id']]=v
 manifest={n:filehash(source/n) for n in ['GRAPH_SHARED_FROZEN.json','S_FROZEN_QA.jsonl','P_FROZEN_QA.jsonl','VIDEO_INPUTS_FROZEN.json','QUESTION_FREEZE_MANIFEST.json']};assert all(manifest[n]==filehash(original/n) for n in ['GRAPH_SHARED_FROZEN.json','P_FROZEN_QA.jsonl','VIDEO_INPUTS_FROZEN.json'])
 save(out/'REUSE_MANIFEST.json',{'source':str(source),'original':str(original),'hashes':manifest,'queries':33,'raw_vote_calls_reconstructed':len(raw),'no_new_model_calls':True,'historical_S2_P2_not_read_or_used_for_selection':True});return export_comparison(qs,votes,out,'DEVELOPMENT_33')
