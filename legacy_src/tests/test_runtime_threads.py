import unittest
from stsg_pilot.runtime import configure_threads
class Torch:
 def __init__(self):self.n=8;self.sets=0
 def get_num_interop_threads(self):return self.n
 def set_num_threads(self,n):self.intra=n
 def set_num_interop_threads(self,n):
  if self.sets:raise RuntimeError('cannot set twice')
  self.sets+=1;self.n=n
class Threads(unittest.TestCase):
 def test_second_runtime_preserves_identical_thread_config(self):
  t=Torch();configure_threads(t);configure_threads(t);self.assertEqual(t.sets,1);self.assertEqual((t.n,t.intra),(1,2))
class Resume(unittest.TestCase):
 def test_completed_batch_returns_without_native_or_solver_calls(self):
  import tempfile,json
  from pathlib import Path
  from unittest.mock import patch
  from four_group.shared32 import run_batch
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'SUMMARY.json').write_text('{"questions":17}');(p/'FREEZE_MANIFEST.json').write_text('{}')
   with patch('four_group.native_batch.execute',side_effect=AssertionError('must not rerun')):
    self.assertEqual(run_batch({},p,[],{}),{'questions':17})
