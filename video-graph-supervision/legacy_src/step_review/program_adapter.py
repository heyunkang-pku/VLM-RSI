"""Independent deterministic program adapter, NOT STEP-native graph-guided QA.
Reads an automatic frozen native partial graph. Never changes source facts.
"""
import hashlib,itertools,json
ALLOWED={'color','material','texture','shape','lid_color'}
def h(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def content_hash(row):return h(row)
def main_candidates(graph,ledgers,temporal_pairs,version='V1'):
 bykey={(x['scope'],x['fact_id']):x for x in ledgers if x['fact_type']!='unresolved_relation_claim'};objects={};attrs={};relations={};candidates=[]
 for (scope,fid),r in bykey.items():
  if r['state']!='ACCEPTED':continue
  if r['fact_type']=='object':objects[(scope,fid)]=r
  elif r['fact_type']=='attribute':attrs[(scope,fid)]=r
  elif r['fact_type']=='relation':relations[(scope,fid)]=r
 def unique(scope,fid):
  r=objects.get((scope,fid))
  if not r:return False
  label=r['candidate_content']['label'].strip().lower();return sum(s==scope and x['candidate_content']['label'].strip().lower()==label for (s,_),x in objects.items())==1
 def dep(scope,fid):
  r=bykey.get((scope,fid));return {'fact_key':scope+'/'+fid+'/'+version,'content_sha256':h(r['candidate_content']),'native_state':r['state']} if r else None
 def emit(typ,question,program,dependencies,state,reason=None,metadata=None):
  qid='q_'+h({'version':version,'type':typ,'program':program})[:16];candidates.append({'question_id':qid,'question_type':typ,'source_ledger_sha256':h(ledgers),'source_pairs_sha256':h(temporal_pairs),'source_graph_sha256':h(graph),'video_id':program['scope'].split('/')[0],'question':question,'program':program,'graph_version':version,'dependencies':dependencies,'status':state,'abstention_reason':reason,'metadata':metadata or {}})
 for (scope,aid),r in sorted(attrs.items()):
  a=r['candidate_content'];oid=r['parent_ids'][0];o=objects.get((scope,oid));label=o['candidate_content']['label'] if o else 'unresolved object';time=r['source_keyframe']['time_sec'];typ=a['type'];program={'op':'attribute','scope':scope,'object_id':oid,'type':typ};deps=[dep(scope,oid)]+[dep(s,k) for (s,k),z in sorted(attrs.items()) if s==scope and z['parent_ids']==[oid] and z['candidate_content']['type']==typ];state='EXECUTABLE';why=None
  if typ not in ALLOWED:state,why='ABSTAIN','ATTRIBUTE_TYPE_NOT_IN_FROZEN_GRAMMAR'
  elif not unique(scope,oid):state,why='ABSTAIN','ENTITY_NOT_UNIQUE_IN_AUTOMATIC_GRAPH'
  elif a['value'].lower() in label.lower():state,why='ABSTAIN','ANSWER_IN_REFERENT_LABEL'
  elif len({z['candidate_content']['value'] for (s,_),z in attrs.items() if s==scope and z['parent_ids']==[oid] and z['candidate_content']['type']==typ})!=1:state,why='ABSTAIN','CONFLICTING_ATTRIBUTE_VALUES'
  emit('attribute',f'At {time:.3f} seconds, what is the {typ.replace("_"," ")} of the {label}?',program,deps,state,why)
 grouped={}
 for (scope,rid),r in relations.items():
  c=r['candidate_content'];grouped.setdefault((scope,c['subject_id'],c['object_id']),[]).append(r)
 for (scope,a,b),rr in sorted(grouped.items()):
  l=objects[(scope,a)]['candidate_content']['label'];r=objects[(scope,b)]['candidate_content']['label'];time=rr[0]['source_keyframe']['time_sec'];deps=[dep(scope,a),dep(scope,b)]+[dep(scope,x['fact_id']) for x in rr];ok=unique(scope,a) and unique(scope,b) and a!=b
  emit('spatial_relation',f'At {time:.3f} seconds, what spatial or contact relationship(s) does the {l} have with the {r}?',{'op':'relation','scope':scope,'subject_id':a,'object_id':b},deps,'EXECUTABLE' if ok else 'ABSTAIN',None if ok else 'AMBIGUOUS_ENDPOINT')
 for pair in temporal_pairs:
  for r in pair.get('results',[]):
   left=r['left'];right=r['right'];ls,li=left.rsplit('/',1);rs,ri=right.rsplit('/',1);lo=objects.get((ls,li));ro=objects.get((rs,ri))
   if not lo or not ro:continue
   lt=lo['source_keyframe']['time_sec'];rt=ro['source_keyframe']['time_sec'];ll=lo['candidate_content']['label'];rl=ro['candidate_content']['label'];ok=r['state'] in ['STATIC_MERGED','REFERENCE_CREATED'] and unique(ls,li) and unique(rs,ri)
   emit('cross_frame_identity',f'Is the {ll} seen at {lt:.3f} seconds the same physical object as the {rl} seen at {rt:.3f} seconds?',{'op':'identity','scope':ls,'left':left,'right':right,'connection_id':r['id']},[dep(ls,li),dep(rs,ri),{'connection_key':r['id']+'/'+version,'content_sha256':h(r),'native_state':r['state']}],'EXECUTABLE' if ok else 'ABSTAIN',None if ok else 'IDENTITY_NOT_ESTABLISHED_OR_AMBIGUOUS',{'positive_only_bias':'No closed-world negative identity inference'})
 for a,b in itertools.combinations(graph.get('motion_edges',[]),2):
  ls=a['source'].rsplit('/',1)[0];valid=a.get('usable_for_program_QA',False) and b.get('usable_for_program_QA',False)
  emit('motion_order_diagnostic',f'Does the action "{a["action"]}" occur before "{b["action"]}"?',{'op':'motion_before','scope':ls,'motion_a':a['id'],'motion_b':b['id']},[{'motion_key':x['id']+'/'+version,'content_sha256':h(x)} for x in [a,b]],'EXECUTABLE' if valid else 'ABSTAIN',None if valid else 'DEPENDENCY_UNSUPPORTED',{'not_main_supervision':True})
 # Dedup only identical program/question, not according to perceived correctness.
 unique_candidates={}
 for x in candidates:unique_candidates.setdefault((x['question_id'],x['question']),x)
 return list(unique_candidates.values())

def execute(candidate,ledgers,temporal_pairs,graph):
 if candidate['status']!='EXECUTABLE':return {'status':'ABSTAIN','reason':candidate['abstention_reason'],'answer':None}
 if candidate.get('source_ledger_sha256')!=h(ledgers) or candidate.get('source_pairs_sha256')!=h(temporal_pairs) or candidate.get('source_graph_sha256')!=h(graph):return {'status':'ABSTAIN','reason':'FROZEN_DEPENDENCY_SET_CHANGED','answer':None}
 p=candidate['program'];s=p['scope'];accepted=[r for r in ledgers if r['state']=='ACCEPTED']
 if p['op']=='attribute':
  values={r['candidate_content']['value'] for r in accepted if r['scope']==s and r['fact_type']=='attribute' and r['parent_ids']==[p['object_id']] and r['candidate_content']['type']==p['type']}
  if len(values)!=1:return {'status':'ABSTAIN','reason':'MISSING_OR_CONFLICTING_ATTRIBUTE','answer':None}
  return {'status':'ANSWERED','answer':next(iter(values))}
 if p['op']=='relation':
  values=sorted({r['candidate_content']['predicate'] for r in accepted if r['scope']==s and r['fact_type']=='relation' and r['candidate_content']['subject_id']==p['subject_id'] and r['candidate_content']['object_id']==p['object_id']})
  return {'status':'ANSWERED','answer':values} if values else {'status':'ABSTAIN','reason':'MISSING_RELATION','answer':None}
 if p['op']=='identity':
  found=[r for pair in temporal_pairs for r in pair.get('results',[]) if r['id']==p['connection_id'] and r['state'] in ['STATIC_MERGED','REFERENCE_CREATED']]
  return {'status':'ANSWERED','answer':'Yes'} if len(found)==1 else {'status':'ABSTAIN','reason':'IDENTITY_NOT_ESTABLISHED','answer':None}
 return {'status':'ABSTAIN','reason':'UNSUPPORTED_PROGRAM_OR_UNVERIFIED_MOTION','answer':None}

def select(candidates,seed=2026110102):
 chosen=[]
 for typ in ['attribute','spatial_relation','cross_frame_identity']:
  group=[x for x in candidates if x['question_type']==typ]
  eligible=[x for x in group if x['status']=='EXECUTABLE'];chosen+=sorted(eligible,key=lambda x:h({'seed':seed,'qid':x['question_id']}))[:8]
 return chosen
