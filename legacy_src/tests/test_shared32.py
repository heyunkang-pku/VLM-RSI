import unittest,tempfile,json
from pathlib import Path
from step_native.temporal import context
class Public32(unittest.TestCase):
 def test_pair_context_never_reads_outside_public(self):
  fs=[{'source_index':i,'frame_id':str(i),'time_sec':float(i),'file':'f','sha256':'x'} for i in range(6)];m={'public32':True,'public_frames':fs,'calibration_view':fs[2]};n=dict(m,calibration_view=fs[3])
  with tempfile.TemporaryDirectory() as d:r=context(Path(d),{'media':m},{'media':n},'pair')
  self.assertEqual([f['source_index'] for f in r['class_video_views']],[1,2,3,4]);self.assertEqual(r['identity_endpoint_frame_ids'],['2','3'])
 def test_two_endpoints_cannot_manufacture_intermediate_frame(self):
  fs=[{'source_index':i,'frame_id':str(i),'time_sec':float(i),'file':'f','sha256':'x'} for i in [1,5]];m={'public32':True,'public_frames':fs,'calibration_view':fs[0]};n=dict(m,calibration_view=fs[1])
  with tempfile.TemporaryDirectory() as d:r=context(Path(d),{'media':m},{'media':n},'p')
  self.assertEqual(len(r['class_video_views']),2)
