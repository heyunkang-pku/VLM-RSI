"""Server-bound source records, logical JSON leaves, explicit rationale links."""
import json,re
from .semantic import bounded_call
from .dependencies import validate_requirements,s_time_bindings
from step_six.common import parsejson,h
class ObjectPairs(list):pass

def sources(q):
 out=[]
 for field in ['question','answer','rationale']:
  value=q.get(field,'');raw=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
  leaves=[]
  def walk(x,path):
   if isinstance(x,ObjectPairs):
    for i,(k,v) in enumerate(x):walk(v,path+'/'+str(k)+'#'+str(i))
   elif isinstance(x,list):
    for i,v in enumerate(x):walk(v,path+'/'+str(i))
   elif isinstance(x,str) and x.strip():leaves.append((path,x))
  if field=='rationale' and raw.lstrip().startswith(('{','[')):
   try:walk(json.loads(raw,object_pairs_hook=ObjectPairs),'$')
   except ValueError:leaves=[('$',raw)]
  else:leaves=[('$',raw)]
  for path,text in leaves:
   for i,part in enumerate(re.split(r'(?<=[.!?])\s+',text)):
    if part.strip():out.append({'source_id':field+':'+str(len(out)),'source_field':field,'text':part.strip(),'raw_field_sha256':h(raw),'logical_path':path,'sentence_index':i,'source_binding':'code supplies exact text; model does not copy/relabel it'})
 return out

def s_dependencies(rt,q,facts,media):
 ss=sources(q);known=set(q['fact_ids']);scopes={facts[x].get('scope') for x in known if x in facts};allowed={f['id']:f for f in facts.values() if f['video_id']==q['video_id'] and (f['id'] in known or f.get('scope') in scopes)};catalog=[{k:f[k] for k in ['id','kind','claim','parent_ids','time_sec'] if k in f} for f in allowed.values()];requirements=[];issues=[];calls=[];source_states=[]
 def add_items(items,source,links=()):
  if not isinstance(items,list):raise ValueError('ITEMS_MUST_BE_ARRAY')
  for i,x in enumerate(items):
   if not isinstance(x,dict):raise ValueError('ITEM_NOT_OBJECT')
   if x.get('kind') not in ['object','attribute','relation','identity','motion','time','entity_resolution'] or not isinstance(x.get('claim'),str) or not x['claim'].strip() or not isinstance(x.get('reason'),str) or not x['reason'].strip():issues.append({'reason':'INVALID_ITEM_INTERFACE','source_id':source['source_id'],'item':x});continue
   a={**x,'requirement_id':'v2req_'+h([q['question_id'],source['source_id'],i,x])[:16],'source_id':source['source_id'],'source_field':source['source_field'],'source_text':source['text'],'quote':source['text'],'source_binding':source,'necessity':'necessary','supports_QA_requirements':list(links),'evidence_scope':x.get('evidence_scope','observation')}
   fid=a.get('evidence_fact_id');f=allowed.get(fid)
   if not f or not isinstance(a.get('fact_ids'),list) or not a['fact_ids'] or fid not in a['fact_ids'] or any(z not in allowed for z in a['fact_ids']):issues.append({'reason':'INVALID_SOURCE_GRAPH_MAPPING','requirement_id':a['requirement_id'],'item':a})
   elif a['kind'] in ['attribute','relation','identity','motion'] and f['kind']!=a['kind']:issues.append({'reason':'EVIDENCE_KIND_MISMATCH','requirement_id':a['requirement_id'],'item':a})
   requirements.append(a)
 # Q/A requirements first. Rationale is absent from these calls, so an R-only
 # phrase cannot be relabeled as an assertion "explicitly in the answer".
 for source in [x for x in ss if x['source_field']!='rationale']:
  prompt='Extract only the visual requirements needed for THIS one source record. The server already binds exact source text, field and ID; do not quote, paraphrase or relabel source metadata. Do not answer or rewrite the frozen question/answer. For question records, extract entity binding/relations/time constraints needed to understand it. For answer records, cover every visual assertion, with no extra background. Use graph IDs only as evidence pointers, not as a mandate to verify every graph fact. Split distinct facts. Do not require all semantic kinds. Kinds allowed: object, attribute, relation, identity, motion, time, entity_resolution. Return an object with keys items (array), covered (boolean), missing (array). Each item has claim, kind, reason (why answer/binding needs it), fact_ids, evidence_fact_id, evidence_scope. Example shape: {"items":[{"claim":"one statement","kind":"attribute","reason":"direct answer value","fact_ids":["id"],"evidence_fact_id":"id","evidence_scope":"observation"}],"covered":true,"missing":[]}. Use empty items and covered=false if unresolved; never invent evidence.\n'+json.dumps({'source_record':source,'frozen_question':q['question'],'frozen_answer':q['answer'],'graph_evidence':catalog},ensure_ascii=False)
  try:
   r,attempts=bounded_call(rt,media[q['video_id']],prompt,'S2_v2_source_requirements',q['question_id']+':'+source['source_id']);calls+=attempts;p=parsejson(r['raw_response']);assert isinstance(p,dict)
   start=len(requirements);add_items(p.get('items'),source);source_states.append({'source_id':source['source_id'],'request_id':r['request_id'],'response':p})
   if p.get('covered') is not True or p.get('missing') or len(requirements)==start:issues.append({'reason':'QA_SOURCE_COVERAGE_UNRESOLVED','source_id':source['source_id'],'response':p})
  except Exception as e:issues.append({'reason':'QA_SOURCE_INTERFACE_FAILURE','source_id':source['source_id'],'error':repr(e)})
 qa=[a for a in requirements if a['source_field']!='rationale'];qa_ids={a['requirement_id'] for a in qa}
 for source in [x for x in ss if x['source_field']=='rationale']:
  prompt='Classify this rationale source record relative to the ALREADY EXPLICIT Q/A requirements. Do not claim rationale text was said in the answer. Choose role background, support, or unresolved. Background is not verified and must have a reason why it is not needed for the answer. Support needs an explicit supports list of existing Q/A requirement IDs plus a counterfactual reason. If supporting reasoning introduces additional atomic premises needed to derive those requirements, return them as items with graph IDs. Do not introduce a table-on-itself relation from a subquestion, or infer identity merely from equal class labels. Never manufacture support links. Return JSON {"role":"background","reason":"why not answer-dependent","supports":[],"items":[]} OR role=support/unresolved. If uncertain choose unresolved. Each item needs claim,kind,reason,fact_ids,evidence_fact_id,evidence_scope. Do not return source quotes or source IDs: the server binds them.\n'+json.dumps({'source_record':source,'question':q['question'],'answer':q['answer'],'QA_requirements':qa,'graph_evidence':catalog},ensure_ascii=False)
  try:
   r,attempts=bounded_call(rt,media[q['video_id']],prompt,'S2_v2_rationale_support_link',q['question_id']+':'+source['source_id']);calls+=attempts;p=parsejson(r['raw_response']);source_states.append({'source_id':source['source_id'],'request_id':r['request_id'],'response':p});role=p.get('role');reason=p.get('reason');links=p.get('supports',[])
   if role=='background' and reason and not links and not p.get('items'):
    requirements.append({'requirement_id':'bg_'+h([q['question_id'],source])[:16],'source_id':source['source_id'],'source_field':'rationale','source_text':source['text'],'source_binding':source,'necessity':'background','reason':reason,'claim':source['text'],'fact_ids':[]})
   elif role=='support' and reason and isinstance(links,list) and links and all(x in qa_ids for x in links):
    if p.get('items'):add_items(p['items'],source,links)
    requirements.append({'requirement_id':'link_'+h([q['question_id'],source])[:16],'source_id':source['source_id'],'source_field':'rationale','source_text':source['text'],'source_binding':source,'necessity':'support_link','supports_QA_requirements':links,'reason':reason,'claim':source['text']})
   else:issues.append({'reason':'RATIONALE_NECESSITY_LINK_UNRESOLVED','source_id':source['source_id'],'response':p})
  except Exception as e:issues.append({'reason':'RATIONALE_INTERFACE_FAILURE','source_id':source['source_id'],'error':repr(e)})
 # Code-owned source IDs remove the old exact-copy/enum-filled template task.
 prompt='Audit frozen Q/A coverage and rationale support classifications. Inspect every supplied source record exactly once by its source_id. Do NOT copy quotes. Only Q/A actual assertions and explicitly justified supporting premises are necessary; unrelated rationale details are background. Flag false necessity explanations, mapping/kind errors or missing answer predicates. Never demand all types. Return JSON {"reviews":[{"source_id":"existing ID","decision":"covered","reason":"specific justification"}]}. Allowed decisions covered,background_valid,missing,unresolved. For background_valid the server requires a rationale record; never dismiss question/answer assertions as background. A support link without real answer dependence is unresolved.\n'+json.dumps({'question':q['question'],'answer':q['answer'],'source_records':ss,'requirements':requirements,'source_classifications':source_states},ensure_ascii=False)
 try:
  r,attempts=bounded_call(rt,media[q['video_id']],prompt,'S2_v2_coverage_audit',q['question_id'],caps=(4096,8192));calls+=attempts;audit=parsejson(r['raw_response']);seen=[];byid={x['source_id']:x for x in ss}
  for row in audit['reviews']:
   sid=row.get('source_id');seen.append(sid);decision=row.get('decision');src=byid.get(sid)
   if not src or not row.get('reason') or decision not in ['covered','background_valid','missing','unresolved']:issues.append({'reason':'INVALID_AUDIT_INTERFACE','row':row});continue
   if decision in ['missing','unresolved'] or (decision=='background_valid' and src['source_field']!='rationale'):issues.append({'reason':'SOURCE_COVERAGE_UNRESOLVED','row':row})
  if sorted(seen)!=sorted(byid):issues.append({'reason':'AUDIT_SOURCE_COVERAGE_MISMATCH'})
 except Exception as e:audit={'error':repr(e)};issues.append({'reason':'COVERAGE_INTERFACE_FAILURE','error':repr(e)})
 atoms=[a for a in requirements if a['necessity']=='necessary'];issues+=validate_requirements(atoms,facts);times=s_time_bindings(q,facts)
 for t in times:
  if not t['consistent']:issues.append({'reason':'PRINTED_TIME_ANCHOR_UNRESOLVED','binding':t})
 if re.search(r'\bthroughout\b|\bconsistently\b|\bentire (?:video|clip)\b',q['question']+' '+str(q['answer']),re.I):issues.append({'reason':'SPARSE_FRAMES_DO_NOT_ESTABLISH_FULL_CLIP_ASSERTION'})
 return {'complete':not issues,'unresolved':issues,'atoms':atoms,'requirements':requirements,'sources':ss,'source_states':source_states,'coverage_audit':audit,'compiler_attempts':calls,'time_bindings':times,'background_assumptions':[a for a in requirements if a['necessity']=='background'],'completeness_basis':'code-bound source interface; model-assisted semantics with explicit support links, not independent truth'}
