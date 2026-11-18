import copy,json,unittest
from unittest.mock import patch
from step_six.common import h
from step_verify_repair.dependencies import rounded_binding,s_time_bindings,p_dependencies,validate_requirements
from step_verify_repair.semantic import bounded_call,s_dependencies
from step_verify_repair.runtime import semantic_key

def fixture():
 scope='v/src_000001';obj={'scope':scope,'fact_id':'o','fact_type':'object','parent_ids':[],'state':'ACCEPTED','candidate_content':{'label':'cup','referent':'red cup beside a green lamp'}};attr={'scope':scope,'fact_id':'a','fact_type':'attribute','parent_ids':['o'],'state':'ACCEPTED','candidate_content':{'type':'color','value':'red'}};other={'scope':scope,'fact_id':'z','fact_type':'object','parent_ids':[],'state':'ACCEPTED','candidate_content':{'label':'lamp','referent':'green lamp'}};ld=[obj,attr,other];g={};pairs=[];facts={}
 for r in ld:
  fid=scope+'/'+r['fact_id'];facts[fid]={'id':fid,'kind':r['fact_type'],'video_id':'v','scope':scope,'time_sec':1.2344999,'parent_ids':[scope+'/'+x for x in r['parent_ids']],'content':r['candidate_content'],'media':{'calibration_view':{'frame_id':'src_000001'}}}
 q={'question_id':'q','route':'P','question':'At 1.234 seconds, what is the color of the cup?','video_id':'v','answer':'red','status':'EXECUTABLE','program':{'op':'attribute','scope':scope,'object_id':'o','type':'color'},'fact_ids':list(facts),'source_ledger_sha256':h(ld),'source_pairs_sha256':h(pairs),'source_graph_sha256':h(g),'program_read_trace':{'value_and_parent_fact_ids':[scope+'/o',scope+'/a']}}
 return q,facts,ld,pairs,g

class VerificationRepairTests(unittest.TestCase):
 def test_time_half_printed_decimal(self):
  self.assertTrue(rounded_binding(1.2344999,'1.234')['consistent']);self.assertFalse(rounded_binding(1.2346,'1.234')['consistent']);self.assertTrue(rounded_binding(19.682646,'19.6826')['consistent'])
 def test_program_answer_and_minimal_dependencies(self):
  q,f,ld,p,g=fixture();before=copy.deepcopy(q);d=p_dependencies(q,f,ld,p,g);self.assertTrue(d['complete']);self.assertEqual(d['execution_replay']['answer'],'red');self.assertEqual(q,before)
  claims=' '.join(a['claim'] for a in d['atoms']);self.assertNotIn('lamp',claims);self.assertNotIn('red cup',claims);self.assertTrue(any(a['kind']=='entity_resolution' for a in d['atoms']));self.assertEqual(d['required_kinds'],['attribute','entity_resolution','object']);self.assertTrue(all(a['reason'] for a in d['atoms']));self.assertIn('v/src_000001/z',[x.get('fact_id') for x in d['background_assumptions']])
 def test_changed_answer_cannot_be_silently_corrected(self):
  q,f,ld,p,g=fixture();q['answer']='blue';d=p_dependencies(q,f,ld,p,g);self.assertFalse(d['complete']);self.assertIn('PROGRAM_REPLAY_DIFFERS_FROM_FROZEN_ANSWER',[x['reason'] for x in d['unresolved']]);self.assertEqual(q['answer'],'blue')
 def test_parent_input_mutation_fails_replay(self):
  q,f,ld,p,g=fixture();ld[0]['candidate_content']['label']='bowl';d=p_dependencies(q,f,ld,p,g);self.assertFalse(d['complete'])
 def test_no_empty_dependency_acceptance(self):self.assertTrue(validate_requirements([],{}))
 def test_cache_key_guards_actual_pixels(self):
  k=lambda hs,rev='r',mode='image':semantic_key(rev,mode,'p',1,0,hs)
  self.assertNotEqual(k(['a']),k(['b']));self.assertNotEqual(k(['a']),k(['a'],'s'));self.assertNotEqual(k(['a']),k(['a'],mode='video'))
 def test_bounded_output_recovery_preserves_attempts(self):
  class RT:
   def __init__(self):self.calls=0
   def ask(self,*a,**kw):self.calls+=1;return {'request_id':str(self.calls),'output_hit_cap':self.calls==1,'raw_response':'{}'}
  rt=RT();r,a=bounded_call(rt,{},'p','r','q');self.assertEqual(rt.calls,2);self.assertEqual(len(a),2);self.assertTrue(a[0]['output_hit_cap'])
 def test_truncated_prefix_is_never_parsed(self):
  class RT:
   def ask(self,*a,**kw):return {'request_id':'x','output_hit_cap':True,'raw_response':'{"maybe":true}'}
  with self.assertRaises(ValueError):bounded_call(RT(),{},'p','r','q')
 def test_time_collision_stays_unresolved(self):
  q={'video_id':'v','question':'What at 1.23 seconds?','answer':'x'};f={'a':{'video_id':'v','time_sec':1.2301},'b':{'video_id':'v','time_sec':1.2302}};self.assertFalse(s_time_bindings(q,f)[0]['consistent'])
 def test_S_answer_cannot_be_dismissed_as_background(self):
  q={'question_id':'s','video_id':'v','route':'S','question':'What color is the cup?','answer':'The cup is red.','rationale':'','fact_ids':['o','a']};f={'o':{'id':'o','kind':'object','video_id':'v','scope':'s','claim':'cup visible','parent_ids':[]},'a':{'id':'a','kind':'attribute','video_id':'v','scope':'s','claim':'cup red','parent_ids':['o']}}
  def fake(rt,m,prompt,role,owner,*args,**kw):
   if role.endswith('coverage_audit'):data={'clause_reviews':[{'clause_id':'question:0','decision':'covered','reason':'binding','missing_requirements':[]},{'clause_id':'answer:0','decision':'background_only','reason':'pretend irrelevant','missing_requirements':[]}]}
   else:
    field='answer' if 'answer:0' in owner else 'question';quote=q['answer'] if field=='answer' else q['question'];data={'requirements':[{'quote':quote,'claim':'cup red','kind':'attribute','necessity':'necessary','reason':'removal changes answer','fact_ids':['o','a'],'evidence_fact_id':'a','evidence_scope':'observation'}],'clause_covered':True,'unresolved':[]}
   return {'request_id':owner,'raw_response':json.dumps(data)},[]
  with patch('step_verify_repair.semantic.bounded_call',side_effect=fake):d=s_dependencies(None,q,f,{'v':{}})
  self.assertFalse(d['complete']);self.assertIn('ANSWER_ASSERTION_DISMISSED_AS_BACKGROUND',[x['reason'] for x in d['unresolved']])
