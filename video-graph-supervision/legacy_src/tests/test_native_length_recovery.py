import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from step_native.recovery import RecoveryRuntime,v0_key,RecoveryGenerationFailure,import_terminal_failures
class LengthRecovery(unittest.TestCase):
 def setup_runtime(self,d):
  rt=object.__new__(RecoveryRuntime);rt.cfg={'v0_root':d+'/old','work_root':d+'/new','model_revision':'fixed'};rt.protocol='V1';rt.cache_hits=0;rt.mode='text';Path(d+'/old/request_cache').mkdir(parents=True);Path(d+'/new').mkdir();rt.begin_chain('frame/seed1');return rt
 def test_reuse_prefix_then_invalidate_even_identical_descendant_prompt(self):
  with tempfile.TemporaryDirectory() as d:
   rt=self.setup_runtime(d);m={'video':{'avg_fps':'30/1'},'source_frames_decoded':90};kw={'role':'extract','seed':4,'temperature':.7,'max_tokens':512};records=[]
   for prompt,cap in [('prefix',False),('truncated',True),('descendant',False)]:
    r={'request_id':'old_'+prompt,'role':'extract','status':'DONE','output_hit_cap':cap,'input_hashes':{'pixels':'same'},'raw_response':'old'};p=Path(d+'/old/request_cache')/(v0_key(rt.cfg,m,'text',prompt,kw)+'.json');p.write_text(json.dumps(r))
   def fake(self,media,ids,prompt,**args):records.append((prompt,args['max_tokens'],self.protocol,args['seed'],args['temperature']));return {'request_id':'new_'+prompt,'role':args['role'],'output_hit_cap':False,'input_hashes':{'pixels':'same'}}
   with patch('step_native.checkpoint_runtime.CheckpointRuntime.ask',fake):
    self.assertEqual(rt.ask(m,[],'prefix',**kw)['request_id'],'old_prefix')
    self.assertEqual(rt.ask(m,[],'truncated',**kw)['request_id'],'new_truncated')
    self.assertEqual(rt.ask(m,[],'descendant',**kw)['request_id'],'new_descendant')
   self.assertEqual([x[0] for x in records],['truncated','descendant']);self.assertTrue(all(x[1]==2048 and x[3:]==(4,.7) for x in records));self.assertNotEqual(records[0][2],records[1][2])
 def test_exactly_one_4096_escalation_and_no_tail_splice(self):
  with tempfile.TemporaryDirectory() as d:
   rt=self.setup_runtime(d);m={'video':{'avg_fps':'30/1'},'source_frames_decoded':90};caps=[]
   def fake(self,media,ids,prompt,**kw):caps.append(kw['max_tokens']);return {'request_id':str(kw['max_tokens']),'role':kw['role'],'output_hit_cap':True,'raw_response':'fresh','input_hashes':{}}
   with patch('step_native.checkpoint_runtime.CheckpointRuntime.ask',fake):r=rt.ask(m,[],'same input',role='relations',seed=1,temperature=0,max_tokens=512)
   self.assertEqual(caps,[2048,4096]);self.assertTrue(r['output_hit_cap']);self.assertEqual(r['raw_response'],'fresh')
 def test_classification_cap_not_increased(self):
  with tempfile.TemporaryDirectory() as d:
   rt=self.setup_runtime(d);m={'video':{'avg_fps':'30/1'},'source_frames_decoded':90};caps=[]
   def fake(self,media,ids,prompt,**kw):caps.append(kw['max_tokens']);return {'request_id':'c','role':kw['role'],'output_hit_cap':False,'input_hashes':{}}
   with patch('step_native.checkpoint_runtime.CheckpointRuntime.ask',fake):rt.ask(m,[],'class',role='classify_o0',seed=1,temperature=.7,max_tokens=512)
   self.assertEqual(caps,[512])
 def test_timed_out_4096_is_terminal_on_resume(self):
  with tempfile.TemporaryDirectory() as d:
   rt=self.setup_runtime(d);m={'video':{'avg_fps':'30/1'},'source_frames_decoded':90};p=Path(d+'/new/attempts/old/gpu0/shard0/requests.jsonl');p.parent.mkdir(parents=True)
   p.write_text(json.dumps({'status':'FAILED','error':'SINGLE_REQUEST_TIMEOUT','input_mode':'text','prompt':'original prompt','seed':1,'temperature':0,'max_new_tokens':4096,'frame_content_hashes':[],'request_id':'terminal_old'})+'\n');import_terminal_failures(Path(d+'/new'));caps=[]
   def fake(self,media,ids,prompt,**kw):caps.append(kw['max_tokens']);return {'request_id':'new2048','role':kw['role'],'output_hit_cap':True,'input_hashes':{}}
   with patch('step_native.checkpoint_runtime.CheckpointRuntime.ask',fake):
    with self.assertRaises(RecoveryGenerationFailure):rt.ask(m,[],'original prompt',role='relations',seed=1,temperature=0,max_tokens=512)
   self.assertEqual(caps,[2048])
if __name__=='__main__':unittest.main()
