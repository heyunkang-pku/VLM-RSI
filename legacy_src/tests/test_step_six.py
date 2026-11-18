import copy,json,tempfile,unittest
from pathlib import Path
from step_six.common import vote,norm,save,j
from step_six.verification import dependency_closure,program_constraints,verify_question
from step_six.graph_routes import path_plans
class SixGroupTests(unittest.TestCase):
 def test_votes_require_six_of_ten(self):
  ss=[{'status':'VALID','answer':' Red. '}] * 5
  self.assertEqual(vote(ss)['status'],'ABSTAIN')
  self.assertEqual(vote(ss+[{'status':'VALID','answer':'red'}])['answer'],'red')
 def test_tie_retained(self):
  r=vote([{'status':'VALID','answer':s} for s in ['a']*5+['b']*5]);self.assertTrue(r['tie']);self.assertIsNone(r['answer'])
 def test_failed_samples_remain_denominator(self):
  r=vote([{'status':'VALID','answer':'a'}]*4+[{'status':'FAILED','answer':None}]*6);self.assertEqual(r['fixed_denominator'],10);self.assertEqual(r['confidence'],.4);self.assertEqual(r['status'],'ABSTAIN')
 def test_normalization_not_semantic_clustering(self):
  self.assertEqual(norm(' ＲＥＤ. '),'red');self.assertNotEqual(norm('dark red'),norm('red'))
 def test_complete_dependency_closure(self):
  ids,missing=dependency_closure(['r'],{'r':{'parent_ids':['a','b']},'a':{'parent_ids':['c']},'b':{'parent_ids':[]},'c':{'parent_ids':[]}});self.assertEqual(ids,['a','b','c','r']);self.assertFalse(missing)
 def test_missing_dependency_never_filled(self):
  ids,missing=dependency_closure(['r'],{'r':{'parent_ids':['absent']}});self.assertEqual(missing,['absent'])
 def test_cycle_terminates(self):
  self.assertEqual(dependency_closure(['a'],{'a':{'parent_ids':['b']},'b':{'parent_ids':['a']}})[0],['a','b'])
 def test_program_uniqueness_is_explicit_visual_constraint(self):
  f={'o':{'kind':'object','content':{'label':'cup','referent':'white cup'}}};r=program_constraints({'fact_ids':['o']},f);self.assertIn('Exactly one cup',r[0]['claim'])
 def test_path_expansion_deterministic(self):
  facts={'o':{'id':'o','kind':'object','parent_ids':[],'video_id':'v','time_sec':1},'a':{'id':'a','kind':'attribute','parent_ids':['o'],'video_id':'v','time_sec':1}}
  g={'event_edges':[]};a=path_plans(g,facts);self.assertEqual(a,path_plans(g,facts));self.assertEqual(len(a),4);self.assertEqual(a[0]['fact_ids'],['a','o']);self.assertEqual(a[1]['status'],'NO_CONNECTED_PAIR')
 def test_unresolved_compiler_never_changes_frozen_question(self):
  q={'question_id':'q','question':'what','answer':'blue','route':'P','fact_ids':['absent'],'video_id':'v'};before=copy.deepcopy(q)
  with tempfile.TemporaryDirectory() as d:
   row=verify_question(None,q,{}, {'v':{}},Path(d));self.assertEqual(row['status'],'UNRESOLVED_COMPILER_FAILURE');self.assertIsNone(row['accepted_answer']);self.assertEqual(q,before)

class FinalizeIsolationTests(unittest.TestCase):
 def test_six_groups_share_frozen_questions_and_candidate_answers(self):
  from step_six.runner import finalize
  from step_six.common import jl,filehash,rows
  import os
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);save(r/'GRAPH_SHARED_FROZEN.json',{'event_edges':[],'motion_edges':[],'reference_edges':[],'static_identity_groups':[]})
   s={'question_id':'s','question':'SQ','answer':'A','route':'S','video_id':'v'};p={'question_id':'p','question':'PQ','answer':['B'],'route':'P','video_id':'v'}
   jl(r/'S_FROZEN_QA.jsonl',[s]);jl(r/'P_FROZEN_QA.jsonl',[p]);jl(r/'SOLVER_QUESTIONS_ONLY.jsonl',[{k:x[k] for k in ['question_id','question','route','video_id']} for x in [s,p]]);save(r/'VIDEO_INPUTS_FROZEN.json',{})
   jl(r/'S_ALL_CANDIDATES.jsonl',[{'status':'FROZEN'}]);jl(r/'P_ALL_CANDIDATES.jsonl',[{'execution':{'status':'ANSWERED'}}]);jl(r/'vqs/RESULTS.jsonl',[{'question_id':'s','status':'ACCEPT'},{'question_id':'p','status':'UNRESOLVED'}])
   save(r/'QUESTION_FREEZE_MANIFEST.json',{k:filehash(r/f) for k,f in [('graph_sha256','GRAPH_SHARED_FROZEN.json'),('S_bank_sha256','S_FROZEN_QA.jsonl'),('P_bank_sha256','P_FROZEN_QA.jsonl'),('solver_questions_sha256','SOLVER_QUESTIONS_ONLY.jsonl'),('input_manifest_sha256','VIDEO_INPUTS_FROZEN.json')]})
   with patch.dict(os.environ,{'ORX_RUN_ID':'CPU_TEST_ONLY'}):finalize(r,{},[])
   out=rows(r/'SIX_GROUP_RESULTS.jsonl');self.assertEqual(len(out),6)
   self.assertEqual({x['question'] for x in out if x['group'].startswith('S')},{'SQ'})
   self.assertEqual(next(x['answer'] for x in out if x['group']=='S2'),'A')
   p2=next(x for x in out if x['group']=='P2');self.assertIsNone(p2['answer']);self.assertEqual(p2['frozen_source_answer'],['B'])
   self.assertNotIn('answer',rows(r/'SOLVER_QUESTIONS_ONLY.jsonl')[0])
