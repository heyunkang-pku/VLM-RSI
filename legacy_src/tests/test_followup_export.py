import unittest
from four_group.followup_run import export_adapter
class Export(unittest.TestCase):
 def test_legacy_candidate_field_is_adapted_without_mutation(self):
  q={'candidate_answer':['supports'],'dependencies':{'facts':['x']}};r=export_adapter(q);self.assertEqual(r['answer'],['supports']);self.assertEqual(r['program_read_trace'],q['dependencies']);self.assertNotIn('answer',q)
