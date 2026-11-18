import copy,unittest
from test_contracts import fixture,prog,ledger
from stsg_pilot.core import *
from stsg_pilot.candidates import generate_candidates
from stsg_pilot.controls import matched_controls

def tracked_fixture():
    g=fixture();g['clips']=[{'clip_id':'c1','interval_sec':[0,8],'frame_ids':['fr1','fr2'],'split_method':'SYNTHETIC'}]
    g['frames'][1]['clip_id']='c1'
    g['facts']=[g['facts'][0],g['facts'][2],g['facts'][3]]
    track=g['facts'][0];track.update(identity_scope='tracked_entity',support_frame_ids=['fr1','fr2'],end_sec_range=[5,5])
    for f in g['facts']:f['clip_ids']=['c1']
    g['facts'][2]['subject_id']='o1'
    return g

def shared_program():return {'op':'BEFORE','args':['ev1','ev2'],'identity_fact_id':None}

class IdentityAndControls(unittest.TestCase):
    def test_shared_track_needs_no_extra_identity_edge(self):
        g=tracked_fixture();q=freeze_question(g,shared_program())
        self.assertEqual(q['identity_mode'],'shared_track');self.assertEqual(q['required_fact_ids'],['ev1','ev2','o1'])
        self.assertEqual(execute(g,q)['answer'],'yes')
        self.assertEqual(execute(g,q,method='B2',ledger=ledger(g))['answer'],'yes')
        self.assertEqual(len(generate_candidates(g)['questions']),2)
    def test_shared_track_is_itself_an_identity_claim(self):
        g=tracked_fixture();q=freeze_question(g,shared_program());l=ledger(g)
        self.assertIn('SAME PHYSICAL ENTITY',checker_payload(g,'o1')['instruction'])
        for verdict in ['no','uncertain']:
            l[0]['visual_verdict']=verdict;l[0]['raw_response']=verdict
            r=execute(g,q,method='B2',ledger=l);self.assertEqual(r['status'],'ABSTAIN');self.assertIsNone(r['answer'])
    def test_missing_track_ledger_cannot_bypass_identity(self):
        g=tracked_fixture();q=freeze_question(g,shared_program())
        self.assertEqual(execute(g,q,method='B2',ledger=ledger(g)[1:])['status'],'ABSTAIN')
    def test_shared_id_without_tracking_evidence_not_enough(self):
        g=tracked_fixture();g['facts'][0].pop('identity_scope')
        with self.assertRaises(ContractError):freeze_question(g,shared_program())
        self.assertEqual(generate_candidates(g)['questions'],[])
    def test_shared_track_must_cover_both_event_frames(self):
        g=tracked_fixture();g['facts'][0]['support_frame_ids']=['fr1']
        with self.assertRaises(ContractError):freeze_question(g,shared_program())
    def test_distinct_nodes_still_require_identity_edge(self):
        g=fixture()
        with self.assertRaises(ContractError):freeze_question(g,shared_program())
        q=freeze_question(g,prog());self.assertIn('id1',q['required_fact_ids'])
    def test_selective_b2_never_changes_b1_answer(self):
        for g,p in [(fixture(),prog()),(tracked_fixture(),shared_program())]:
            q=freeze_question(g,p);a=execute(g,q);b=execute(g,q,method='B2',ledger=ledger(g))
            self.assertEqual(a['answer'],b['answer'])
    def test_controls_match_count_and_reuse_b1_only(self):
        g=fixture();qs=generate_candidates(g)['questions'];a=[execute(g,q) for q in qs]
        b=[execute(g,q,method='B2',ledger=ledger(g)) for q in qs];b[0].update(status='ABSTAIN',answer=None)
        r=matched_controls(qs,a,b,{g['video']['video_id']:g})
        self.assertEqual(r['model_calls_added'],0);self.assertEqual(r['target_accepted'],1)
        self.assertEqual(r,matched_controls(qs,a,b,{g['video']['video_id']:g}))
        amap={x['question_id']:x for x in a}
        for rows in r['methods'].values():
            self.assertEqual(sum(x['status']=='ANSWERED' for x in rows),1)
            for x in rows:
                if x['status']=='ANSWERED':self.assertEqual(x['answer'],amap[x['question_id']]['answer'])
    def test_controls_zero_coverage_defined(self):
        g=fixture();qs=generate_candidates(g)['questions'];a=[execute(g,q) for q in qs]
        b=[execute(g,q,method='B2',ledger=[]) for q in qs]
        r=matched_controls(qs,a,b,{g['video']['video_id']:g})
        self.assertTrue(all(x['status']=='ABSTAIN' for rows in r['methods'].values() for x in rows))
    def test_controls_refuse_answer_repair(self):
        g=fixture();qs=generate_candidates(g)['questions'];a=[execute(g,q) for q in qs]
        b=[execute(g,q,method='B2',ledger=ledger(g)) for q in qs];b[0]['answer']='corrupted'
        with self.assertRaises(ContractError):matched_controls(qs,a,b,{g['video']['video_id']:g})
    def test_controls_no_unfinished_as_rejected(self):
        g=fixture();qs=generate_candidates(g)['questions'];a=[execute(g,q) for q in qs]
        b=not_run_rows(qs);b=[x for x in b if x['method']=='B2']
        with self.assertRaises(ContractError):matched_controls(qs,a,b,{g['video']['video_id']:g})
