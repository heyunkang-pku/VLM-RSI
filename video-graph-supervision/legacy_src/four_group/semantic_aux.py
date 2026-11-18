"""Text-only auxiliary equivalence, never alters clusters, answers or selection."""
from pathlib import Path
import json
from .routes import bounded
from step_six.common import j,rows,jl,make_runtime,choose_gpu,cost,allocation,parsejson
from stsg_pilot.runtime import save,emit

def execute(cfg,root,comparisons,media):
 root=Path(root);work=root/'semantic_aux';work.mkdir(parents=True,exist_ok=True);rt=make_runtime(cfg,work,'auxiliary_semantics',choose_gpu());out=[]
 try:
  for dataset,record in comparisons:
   qid=record['question_id'];p=work/'items'/(dataset+'_'+qid+'.json')
   if p.exists():row=j(p)
   elif not record['vote']['plurality_candidates']:row={'dataset':dataset,'question_id':qid,'status':'NOT_COMPARABLE_NO_VALID_VOTE','semantic_truth':'NOT_INDEPENDENT_TRUTH'}
   else:
    row={'dataset':dataset,'question_id':qid,'status':'UNRESOLVED','semantic_truth':'NOT_INDEPENDENT_TRUTH'}
    try:
     prompt='Compare two answer texts to the same question. This is semantic assistance, NOT correctness scoring and NOT video verification. Treat relational direction, subject/object roles, negation, counts and times strictly: table supports container can be compatible with container on table; table on container is NOT equivalent. Do not equate words by overlap. Compare frozen candidate answer against EACH highest-vote candidate independently. Labels: equivalent; compatible_detail_difference; contradictory; cannot_determine. Return JSON {"comparisons":[{"vote_candidate":"exact provided normalized string","label":"one label","reason":"specific role/claim comparison"}]}. Do not change answers, voting clusters or question.\n'+json.dumps({'question':record['question'],'candidate_answer':record['candidate_answer'],'highest_vote_candidates':record['vote']['plurality_candidates']},ensure_ascii=False)
     r,attempts=bounded(rt,media[record['video_id']],prompt,'auxiliary_answer_semantics',dataset+':'+qid,caps=(1024,2048));parsed=parsejson(r['raw_response']);cc=parsed['comparisons'];assert sorted(x['vote_candidate'] for x in cc)==sorted(record['vote']['plurality_candidates']);assert all(x['label'] in ['equivalent','compatible_detail_difference','contradictory','cannot_determine'] for x in cc);row.update(status='COMPARED',comparisons=cc,request_id=r['request_id'],attempts=attempts)
    except Exception as e:row.update(error=repr(e))
   save(p,row);out.append(row);emit('semantic_aux_complete',dataset=dataset,question=qid,status=row['status'])
  jl(work/'RESULTS.jsonl',out)
 finally:allocation(rt,work);save(work/'COST.json',cost(work))
