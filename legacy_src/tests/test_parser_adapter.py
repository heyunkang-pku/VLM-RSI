import copy,json,unittest
from test_gate_b import tracked_fixture,shared_program
from stsg_pilot.core import *
from stsg_pilot.parsing import parse_json,make_clip_graph,attach_frequency,fact_signature
from stsg_pilot.smoke import verify_select_b1
from test_contracts import ledger

def parse_fixture(run_id='p0'):
    g=tracked_fixture();media={k:g[k] for k in ['video','frames','clips']};clip=g['clips'][0];run=copy.deepcopy(g['parser_runs'][0]);run['parser_run_id']=run_id
    record={'objects':[{'id':'x','description':'red-shirt person','node_type':'dynamic','identity_scope':'tracked_entity','frame_ids':['fr1','fr2']}],
            'events':[{'id':'e1','kind':'event','subject_id':'x','predicate':'pick up cup','frame_ids':['fr1'],'start_sec_range':[1,1],'end_sec_range':[2,2]},
                      {'id':'e2','kind':'event','subject_id':'x','predicate':'put down cup','frame_ids':['fr2'],'start_sec_range':[5,5],'end_sec_range':[6,6]}],
            'attributes':[],'relations':[],'identities':[]}
    return media,clip,record,run
class ParserAdapter(unittest.TestCase):
    def test_parser_json_no_guessing_partial_structure(self):
        self.assertEqual(parse_json('```json\n{"objects":[]}\n```'),{'objects':[]})
        for text in ['Some explanation {"objects":[]}','{"objects": [','```json\n{} trailing\n```']:
            with self.assertRaises((ValueError,ContractError)):parse_json(text)
    def test_actual_translator_preserves_track_and_events(self):
        m,c,r,p=parse_fixture();g=make_clip_graph(m,c,r,p);qs=__import__('stsg_pilot.candidates',fromlist=['generate_candidates']).generate_candidates(g)
        self.assertEqual(len(qs['questions']),2);self.assertTrue(all(q['identity_mode']=='shared_track' for q in qs['questions']))
    def test_parser_claim_dangling_or_unknown_fields_fail_closed(self):
        for modify in [lambda r:r.update(gold_answer='yes'),lambda r:r['events'][0].update(subject_id='missing'),lambda r:r['events'][0].update(frame_ids=['wrong'])]:
            m,c,r,p=parse_fixture();modify(r)
            with self.assertRaises((ContractError,KeyError)):make_clip_graph(m,c,r,p)
    def test_cross_sample_matching_ignores_arbitrary_local_ids(self):
        m,c,r,p=parse_fixture();a=make_clip_graph(m,c,r,p)
        r2=copy.deepcopy(r);r2['objects'][0]['id']='different-id'
        for e in r2['events']:e['subject_id']='different-id'
        p2=copy.deepcopy(p);p2['parser_run_id']='p1';p2['seed']=1
        b=make_clip_graph(m,c,r2,p2)
        result=attach_frequency(copy.deepcopy(a),{'p0':a,'p1':b},[p,p2])
        self.assertTrue(all(frequency(result,f)==1 for f in result['facts']))
    def test_interval_disagreement_does_not_count_as_same_fact(self):
        m,c,r,p=parse_fixture();a=make_clip_graph(m,c,r,p)
        r2=copy.deepcopy(r);r2['events'][0]['end_sec_range']=[3,3]
        p2=copy.deepcopy(p);p2['parser_run_id']='p1';p2['seed']=1;b=make_clip_graph(m,c,r2,p2)
        result=attach_frequency(copy.deepcopy(a),{'p0':a,'p1':b},[p,p2]);f=next(f for f in result['facts'] if f['fact_id']=='c1_e1')
        self.assertEqual(frequency(result,f),.5)
    def test_duplicate_descriptions_never_give_cross_sample_identity_votes(self):
        m,c,r,p=parse_fixture();dup=copy.deepcopy(r['objects'][0]);dup['id']='y';r['objects'].append(dup);a=make_clip_graph(m,c,r,p)
        p2=copy.deepcopy(p);p2['parser_run_id']='p1';p2['seed']=1;b=make_clip_graph(m,c,r,p2)
        result=attach_frequency(copy.deepcopy(a),{'p0':a,'p1':b},[p,p2]);self.assertTrue(all(frequency(result,f)==.5 for f in result['facts']))
    def test_selective_verifier_returns_existing_b1_label(self):
        g=tracked_fixture();q=freeze_question(g,shared_program());a=execute(g,q)
        b=verify_select_b1(g,q,a,ledger(g),{'frequency_threshold':.75})
        self.assertEqual(b['answer'],a['answer']);self.assertEqual(b['function'],'Selective Verification')
        corrupt=copy.deepcopy(a);corrupt['answer']='no'
        with self.assertRaises(ContractError):verify_select_b1(g,q,corrupt,ledger(g),{'frequency_threshold':.75})

class ModelGeometry(unittest.TestCase):
    def test_qwen3_checkpoint_alignment_not_qwen25_alignment(self):
        from stsg_pilot.media import check_geometry
        check_geometry(160,288,16,2)
        check_geometry(224,224,16,2)
        with self.assertRaises(ContractError):check_geometry(168,280,16,2)
