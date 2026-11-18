"""Freeze a raw-graph-only universe before any solver/checker/gold inputs exist."""
from itertools import combinations
from .core import validate_graph,freeze_question,digest,ContractError,require

def generate_candidates(raw_graph,*,seed=20261030,cap=5):
    require(type(cap) is int and cap>0,'BAD_QUESTION_CAP')
    _,_,_,facts=validate_graph(raw_graph)
    events=sorted((f for f in facts.values() if f['kind'] in ['event','motion']),key=lambda f:f['fact_id'])
    identities=sorted((f for f in facts.values() if f['kind']=='identity'),key=lambda f:f['fact_id'])
    questions=[];rejections=[]
    for a,b in combinations(events,2):
        if a['predicate']==b['predicate']:
            rejections.append({'events':[a['fact_id'],b['fact_id']],'reason':'INDISTINGUISHABLE_EVENT_WORDING'})
            continue
        links=([None] if a['subject_id']==b['subject_id'] else []) + [link['fact_id'] for link in identities
            if {a['subject_id'],b['subject_id']}=={link['subject_id'],link['object_id']}]
        if not links:
            rejections.append({'events':[a['fact_id'],b['fact_id']],'reason':'NO_IDENTITY_SUPPORT'})
        for link in links:
            for op in ['BEFORE','WHICH_FIRST']:
                p={'op':op,'args':[a['fact_id'],b['fact_id']],'identity_fact_id':link}
                try:questions.append(freeze_question(raw_graph,p,seed))
                except ContractError as e:rejections.append({'program':p,'reason':str(e)})
    # Stable pseudorandom order independent of model output, gold, or JSON row order.
    questions.sort(key=lambda q:digest([seed,q['program']]))
    chosen=questions[:cap]
    return {'raw_graph_sha256':digest(raw_graph),'seed':seed,'candidate_generated_from_raw_graph':True,
            'structural_candidate_count':len(questions),'question_cap':cap,
            'omitted_due_to_predeclared_cap':len(questions)-len(chosen),'rejections':rejections,
            'questions':chosen,'question_set_sha256':digest(chosen)}
