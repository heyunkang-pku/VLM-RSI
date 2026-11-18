"""S-only justified semantic coverage. Necessary assertions vs background."""
import json,re
from .dependencies import requirement,validate_requirements,rounded_binding,s_time_bindings
from step_six.common import parsejson,h,save

def bounded_call(rt,m,prompt,role,owner,mode='text',caps=(2048,4096)):
 attempts=[]
 for cap in caps:
  rt.mode=mode;r=rt.ask(m,[],prompt,role=role,owner=owner,seed=2026110103,temperature=0,max_tokens=cap);attempts.append({'request_id':r['request_id'],'cap':cap,'output_hit_cap':r['output_hit_cap']})
  if not r['output_hit_cap']:return r,attempts
 raise ValueError('BOUNDED_OUTPUT_CAP_EXHAUSTED:'+json.dumps(attempts))

def clauses(q):
 out=[]
 for field in ['question','answer','rationale']:
  value=q.get(field,'');text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
  for i,part in enumerate(re.split(r'(?<=[.!?])\s+|\n+',text)):
   if part.strip():out.append({'clause_id':field+':'+str(i),'source_field':field,'text':part.strip()})
 return out

def s_dependencies(rt,q,facts,media):
 cs=clauses(q);known=set(q['fact_ids']);scopes={facts[x].get('scope') for x in known if x in facts};available=[f for f in facts.values() if f['video_id']==q['video_id'] and (f['id'] in known or f.get('scope') in scopes)]
 # All graph evidence at relevant observations is eligible, not only entity
 # mentions in rationale. Unmapped claims stay unresolved rather than invented.
 catalog=[{k:f[k] for k in ['id','kind','claim','parent_ids'] if k in f}|({'time_sec':f['time_sec']} if 'time_sec' in f else {}) for f in available];allowed={f['id'] for f in available};reqs=[];issues=[];calls=[]
 for c in cs:
  prompt='Analyze ONLY this quoted clause within the frozen question/answer/rationale. Do not answer or rewrite it. Extract atomic VISUAL requirements. Every assertion made by the candidate ANSWER must be covered, even extra detail. A QUESTION referring constraint is necessary only when needed to identify what is asked. RATIONALE-only details are background unless an explicit link explains why the frozen answer depends on them. Do not require all STEP graph path nodes or all semantic categories by default. Never infer tracking, movement or invariance from two equal class labels. Rounded printed times are observation anchors with half-last-decimal tolerance, not new exact timestamps. Classify each item necessary/background/unresolved, give a counterfactual reason (what changes in question binding or frozen answer if it fails). If relevance is uncertain mark unresolved, not background. Map claims to graph IDs; never invent evidence. Quote an exact substring of this clause. Return JSON {"requirements":[{"quote":"verbatim substring","claim":"one atomic statement","kind":"object OR attribute OR relation OR identity OR motion OR time OR entity_resolution","necessity":"necessary OR background OR unresolved","reason":"explicit dependency/counterfactual reason","fact_ids":["existing IDs"],"evidence_fact_id":"one ID","evidence_scope":"observation OR interval OR full_clip","why_other_path_facts_not_needed":"optional rationale"}],"clause_covered":true,"unresolved":["specific missing dependency"]}. At most8 atomic items; if insufficient say clause_covered=false. No unrelated background assumptions.\n'+json.dumps({'frozen_question':q['question'],'frozen_answer':q['answer'],'frozen_rationale':q.get('rationale'),'clause':c,'available_graph_evidence':catalog},ensure_ascii=False)
  try:
   r,attempts=bounded_call(rt,media[q['video_id']],prompt,'S2_justified_clause_requirements',q['question_id']+':'+c['clause_id']);calls+=attempts;p=parsejson(r['raw_response']);items=p['requirements'];assert isinstance(items,list)
   if p.get('clause_covered') is not True or p.get('unresolved'):issues.append({'reason':'CLAUSE_DEPENDENCIES_UNRESOLVED','clause_id':c['clause_id'],'details':p.get('unresolved')})
   if not items and c['source_field'] in ['question','answer']:issues.append({'reason':'EMPTY_QUESTION_OR_ANSWER_CLAUSE_COVERAGE','clause_id':c['clause_id']})
   for i,a in enumerate(items):
    if a.get('necessity') not in ['necessary','background','unresolved'] or not a.get('reason') or not a.get('quote') or a['quote'] not in c['text']:issues.append({'reason':'INVALID_REQUIREMENT_REASON_OR_QUOTE','clause_id':c['clause_id'],'item':a});continue
    if a.get('kind') not in ['object','attribute','relation','identity','motion','time','entity_resolution']:issues.append({'reason':'UNSUPPORTED_SEMANTIC_KIND','item':a});continue
    a.update(requirement_id='Sreq_'+h([q['question_id'],c['clause_id'],i,a])[:16],source_field=c['source_field'],clause_id=c['clause_id'],compiler_request_id=r['request_id']);reqs.append(a)
    if a['necessity']=='unresolved':issues.append({'reason':'REQUIREMENT_NECESSITY_UNRESOLVED','requirement_id':a['requirement_id']})
    if a['necessity']=='necessary' and any(x not in allowed for x in a.get('fact_ids',[])):issues.append({'reason':'GRAPH_EVIDENCE_OUTSIDE_DECLARED_CATALOG','requirement_id':a['requirement_id']})
  except Exception as e:issues.append({'reason':'CLAUSE_COMPILER_FAILURE','clause_id':c['clause_id'],'error':repr(e)})
 for clause in cs:
  if clause['source_field']=='answer' and not any(a['clause_id']==clause['clause_id'] and a['necessity']=='necessary' for a in reqs):issues.append({'reason':'ANSWER_CLAUSE_HAS_NO_NECESSARY_ASSERTION','clause_id':clause['clause_id']})
 # A second, scoped coverage auditor must cite an actual clause and explain
 # answer dependence; naked "motion/time missing" flags cannot become facts.
 prompt='Audit necessary dependency coverage for the frozen Q/A and supporting rationale. Check every Q/A assertion and every reference required to resolve the question. Rationale background is not automatically necessary. Do NOT demand motion/identity/temporal facts just because they are possible types. Do not reject half-last-decimal source-time rounding. Check classifications and justify any missing requirement by an exact clause quote and answer dependency. Return JSON {"clause_reviews":[{"clause_id":"ID","decision":"covered OR background_only OR missing OR unresolved","reason":"why; for missing explain counterfactual effect on answer","missing_requirements":[{"quote":"exact clause substring","claim":"atomic missing assertion","kind":"one kind","reason":"why needed","fact_ids":["IDs if known"]}]}]}. Cover each input clause exactly once. A question/answer clause can be background_only only for nonassertive grammatical scaffolding with explicit reason. Do not invent missing claims or treat all graph-path nodes as necessary.\n'+json.dumps({'question':q['question'],'answer':q['answer'],'clauses':cs,'requirements':reqs},ensure_ascii=False)
 try:
  r,attempts=bounded_call(rt,media[q['video_id']],prompt,'S2_scoped_necessity_coverage_audit',q['question_id'],caps=(4096,8192));calls+=attempts;audit=parsejson(r['raw_response']);seen=[]
  for row in audit['clause_reviews']:
   cid=row.get('clause_id');seen.append(cid);c=next((c for c in cs if c['clause_id']==cid),None)
   if not c or not row.get('reason') or row.get('decision') not in ['covered','background_only','missing','unresolved']:issues.append({'reason':'INVALID_COVERAGE_AUDIT_ROW','row':row});continue
   if row['decision'] in ['missing','unresolved']:issues.append({'reason':'NECESSARY_COVERAGE_UNRESOLVED','clause_id':cid,'audit':row})
   if row['decision']=='background_only' and c['source_field']=='answer':issues.append({'reason':'ANSWER_ASSERTION_DISMISSED_AS_BACKGROUND','clause_id':cid,'audit':row})
   for missing in row.get('missing_requirements',[]):
    if not missing.get('quote') or missing['quote'] not in c['text'] or not missing.get('reason'):issues.append({'reason':'AUDITOR_UNGROUNDED_EXTRA_REQUIREMENT','clause_id':cid,'audit':missing})
  if sorted(seen)!=sorted(c['clause_id'] for c in cs):issues.append({'reason':'AUDIT_CLAUSE_COVERAGE_MISMATCH'})
 except Exception as e:audit={'error':repr(e)};issues.append({'reason':'COVERAGE_AUDIT_FAILURE','error':repr(e)})
 atoms=[a for a in reqs if a['necessity']=='necessary'];issues+=validate_requirements(atoms,facts)
 times=s_time_bindings(q,facts)
 for t in times:
  if not t['consistent']:issues.append({'reason':'PRINTED_TIME_ANCHOR_UNRESOLVED','binding':t})
 if re.search(r'\bthroughout\b|\bconsistently\b|\bentire (?:video|clip)\b',q['question']+' '+str(q['answer']),re.I):issues.append({'reason':'FULL_CLIP_ASSERTION_NOT_PROVABLE_FROM_SPARSE_FROZEN_FRAMES','basis':'literal frozen Q/A extent quantifier'})
 for a in atoms:
  if a.get('evidence_scope')=='full_clip':issues.append({'reason':'FULL_CLIP_ASSERTION_NOT_PROVABLE_FROM_SPARSE_FROZEN_FRAMES','requirement_id':a['requirement_id']})
  if a.get('kind')=='motion' and any(facts.get(x,{}).get('unresolved_reason') for x in a.get('fact_ids',[])):issues.append({'reason':'MOTION_GROUNDING_UNRESOLVED','requirement_id':a['requirement_id']})
 return {'complete':not issues,'unresolved':issues,'atoms':atoms,'requirements':reqs,'clauses':cs,'coverage_audit':audit,'compiler_attempts':calls,'time_bindings':times,'background_assumptions':[a for a in reqs if a['necessity']=='background'],'required_kinds':sorted({a['kind'] for a in atoms}),'completeness_basis':'clause-grounded model-assisted necessity audit, not independent truth'}
