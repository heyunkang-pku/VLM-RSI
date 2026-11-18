import unittest,tempfile,json
from pathlib import Path
from four_group.results import aggregate
class FourGroupVotesTests(unittest.TestCase):
 def test_plurality_does_not_disappear_under_strict_abstention(self):
  r=aggregate([{'status':'VALID','answer':'a'}]*4+[{'status':'VALID','answer':'b'}]*3+[{'status':'ABSTAIN'}]*3);self.assertEqual(r['plurality_answer'],'a');self.assertIsNone(r['strict_majority_answer']);self.assertEqual(r['fixed_denominator'],10)
 def test_tie_preserves_all_winners(self):
  r=aggregate([{'status':'VALID','answer':'a'}]*5+[{'status':'VALID','answer':'b'}]*5);self.assertTrue(r['tie']);self.assertEqual(r['plurality_candidates'],['a','b']);self.assertIsNone(r['plurality_answer'])
 def test_invalid_all_not_silently_removed(self):
  r=aggregate([{'status':'FAILED','error':'cap'}]*10);self.assertTrue(r['no_valid_answer']);self.assertEqual(r['sample_status_counts']['FAILED'],10)
 def test_exact_six_works(self):self.assertEqual(aggregate([{'status':'VALID','answer':'Red.'}]*6)['strict_majority_answer'],'red')
 def test_no_extra_verifier_imported(self):
  files=[p.read_text() for p in Path('four_group').glob('*.py')];self.assertFalse(any('from step_six.verification' in s or 'from step_verify_repair' in s for s in files))
 def test_no_connected_pair_retains_four_attempts_per_video(self):
  from four_group.routes import s_route
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);(r/'GRAPH_SHARED_FROZEN.json').write_text('{}');frozen=s_route(None,r,{'event_edges':[]},{},{},[{'video_id':'video_1'},{'video_id':'video_2'}]);self.assertEqual(frozen,[]);self.assertEqual(len((r/'S_ALL_CANDIDATES.jsonl').read_text().splitlines()),8)
 def test_old_uniqueness_gate_not_a_new_program_filter(self):
  from four_group.routes import p_route
  from tests.test_verification_repair import fixture
  q,f,ld,p,g=fixture();other=dict(ld[0],fact_id='o2');other['candidate_content']=dict(other['candidate_content']);ld.append(other)
  for row in ld:row['source_keyframe']={'time_sec':1.234}
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);(r/'GRAPH_SHARED_FROZEN.json').write_text('{}');chosen=p_route(r,g,ld,p,[{'video_id':'v'}]);self.assertTrue(chosen);self.assertEqual(chosen[0]['execution']['status'],'ANSWERED');self.assertEqual(chosen[0]['historical_adapter_reason_diagnostic_only'],'ENTITY_NOT_UNIQUE_IN_AUTOMATIC_GRAPH')
