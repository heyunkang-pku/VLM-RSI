"""Deterministic P semantic read slicing and precision-aware observation binding."""
import copy,re,json
from decimal import Decimal
from step_six.common import h

def rounded_binding(exact,display):
 precision=len(display.split('.')[1]) if '.' in display else 0
 half=Decimal(5).scaleb(-precision-1);error=abs(Decimal(str(exact))-Decimal(display))
 return {'exact_source_seconds':exact,'question_display':display,'precision_digits':precision,'rounding_half_unit':str(half),'absolute_error':str(error),'consistent':error<=half+Decimal('1e-12'),'interpretation':'rounded observation anchor, not new exact timestamp/event boundary'}

def time_bindings(q,facts):
 # Bind observations, not arbitrary answer numerals/IDs. Tolerance is derived
 # from the actually printed decimal precision, never an adjustable threshold.
 if q['route']=='P':
  p=q['program'];oids=[p['left'],p['right']] if p['op']=='identity' else [p['scope']+'/'+p.get('object_id',p.get('subject_id'))]
  displays=re.findall(r'(\d+(?:\.\d+)?) seconds',q['question'])
  if len(displays)!=len(oids):return [{'consistent':False,'reason':'OBSERVATION_TIME_BINDING_COUNT_MISMATCH','display_tokens':displays,'objects':oids}]
  out=[]
  for fid,d in zip(oids,displays):
   b=rounded_binding(facts[fid]['time_sec'],d);b.update(fact_id=fid,frame_id=facts[fid]['media']['calibration_view']['frame_id']);out.append(b)
  return out
 return []

def requirement(q,claim,kind,ids,evidence,reason,source='program',quote=None,necessity='necessary'):
 return {'requirement_id':'req_'+h([q['question_id'],claim,ids,reason])[:16],'claim':claim,'kind':kind,'fact_ids':ids,'evidence_fact_id':evidence,'necessity':necessity,'reason':reason,'source_field':source,'source_quote':quote,'evidence_scope':'observation_only'}

def p_dependencies(q,facts,ledger,pairs,graph):
 from step_review.program_adapter import execute
 replay=execute(q,ledger,pairs,graph);issues=[];atoms=[];reasons=[];p=q['program'];op=p['op'];used=set()
 if replay.get('status')!='ANSWERED' or replay.get('answer')!=q['answer']:issues.append({'reason':'PROGRAM_REPLAY_DIFFERS_FROM_FROZEN_ANSWER','replay':replay})
 def obj(fid):
  f=facts[fid];used.add(fid);label=f['content']['label']
  atoms.append(requirement(q,'A '+label+' is visible in the supplied frame.','object',[fid],fid,'Question names this entity; visual existence is necessary for binding.'))
  atoms.append(requirement(q,'Exactly one '+label+' is visible in the supplied frame.','entity_resolution',[fid],fid,'Frozen question uses a class label without an instance qualifier; unique visual binding is required.'))
  # Descriptive attributes absent from the public question do not silently
  # become necessary facts merely because the FSG parser mentioned them.
  reasons.append({'fact_id':fid,'field':'FSG referent description','necessity':'background','reason':'Frozen program/public question binds by unique class label; extra parser adjectives are not used as answer premises.','value_retained':f['content']['referent']})
  return label
 if op=='attribute':
  oid=p['scope']+'/'+p['object_id'];label=obj(oid)
  ids=sorted(fid for fid,f in facts.items() if f['kind']=='attribute' and f['scope']==p['scope'] and f['parent_ids']==[oid] and f['content']['type']==p['type'])
  for fid in ids:
   f=facts[fid];used.add(fid);atoms.append(requirement(q,'The '+label+' has '+p['type'].replace('_',' ')+' '+f['content']['value']+'.','attribute',[oid,fid],fid,'This attribute value is directly read by the frozen program and determines its answer.'))
  if not ids:issues.append({'reason':'MISSING_EXECUTED_ATTRIBUTE'})
 elif op=='relation':
  a=p['scope']+'/'+p['subject_id'];b=p['scope']+'/'+p['object_id'];la,lb=obj(a),obj(b)
  ids=sorted(fid for fid,f in facts.items() if f['kind']=='relation' and f['scope']==p['scope'] and f['parent_ids']==[a,b])
  for fid in ids:
   used.add(fid);atoms.append(requirement(q,'The '+la+' '+facts[fid]['content']['predicate']+' the '+lb+'.','relation',[a,b,fid],fid,'Each returned predicate contributes to the frozen set-valued relation answer.'))
  # Frozen relational questions request relationship(s), not a count over all
  # unseen relations. Exhaustiveness cannot be proved from a partial STSG.
  if not ids:issues.append({'reason':'MISSING_EXECUTED_RELATION'})
  reasons.append({'necessity':'unresolved','field':'relation completeness','reason':'All graph-returned predicates are checked; independent completeness of all real-world relations is unproven. This is reported separately from positive-claim verification.'})
 elif op=='identity':
  a,b=p['left'],p['right'];la,lb=obj(a),obj(b);fid=p['connection_id'];used.add(fid)
  if fid not in facts:issues.append({'reason':'MISSING_IDENTITY_CONNECTION'})
  else:
   atoms.append(requirement(q,'The '+la+' at the earlier indicated observation and the '+lb+' at the later indicated observation are the same physical object.','identity',[a,b,fid],fid,'The frozen Yes answer depends on this explicit cross-frame physical identity connection, not merely on equal class descriptions.'))
 else:issues.append({'reason':'UNSUPPORTED_FROZEN_PROGRAM'})
 for fid in q['fact_ids']:
  if fid not in used:reasons.append({'fact_id':fid,'necessity':'background','reason':'Visited by a scope/index scan but does not determine selected entity, answer value or identity; visual class uniqueness is checked separately.'})
 times=time_bindings(q,facts)
 for b in times:
  if not b['consistent']:issues.append({'reason':'QUESTION_SOURCE_TIME_UNRESOLVED','binding':b})
 # All deterministic constraints added BEFORE coverage/type validation.
 coverage=validate_requirements(atoms,facts)
 issues+=coverage
 return {'complete':not issues,'unresolved':issues,'atoms':atoms,'requirements':atoms,'background_assumptions':reasons,'time_bindings':times,'execution_replay':replay,'semantic_read_fact_ids':sorted(used),'raw_index_trace_preserved':q.get('program_read_trace'),'required_kinds':sorted({a['kind'] for a in atoms}),'completeness_basis':'deterministic frozen-program semantic slicing; no LLM invents P premises','relation_answer_exhaustiveness':'PENDING_INDEPENDENT_TRUTH' if op=='relation' else 'not_applicable'}

def validate_requirements(atoms,facts):
 errors=[]
 if not atoms:return [{'reason':'EMPTY_NECESSARY_DEPENDENCY_SET'}]
 for a in atoms:
  if a.get('necessity')!='necessary':errors.append({'reason':'NON_NECESSARY_ATOM_IN_CHECK_SET','id':a.get('requirement_id')})
  if not a.get('reason') or not a.get('claim'):errors.append({'reason':'MISSING_REQUIREMENT_JUSTIFICATION','id':a.get('requirement_id')})
  if not a.get('fact_ids') or any(fid not in facts for fid in a['fact_ids']) or a.get('evidence_fact_id') not in a['fact_ids']:errors.append({'reason':'UNMAPPED_NECESSARY_FACT','id':a.get('requirement_id')})
 return errors

def s_time_bindings(q,facts):
 text=q['question']+' '+str(q['answer']);tokens=re.findall(r'(\d+(?:\.\d+)?)\s+seconds',text)
 for a,b in re.findall(r'(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)\s+seconds',text):tokens.extend([a,b])
 times=sorted({f['time_sec'] for f in facts.values() if f['video_id']==q['video_id'] and 'time_sec' in f});out=[]
 for token in sorted(set(tokens)):
  fits=[rounded_binding(t,token) for t in times if rounded_binding(t,token)['consistent']]
  out.append({'question_display':token,'consistent':len(fits)==1,'candidate_bindings':fits,'reason':'unique frozen observation within printed rounding interval' if len(fits)==1 else 'missing or ambiguous printed-time anchor; no inferred boundary'})
 return out
