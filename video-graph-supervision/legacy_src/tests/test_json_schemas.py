"""Optional formal-schema checks. Full Gate A verification uses jsonschema==4.25.1."""
import copy,json,unittest
from pathlib import Path
try:
    from jsonschema import Draft202012Validator,ValidationError
except ImportError:
    Draft202012Validator=None
from test_contracts import fixture,prog,ledger
from stsg_pilot.core import freeze_question
P=Path(__file__).resolve().parents[1]
@unittest.skipUnless(Draft202012Validator,'Install optional requirements-schema-check.txt')
class FormalSchemas(unittest.TestCase):
    def schema(self,name):return json.loads((P/'schemas'/f'{name}.schema.json').read_text())
    def validate(self,name,x):Draft202012Validator(self.schema(name)).validate(x)
    def test_35_all_schemas_are_valid_draft202012(self):
        for name in ['raw_graph','program','locked_question','verification_ledger']:
            Draft202012Validator.check_schema(self.schema(name))
    def test_36_synthetic_raw_graph_matches_schema(self):self.validate('raw_graph',fixture())
    def test_37_program_matches_schema(self):self.validate('program',prog())
    def test_38_locked_question_matches_schema(self):self.validate('locked_question',freeze_question(fixture(),prog()))
    def test_39_ledger_matches_schema(self):self.validate('verification_ledger',ledger(fixture()))
    def test_40_label_fields_rejected_by_formal_schema(self):
        g=fixture();g['gold_answer']='yes'
        with self.assertRaises(ValidationError):self.validate('raw_graph',g)
    def test_41_unknown_identity_must_be_explicit(self):
        g=fixture();g['facts'][-1].pop('identity_status')
        with self.assertRaises(ValidationError):self.validate('raw_graph',g)
    def test_42_exported_fixtures_match_current_contract(self):
        g=json.loads((P/'tests/fixtures/synthetic_two_clip_graph.json').read_text())
        q=json.loads((P/'tests/fixtures/synthetic_locked_question.json').read_text())
        self.assertEqual(freeze_question(g,prog()),q)
        self.validate('raw_graph',g);self.validate('locked_question',q)
