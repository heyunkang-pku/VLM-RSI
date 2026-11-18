import unittest
from four_group.public_qa import s_public_check,render_p
from four_group.multitime import multi_indices
class Public(unittest.TestCase):
 def test_multitime_single_scene(self):self.assertEqual(multi_indices({'scenes':[{'start_source_index':0,'end_source_index_exclusive':100}],'selected_keyframe_source_indices':[11]}),[0,11,33,66,99])
 def test_no_ids(self):self.assertTrue(s_public_check('What color is bottle1?','green'))
 def test_specific_question(self):self.assertIsNone(s_public_check('What color is the bottle cap?','green'))
 def test_answer_leakage(self):
  q={'program':{'scope':'v/f','op':'attribute','type':'color','object_id':'o1'},'answer':'red','question':'At 1.000 seconds, what is the color?','metadata':{}};obj={('v/f','o1'):{'candidate_content':{'label':'red cup'}}};self.assertEqual(render_p(q,obj)[1],'TARGET_ANSWER_IN_REFERENT')
