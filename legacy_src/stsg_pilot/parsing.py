"""Deterministic translation of model records; no model retry, answer repair or gold."""
import json,re
from copy import deepcopy
from .core import keys,require,validate_graph,digest

PARSER_SPEC='''Return ONLY JSON with keys objects,attributes,relations,events,identities (arrays, [] if no evidence).
Objects: {"id":"o1","description":"distinctive visible entity","node_type":"static|dynamic|unknown","identity_scope":"tracked_entity|single_frame","frame_ids":["f000",...]}. Each object ID is local to this clip. Only use tracked_entity when the SAME PHYSICAL entity can be tracked across all declared frames; include every frame supporting that object's events. Otherwise use separate IDs and uncertain identity links. Do not infer identity just from similar labels.
Attributes: {"id":"a1","subject_id":"o1","predicate":"color","value":"red","frame_ids":[...]}
Relations: {"id":"r1","subject_id":"o1","object_id":"o2","predicate":"holds","frame_ids":[...]}
Events: {"id":"e1","kind":"event|motion","subject_id":"o1","predicate":"concrete action with object, such as lifts cup","frame_ids":[...],"start_sec_range":[earliest,latest],"end_sec_range":[earliest,latest]}. Times are GLOBAL seconds from the supplied frame clock; ranges include uncertainty. 0<=start_earliest<=start_latest<=end_earliest<=end_latest<=clip_end. Supporting frame times must lie within start_earliest..end_latest. Report at most6 clearly observable events and at most3 objects. Do not invent events or shrink uncertainty to force ordering. Do not create questions or answers.
Identities (optional intra-clip links): {"id":"i1","subject_id":"o1","object_id":"o2","identity_status":"known|unknown","frame_ids":[...]}. They assert identity between DIFFERENT local entity instances. No global absence/count/causal claims. No outside knowledge. Use only the actual frame IDs supplied; descriptions must be concise. At most4 attributes and4 relations. No markdown.'''
BRIDGE_SPEC='''Compare the supplied object descriptions and video frames from two adjacent clips. Return ONLY {"identities":[{"id":"b1","subject_id":"c0_o1","object_id":"c1_o1","identity_status":"known|unknown","frame_ids":[...]}]}. Only list identity hypotheses supported by the frames; known means SAME physical entity, not same class. Include supporting frames from BOTH objects' clips. [] is valid if no justified link. No new object, event, question or answer. Never force a match.'''

def parse_json(text):
    t=text.strip()
    if t.startswith('```'):
        m=re.fullmatch(r'```(?:json)?\s*(.*?)\s*```',t,re.S);require(m is not None,'INVALID_JSON_FENCE');t=m.group(1)
    return json.loads(t)

def make_clip_graph(media,clip,record,run):
    keys(record,['objects','attributes','relations','events','identities'])
    require(sum(len(record[k]) for k in ['objects','attributes','relations','events','identities'])<=64,'TOTAL_FACT_CAP_EXCEEDED')
    fs={f['frame_id']:f for f in media['frames']};prefix=clip['clip_id']+'_';facts=[];ids=[]
    def fact(row,kind,predicate,required,optional=()):
        keys(row,required,optional);require(isinstance(row['frame_ids'],list) and bool(row['frame_ids']),'NO_EVIDENCE_FRAMES')
        require(set(row['frame_ids'])<=set(clip['frame_ids']),'UNKNOWN_OR_WRONG_CLIP_FRAMES')
        ts=[fs[i]['time_sec'] for i in row['frame_ids']];fid=prefix+row['id'];ids.append(fid)
        f={'fact_id':fid,'kind':kind,'predicate':predicate,'clip_ids':[clip['clip_id']],'support_frame_ids':row['frame_ids'],
           'parser_run_id':run['parser_run_id'],'matched_parser_run_ids':[run['parser_run_id']],
           'start_sec_range':[min(ts)]*2,'end_sec_range':[max(ts)]*2,'depends_on':[]}
        for k in ['subject_id','object_id']:
            if k in row:f[k]=prefix+row[k]
        return f
    for o in record['objects']:
        f=fact(o,'object',o['description'],['id','description','node_type','identity_scope','frame_ids']);f.update(node_type=o['node_type'],identity_scope=o['identity_scope']);facts.append(f)
    for a in record['attributes']:
        f=fact(a,'attribute',a['predicate'],['id','subject_id','predicate','value','frame_ids']);f['attribute_value']=a['value'];facts.append(f)
    for r in record['relations']:
        facts.append(fact(r,'relation',r['predicate'],['id','subject_id','object_id','predicate','frame_ids']))
    for e in record['events']:
        require(e['kind'] in ['event','motion'],'EVENT_KIND')
        f=fact(e,e['kind'],e['predicate'],['id','kind','subject_id','predicate','frame_ids','start_sec_range','end_sec_range']);f.update(start_sec_range=e['start_sec_range'],end_sec_range=e['end_sec_range']);facts.append(f)
    for i in record['identities']:
        f=fact(i,'identity','same physical entity',['id','subject_id','object_id','identity_status','frame_ids']);f['identity_status']=i['identity_status'];facts.append(f)
    g={'schema_version':'pilot-v1','video':deepcopy(media['video']),'clips':[deepcopy(clip)],'frames':[deepcopy(fs[i]) for i in clip['frame_ids']],'parser_runs':[run],'facts':facts}
    validate_graph(g);return g

def fact_signature(g,f):
    # Exact, conservative cross-sample match; no LLM equivalence and no occurrence counting.
    facts={x['fact_id']:x for x in g['facts']}
    canon=lambda s:' '.join(str(s).strip().lower().split())
    labels=[canon(x['predicate']) for x in g['facts'] if x['kind']=='object']
    # Duplicate descriptions do not identify interchangeable entities. Match no
    # cross-sample votes for such a graph; its own sample still matches itself.
    if len(labels)!=len(set(labels)):
        return digest(['AMBIGUOUS_ENTITY_ALIGNMENT',f['parser_run_id'],f['fact_id']])
    sig={k:f[k] for k in ['kind','predicate','clip_ids','support_frame_ids','start_sec_range','end_sec_range']}
    sig['predicate']=canon(sig['predicate']);sig['support_frame_ids']=sorted(sig['support_frame_ids'])
    for k in ['subject_id','object_id']:
        if k in f:sig[k]=canon(facts[f[k]]['predicate'])
    for k in ['node_type','identity_scope','attribute_value','identity_status']:
        if k in f:sig[k]=f[k]
    return digest(sig)

def attach_frequency(root,samples,runs):
    tables={rid:{fact_signature(g,f) for f in g['facts']} for rid,g in samples.items()}
    for f in root['facts']:
        sig=fact_signature(root,f)
        f['matched_parser_run_ids']=[r['parser_run_id'] for r in runs if sig in tables.get(r['parser_run_id'],set())]
        require(f['parser_run_id'] in f['matched_parser_run_ids'],'ROOT_FACT_MUST_MATCH_ITSELF')
    root['parser_runs']=runs;validate_graph(root);return root
