import unittest
from four_group.event_mcq import validate,similar
class Event(unittest.TestCase):
 def test_near_duplicate(self):self.assertTrue(similar('What happened after the man lifted the cup?','What happened after the man lifted a cup?'))
 def test_clip_description_not_bound_event(self):
  q={'type':'event_order','options':['one','two','three','four'],'answer_index':0,'evidence_frame_ids':['f1','f2'],'cross_frame_reason':'temporal order','fact_ids':['x'],'event_or_action_edge_ids':['e1','e2'],'question':'Which action happened first?'}
  g={'motion_edges':[],'event_edges':[{'id':'e1'},{'id':'e2'}]};self.assertEqual(validate(q,g,{'x':{}},[],{'f1','f2'},[]),'EVENT_ENTITY_OR_INTERVAL_UNRESOLVED')
 def test_single_frame_rejected(self):
  q={'type':'state_change','options':['a','b','c','d'],'answer_index':0,'evidence_frame_ids':['x']};self.assertEqual(validate(q,{}, {},[],{'x'},[]),'FRAME_IDS')
