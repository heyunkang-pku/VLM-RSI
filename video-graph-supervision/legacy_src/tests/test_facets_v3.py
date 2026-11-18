import unittest,copy
from unittest.mock import patch
from tests.test_verification_repair import fixture
from step_verify_repair.facets_v3 import p_main,s_main
from step_verify_repair.gates_v2 import decide_status
class FacetTests(unittest.TestCase):
 def test_ambiguity_no_not_a_main_atom(self):
  q,f,ld,p,g=fixture();d=p_main(q,f,ld,p,g);self.assertTrue(d['complete']);self.assertNotIn('entity_resolution',[x['kind'] for x in d['atoms']]);self.assertTrue(d['ambiguity_requirements']);self.assertEqual(d['question_ambiguity']['status'],'PENDING_INDEPENDENT_REVIEW')
 def test_rationale_failure_does_not_veto_main(self):
  q={'question_id':'q','video_id':'v','question':'What color?','answer':'red','rationale':'false background','fact_ids':['a']};before=copy.deepcopy(q);dep={'complete':True,'unresolved':[],'atoms':[{'kind':'attribute'}]}
  with patch('step_verify_repair.facets_v3.strict_s_dependencies',return_value=dep) as main,patch('step_verify_repair.facets_v3.bounded_call',side_effect=ValueError('reasoning failed')):d=s_main(None,q,{}, {'v':{}})
  self.assertEqual(main.call_args.args[1]['rationale'],'');self.assertTrue(d['complete']);self.assertEqual(q,before);self.assertEqual(d['reasoning_review']['status'],'UNRESOLVED_TEXT_REVIEW');self.assertEqual(decide_status(d,[{'sufficient':True}],[{'verdict':'YES'}]),'ACCEPT')
 def test_rationale_is_not_added_as_main_assertion(self):
  q={'question_id':'q','video_id':'v','question':'color','answer':'red','rationale':'extra movements','fact_ids':['a']}
  with patch('step_verify_repair.facets_v3.strict_s_dependencies',return_value={'complete':False,'unresolved':[{'reason':'missing referent'}],'atoms':[]}),patch('step_verify_repair.facets_v3.bounded_call',side_effect=ValueError('background')):d=s_main(None,q,{}, {'v':{}})
  self.assertFalse(d['complete']);self.assertEqual(len(d['unresolved']),1)
