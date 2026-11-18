"""Development-only v3. Main facts and auxiliary judgments never share gates."""
import copy,json
from .dependencies import p_dependencies,validate_requirements
from .gates_v2 import p_annotations
from .semantic_v2 import s_dependencies as strict_s_dependencies
from .semantic import bounded_call
from step_six.common import parsejson

def p_main(q,facts,ledger,pairs,graph):
 dep=p_dependencies(q,facts,ledger,pairs,graph)
 strict=p_annotations(dep,q,facts)
 # Existence remains a positive prerequisite. Class uniqueness is a public
 # referring/ambiguity judgment, NOT a positive program fact or fact NO.
 dep['ambiguity_requirements']=[x for x in dep['atoms'] if x['kind']=='entity_resolution']
 dep['atoms']=[x for x in dep['atoms'] if x['kind']!='entity_resolution'];dep['requirements']=dep['atoms']
 dep['unresolved']=[x for x in dep['unresolved'] if x['reason'] not in ['NON_NECESSARY_ATOM_IN_CHECK_SET','EMPTY_NECESSARY_DEPENDENCY_SET']];dep['unresolved']+=validate_requirements(dep['atoms'],facts);dep['complete']=not dep['unresolved']
 dep['question_ambiguity']={'status':'PENDING_INDEPENDENT_REVIEW','referring_bindings':strict['referring_bindings'],'flags':[x for x in strict['unresolved'] if x['reason']=='PUBLIC_REFERENCE_INSUFFICIENTLY_QUALIFIED'],'uniqueness_requirements':dep['ambiguity_requirements'],'does_not_veto_positive_fact_status':True}
 dep['answer_completeness']={**strict['relation_completeness'],'status':'UNVERIFIED' if q['program']['op']=='relation' else 'PROGRAM_RETURN_VALUE_FROZEN_NOT_A_GLOBAL_QA_CORRECTNESS_PROOF','does_not_veto_positive_fact_status':True}
 dep['reasoning_review']={'status':'NOT_APPLICABLE_NO_NATIVE_RATIONALE','program_trace_retained':True}
 dep['main_acceptance_scope']='positive facts conditional on frozen program entity/time bindings; NOT public referent uniqueness or exhaustive real-world relation answer'
 dep['required_kinds']=sorted({x['kind'] for x in dep['atoms']});return dep

def s_main(rt,q,facts,media):
 original=copy.deepcopy(q);mainq=copy.deepcopy(q);mainq['rationale']=''
 # The frozen graph path remains an evidence-search hint. Rationale text is
 # never fed into main source requirements and never creates main premises.
 dep=strict_s_dependencies(rt,mainq,facts,media)
 dep['rationale_evidence_hints']={'graph_fact_ids':q.get('fact_ids',[]),'untrusted_rationale_retained_separately':True,'not_a_necessary_fact_list':True}
 dep['main_acceptance_scope']='question-required referring constraints and verifiable frozen answer assertions only'
 dep['question_ambiguity']={'status':'PENDING_INDEPENDENT_REVIEW','required_referring_constraints_in_main':True}
 dep['answer_completeness']={'status':'MAIN_AUDIT_COVERS_ASSERTIONS_PRESENT_IN_FROZEN_ANSWER; independent answer sufficiency pending'}
 prompt='Review the rationale separately from main answer verification. Do not answer or rewrite the frozen Q/A/R. This is TEXT/graph-consistency review, not a visual fact check. List unsupported inference, contradiction, irrelevant background or missing logical steps. Rationale may suggest where evidence should be sought, but must not add conditions to the main answer acceptance gate. Return JSON {"status":"text_review_complete","issues":[{"text":"rationale fragment","reason":"specific issue","type":"contradiction OR unsupported OR irrelevant OR missing_step"}],"evidence_hints":["where to look"],"visual_truth":"NOT_EVALUATED"}.\n'+json.dumps({'question':q['question'],'frozen_answer':q['answer'],'rationale':q.get('rationale'),'main_requirements':dep['atoms']},ensure_ascii=False)
 try:
  r,attempts=bounded_call(rt,media[q['video_id']],prompt,'V3_SEPARATE_REASONING_REVIEW',q['question_id'],caps=(2048,4096));review=parsejson(r['raw_response'])
  if not isinstance(review,dict) or not isinstance(review.get('issues'),list):raise ValueError('REASONING_REVIEW_INTERFACE')
  dep['reasoning_review']={'status':'TEXT_REVIEW_ONLY','model_review':review,'request_id':r['request_id'],'attempts':attempts,'visual_truth':'NOT_EVALUATED','does_not_veto_main_status':True}
 except Exception as e:dep['reasoning_review']={'status':'UNRESOLVED_TEXT_REVIEW','error':repr(e),'does_not_veto_main_status':True}
 assert q==original;return dep
