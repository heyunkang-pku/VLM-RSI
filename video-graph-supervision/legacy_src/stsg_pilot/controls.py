"""Zero-call matched-coverage selection controls over immutable B1 predictions."""
from copy import deepcopy
from .core import require,digest,frequency,validate_graph

def matched_controls(questions,b1,b2,graphs,seed=20261030):
    qmap={q['question_id']:q for q in questions}
    require(len(qmap)==len(questions),'DUPLICATE_QUESTION_ID')
    a={r['question_id']:r for r in b1};b={r['question_id']:r for r in b2}
    require(len(a)==len(b1) and len(b)==len(b2) and set(a)==set(b)==set(qmap),'MATCHED_CONTROL_JOIN')
    require(all(r['status']!='NOT_RUN' for r in b1+b2),'INCOMPLETE_SELECTION_CANNOT_MATCH')
    for i,r in b.items():
        if r['status']=='ANSWERED':
            require(a[i]['status']=='ANSWERED' and a[i]['answer']==r['answer'],'B2_CHANGED_B1_ANSWER')
    k=sum(r['status']=='ANSWERED' for r in b2)
    eligible=[i for i,r in a.items() if r['status']=='ANSWERED']
    require(k<=len(eligible),'B2_NOT_SUBSET_OF_B1')
    scores={}
    for i in eligible:
        q=qmap[i];g=graphs[q['video_id']];facts=validate_graph(g)[-1]
        scores[i]=min(frequency(g,facts[f]) for f in q['required_fact_ids'])
    random_ids=sorted(eligible,key=lambda i:digest([seed,i]))[:k]
    freq_ids=sorted(eligible,key=lambda i:(-scores[i],digest([seed,i])))[:k]
    results={}
    for name,chosen in [('B1-Random',random_ids),('B1-Frequency',freq_ids)]:
        rows=[]
        for i in qmap:
            r=deepcopy(a[i]);r['method']=name
            r['selection_score']=scores.get(i) if name=='B1-Frequency' else digest([seed,i])
            if i not in chosen:r.update(status='ABSTAIN',answer=None,reason='MATCHED_COVERAGE_FILTER')
            rows.append(r)
        results[name]=rows
    return {'N':len(questions),'target_accepted':k,'seed':seed,'matching':'global accepted count; no gold; eligible=B1 ANSWERED',
            'model_calls_added':0,'methods':results}
