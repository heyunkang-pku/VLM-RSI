import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from step_native.frame_execution import candidate_output_failure,process_frame

class FrameRecovery(unittest.TestCase):
 def test_only_expected_output_failures_are_local(self):
  self.assertTrue(candidate_output_failure(RuntimeError('OUTPUT_TOKEN_CAP_HIT:relations_o001')))
  self.assertTrue(candidate_output_failure(ValueError('INSTANCE_ROWS_QUANTITY_MISMATCH')))
  self.assertFalse(candidate_output_failure(RuntimeError('CUDA out of memory')))
  self.assertFalse(candidate_output_failure(ValueError('unexpected bug')))

 def test_truncation_is_retained_and_not_resampled_on_resume(self):
  with tempfile.TemporaryDirectory() as d:
   task={'folder':d,'scope':'video_test/src_1','candidate_existing':False,'media':{}}
   cfg={'candidate_seed':1}
   with patch('step_native.frame_execution.run_chain',side_effect=RuntimeError('OUTPUT_TOKEN_CAP_HIT:relations_o001')) as chain:
    process_frame(None,cfg,task)
    process_frame(None,cfg,task)
    self.assertEqual(chain.call_count,1)
   st=json.loads((Path(d)/'STATE.json').read_text())
   self.assertEqual(st['state'],'CANDIDATE_UNAVAILABLE')
   self.assertTrue(st['retained_in_keyframe_denominator'])
   self.assertFalse((Path(d)/'verification/STATE.json').exists())

 def test_runtime_fault_is_not_silently_skipped(self):
  with tempfile.TemporaryDirectory() as d:
   task={'folder':d,'scope':'video_test/src_1','candidate_existing':False,'media':{}}
   with patch('step_native.frame_execution.run_chain',side_effect=RuntimeError('CUDA out of memory')):
    with self.assertRaisesRegex(RuntimeError,'CUDA'):process_frame(None,{'candidate_seed':1},task)

if __name__=='__main__':unittest.main()
