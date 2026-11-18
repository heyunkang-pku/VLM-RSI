import copy,json,tempfile,unittest
from pathlib import Path
from test_gate_b import tracked_fixture
from test_contracts import ledger
from stsg_pilot.staged_parser import expand_fsg,expand_events
from stsg_pilot.windowed_parser import windows,windowed_parse_video
from stsg_pilot.core import *
class WindowedParser(unittest.TestCase):
    def test_scalar_frame_id_is_exact_format_normalization(self):
        g=tracked_fixture();r={'objects':[{'id':'o','description':'entity','node_type':'dynamic','identity_scope':'single_frame','frame_ids':'fr1'}],'attributes':[],'relations':[]}
        before=copy.deepcopy(r);out=expand_fsg(r,g['clips'][0]);self.assertEqual(out['objects'][0]['frame_ids'],['fr1']);self.assertEqual(r,before)
        r['objects'][0]['frame_ids']='fr999'
        with self.assertRaises(ContractError):expand_fsg(r,g['clips'][0])
    def test_windows_partition_observations_without_more_frames(self):
        ids=[f'f{i}' for i in range(22)];parts=windows(ids,4)
        self.assertEqual([i for p in parts for i in p],ids);self.assertEqual(len(set(i for p in parts for i in p)),22)
        self.assertEqual(len(parts),4)
    def test_cached_fsg_and_local_events_keep_shared_identity_and_frequency(self):
        g=tracked_fixture();media={k:g[k] for k in ['video','frames','clips']};media['scenes_detected']=1
        fsg={'objects':[{'id':'o1','description':'SYNTHETIC person','node_type':'dynamic','identity_scope':'tracked_entity','frame_ids':'ALL'}],'attributes':[],'relations':[]}
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);(d/'cache/worker0').mkdir(parents=True);out=d/'out';out.mkdir()
            rows=[{'role':'parser_fsg','video_id':g['video']['video_id'],'status':'DONE','request_id':f'cache{i}','model_revision':'SYNTHETIC','prompt_sha256':'a'*64,'seed':i,'frame_content_hashes':[f['sha256'] for f in g['frames']],'shown_frame_ids':['fr1','fr2'],'raw_response':json.dumps(fsg),'output_hit_cap':False} for i in range(4)]
            (d/'cache/worker0/requests.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            class Fake:
                def __init__(self):self.calls=0
                def ask(self,*a,**kw):
                    self.calls+=1;assert kw['role']=='parser_events_window';fid='fr1' if 'window0' in kw['owner'] else 'fr2';verb='pick up cup' if fid=='fr1' else 'put down cup'
                    r={'events':[{'id':'e','kind':'event','subject_id':'o1','predicate':verb,'frame_ids':fid,'start_frame_range':[fid,fid],'end_frame_range':[fid,fid]}],'identities':[]}
                    return {'request_id':f'new{self.calls}','model_revision':'SYNTHETIC','prompt_sha256':'b'*64,'seed':kw['seed'],'raw_response':json.dumps(r),'output_hit_cap':False}
            cfg={'seed':1,'model_revision':'SYNTHETIC','fsg_cache_root':str(d/'cache'),'event_observation_windows':2,'event_max_tokens':512,'max_facts':64,'max_questions_per_video':5}
            rt=Fake();graph,qs=windowed_parse_video(rt,media,out,cfg)
            self.assertEqual(rt.calls,8);self.assertEqual(len(qs['questions']),2)
            self.assertTrue(all(frequency(graph,f)==1 for f in graph['facts']))
            for q in qs['questions']:
                self.assertEqual(q['identity_mode'],'shared_track')
                self.assertEqual(execute(graph,q)['answer'],execute(graph,q,method='B2',ledger=ledger(graph))['answer'])
            loss=json.loads((out/'parser_loss.json').read_text());self.assertEqual(loss['new_fsg_model_calls'],0)
            self.assertTrue(all(not w['true_scene_cut'] for w in loss['windows']))
