import unittest
from step_native.v2_recovery import semantic
class V2CacheTests(unittest.TestCase):
 def test_seed_is_evidence(self):self.assertNotEqual(semantic('image','p',1,.7,['a']),semantic('image','p',2,.7,['a']))
 def test_actual_pixels_and_mode(self):
  self.assertNotEqual(semantic('image','p',1,0,['a']),semantic('image','p',1,0,['b']))
  self.assertNotEqual(semantic('image','p',1,0,['a']),semantic('video','p',1,0,['a']))
 def test_prompt_and_temperature(self):
  self.assertNotEqual(semantic('text','p',1,0,[]),semantic('text','q',1,0,[]))
  self.assertNotEqual(semantic('text','p',1,0,[]),semantic('text','p',1,.7,[]))
