"""Pre-visual scope validation and completeness-before-verdict status order."""
import re,copy
from .dependencies import rounded_binding

def displayed_times(text):
 tokens=re.findall(r'(\d+(?:\.\d+)?)\s+seconds',text)
 for a,b in re.findall(r'(\d+(?:\.\d+)?)\s+(?:to|and)\s+(\d+(?:\.\d+)?)\s+seconds',text):tokens.extend([a,b])
 return list(dict.fromkeys(tokens))

def evidence_preflight(atom,q,facts,media,mode):
 frames=[media['calibration_view']] if mode=='image' else media['class_video_views'];times=sorted(set(float(x['time_sec']) for x in frames));issues=[];fid=atom.get('evidence_fact_id');f=facts.get(fid,{});anchors=[]
 if q['route']=='P':
  ids=f.get('parent_ids',[]) if atom['kind']=='identity' else [fid]
  for x in ids:
   if x in facts and 'time_sec' in facts[x]:anchors.append({'exact_time':facts[x]['time_sec'],'fact_id':x})
 else:
  text=atom.get('source_text','');tokens=displayed_times(text) or displayed_times(q['question'])
  for token in tokens:anchors.append({'display_time':token})
  if not anchors and 'time_sec' in f:anchors.append({'exact_time':f['time_sec'],'fact_id':fid})
 if not frames:issues.append('EMPTY_VISUAL_INPUT')
 if atom.get('evidence_scope')=='full_clip' or re.search(r'\bthroughout\b|\bconsistently\b|\bentire (?:clip|video)\b',atom.get('claim',''),re.I):issues.append('SPARSE_FRAMES_DO_NOT_ESTABLISH_FULL_CLIP_QUANTIFIER')
 if atom['kind'] in ['identity','motion','time'] and (mode!='video' or len(times)<2):issues.append('TEMPORAL_FACT_NEEDS_DISTINCT_OBSERVATIONS')
 for anchor in anchors:
  if 'exact_time' in anchor:
   covered=any(abs(t-anchor['exact_time'])<1e-8 for t in times)
  else:covered=any(rounded_binding(t,anchor['display_time'])['consistent'] for t in times)
  anchor['covered_by_actual_input']=covered
  if not covered:issues.append('REQUESTED_OBSERVATION_NOT_IN_ACTUAL_INPUT')
 if atom['kind'] in ['identity','motion','time'] and not anchors:issues.append('UNBOUND_TEMPORAL_REQUIREMENT')
 return {'sufficient':not issues,'issues':list(dict.fromkeys(issues)),'required_anchors':anchors,'actual_times_sec':times,'actual_range_sec':[min(times),max(times)] if times else None,'frame_ids':[x['frame_id'] for x in frames],'pixel_hashes':[x['sha256'] for x in frames],'mode':mode,'tensor_hashes':'NOT_COMPUTED_BEFORE_MODEL_ENCODING'}

def decide_status(dep,preflights,checks):
 # A model NO is not admissible if the necessity audit or input scope failed.
 if not dep.get('complete'):return 'UNRESOLVED_DEPENDENCY_BEFORE_VISUAL'
 if len(preflights)!=len(dep.get('atoms',[])) or any(not p.get('sufficient') for p in preflights):return 'UNRESOLVED_EVIDENCE_BEFORE_VISUAL'
 if len(checks)!=len(dep['atoms']) or not checks:return 'UNRESOLVED_VISUAL_OUTPUT'
 if any(c.get('verdict') not in ['YES','NO'] for c in checks):return 'UNRESOLVED_VISUAL_OUTPUT'
 if any(c['verdict']=='NO' for c in checks):return 'ABSTAIN_REQUIRED_FACT_MODEL_NO'
 return 'ACCEPT'

def p_annotations(dep,q,facts):
 dep=copy.deepcopy(dep);bindings=[]
 for a in dep['atoms']:
  if a['kind']!='object':continue
  fid=a['evidence_fact_id'];f=facts[fid];label=f['content']['label'];generic=label.strip().lower() in ['surface','object','objects','item','thing','area','material']
  rec={'fact_id':fid,'public_expression':label,'observation_frame':f['media']['calibration_view']['frame_id'],'exact_seconds':f['time_sec'],'scope':'supplied frozen observation, not all objects in entire video','public_instance_qualifiers':[],'private_FSG_description_not_added_to_question':f['content']['referent'],'reference_status':'UNQUALIFIED_GENERIC_REFERENCE' if generic else 'CLASS_REFERENCE_REQUIRES_LOCAL_VISUAL_UNIQUENESS','reason':'No private graph adjective may be silently used to resolve the frozen public question.'};bindings.append(rec)
  if generic:dep['unresolved'].append({'reason':'PUBLIC_REFERENCE_INSUFFICIENTLY_QUALIFIED','binding':rec})
 relation=q['program']['op']=='relation';dep['referring_bindings']=bindings;dep['relation_completeness']={'applicable':relation,'graph_returned_predicates_enumerated':relation,'positive_claims_status':'check_results_recorded_separately','real_world_relation_set_complete':'UNVERIFIED' if relation else 'NOT_APPLICABLE','acceptance_scope':'positive predicates alone do not certify the full set-valued QA answer' if relation else 'not_applicable'}
 if relation:dep['unresolved'].append({'reason':'RELATION_SET_COMPLETENESS_UNVERIFIED','reason_detail':'Partial STSG and positive visual checks cannot establish that no other answering predicate is missing.'})
 dep['complete']=not dep['unresolved'];return dep
