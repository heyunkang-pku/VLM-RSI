"""All inputs synthetic. No real video, human review or model outputs used."""
import copy
import json
import unittest
from fractions import Fraction
from stsg_pilot.core import *
from stsg_pilot.metrics import summarize
from stsg_pilot.adapters import launch_models

def fixture():
    # Two synthetic clips, local identity nodes, nonzero PTS origin, VFR support.
    frames=[{'frame_id':'fr1','clip_id':'c1','pts':1100,'time_sec':1.,'sha256':'a'*64,'file':'SYNTHETIC/fr1.jpg'},
            {'frame_id':'fr2','clip_id':'c2','pts':1500,'time_sec':5.,'sha256':'b'*64,'file':'SYNTHETIC/fr2.jpg'}]
    runs=[{'parser_run_id':f'p{i}','model_revision':'SYNTHETIC-NO-MODEL',
           'prompt_hash':'c'*64,'seed':i,'frame_ids':['fr1','fr2'],'sample_group':'same-evidence'} for i in range(4)]
    def fact(i,kind,pred,clips,frames,lo,hi,**kw):
        if kind=='object':kw['node_type']='dynamic'
        return dict(fact_id=i,kind=kind,predicate=pred,clip_ids=clips,support_frame_ids=frames,
                    parser_run_id='p0',matched_parser_run_ids=['p0','p1','p2','p3'],
                    start_sec_range=[lo,lo],end_sec_range=[hi,hi],depends_on=[],**kw)
    facts=[fact('o1','object','red-shirt person in clip1',['c1'],['fr1'],1,1),
           fact('o2','object','red-shirt person in clip2',['c2'],['fr2'],5,5),
           fact('ev1','event','pick up cup',['c1'],['fr1'],1,2,subject_id='o1'),
           fact('ev2','motion','put down cup',['c2'],['fr2'],5,6,subject_id='o2'),
           fact('id1','identity','same physical person',['c1','c2'],['fr1','fr2'],1,5,
                subject_id='o1',object_id='o2',identity_status='known')]
    return {'schema_version':'pilot-v1','video':{'video_id':'SYNTHETIC-v1','source_video_id':'SYNTHETIC-source',
           'path':'SYNTHETIC/does-not-exist.mp4','sha256':'d'*64,'duration_sec':8.,'avg_fps':'30000/1001',
           'time_base':'1/100','start_pts':1000,'source':'synthetic-unit-test','split':'fixture','license_status':'fixture'},
           'clips':[{'clip_id':'c1','interval_sec':[0,4],'frame_ids':['fr1'],'split_method':'SYNTHETIC'},
                    {'clip_id':'c2','interval_sec':[4,8],'frame_ids':['fr2'],'split_method':'SYNTHETIC'}],
           'frames':frames,'parser_runs':runs,'facts':facts}

def prog(op='BEFORE'):
    return {'op':op,'args':['ev1','ev2'],'identity_fact_id':'id1'}
def ledger(g):
    return [ledger_entry(g,f['fact_id'],'yes','SYNTHETIC-CHECKER',f['support_frame_ids'],checker_run_id='SYNTHETIC-CHECK-RUN',raw_response='yes',reason='synthetic fixture only') for f in g['facts']]

class Contracts(unittest.TestCase):
    def setUp(self):self.g=fixture();self.q=freeze_question(self.g,prog())
    def run_b2(self,led=None,q=None,g=None):
        return execute(g or self.g,q or self.q,method='B2',ledger=ledger(self.g) if led is None else led)
    def test_01_rational_fps_and_pts(self):
        self.assertEqual(pts_seconds(1001,'1/30000'),Fraction(1001,30000))
        self.assertEqual(pts_seconds(1500,'1/100',1000),5)
        self.assertEqual(sample_pts([1000,1001,1010,1100],'1/100',1000,3),[1000,1010,1100])
    def test_02_pts_boundary_and_bad_clock(self):
        self.assertEqual(sample_pts([7],'1/2',7,1),[7])
        for args in [([1,1],'1/2',0,2),([2,1],'1/2',0,2),([1],'0',0,1),([1],'1',2,1)]:
            with self.assertRaises(ContractError):sample_pts(*args)
        g=fixture();g['frames'][0]['time_sec']=1.1
        with self.assertRaises(ContractError):validate_graph(g)
    def test_03_determinism_and_immutable_input(self):
        before=digest(self.g);a=execute(self.g,self.q);b=execute(self.g,self.q)
        self.assertEqual(a,b);self.assertEqual(before,digest(self.g));self.assertEqual(a['answer'],'yes')
        self.assertEqual(digest({'x':1,'y':2}),digest({'y':2,'x':1}))
    def test_04_rejected_required_fact_abstains(self):
        l=ledger(self.g);l[0]['visual_verdict']='no';l[0]['raw_response']='no'
        r=self.run_b2(l);self.assertEqual(r['status'],'ABSTAIN');self.assertIsNone(r['answer'])
    def test_05_missing_or_uncertain_fact_abstains(self):
        self.assertEqual(self.run_b2(ledger(self.g)[1:])['status'],'ABSTAIN')
        l=ledger(self.g);l[0]['visual_verdict']='uncertain';l[0]['raw_response']='uncertain'
        self.assertEqual(self.run_b2(l)['status'],'ABSTAIN')
    def test_06_touching_or_overlap_not_strict_order(self):
        # Build same-clip boundary fixture so provenance stays structurally valid.
        g=fixture();g['clips']=[{'clip_id':'c1','interval_sec':[0,8],'frame_ids':['fr1','fr2'],'split_method':'SYNTHETIC'}]
        g['frames'][1]['clip_id']='c1'
        for f in g['facts']:f['clip_ids']=['c1']
        g['facts'][2]['end_sec_range']=[5,5]
        r=execute(g,freeze_question(g,prog()));self.assertEqual(r['reason'],'OVERLAPPING_OR_UNCERTAIN_ORDER')
        g['facts'][2]['end_sec_range']=[4.9,5.1]
        self.assertEqual(execute(g,freeze_question(g,prog()))['status'],'ABSTAIN')
    def test_07_unknown_crossclip_identity(self):
        g=fixture();g['facts'][-1]['identity_status']='unknown';q=freeze_question(g,prog())
        self.assertEqual(execute(g,q)['reason'],'UNKNOWN_IDENTITY')
        self.assertEqual(execute(g,q,method='B2',ledger=ledger(g))['status'],'ABSTAIN')
    def test_08_crossclip_dependency_closure(self):
        self.assertEqual(self.q['required_fact_ids'],['ev1','ev2','id1','o1','o2'])
        r=self.run_b2();self.assertEqual(r['answer'],'yes')
        self.assertEqual({x['read_fact_id'] for x in r['execution_trace'] if 'read_fact_id' in x},set(self.q['required_fact_ids']))
    def test_09_which_first_and_reverse_order(self):
        q=freeze_question(self.g,prog('WHICH_FIRST'));self.assertEqual(execute(self.g,q)['answer'],'A')
        p=prog('WHICH_FIRST');p['args'].reverse();q=freeze_question(self.g,p)
        self.assertEqual(execute(self.g,q)['answer'],'B')
        p['op']='BEFORE';q=freeze_question(self.g,p);self.assertEqual(execute(self.g,q)['answer'],'no')
    def test_10_normalization_no_graph_answer_argument(self):
        texts=['true','YES','yes',' True ','yes','no','explanation yes','']
        r=majority_vote(self.q['question_id'],texts,'boolean');self.assertEqual(r['answer'],'yes')
        self.assertEqual(r['vote_fraction'],5/8);self.assertEqual(r['invalid_format_count'],2)
        self.assertEqual(normalize_answer('(B)','choice'),'B')
    def test_11_invalids_do_not_inflate_confidence(self):
        r=majority_vote('q',['yes','yes']+['bad']*6,'boolean')
        self.assertEqual(r['status'],'ABSTAIN');self.assertEqual(r['vote_fraction'],.25)
        r=majority_vote('q',['yes']*4+['no']*4,'boolean');self.assertEqual(r['status'],'ABSTAIN')
        with self.assertRaises(ContractError):majority_vote('q',['yes']*7,'boolean')
    def test_12_shared_question_ids_not_run(self):
        rows=not_run_rows([self.q]);self.assertEqual({r['question_id'] for r in rows},{self.q['question_id']})
        self.assertEqual({r['method'] for r in rows},{'B0','B1','B2'})
        self.assertTrue(all(r['status']=='NOT_RUN' and r['answer'] is None for r in rows))
    def test_13_missing_gold_denominators(self):
        rs=[{'question_id':'q1','method':'B2','status':'ANSWERED','answer':'yes'},
            {'question_id':'q2','method':'B2','status':'ANSWERED','answer':'no'},
            {'question_id':'q3','method':'B2','status':'ABSTAIN','answer':None}]
        gold={'q1':{'gold_status':'valid','gold_answer_confidence':'high','gold_answer':'yes'}}
        r=summarize(['q1','q2','q3'],rs,gold,'B2')
        self.assertEqual(r['coverage'],2/3);self.assertEqual(r['accepted_with_valid_gold'],1)
        self.assertEqual(r['precision'],1);self.assertIsNone(r['correct_yield'])
        self.assertIsNone(r['hard_correct_yield']);self.assertEqual(r['missing_gold_count'],2)
    def test_14_invalid_and_low_confidence_gold_excluded(self):
        rows=[{'question_id':f'q{i}','method':'B1','status':'ANSWERED','answer':'yes'} for i in range(3)]
        gold={'q0':{'gold_status':'valid','gold_answer_confidence':'high','gold_answer':'no','empirical_hard':True},
              'q1':{'gold_status':'valid','gold_answer_confidence':'low','gold_answer':'yes'},
              'q2':{'gold_status':'ambiguous','gold_answer_confidence':'low','gold_answer':None}}
        r=summarize(list(gold),rows,gold,'B1');self.assertEqual(r['precision'],0)
        self.assertEqual(r['accepted_with_valid_gold'],1);self.assertEqual(r['low_confidence_excluded'],1)
    def test_15_not_run_is_not_zero_performance(self):
        r=summarize([self.q['question_id']],not_run_rows([self.q]),{},'B0')
        self.assertEqual(r['status'],'NOT_RUN');self.assertIsNone(r['coverage']);self.assertIsNone(r['precision'])
    def test_16_frozen_question_and_program_hash(self):
        for key,value in [('question','changed'),('required_fact_ids',['ev1']),('answer_type','choice')]:
            q=copy.deepcopy(self.q);q[key]=value;self.assertEqual(execute(self.g,q)['status'],'ABSTAIN')
        q=copy.deepcopy(self.q);q['program']['op']='WHICH_FIRST';self.assertEqual(execute(self.g,q)['status'],'ABSTAIN')
    def test_17_graph_mutation_invalidates_question_and_ledger(self):
        g=fixture();g['facts'][2]['predicate']='corrupted'
        self.assertEqual(execute(g,self.q)['status'],'ABSTAIN')
        q=freeze_question(g,prog());self.assertIn('STALE_LEDGER',execute(g,q,method='B2',ledger=ledger(self.g))['reason'])
    def test_18_no_dangling_or_duplicate_facts(self):
        for mutate in [lambda g:g['facts'][2].update(depends_on=['absent']),
                       lambda g:g['facts'].append(copy.deepcopy(g['facts'][0])),
                       lambda g:g['facts'][2].update(support_frame_ids=['missing']),
                       lambda g:g['facts'][2].update(parser_run_id='absent')]:
            g=fixture();mutate(g)
            with self.assertRaises(ContractError):validate_graph(g)
    def test_19_ledger_ids_and_support_validation(self):
        l=ledger(self.g);l[0]['fact_id']='absent';self.assertEqual(self.run_b2(l)['status'],'ABSTAIN')
        l=ledger(self.g);l[0]['checked_frame_ids']=[];self.assertEqual(self.run_b2(l)['status'],'ABSTAIN')
        l=ledger(self.g);l.append(copy.deepcopy(l[0]));self.assertEqual(self.run_b2(l)['status'],'ABSTAIN')
    def test_20_cycle_is_rejected(self):
        g=fixture();g['facts'][0]['depends_on']=['ev1']
        with self.assertRaises(ContractError):validate_graph(g)
    def test_21_frequency_counts_parse_samples_not_occurrences(self):
        g=fixture();g['facts'][0]['matched_parser_run_ids']=['p0','p1'];q=freeze_question(g,prog())
        self.assertEqual(frequency(g,g['facts'][0]),.5)
        self.assertEqual(execute(g,q,method='B2',ledger=ledger(g))['status'],'ABSTAIN')
        self.assertEqual(execute(g,q,method='B2',ledger=ledger(g),threshold=.5)['status'],'ANSWERED')
        g['facts'][0]['matched_parser_run_ids']=['p0','p0']
        with self.assertRaises(ContractError):validate_graph(g)
    def test_22_frequency_cannot_mix_different_evidence(self):
        g=fixture();g['parser_runs'][1]['frame_ids']=['fr1']
        with self.assertRaises(ContractError):validate_graph(g)
    def test_23_b0_payload_has_no_graph_program_answer_or_gold(self):
        x=b0_payload(self.g,self.q);self.assertEqual(set(x),{'video_id','frames','question','answer_type','format_instruction'})
        for key in ['program','required_fact_ids','facts','gold_answer','B1_answer']:self.assertNotIn(key,x)
    def test_24_checker_has_one_claim_no_question_or_program_answer(self):
        x=checker_payload(self.g,'id1');self.assertEqual(set(x),{'video_id','claim','referents','frames','instruction'})
        self.assertNotIn(self.q['question'],json.dumps(x));self.assertNotIn('program',x)
    def test_25_human_labels_cannot_enter_parser_schema(self):
        x=parser_payload(self.g['video'],self.g['frames']);self.assertNotIn('gold_answer',x)
        for k in ['gold_answer','human_csv','review_id','standard_answer','threshold']:
            v=copy.deepcopy(self.g['video']);v[k]='forbidden'
            with self.assertRaises(ContractError):parser_payload(v,self.g['frames'])
        g=fixture();g['gold_answer']='yes'
        with self.assertRaises(ContractError):validate_graph(g)
    def test_26_open_world_count_and_global_negation_unsupported(self):
        for op in ['COUNT','NOT_EXISTS','TWO_HOP_RELATION','CAUSE']:
            p=prog(op)
            with self.assertRaises(ContractError):freeze_question(self.g,p)
    def test_27_cannot_hide_entity_dependency_or_wrong_link(self):
        q=copy.deepcopy(self.q);q['required_fact_ids']=['ev1','ev2'];row=copy.deepcopy(q);row.pop('frozen_sha256');q['frozen_sha256']=digest(row)
        self.assertEqual(execute(self.g,q)['status'],'ABSTAIN')
        p=prog();p['identity_fact_id']='o1'
        with self.assertRaises(ContractError):freeze_question(self.g,p)
    def test_28_no_gpu_launch(self):
        with self.assertRaises(PermissionError):launch_models()
    def test_29_metrics_duplicate_or_missing_join_rejected(self):
        rows=not_run_rows([self.q]);rows=[r for r in rows if r['method']=='B1']
        with self.assertRaises(ContractError):summarize([self.q['question_id']],rows*2,{},'B1')
        with self.assertRaises(ContractError):summarize([self.q['question_id']],[],{},'B1')
    def test_30_global_id_collision(self):
        g=fixture();g['facts'][0]['fact_id']='fr1'
        with self.assertRaises(ContractError):validate_graph(g)


    def test_31_raw_only_question_universe(self):
        from stsg_pilot.candidates import generate_candidates
        a=generate_candidates(self.g);b=generate_candidates(self.g)
        self.assertEqual(a,b);self.assertEqual(a['structural_candidate_count'],2)
        self.assertTrue(all(q['candidate_generated_from_raw_graph'] and q['cross_clip'] for q in a['questions']))
        self.assertEqual({q['program']['op'] for q in a['questions']},{'BEFORE','WHICH_FIRST'})
    def test_32_caps_recorded_not_hidden(self):
        from stsg_pilot.candidates import generate_candidates
        r=generate_candidates(self.g,cap=1)
        self.assertEqual(len(r['questions']),1);self.assertEqual(r['omitted_due_to_predeclared_cap'],1)
    def test_33_ambiguous_identical_wording_rejected_equally(self):
        from stsg_pilot.candidates import generate_candidates
        g=fixture();g['facts'][3]['predicate']=g['facts'][2]['predicate']
        r=generate_candidates(g);self.assertEqual(r['questions'],[])
        self.assertEqual(r['rejections'][0]['reason'],'INDISTINGUISHABLE_EVENT_WORDING')
    def test_34_attribute_nodes_are_checked_dependencies(self):
        g=fixture();a=copy.deepcopy(g['facts'][0]);a.update(fact_id='attr1',kind='attribute',predicate='shirt_color',attribute_value='red',subject_id='o1');a.pop('node_type');g['facts'].append(a)
        g['facts'][2]['depends_on']=['attr1'];q=freeze_question(g,prog())
        self.assertIn('attr1',q['required_fact_ids']);self.assertEqual(execute(g,q,method='B2',ledger=ledger(g))['status'],'ANSWERED')
        self.assertEqual(checker_payload(g,'attr1')['claim']['attribute_value'],'red')
        l=[e for e in ledger(g) if e['fact_id']!='attr1']
        self.assertEqual(execute(g,q,method='B2',ledger=l)['status'],'ABSTAIN')


    def test_43_invalid_checker_response_never_becomes_yes(self):
        self.assertEqual(parse_check_response('not sure, yes maybe'),'uncertain')
        with self.assertRaises(ContractError):
            ledger_entry(self.g,'o1','yes','SYNTHETIC',['fr1'],checker_run_id='test',raw_response='no',reason='')
        l=ledger(self.g);l[0]['raw_response']='no'
        self.assertEqual(self.run_b2(l)['status'],'ABSTAIN')


    def test_44_crossclip_local_node_cannot_be_used_without_link(self):
        g=fixture();g['facts'][2]['subject_id']='o2'
        with self.assertRaises(ContractError):validate_graph(g)

if __name__=='__main__':unittest.main(verbosity=2)



