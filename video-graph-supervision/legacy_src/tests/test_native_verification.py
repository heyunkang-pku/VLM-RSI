import unittest,tempfile
from pathlib import Path
from step_native.native_verification import classify_correspondence,sample_signature_set,verify
from step_native.records import triples_with_issues
class Fake:
 mode=None
 def __init__(self,no=False):self.no=no;self.n=0
 def ask(self,media,ids,prompt,**kw):
  self.n+=1;role=kw['role'];reply='{"matches":["o0"],"reason":"same physical instance"}' if role=='frequency_instance_correspondence' else ('No' if self.no else 'Yes')
  return {'raw_response':reply,'request_id':'mock'+str(self.n)}
class VerificationContracts(unittest.TestCase):
 def graph(self):return {'object_nodes':[{'id':'o0','referent':'unique red box','classification':'static','source_request_ids':['q1']}],'attribute_nodes':[{'id':'a0','type':'color','value':'red','source_request_ids':['q2']}],'attribute_edges':[{'id':'h0','subject_id':'o0','attribute_id':'a0'}],'relation_edges':[],'unresolved_relation_claims':[]}
 def test_duplicate_instance_correspondence_not_forced(self):self.assertEqual(classify_correspondence({'a':['x'],'b':['x']}),{'a':None,'b':None})
 def test_ambiguous_candidates_not_picked(self):self.assertIsNone(classify_correspondence({'a':['x','y']})['a'])
 def test_sample_duplicate_fact_counts_once(self):
  g=self.graph();g['attribute_nodes']*=2;self.assertEqual(len(sample_signature_set(g,'attribute')),1)
 def test_failed_samples_remain_in_denominator(self):
  with tempfile.TemporaryDirectory() as d:
   g=self.graph();ss=[{'valid':i<3,'graph':g,'sample_id':str(i)} for i in range(5)];cfg={'sampling_replicas':5,'seed':1,'minimum_sample_occurrences':3,'work_root':d};media={'calibration_view':{},'clip_intervals':[]};_,rows=verify(Fake(),cfg,Path(d)/'check',g,media,ss,'scope');self.assertEqual(rows[0]['fixed_denominator'],5);self.assertEqual(rows[0]['frequency'],.6);self.assertTrue(rows[0]['sampling_incomplete'])
 def test_parent_rejection_cascades_without_attribute_check(self):
  with tempfile.TemporaryDirectory() as d:
   g=self.graph();ss=[{'valid':True,'graph':g,'sample_id':str(i)} for i in range(5)];cfg={'sampling_replicas':5,'seed':1,'minimum_sample_occurrences':3,'work_root':d};_,rows=verify(Fake(no=True),cfg,Path(d)/'check',g,{'calibration_view':{}},ss,'scope');self.assertEqual(rows[1]['state'],'BLOCKED_PARENT');self.assertIsNone(rows[1]['visual_request_id'])
 def test_good_tuples_survive_other_ambiguous_tuple(self):
  good,bad=triples_with_issues('<[cup1, unique red], on, table1> <cup1, red, on, table1>');self.assertEqual(len(good),1);self.assertEqual(len(bad),1)
if __name__=='__main__':unittest.main()
