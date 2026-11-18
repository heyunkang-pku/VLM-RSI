import unittest,copy,json
from unittest.mock import patch
from step_verify_repair.semantic_v2 import sources,s_dependencies
from step_verify_repair.gates_v2 import evidence_preflight,decide_status,p_annotations

class V2GateTests(unittest.TestCase):
 def test_duplicate_json_rationale_leaves_not_braces(self):
  q={'question':'Q?','answer':'A.','rationale':'{"Q":"first","A":"one","Q":"second","A":"two"}'};r=[x for x in sources(q) if x['source_field']=='rationale'];self.assertEqual([x['text'] for x in r],['first','one','second','two']);self.assertEqual(len({x['logical_path'] for x in r}),4)
 def test_answer_source_cannot_be_relabelled_by_model(self):
  q={'question_id':'s','video_id':'v','question':'Which cup?','answer':'It is red.','rationale':'irrelevant room decoration','fact_ids':['o']};f={'o':{'id':'o','kind':'object','claim':'cup','parent_ids':[],'scope':'scope','video_id':'v'}}
  def fake(rt,m,prompt,role,owner,*args,**kw):
   if role=='S2_v2_coverage_audit':
    data={'reviews':[{'source_id':x['source_id'],'decision':'background_valid' if x['source_field']=='rationale' else 'covered','reason':'explicit relation to Q/A'} for x in sources(q)]}
   elif role=='S2_v2_rationale_support_link':data={'role':'background','reason':'decoration does not determine cup/color','supports':[],'items':[]}
   else:data={'items':[{'claim':'cup visible','kind':'object','reason':'bind cup','fact_ids':['o'],'evidence_fact_id':'o','source_field':'rationale','quote':'FAKE'}],'covered':True,'missing':[]}
   return {'request_id':owner,'raw_response':json.dumps(data)},[]
  with patch('step_verify_repair.semantic_v2.bounded_call',side_effect=fake):d=s_dependencies(None,q,f,{'v':{}})
  answer=[x for x in d['atoms'] if x['source_field']=='answer'];self.assertEqual(len(answer),1);self.assertEqual(answer[0]['quote'],q['answer']);self.assertEqual(len(d['background_assumptions']),1)
 def test_incomplete_dependencies_override_NO(self):
  self.assertEqual(decide_status({'complete':False,'atoms':[{}]},[{'sufficient':True}],[{'verdict':'NO'}]),'UNRESOLVED_DEPENDENCY_BEFORE_VISUAL')
 def test_insufficient_scope_overrides_NO(self):
  self.assertEqual(decide_status({'complete':True,'atoms':[{}]},[{'sufficient':False}],[{'verdict':'NO'}]),'UNRESOLVED_EVIDENCE_BEFORE_VISUAL')
 def test_valid_NO_requires_both_prechecks(self):self.assertEqual(decide_status({'complete':True,'atoms':[{}]},[{'sufficient':True}],[{'verdict':'NO'}]),'ABSTAIN_REQUIRED_FACT_MODEL_NO')
 def test_no_vacuous_accept(self):self.assertNotEqual(decide_status({'complete':True,'atoms':[]},[],[]),'ACCEPT')
 def test_missing_endpoint_before_any_visual_call(self):
  q={'route':'S','question':'What changed from 16.09 to 17.47 seconds?'};a={'kind':'identity','claim':'same bag','source_text':q['question'],'evidence_scope':'interval','evidence_fact_id':'e'};m={'class_video_views':[{'time_sec':16.0925,'frame_id':'a','sha256':'a'},{'time_sec':16.7335,'frame_id':'b','sha256':'b'}]};p=evidence_preflight(a,q,{'e':{}},m,'video');self.assertFalse(p['sufficient']);self.assertIn('REQUESTED_OBSERVATION_NOT_IN_ACTUAL_INPUT',p['issues'])
 def test_half_decimal_matches_do_not_require_exact_print(self):
  q={'route':'S','question':'What at 1.234 seconds?'};a={'kind':'attribute','claim':'red','source_text':q['question'],'evidence_fact_id':'e'};f={'time_sec':1.2344,'frame_id':'a','sha256':'a'};p=evidence_preflight(a,q,{'e':{}},{'calibration_view':f},'image');self.assertTrue(p['sufficient'])
 def test_time_range_inside_envelope_but_missing_endpoint_is_unresolved(self):
  q={'route':'S','question':'At 1.000 seconds?'};a={'kind':'attribute','claim':'red','source_text':q['question'],'evidence_fact_id':'e'};m={'class_video_views':[{'time_sec':0,'frame_id':'a','sha256':'a'},{'time_sec':2,'frame_id':'b','sha256':'b'}]};self.assertFalse(evidence_preflight(a,q,{'e':{}},m,'video')['sufficient'])
 def test_relation_positives_not_exhaustive(self):
  dep={'complete':True,'unresolved':[],'atoms':[]};q={'program':{'op':'relation'}};d=p_annotations(dep,q,{});self.assertFalse(d['complete']);self.assertEqual(d['relation_completeness']['real_world_relation_set_complete'],'UNVERIFIED');self.assertTrue(dep['complete'])
 def test_surface_not_bound_by_private_qualifier(self):
  a={'kind':'object','evidence_fact_id':'o'};f={'o':{'content':{'label':'surface','referent':'gray surface'},'time_sec':1,'media':{'calibration_view':{'frame_id':'a'}}}};d=p_annotations({'atoms':[a],'unresolved':[]},{'program':{'op':'attribute'}},f);self.assertFalse(d['complete']);self.assertEqual(d['referring_bindings'][0]['public_expression'],'surface')

class WorkerPreflightIntegrationTest(unittest.TestCase):
 def test_visual_ask_is_never_called_for_missing_endpoint(self):
  import tempfile,time,os
  from pathlib import Path
  from step_six.common import save,jl,j
  from step_verify_repair.runner import worker
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);f=r/'frozen';q={'question_id':'s','route':'S','video_id':'v','question':'What from 16.09 to 17.47 seconds?','answer':'a'};atom={'requirement_id':'r','kind':'identity','claim':'same item','source_text':q['question'],'source_field':'question','reason':'identity premise','fact_ids':['e'],'evidence_fact_id':'e'};dep={'complete':True,'atoms':[atom],'unresolved':[]};media={'class_video_views':[{'time_sec':16.092,'frame_id':'a','sha256':'a'},{'time_sec':16.734,'frame_id':'b','sha256':'b'}]}
   for name,value in [('FACT_REGISTRY.json',{'e':{}}),('VIDEO_INPUTS_FROZEN.json',{}),('GRAPH_SHARED_FROZEN.json',{}),('SOURCE_NATIVE_LEDGER.json',[]),('SOURCE_TEMPORAL_PAIRS.json',[])]:save(f/name,value)
   jl(f/'previous_repair/REPAIRED_CHECK_RESULTS.jsonl',[{'question_id':'s','status':'ABSTAIN_REQUIRED_FACT_MODEL_NO','checks':[{'verdict':'NO','claim':'old ungrounded'}]}]);save(r/'shard_0.json',[q])
   class Fake:
    def __init__(self,*args):self.gpu='0';self.started=time.monotonic();self.model_load_seconds=0;self.calls=self.initial_calls=self.cache_hits=0
   with patch('step_verify_repair.runner.RepairRuntime',Fake),patch('step_verify_repair.runner.s_main',return_value=dep),patch('step_verify_repair.runner.pair_contexts',return_value={}),patch('step_verify_repair.runner.atom_media',return_value=(media,'video')),patch('step_verify_repair.runner.bounded_call',side_effect=AssertionError('visual must not run')) as ask:
    worker({'work_root':str(r),'protocol_version':'unit','temporal_root':'unused'},0,'0')
   ask.assert_not_called();result=j(r/'questions/s.json');self.assertEqual(result['status'],'UNRESOLVED_EVIDENCE_BEFORE_VISUAL');self.assertEqual(result['checks'][0]['verdict'],'NOT_RUN_PRECHECK')
