"""Frozen public32 follow-up: directional surface parsing, explicit graph queries."""
import json,re,itertools,collections,copy,hashlib,csv,html,shutil
from pathlib import Path
from step_six.common import j,rows,jl,h,norm
from stsg_pilot.runtime import save
INVERSE={'on':'supports','supports':'on','above':'below','below':'above','left of':'right of','right of':'left of','in front of':'behind','behind':'in front of','next to':'next to','holding':'held by','held by':'holding','in contact with':'in contact with'}
def entity(s):
 s=norm(s);s=re.sub(r'^(the|a|an) ','',s);return s
ALIASES={'counter':'countertop','kitchen countertop':'kitchen counter','tin of colored pencils':'metal tin of colored pencils','white cup':'white cup'}
def same(a,b):return entity(a)==entity(b) or ALIASES.get(entity(a),entity(a))==ALIASES.get(entity(b),entity(b))
def relation(text,subject,obj):
 """Exact endpoint spans + finite predicate grammar, no semantic model/guessing."""
 t=text.lower().strip().rstrip('.');t=t.replace('with their right hand','').strip();t=re.sub(r'\s+',' ',t)
 predicates=[('has a supporting relationship with','supports'),('supports','supports'),('is holding','holding'),('is standing in front of','in front of'),('is standing on','on'),('is positioned next to','next to'),('is placed next to','next to'),('is positioned to the left of','left of'),('is to the right of','right of'),('is on the left side of','left of'),('is beneath','below'),('is below','below'),('is under','below'),('is above','above'),('is in front of','in front of'),('is behind','behind'),('is on','on')]
 for token,pred in predicates:
  m=re.fullmatch(r'(.+?) '+re.escape(token)+r' (.+)',t)
  if not m:continue
  a,b=m.groups();b=re.split(r',|\bwith their\b|\bnext to\b|\bto the left of\b',b)[0].strip()
  if same(a,subject) and same(b,obj):return [subject,pred,obj], 'DIRECT_EXPLICIT'
  if same(a,obj) and same(b,subject):return [subject,INVERSE[pred],obj], 'INVERT_EXPLICIT'
 return None,'UNRESOLVED_ENDPOINT_OR_PREDICATE'
def union_graph(g,pairs):
 nodes=g['source_nodes'];parent={x:x for x in nodes};proof=[]
 def find(a):
  while parent[a]!=a:a=parent[a]
  return a
 for p in pairs:
  for r in p.get('results',[]):
   if r['verdict']=='YES' and r['state'] in ['STATIC_MERGED','REFERENCE_CREATED','MOTION_EXTRACTED_NOT_INDEPENDENTLY_VALIDATED']:
    a,b=find(r['left']),find(r['right']);parent[b]=a;proof.append(r)
 groups=collections.defaultdict(list)
 for x in nodes:groups[find(x)].append(x)
 bad={key for key,vs in groups.items() if len({nodes[v]['scope'] for v in vs})<len(vs)}
 return nodes,find,groups,bad,proof

def proof_path(start,end,edges):
 adjacency=collections.defaultdict(list)
 for e in edges:
  adjacency[e['left']].append((e['right'],e));adjacency[e['right']].append((e['left'],e))
 queue=[(start,[])];seen={start}
 for node,path in queue:
  if node==end:return path
  for nxt,edge in adjacency[node]:
   if nxt not in seen:seen.add(nxt);queue.append((nxt,path+[edge]))
 raise ValueError('IDENTITY_PATH_MISSING')

def offline(base,out):
 base,out=Path(base),Path(out);out.mkdir(parents=True,exist_ok=True);old=[];new=[];led=[];motion=[];den=[];freeze={}
 for batch in ['first2','remaining8']:
  root=base/batch;qs=rows(root/'four_groups/PER_QUESTION.jsonl');old+=qs;g=j(root/'GRAPH_SHARED_FROZEN.json');pairs=j(root/'SOURCE_TEMPORAL_PAIRS.json');freeze[batch]={n:h(j(root/n)) if n.endswith('.json') else h(rows(root/n)) for n in ['GRAPH_SHARED_FROZEN.json','S_FROZEN_QA.jsonl','P_FROZEN_QA.jsonl']}
  for q in qs:
   if q['route']!='P' or not q['vote']['no_valid_answer']:continue
   m=re.search(r'does the (.*?) have with the (.*?)\?',q['question']);assert m;sub,obj=m.groups()
   for sample in q['samples']:
    try:a=json.loads(sample['raw_response']).get('answer');triple,rule=relation(a or '',sub,obj)
    except Exception:triple,rule=None,'UNPARSEABLE'
    led.append({'question_id':q['question_id'],'sample_index':sample['sample_index'],'original_status':sample['status'],'raw_response':sample['raw_response'],'requested_subject':sub,'requested_object':obj,'triple':triple,'rule':rule,'status':'RECOVERED' if triple else 'UNRESOLVED','original_request_id':sample.get('request_id')})
  nodes,find,groups,bad,proof=union_graph(g,pairs);cooccur={}
  for scope,vs in itertools.groupby(sorted(nodes,key=lambda x:nodes[x]['scope']),key=lambda x:nodes[x]['scope']):
   vv=list(vs)
   for a,b in itertools.combinations(vv,2):
    x,y=find(a),find(b)
    if x!=y and x not in bad and y not in bad:cooccur.setdefault(tuple(sorted([x,y])),[a,b])
  negatives=[]
  for pair in pairs:
   for result in pair.get('results',[]):
    a,b=result['left'],result['right'];x,y=find(a),find(b)
    if x==y or x in bad or y in bad:continue
    witness=cooccur.get(tuple(sorted([x,y])))
    if not witness:continue
    # Reject ambiguous class-only public referents rather than introduce IDs/answers.
    ln,rn=nodes[a],nodes[b];ll,rl=ln['object']['label'],rn['object']['label']
    if any(sum(n['scope']==node['scope'] and n['object']['label']==lab for n in nodes.values())!=1 for node,lab in [(ln,ll),(rn,rl)]):continue
    q=f'Is the {ll} at {ln["source_frame"]["time_sec"]:.6f} seconds the same physical object as the {rl} at {rn["source_frame"]["time_sec"]:.6f} seconds?'
    negatives.append({'question_id':'newP_'+h([a,b,witness])[:16],'video_id':a.split('/')[0],'route':'P','question_type':'identity_negative','question':q,'answer':'No','program':{'op':'distinct_via_cooccurrence_and_identity_paths','left':a,'right':b,'witness':witness},'dependencies':{'identity_edges':proof_path(a,next(w for w in witness if find(w)==x),proof)+proof_path(b,next(w for w in witness if find(w)==y),proof),'cooccurring_distinct_nodes':witness,'evidence_frames':[nodes[z]['source_frame'] for z in set([a,b]+witness)]},'same_class_endpoints':ll==rl,'truth':'conditional on native graph; same-frame instance separation not independent truth'})
  for vid in sorted({n.split('/')[0] for n in nodes}):
   vv=[q for q in negatives if q['video_id']==vid];chosen=sorted(vv,key=lambda q:(not q['same_class_endpoints'],h(q['question_id'])))[:2];new+=chosen;den.append({'video_id':vid,'eligible_negative_pairs':len(vv),'selected':len(chosen),'inconsistent_identity_groups':len(bad),'no_edge_is_not_negative':True})
  used={(q['program']['left'],q['program']['right']) for q in qs if (q.get('program') or {}).get('op')=='identity'}
  positive=[]
  for edge in proof:
   a,b=edge['left'],edge['right'];ln,rn=nodes[a],nodes[b]
   if (a,b) in used or find(a) in bad:continue
   if any(sum(n['scope']==node['scope'] and n['object']['label']==node['object']['label'] for n in nodes.values())!=1 for node in [ln,rn]):continue
   positive.append({'question_id':'newP_'+h(['positive',a,b])[:16],'route':'P','video_id':a.split('/')[0],'question_type':'identity_positive','question':f'Is the {ln["object"]["label"]} at {ln["source_frame"]["time_sec"]:.6f} seconds the same physical object as the {rn["object"]["label"]} at {rn["source_frame"]["time_sec"]:.6f} seconds?','answer':'Yes','program':{'op':'native_identity_yes','left':a,'right':b,'connection':edge['id']},'dependencies':{'identity_edges':[edge],'evidence_frames':[ln['source_frame'],rn['source_frame']]},'same_class_endpoints':ln['object']['label']==rn['object']['label'],'truth':'native graph conditional, no independent labels'})
  for vid in sorted({n.split('/')[0] for n in nodes}):new+=sorted([q for q in positive if q['video_id']==vid],key=lambda q:h(q['question_id']))[:2]
  attrs={a['id']:a for a in g['merged_fsg_view']['attribute_nodes']};at=collections.defaultdict(dict)
  for edge in g['merged_fsg_view']['attribute_edges']:
   a=attrs[edge['attribute_id']];scope=a['source_scope'];original=next((n for n in nodes if nodes[n]['scope']==scope and n in g['merged_fsg_view']['canonical_object_ids'] and g['merged_fsg_view']['canonical_object_ids'][n]==edge['subject_id']),None)
   if original:at[original].setdefault(a['type'],[]).append(a)
  # Motion candidates have unresolved affected-object binding: only endpoint observed attributes may be queried.
  for edge in g['motion_edges']:
   left,right=edge['left'],edge['right'];candidates=[]
   for typ in sorted(set(at[left])&set(at[right])):
    a,b=at[left][typ],at[right][typ]
    if len({x['value'] for x in a})!=1 or len({x['value'] for x in b})!=1:continue
    if norm(a[0]['value'])==norm(b[0]['value']):continue
    if typ not in ['position','state','condition','action','orientation','pose']:continue
    ln,rn=nodes[left],nodes[right];label=ln['object']['label']
    if label!=rn['object']['label']:continue
    q={'question_id':'newP_'+h([edge['id'],typ])[:16],'video_id':left.split('/')[0],'route':'P','question_type':'observed_state_change','question':f'How does the {typ} of the {label} differ between {ln["source_frame"]["time_sec"]:.6f} and {rn["source_frame"]["time_sec"]:.6f} seconds?','answer':{'earlier':a[0]['value'],'later':b[0]['value']},'program':{'op':'compare_two_observed_values','type':typ,'left':a[0]['id'],'right':b[0]['id']},'dependencies':{'identity':edge['identity_request_id'],'motion_candidate':edge['id'],'earlier_attribute':a,'later_attribute':b,'evidence_frames':[ln['source_frame'],rn['source_frame']]},'truth':'endpoint observations only, no inferred intermediate action'};candidates.append(q)
   motion.append({'motion_id':edge['id'],'video_id':left.split('/')[0],'state_change_candidates':candidates,'order_status':'UNRESOLVED_NO_BOUND_EVENT_INSTANCES_OR_ONSET_BOUNDARIES','affected_object_bound':not edge.get('affected_object_text_is_not_graph_reference',True)})
 for vid in sorted({m['video_id'] for m in motion}):new+=sorted([q for m in motion if m['video_id']==vid for q in m['state_change_candidates']],key=lambda q:h(q['question_id']))[:2]
 jl(out/'RELATION_RECOVERY.jsonl',led);jl(out/'NEW_P_FROZEN.jsonl',new);save(out/'NEGATIVE_YIELD.json',den);save(out/'MOTION_AUDIT.json',motion);save(out/'SOURCE_FREEZE.json',freeze)
 recovered=[]
 for q in old:
  ll=[x for x in led if x['question_id']==q['question_id']]
  if not ll:continue
  votes=collections.Counter(x['triple'][1] for x in ll if x['triple']);top=max(votes.values(),default=0);winners=sorted(k for k,v in votes.items() if v==top);recovered.append({'question_id':q['question_id'],'votes':dict(votes),'fixed_denominator':10,'valid':sum(votes.values()),'winners':winners,'strict_majority':winners[0] if top>5 and len(winners)==1 else None,'original_format_failures':10,'candidate':q['candidate_answer'],'accuracy':'PENDING'})
 save(out/'RELATION_COMPATIBLE_SCORES.json',recovered);save(out/'OFFLINE_SUMMARY.json',{'relation_draws':len(led),'recovered':sum(x['status']=='RECOVERED' for x in led),'newP':len(new),'types':dict(collections.Counter(q['question_type'] for q in new)),'motion_denominator':len(motion),'no_new_model_calls':True})
 return old,new
if __name__=='__main__':
 import sys
 offline(sys.argv[1],sys.argv[2])
