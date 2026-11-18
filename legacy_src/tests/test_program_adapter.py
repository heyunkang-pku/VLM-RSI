import unittest,copy
from step_review.program_adapter import main_candidates,execute,select
class ProgramContracts(unittest.TestCase):
 def fixture(self):
  s='video_test/src_1';o={'scope':s,'fact_id':'o0','fact_type':'object','state':'ACCEPTED','candidate_content':{'label':'box'},'source_keyframe':{'time_sec':1}};a={'scope':s,'fact_id':'a0','fact_type':'attribute','state':'ACCEPTED','parent_ids':['o0'],'candidate_content':{'type':'color','value':'red'},'source_keyframe':{'time_sec':1}};return [o,a]
 def test_really_executes_attribute(self):
  rows=self.fixture();q=main_candidates({},rows,[])[0];self.assertEqual(execute(q,rows,[],{})['answer'],'red')
 def test_changed_fact_dependencies_abstain(self):
  rows=self.fixture();q=main_candidates({},rows,[])[0];changed=copy.deepcopy(rows);changed[1]['candidate_content']['value']='blue';self.assertEqual(execute(q,changed,[],{})['status'],'ABSTAIN')
 def test_ambiguous_class_does_not_use_ordinal(self):
  rows=self.fixture();extra=copy.deepcopy(rows[0]);extra['fact_id']='o1';rows.append(extra);q=main_candidates({},rows,[])[0];self.assertEqual(q['status'],'ABSTAIN')
 def test_conflicting_attribute_values_abstain(self):
  rows=self.fixture();a=copy.deepcopy(rows[1]);a.update(fact_id='a1');a['candidate_content']['value']='blue';rows.append(a);self.assertTrue(all(x['status']=='ABSTAIN' for x in main_candidates({},rows,[])))
 def test_missing_motion_support_cannot_be_disabled(self):
  rows=self.fixture();edges=[{'id':f'm{i}','source':'video_test/src_1/o0','action':'moving','usable_for_program_QA':False} for i in range(2)];q=main_candidates({'motion_edges':edges},rows,[])[-1];self.assertEqual(q['abstention_reason'],'DEPENDENCY_UNSUPPORTED');self.assertEqual(execute(q,rows,[],{})['status'],'ABSTAIN')
 def test_deterministic_selection_never_exceeds_quota(self):
  rows=self.fixture();q=main_candidates({},rows,[]);self.assertEqual(select(q),select(list(reversed(q))))
if __name__=='__main__':unittest.main()
