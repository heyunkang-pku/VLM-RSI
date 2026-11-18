import copy,json,tempfile,unittest
from pathlib import Path
from test_gate_b import tracked_fixture
from test_contracts import ledger
from stsg_pilot.staged_parser import expand_fsg,expand_events,staged_parse_video
from stsg_pilot.core import *

class StagedParser(unittest.TestCase):
    def test_explicit_all_is_a_claim_not_inferred_missing_observation(self):
        g=tracked_fixture();clip=g['clips'][0]
        r={'objects':[{'id':'o1','description':'person','node_type':'dynamic','identity_scope':'tracked_entity','frame_ids':'ALL'}],'attributes':[],'relations':[]}
        before=copy.deepcopy(r);out=expand_fsg(r,clip)
        self.assertEqual(out['objects'][0]['frame_ids'],['fr1','fr2']);self.assertEqual(r,before)
    def test_actual_pts_range_conversion_not_index_over_fps(self):
        g=tracked_fixture();r={'events':[{'id':'e','kind':'event','subject_id':'o1','predicate':'acts','frame_ids':['fr1','fr2'],'start_frame_range':['fr1','fr1'],'end_frame_range':['fr2','fr2']}],'identities':[]}
        out=expand_events(r,g,g['clips'][0]);self.assertEqual(out['events'][0]['start_sec_range'],[1,1]);self.assertEqual(out['events'][0]['end_sec_range'],[5,5]);self.assertIn('start_frame_range',r['events'][0])
    def test_unknown_frame_boundary_not_guessed(self):
        g=tracked_fixture();r={'events':[{'id':'e','kind':'event','subject_id':'o1','predicate':'acts','frame_ids':['fr1'],'start_frame_range':['not-seen','fr1'],'end_frame_range':['fr2','fr2']}],'identities':[]}
        with self.assertRaises(ContractError):expand_events(r,g,g['clips'][0])
    def test_shared_track_staged_frequency_dependency_and_selective_gate(self):
        g=tracked_fixture();media={k:g[k] for k in ['video','frames','clips']};media['scenes_detected']=1
        fsg={'objects':[{'id':'o1','description':'SYNTHETIC red-shirt person','node_type':'dynamic','identity_scope':'tracked_entity','frame_ids':'ALL'}],'attributes':[],'relations':[]}
        ev={'events':[{'id':'e1','kind':'event','subject_id':'o1','predicate':'pick up cup','frame_ids':['fr1'],'start_frame_range':['fr1','fr1'],'end_frame_range':['fr1','fr1']},
                      {'id':'e2','kind':'event','subject_id':'o1','predicate':'put down cup','frame_ids':['fr2'],'start_frame_range':['fr2','fr2'],'end_frame_range':['fr2','fr2']}],'identities':[]}
        class FakeRuntime:
            def __init__(self):self.calls=0
            def ask(self,*a,**kw):
                self.calls+=1
                return {'request_id':f'p{self.calls}','model_revision':'SYNTHETIC','prompt_sha256':'a'*64,'seed':kw['seed'],'raw_response':json.dumps(fsg if kw['role']=='parser_fsg' else ev),'output_hit_cap':False}
        cfg={'seed':20261030,'object_max_tokens':2048,'event_max_tokens':2048,'max_facts':64,'max_questions_per_video':5}
        with tempfile.TemporaryDirectory() as d:
            rt=FakeRuntime();graph,qs=staged_parse_video(rt,media,Path(d),cfg)
            self.assertEqual(rt.calls,8);self.assertEqual(len(qs['questions']),2)
            self.assertTrue(all(frequency(graph,f)==1 for f in graph['facts']))
            self.assertEqual(len({r['sample_group'] for r in graph['parser_runs']}),2)
            for q in qs['questions']:
                self.assertEqual(q['identity_mode'],'shared_track')
                self.assertEqual(execute(graph,q)['answer'],execute(graph,q,method='B2',ledger=ledger(graph))['answer'])
