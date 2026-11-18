import unittest
from step_native.temporal import unique_yes,static_union,text_field
class NativeTemporal(unittest.TestCase):
 def test_ambiguous_yes_correspondence_is_not_chosen(self):
  rows=[{'id':'a','left':'x','right':'y','verdict':'YES'},{'id':'b','left':'x','right':'z','verdict':'YES'}]
  self.assertEqual(unique_yes(rows),set())
 def test_no_is_not_same_identity(self):
  self.assertEqual(unique_yes([{'id':'a','left':'x','right':'y','verdict':'NO'}]),set())
 def test_transitive_merge_cannot_merge_two_instances_in_same_frame(self):
  nodes={'a':{'scope':'f1'},'b':{'scope':'f2'},'c':{'scope':'f3'},'d':{'scope':'f1'}}
  groups,bad=static_union(nodes,[('p1','a','b'),('p2','b','c'),('p3','c','d')]);self.assertEqual(bad,['p3']);self.assertIn(['a','b','c'],groups)
 def test_pseudo_json_keeps_predicate_and_none(self):
  self.assertEqual(text_field('[["predicate":"walking", "object":"None"]]','object'),'None')
 def test_multiple_actions_not_arbitrarily_chosen(self):
  with self.assertRaises(ValueError):text_field('["action":"a", "action":"b"]','action')
if __name__=='__main__':unittest.main()
