import unittest
from four_group.followup import relation
class Relations(unittest.TestCase):
 def test_direction(self):self.assertEqual(relation('The cloth is on the table.','table','cloth')[0],['table','supports','cloth'])
 def test_direct(self):self.assertEqual(relation('The cloth is on the table.','cloth','table')[0],['cloth','on','table'])
 def test_bare_or_pronoun_unresolved(self):
  self.assertIsNone(relation('on','cloth','table')[0]);self.assertIsNone(relation('It is on the table','cloth','table')[0])
 def test_no_false_reverse(self):self.assertEqual(relation('The table is on the cloth','table','cloth')[0],['table','on','cloth'])
 def test_extra_endpoint_not_guessed(self):self.assertIsNone(relation('The person is holding something','person','bottle')[0])
