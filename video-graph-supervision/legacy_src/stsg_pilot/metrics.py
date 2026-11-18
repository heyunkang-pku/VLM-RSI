"""Exploratory diagnostics only; no weighted/cluster CI estimator claimed at Gate A."""
from .core import require, unique

def summarize(question_ids,rows,gold,method):
    unique(question_ids,'DUPLICATE_QUESTION_ID');n=len(question_ids)
    rs=[r for r in rows if r['method']==method]
    require(len(rs)==n and {r['question_id'] for r in rs}==set(question_ids),'INCOMPLETE_OR_DUPLICATE_JOIN')
    require(all(r['status'] in ['NOT_RUN','ABSTAIN','ANSWERED'] for r in rs),'STATUS_ENUM')
    require(all((r['answer'] is not None)==(r['status']=='ANSWERED') for r in rs),'STATUS_ANSWER_MISMATCH')
    require(set(gold)<=set(question_ids),'UNKNOWN_GOLD_ID')
    missing=sum(r['status']=='NOT_RUN' for r in rs)
    if not n or missing:
        return {'status':'NOT_RUN' if not n or missing==n else 'INCOMPLETE','N':n,'not_run':missing,
                'coverage':None,'precision':None,'correct_yield':None,'hard_correct_yield':None}
    accepted=[r for r in rs if r['status']=='ANSWERED']
    eligible={i:g for i,g in gold.items() if g['gold_status']=='valid' and g['gold_answer_confidence'] in ['high','medium']}
    checked=[r for r in accepted if r['question_id'] in eligible]
    correct=[r for r in checked if r['answer']==eligible[r['question_id']]['gold_answer']]
    gold_complete=len(gold)==n
    eligible_hard=[i for i,g in eligible.items() if 'empirical_hard' in g]
    hard_complete=gold_complete and len(eligible_hard)==len(eligible)
    return {'status':'COMPLETE_INFERENCE','N':n,'accepted':len(accepted),'not_run':0,
            'coverage':len(accepted)/n,'accepted_with_valid_gold':len(checked),
            'precision':len(correct)/len(checked) if checked else None,
            'observed_correct_count':len(correct),'missing_gold_count':n-len(gold),
            'gold_status_counts':{s:sum(g['gold_status']==s for g in gold.values()) for s in ['valid','ambiguous','unanswerable','insufficient_visual_evidence']},
            'low_confidence_excluded':sum(g['gold_status']=='valid' and g['gold_answer_confidence']=='low' for g in gold.values()),
            'correct_yield':len(correct) if gold_complete else None,
            'correct_yield_on_all_candidates':len(correct)/n if gold_complete else None,
            'hard_correct_yield':sum(eligible[r['question_id']]['empirical_hard'] for r in correct) if hard_complete else None,
            'hard_correct_rate_on_all_candidates':sum(eligible[r['question_id']]['empirical_hard'] for r in correct)/n if hard_complete else None,
            'estimand':'high/medium confidence valid gold; unweighted reviewed subset; not population precision if sampled'}
