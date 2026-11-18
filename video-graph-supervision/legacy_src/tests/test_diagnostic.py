import copy,unittest
from stsg_pilot.parser_diagnostic import analyze,prompts,objects_from_fsg
from stsg_pilot.staged_parser import EVENT_SPEC
class DiagnosticContracts(unittest.TestCase):
    def setUp(self):
        self.media={'frames':[{'frame_id':f'f{i:03d}','time_sec':i} for i in range(3)]}
        self.graph={'facts':[{'fact_id':'c0_o1','kind':'object','predicate':'a visible hand','node_type':'dynamic','identity_scope':'tracked_entity','support_frame_ids':['f000','f001','f002']}]}
    def response(self,text):return {'condition':'B','raw_response':text,'video_id':'video_7793'}
    def test_minimal_nonempty_without_fsg_id(self):
        r=analyze(self.response('{"events":[{"action":"hand lifts cup","subject":"hand","evidence_frames":["f001"],"start_frame":"f000","end_frame":"f002"}]}'),self.media,self.graph)
        self.assertTrue(r['schema_valid']);self.assertEqual(r['event_count'],1);self.assertEqual(r['visual_support'],'REQUIRES_FRAME_REVIEW')
    def test_empty_is_valid_but_not_productive(self):
        r=analyze(self.response('{"events":[]}'),self.media,self.graph);self.assertTrue(r['schema_valid']);self.assertEqual(r['event_count'],0)
    def test_hallucinated_frame_rejected(self):
        r=analyze(self.response('{"events":[{"action":"lifts","subject":"hand","evidence_frames":["f999"],"start_frame":"f000","end_frame":"f002"}]}'),self.media,self.graph);self.assertFalse(r['schema_valid'])
    def test_inverted_boundary_rejected(self):
        r=analyze(self.response('{"events":[{"action":"lifts","subject":"hand","evidence_frames":["f001"],"start_frame":"f002","end_frame":"f000"}]}'),self.media,self.graph);self.assertFalse(r['schema_valid'])
    def test_protocol_c_unchanged_and_no_response_leak(self):
        before=copy.deepcopy(self.graph);p=prompts(self.graph)
        self.assertTrue(p['C'].startswith(EVENT_SPEC+'\nExisting immutable local objects: '));self.assertNotIn('a visible hand',p['A']);self.assertNotIn('a visible hand',p['B']);self.assertEqual(self.graph,before)
    def test_unparseable_separate_from_empty(self):
        r=analyze(self.response('an action'),self.media,self.graph);self.assertFalse(r['json_parsed']);self.assertIsNone(r['event_count'])
if __name__=='__main__':unittest.main()
