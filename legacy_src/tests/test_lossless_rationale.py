import json,tempfile,unittest,os,time
from pathlib import Path
from unittest.mock import patch
from step_six.rationale_recovery import raw_member,stage_recovery
from step_six.common import save,jl,j,rows,filehash
class LosslessRationaleTests(unittest.TestCase):
 def test_string_unchanged(self):self.assertEqual(raw_member('{"Q":"x","R":"a \\"quote\\"","A":"y"}','R'),'a "quote"')
 def test_nested_duplicate_text_retained(self):
  s='{"Q":"x","R":{"subquestion":"one","answer":"a","subquestion":"two","answer":"b"},"A":"y"}'
  r=raw_member(s,'R');self.assertIn('"one"',r);self.assertIn('"two"',r);self.assertEqual(r.count('"subquestion"'),2)
 def test_array_rationale(self):self.assertEqual(raw_member('{"R":[{"Q":"x","A":"y"}]}','R'),'[{"Q":"x","A":"y"}]')
 def test_top_level_duplicates_rejected(self):
  with self.assertRaises(ValueError):raw_member('{"R":"one","R":"two"}','R')
 def test_answer_object_rejected(self):
  with self.assertRaises(ValueError):raw_member('{"A":{"guess":"x"}}','A')
 def test_refinement_only_reuses_graph_and_P_bytes(self):
  with tempfile.TemporaryDirectory() as d:
   parent=Path(d)/'parent';root=Path(d)/'new';parent.mkdir();m={'v':{}}
   for name,value in [('GRAPH_SHARED_FROZEN.json',{'status':'PARTIAL'}),('FACT_REGISTRY.json',{}),('SOURCE_NATIVE_LEDGER.json',[]),('SOURCE_TEMPORAL_PAIRS.json',[]),('VIDEO_INPUTS_FROZEN.json',m),('S_PATH_PLANS_FROZEN.json',[{'plan_id':'sp','video_id':'v','status':'PLANNED','fact_ids':['f'],'event_context':None}]),('YIELD_COST_SUMMARY.json',{'groups':{}})]:save(parent/name,value)
   p={'question_id':'p','route':'P','question':'pquestion','video_id':'v','answer':'old'};jl(parent/'P_FROZEN_QA.jsonl',[p]);jl(parent/'P_ALL_CANDIDATES.jsonl',[p]);jl(parent/'S_FROZEN_QA.jsonl',[]);jl(parent/'vqs/RESULTS.jsonl',[])
   raw='{"Q":"q","R":{"step":"one","step":"two"},"A":"a","used_fact_ids":["f"]}'
   jl(parent/'graph_qra_calls/runtime/requests.jsonl',[{'role':'native_graph_path_initial_QRA','owner':'sp','raw_response':raw,'request_id':'oldinitial','output_hit_cap':False}])
   class Fake:
    gpu='0';started=time.monotonic();model_load_seconds=0;calls=1;initial_calls=0;cache_hits=0
   final={'request_id':'refine_only','raw_response':'{"Q":"q refined","R":["one","two"],"A":"a"}'}
   with patch.dict(os.environ,{'ORX_RUN_ID':'UNIT_TEST','ORX_COMMIT':'UNIT_TEST'}),patch('step_six.rationale_recovery.choose_gpu',return_value='0'),patch('step_six.rationale_recovery.make_runtime',return_value=Fake()),patch('step_six.rationale_recovery.ask',return_value=final) as ask:
    stage_recovery({'resume_six_root':str(parent)},root)
   self.assertEqual(ask.call_count,1);self.assertIn('"step":"one","step":"two"',ask.call_args.args[2]);self.assertEqual(filehash(root/'GRAPH_SHARED_FROZEN.json'),filehash(parent/'GRAPH_SHARED_FROZEN.json'));self.assertEqual(filehash(root/'P_FROZEN_QA.jsonl'),filehash(parent/'P_FROZEN_QA.jsonl'));self.assertEqual(rows(root/'S_FROZEN_QA.jsonl')[0]['initial_request_id'],'oldinitial');self.assertEqual(rows(root/'SOLVER_QUESTIONS_ONLY.jsonl')[0]['question'],'q refined');self.assertNotIn('answer',rows(root/'SOLVER_QUESTIONS_ONLY.jsonl')[0])
