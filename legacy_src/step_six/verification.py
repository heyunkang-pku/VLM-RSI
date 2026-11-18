"""VQS-style VIDEO adaptation: explicit question dependencies, accept/abstain only.
Never modifies the frozen candidate, native STEP ledger, or shared graph.
"""
import copy,json,re
from pathlib import Path
from .common import *
from step_native.native_verification import verdict

def dependency_closure(ids,facts):
 seen=set();missing=[]
 def add(fid):
  if fid in seen:return
  seen.add(fid)
  if fid not in facts:missing.append(fid);return
  for parent in facts[fid]['parent_ids']:add(parent)
 for fid in ids:add(fid)
 return sorted(seen),missing

def program_constraints(q,facts):
 # Program label resolution assumes uniqueness at each queried observation.
 # A partial graph cannot establish that by closed-world absence. Check it
 # against the actual image, rather than accepting "one recorded node" as truth.
 out=[]
 for fid in (q.get('program_read_trace',{}).get('value_and_parent_fact_ids',q['fact_ids']) if isinstance(q.get('program_read_trace',{}),dict) else q['fact_ids']):
  f=facts.get(fid)
  if not f or f['kind']!='object':continue
  c=f['content'];claim='Exactly one '+c['label']+' is visible in this frame, and it matches this description: '+c['referent']+'.'
  out.append({'claim':claim,'kind':'entity_resolution','fact_ids':[fid],'evidence_fact_id':fid,'constraint_origin':'program scope/class uniqueness; visual open-world check'})
 return out

def build_dependencies(rt,q,facts,media):
 ids,missing=dependency_closure(q['fact_ids'],facts);unresolved=[{'reason':'MISSING_GRAPH_DEPENDENCY','fact_id':x} for x in missing]
 deps=[{k:v for k,v in facts[f].items() if k in ['id','claim','kind','parent_ids','time_sec','content']} for f in ids if f in facts]
 # S route: consider full Q/A/R and semantic constraints, not just rationale entities.
 # P: all executable read dependencies incl referent descriptions must be atomized.
 prompt='Act as a conservative dependency compiler, NOT a video answerer. Analyze the entire frozen question, candidate answer, and rationale/program including all referring descriptions, uniqueness, attributes, relationships, movement, cross-frame physical identity and temporal constraints. Return the COMPLETE answer-dependent atomic visual facts. Split compound descriptions into individual claims. Each claim must map to provided graph fact IDs, never invent a graph fact. Include at least one atomic claim for EVERY required_dependency_id and all of its referring attributes/relations. A graph fact ID may support multiple atoms. Preserve observation times. If any semantic dependency cannot be completely identified, mapped, or distinguished from a graph assumption, set complete=false with reasons. Do not rewrite Q/A/R. Return JSON {"complete":true/false,"unresolved":["reason"],"covered_dependency_ids":["id"],"required_kinds":["object|attribute|relation|identity|motion|time|entity_resolution"],"claims":[{"claim":"atomic visual statement","kind":"one kind","fact_ids":["id"],"evidence_fact_id":"one provided id"}]} .\n'+json.dumps({'question':q['question'],'answer':q['answer'],'rationale':q.get('rationale'),'program':q.get('program'),'execution_read_trace':q.get('program_read_trace'),'required_dependency_ids':ids,'graph_facts':deps,'clip_time_context':q.get('time_range_sec')},ensure_ascii=False)
 r=ask(rt,media[q['video_id']],prompt,'VQS_video_dependency_compiler',q['question_id'],'text',4096);parsed=parsejson(r['raw_response']);atoms=parsed.get('claims',[])
 if not isinstance(atoms,list):raise ValueError('ATOMIC_CLAIMS_NOT_LIST')
 covered=set()
 for atom in atoms:
  if not isinstance(atom.get('claim'),str) or not atom['claim'].strip():unresolved.append({'reason':'EMPTY_ATOMIC_CLAIM'});continue
  fids=atom.get('fact_ids',[]);e=atom.get('evidence_fact_id')
  if not fids or any(fid not in ids for fid in fids) or e not in fids:unresolved.append({'reason':'UNMAPPED_ATOMIC_CLAIM','claim':atom});continue
  covered.update(fids)
 if set(ids)-covered:unresolved.append({'reason':'UNCOVERED_REQUIRED_GRAPH_FACTS','ids':sorted(set(ids)-covered)})
 if set(parsed.get('covered_dependency_ids',[]))!=set(ids):unresolved.append({'reason':'COMPILER_COVERAGE_DECLARATION_MISMATCH'})
 if parsed.get('complete') is not True:unresolved.append({'reason':'COMPILER_DECLARED_INCOMPLETE','details':parsed.get('unresolved',[])})
 if parsed.get('unresolved'):unresolved.append({'reason':'SEMANTIC_DEPENDENCIES_UNRESOLVED','details':parsed['unresolved']})
 # Do not turn coarse holistic event descriptions into verified action timing.
 for fid in ids:
  if fid in facts and facts[fid].get('unresolved_reason'):unresolved.append({'reason':facts[fid]['unresolved_reason'],'fact_id':fid})
 if not atoms:unresolved.append({'reason':'EMPTY_CLAIM_SET_CANNOT_PASS'})
 kinds=set(a.get('kind') for a in atoms)
 if set(parsed.get('required_kinds',[]))-kinds:unresolved.append({'reason':'MISSING_REQUIRED_SEMANTIC_TYPE','kinds':sorted(set(parsed['required_kinds'])-kinds)})
 if q['route']=='P':atoms+=program_constraints(q,facts)
 # Independent coverage audit of ALL Q/A/R text against explicit atoms. This is
 # model-assisted completeness evidence, never independent truth/accuracy.
 auditprompt='Audit dependency coverage conservatively. Does this atomic list cover EVERY visual assumption needed for the frozen question and proposed answer, including referent descriptions, uniqueness, identity, time, and reasoning steps? Output JSON {"complete":true/false,"missing":["specific missing assumption"]}. Do not answer the question.\n'+json.dumps({'question':q['question'],'candidate_answer':q['answer'],'rationale':q.get('rationale'),'program':q.get('program'),'atomic_claims':atoms},ensure_ascii=False)
 ar=ask(rt,media[q['video_id']],auditprompt,'VQS_full_question_dependency_coverage_audit',q['question_id'],'text',1024);audit=parsejson(ar['raw_response'])
 if audit.get('complete') is not True or audit.get('missing'):unresolved.append({'reason':'FULL_QUESTION_COVERAGE_UNRESOLVED','audit':audit})
 return {'request_id':r['request_id'],'coverage_audit_request_id':ar['request_id'],'complete':not unresolved,'unresolved':unresolved,'required_ids':ids,'atoms':atoms,'raw_compilation':parsed,'coverage_audit':audit,'completeness_is_model_assisted_not_independent_truth':True}

def checker_media(atom,facts,media):
 f=facts[atom['evidence_fact_id']];kind=atom['kind']
 if kind in ['motion','identity','time'] or f['verification_mode']=='video':
  m=copy.deepcopy(media[f['video_id']]);m['clip_intervals']=[atom.get('time_range_sec',f.get('content',{}).get('observation_interval_sec',[0,max(x['time_sec'] for x in m['class_video_views'])]))];return m,'video'
 return copy.deepcopy(f['media']),'image'

def verify_question(rt,q,facts,media,root):
 path=root/'per_question'/(q['question_id']+'.json')
 if path.exists():return j(path)
 before=h(q);row={'question_id':q['question_id'],'route':q['route'],'frozen_answer':q['answer'],'frozen_question_sha256':before,'status':'UNRESOLVED','accepted_answer':None,'native_STEP_verification_is_separate':True,'human_accuracy':'PENDING'}
 try:
  dep=build_dependencies(rt,q,facts,media);row['dependencies']=dep;checks=[]
  for ix,atom in enumerate(dep['atoms']):
   if atom.get('evidence_fact_id') not in facts:continue
   try:
    m,mode=checker_media(atom,facts,media);prompt=atom['claim']+'\nLooking only at the '+('image' if mode=='image' else 'supplied video frames and their authoritative times')+', is that statement true? Answer with one word, YES or NO.'
    r=ask(rt,m,prompt,'VQS_question_conditioned_atomic_fact',q['question_id']+':'+str(ix),mode,4);v=verdict(r['raw_response']);check={**atom,'verdict':v,'request_id':r['request_id'],'raw_response':r['raw_response'],'input_hashes':r['input_hashes'],'frame_content_hashes':r['frame_content_hashes'],'visual_mode':mode,'model_revision':rt.cfg['model_revision']}
   except Exception as e:check={**atom,'verdict':'UNRESOLVED','error':repr(e)}
   checks.append(check);append(root/'CHECKER_LEDGER.jsonl',{'question_id':q['question_id'],'atomic_index':ix,**check})
  row['checks']=checks
  if any(c['verdict']=='NO' for c in checks):row['status']='ABSTAIN_FACT_REJECTED'
  elif dep['complete'] and checks and len(checks)==len(dep['atoms']) and all(c['verdict']=='YES' for c in checks):row.update(status='ACCEPT',accepted_answer=q['answer'])
  else:row['status']='UNRESOLVED_DEPENDENCY_OR_VISUAL'
 except Exception as e:row.update(status='UNRESOLVED_COMPILER_FAILURE',error=repr(e))
 assert h(q)==before;save(path,row);return row
