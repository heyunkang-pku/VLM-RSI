import copy
import unittest
from four_group.event_mcq_v2 import validate, freeze_candidate, duplicate

class NarrativeV2(unittest.TestCase):
    def setUp(self):
        self.text = 'The hand places a red mug. The hand then places a remote. Next, the hand places a cable.'
        self.graph = {'clip_observations':[{'id':'clip1','description':self.text,'input_frame_ids':['f1','f2','f3'],'observation_interval_sec':[0,20]}], 'motion_edges':[], 'facts':[], 'identity_pair_ledger':[]}
        self.q = {'type':'event_order','question':'Which was placed earlier, the red mug or the remote?','options':['The red mug','The remote'],'answer_index':0,'event_or_action_edge_ids':['clip1'],'fact_ids':[],'identity_connection_ids':[],'evidence_frame_ids':['f1','f2','f3'],'evidence_granularity':'whole_clip','text_evidence':[{'record_id':'clip1','field':'description','quote':self.text}],'cross_frame_reason':'Then explicitly orders the placing actions.','requirements':dict(precise_event_bounds=False,executable_event_instances=False,cross_frame_identity_binding=False),'requirement_reasons':dict(precise_event_bounds='Narrated order does not need precise times.',executable_event_instances='Text attribution only.',cross_frame_identity_binding='Objects explicitly named in the same narrative.')}
    def check(self,q=None,g=None,excluded=None):
        return validate(q or self.q,g or self.graph,{'f1','f2','f3'},excluded or [],'event_order')
    def test_explicit_clip_order_without_bounds_is_accepted(self):
        self.assertIsNone(self.check())
    def test_two_compared_options_in_question_are_not_automatic_leak(self):
        self.assertIsNone(self.check())
    def test_false_program_flag_does_not_disqualify_narrative(self):
        g=copy.deepcopy(self.graph);g['motion_edges']=[dict(id='m1',action=self.text,necessary_source_frames=['f1','f2'],observation_interval_sec=[0,4],usable_for_program_QA=False)]
        q=copy.deepcopy(self.q);q.update(event_or_action_edge_ids=['m1'],evidence_frame_ids=['f1','f2'],evidence_granularity='observation_window',text_evidence=[dict(record_id='m1',field='action',quote=self.text)])
        self.assertIsNone(self.check(q,g))
    def test_invented_quote_rejected(self):
        q=copy.deepcopy(self.q);q['text_evidence'][0]['quote']='A fabricated event happened before the other.'
        self.assertEqual(self.check(q),'QUOTE_NOT_EXACT')
    def test_exact_record_attribution_required(self):
        q=copy.deepcopy(self.q);q['text_evidence'][0]['record_id']='missing'
        self.assertEqual(self.check(q),'INCOMPLETE_RECORD_ATTRIBUTION')
    def test_precise_bounds_only_required_when_declared_needed(self):
        q=copy.deepcopy(self.q);q['requirements']['precise_event_bounds']=True
        self.assertEqual(self.check(q),'REQUIRED_PRECISE_BOUNDS_MISSING')
    def test_identity_when_needed_cannot_be_silently_bypassed(self):
        q=copy.deepcopy(self.q);q['requirements']['cross_frame_identity_binding']=True
        self.assertEqual(self.check(q),'REQUIRED_IDENTITY_BINDING_MISSING')
    def test_unattributed_frames_rejected(self):
        q=copy.deepcopy(self.q);q['evidence_frame_ids']=['f1','f4']
        self.assertEqual(self.check(q),'INVALID_FRAME_IDS')
    def test_manual_question_and_paraphrase_rejected(self):
        self.assertEqual(self.check(excluded=[self.q['question']]),'EXACT_OR_NEAR_DUPLICATE')
        self.assertTrue(duplicate('Which was placed first, the red mug or the remote?',[self.q['question']]))
    def test_shuffle_retains_answer_identity(self):
        q=copy.deepcopy(self.q);q['video_id']='video_44'
        f=freeze_candidate(q,{'class_video_views':[]})
        self.assertEqual(f['options']['ABCD'.index(f['graph_answer'])],'The red mug')
        self.assertEqual(q['options'],['The red mug','The remote'])
    def test_explicit_answer_leak_rejected(self):
        q=copy.deepcopy(self.q);q['question']='The correct answer is the red mug. Which happened earlier?'
        self.assertEqual(self.check(q),'EXPLICIT_ANSWER_LEAK')
    def test_manual_relation_pair_reversed_and_paraphrased_excluded(self):
        from four_group.event_mcq_v2 import manual_relation_duplicate
        self.assertTrue(manual_relation_duplicate({'video_id':'video_44','type':'event_order','question':'What was deposited later?','options':['A remote controller','A white cord']}))
        self.assertFalse(manual_relation_duplicate({'video_id':'video_44','type':'event_order','question':'Which arrived earlier?','options':['The red mug','The white cable']}))
    def test_narrative_projection_preserves_source_bytes_and_ids(self):
        from four_group.event_mcq_v2 import narrative_view, records_for
        before=copy.deepcopy(self.graph)
        view=narrative_view(self.graph)
        self.assertEqual(view['clip_observations'],self.graph['clip_observations'])
        self.assertEqual(list(records_for(view)),['clip1'])
        view['clip_observations'][0]['description']='not a source edit'
        self.assertEqual(self.graph,before)
    def test_precise_time_question_is_not_event_order(self):
        q=copy.deepcopy(self.q);q['question']='At what time was the yellow cup placed?'
        self.assertEqual(self.check(q),'PRECISE_TIME_QUESTION_NOT_ALLOWED')
    def test_sentence_citation_materializes_exact_original_slice(self):
        from four_group.event_mcq_v2 import materialize_citations, sentence_catalog
        q=copy.deepcopy(self.q);q['text_evidence']=[{'record_id':'clip1','field':'description','sentence_ids':[0,1]}]
        resolved=materialize_citations(q,self.graph)
        quote=resolved['text_evidence'][0]['quote']
        self.assertIn(quote,self.text)
        self.assertIn('The hand then places a remote.',quote)
        self.assertIsNone(self.check(resolved))
        self.assertNotIn('quote',q['text_evidence'][0])
    def test_sentence_selector_does_not_repair_paraphrased_quote(self):
        from four_group.event_mcq_v2 import materialize_citations
        q=copy.deepcopy(self.q);q['text_evidence'][0]['sentence_ids']=[0,1]
        q['text_evidence'][0]['quote']='The person placed a mug followed by a remote.'
        with self.assertRaisesRegex(AssertionError,'SUPPLIED_QUOTE_CONFLICTS'):
            materialize_citations(q,self.graph)
    def test_unknown_or_gapped_sentence_selection_rejected(self):
        from four_group.event_mcq_v2 import materialize_citations
        for ids in ([0,2],[99]):
            q=copy.deepcopy(self.q);q['text_evidence']=[dict(record_id='clip1',field='description',sentence_ids=ids)]
            with self.assertRaises(AssertionError):materialize_citations(q,self.graph)
    def test_null_description_is_missing_evidence_not_an_exception_or_string(self):
        from four_group.event_mcq_v2 import sentence_catalog, narrative_view, materialize_citations
        g=copy.deepcopy(self.graph);g['clip_observations'][0]['description']=None
        self.assertEqual(sentence_catalog(g)['clip1']['description'],[])
        self.assertIsNone(narrative_view(g)['clip_observations'][0]['description'])
        q=copy.deepcopy(self.q);q['text_evidence']=[dict(record_id='clip1',field='description',sentence_ids=[0])]
        with self.assertRaisesRegex(AssertionError,'UNKNOWN_SENTENCE_ID'):materialize_citations(q,g)
