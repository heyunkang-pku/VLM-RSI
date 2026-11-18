import unittest
from step_native.splitting import select_subshots
from step_native import records as R,prompts
class NativeContracts(unittest.TestCase):
    def test_contiguous_runs_not_global_cluster_count(self):
        rows=select_subshots([0,0,1,1,0],[(0,5)],[None,2.,3.,1.,4.]);self.assertEqual([r['selected_source_index'] for r in rows],[1,3,4])
    def test_scene_boundary_never_merged(self):
        rows=select_subshots([0,0,0,0],[(0,2),(2,4)],[None,2.,1.,3.]);self.assertEqual(len(rows),2)
    def test_ssd_tie_earliest(self):self.assertEqual(select_subshots([0,0,0],[(0,3)],[None,1.,1.])[0]['selected_source_index'],1)
    def test_no_valid_predecessor_is_explicit(self):self.assertTrue(select_subshots([0],[(0,1)],[None])[0]['degenerate_singleton_no_predecessor'])
    def test_instance_counts_must_match(self):
        with self.assertRaises(ValueError):R.instances('Object: cup\nQuantity: 2\n1. cup1: left','cup')
    def test_original_pseudojson_attributes_preserved(self):self.assertEqual(len(R.attributes('["object":"man","attributes":["clothing":"shirt","clothing":"shorts"]]')),2)
    def test_object_list(self):self.assertEqual(R.object_classes('Meaningful objects are [mugs, balls, table].'),['mugs','balls','table'])
    def test_duplicate_class_does_not_force_identity(self):
        ns=[{'id':str(i),'label':'mug','instance_name':f'mug{i}','referent':f'mug{i} left'} for i in range(2)];self.assertEqual(R.target_candidates('the mug',ns),['0','1'])
    def test_triple_extra_comma_rejected(self):
        with self.assertRaises(ValueError):R.triples('<mug1, left, on, table>')
    def test_native_prompts_are_purpose_separated(self):
        self.assertNotIn('JSON',prompts.NARRATIVE);self.assertIn('Quantity:',prompts.INSTANCES);self.assertNotIn('event',prompts.OBJECTS.lower());self.assertIn('<subject, predicate, object>',prompts.REL_EXTRACT)
if __name__=='__main__':unittest.main()
