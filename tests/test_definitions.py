"""S1 only: synthetic definitions, private files, no inference or test execution."""
import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import definitions as d

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT/'tests/fixtures/definitions'


class DefinitionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.c = d.load_json(FIXTURES/'valid/competition.json')
        self.r = d.load_json(FIXTURES/'valid/rubric.json')
        self.assets = FIXTURES/'valid/assets'
        self.addCleanup(patch.stopall)
        patch('socket.create_connection', side_effect=AssertionError('network forbidden')).start()
        patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')).start()

    def fails(self, code, fn, *args, **kwargs):
        with self.assertRaises(d.DefinitionError) as context:
            fn(*args, **kwargs)
        self.assertEqual(context.exception.code, code)
        return context.exception

    def competition(self, value=None, rubric=None, **kwargs):
        return d.validate_competition(value if value is not None else self.c,
            rubric if rubric is not None else self.r, asset_root=self.assets, **kwargs)

    def rebind(self):
        self.c['rubric']['sha256'] = d.content_sha256(self.r)


class JsonTests(DefinitionCase):
    def test_roundtrip_and_independent_validated_copy(self):
        c = self.competition()
        self.assertEqual(c, self.c)
        c['prompt']['text'] = 'caller mutation'
        self.assertNotEqual(c, self.c)
        self.assertEqual(d.parse_json_bytes(d.canonical_json_bytes(self.r)), self.r)

    def test_fixed_canonical_vector_order_and_no_newline(self):
        value = {'z': [None, False, True, 12], 'ä': '雪', 'a': {'b': '0.25'}}
        expected = '{"a":{"b":"0.25"},"z":[null,false,true,12],"ä":"雪"}'.encode()
        self.assertEqual(d.canonical_json_bytes(value), expected)
        self.assertEqual(d.content_sha256(value), hashlib.sha256(expected).hexdigest())
        reversed_fields = dict(reversed(list(value.items())))
        self.assertEqual(d.content_sha256(value), d.content_sha256(reversed_fields))
        self.assertNotEqual(d.content_sha256([1, 2]), d.content_sha256([2, 1]))

    def test_original_whitespace_key_order_and_unicode_escapes_do_not_affect_hash(self):
        for data in [b'{"b":2,"a":"\\u00e4"}', '{ "a": "ä", "b": 2 }\n'.encode()]:
            self.assertEqual(d.content_sha256(d.parse_json_bytes(data)), d.content_sha256({'a': 'ä', 'b': 2}))

    def test_no_unicode_normalization(self):
        self.assertNotEqual(d.content_sha256('é'), d.content_sha256('e\u0301'))
        self.assertEqual(d.parse_json_bytes(b'"\\ud83d\\ude00"'), '😀')

    def test_utf8_bom_and_invalid_surrogates(self):
        for data, code in [(b'\xef\xbb\xbf{}', 'json_bom_forbidden'), (b'\xff', 'json_utf8_invalid'),
                           (b'"\\ud800"', 'json_unicode_invalid'), (b'"\\udfff"', 'json_unicode_invalid')]:
            with self.subTest(data=data):self.fails(code, d.parse_json_bytes, data)
        for value in ['\ud800', {'\udfff': 'value'}]:
            self.fails('json_unicode_invalid', d.canonical_json_bytes, value)

    def test_duplicate_key_at_any_depth(self):
        for data in [b'{"x":1,"x":2}', b'{"nested":{"x":1,"\\u0078":2}}']:
            self.fails('json_duplicate_key', d.parse_json_bytes, data)

    def test_numbers_floats_nonfinite_and_non_json_python_types(self):
        for data in [b'1.0', b'1e309', b'NaN', b'Infinity', b'-Infinity']:
            self.fails('json_number_forbidden', d.parse_json_bytes, data)
        for value in [1.0, float('nan'), float('inf'), (1, 2), {1}, b'bytes']:
            self.fails('json_type_invalid', d.canonical_json_bytes, value)
        self.fails('json_key_type', d.canonical_json_bytes, {1: 'value'})
        self.assertEqual(d.canonical_json_bytes(True), b'true')

    def test_json_size_nodes_depth_strings_and_integer_limits(self):
        limits = replace(d.DEFAULT_LIMITS, max_json_bytes=8)
        self.fails('json_size_limit', d.parse_json_bytes, b' '*9, limits=limits)
        self.fails('json_size_limit', d.canonical_json_bytes, ['12345678']*10, limits=limits)
        for fn, value in [(d.parse_json_bytes, b'[[[[0]]]]'), (d.canonical_json_bytes, [[[[0]]]])]:
            self.fails('json_depth_limit', fn, value, limits=replace(d.DEFAULT_LIMITS, max_depth=2))
        self.fails('json_node_limit', d.canonical_json_bytes, [0]*5, limits=replace(d.DEFAULT_LIMITS, max_nodes=3))
        self.fails('json_string_limit', d.canonical_json_bytes, '雪雪', limits=replace(d.DEFAULT_LIMITS, max_string_bytes=5))
        self.fails('json_integer_limit', d.canonical_json_bytes, 256, limits=replace(d.DEFAULT_LIMITS, max_integer_bits=8))
        self.fails('limits_invalid', d.Limits, max_depth=True)

    def test_parser_and_encoder_agree_on_depth_boundary(self):
        value = []
        for _ in range(31):value = [value]
        encoded = d.canonical_json_bytes(value)
        self.assertEqual(d.parse_json_bytes(encoded), value)
        self.fails('json_depth_limit', d.canonical_json_bytes, [value])
        self.fails('json_depth_limit', d.parse_json_bytes, b'['+encoded+b']')

    def test_brackets_inside_strings_and_cyclic_containers(self):
        self.assertEqual(d.parse_json_bytes(b'"[[[{\\\""'), '[[[{"')
        value = [];value.append(value)
        self.fails('json_cycle', d.canonical_json_bytes, value)

    def test_canonical_decimal_strings(self):
        for value in ['0', '1', '0.25', '-0.25', '10.001']:
            self.assertEqual(d.validate_decimal_string(value), value)
        for value in ['-0', '01', '+1', '1.0', '0.00', '1e2', 'NaN', 'Infinity', '.5', ' 1', '1.', '١', True, 1]:
            with self.subTest(value=value):self.fails('decimal_invalid', d.validate_decimal_string, value)
        self.fails('decimal_negative', d.validate_decimal_string, '-1', nonnegative=True)

    def test_content_hash_validation_and_drift(self):
        expected = d.content_sha256(self.c)
        self.assertEqual(d.verify_content_sha256(self.c, expected), expected)
        self.c['name'] += ' changed'
        self.fails('content_hash_mismatch', d.verify_content_sha256, self.c, expected)
        for value in ['A'*64, 'sha256:'+'a'*64, '', None, True]:
            self.fails('sha256_invalid', d.verify_content_sha256, self.c, value)

    def test_invalid_static_json_fixtures(self):
        for name, code in [('duplicate-key', 'json_duplicate_key'), ('malformed', 'json_invalid'),
                           ('nonfinite', 'json_number_forbidden'), ('surrogate', 'json_unicode_invalid')]:
            self.fails(code, d.load_json, FIXTURES/'invalid'/(name+'.json'))


class CompetitionTests(DefinitionCase):
    def test_unknown_fields_at_all_levels_including_hardware(self):
        for field in ['threads', 'models', 'gpu_mode', 'hardware', 'extra']:
            self.fails('unknown_field', self.competition, dict(self.c, **{field: []}))
        for field in ['prompt', 'rubric']:
            value = copy.deepcopy(self.c);value[field]['extra'] = 'value'
            self.fails('unknown_field', self.competition, value)
        value = d.load_json(FIXTURES/'invalid/competition-unknown-field.json')
        self.fails('unknown_field', self.competition, value)

    def test_required_fields_and_single_shared_prompt(self):
        for field in self.c:
            value = dict(self.c);value.pop(field)
            self.fails('missing_field', self.competition, value)
        value = copy.deepcopy(self.c);value['prompt'] = [value['prompt']]
        self.fails('object_required', self.competition, value)

    def test_uuids_versions_and_bool_instead_of_integer(self):
        for value in ['bad', '11111111111141118111111111111111', '', 1, None]:
            c = dict(self.c, competition_id=value)
            self.fails('uuid_invalid', self.competition, c)
        for value in [True, 2, '1', None, 0]:
            self.fails('schema_version_unsupported', self.competition, dict(self.c, schema_version=value))
        for value in [True, 0, -1, '1']:
            self.fails('integer_invalid', self.competition, dict(self.c, definition_revision=value))
        value = copy.deepcopy(self.c);value['prompt']['version'] = False
        self.fails('integer_invalid', self.competition, value)
        self.fails('kind_invalid', self.competition, dict(self.c, kind='run_plan'))

    def test_exact_prompt_bytes_last_newline_and_hash(self):
        a = copy.deepcopy(self.c);a['prompt']['text'] += '\n'
        self.fails('prompt_hash_mismatch', self.competition, a)
        a['prompt']['sha256'] = hashlib.sha256(a['prompt']['text'].encode()).hexdigest()
        self.assertNotEqual(d.content_sha256(a), d.content_sha256(self.c))
        self.competition(a)

    def test_prompt_change_needs_new_prompt_and_definition_revisions(self):
        a = copy.deepcopy(self.c);a['prompt']['text'] += '\n'
        a['prompt']['sha256'] = hashlib.sha256(a['prompt']['text'].encode()).hexdigest()
        self.fails('revision_conflict', self.competition, a, previous=self.c)
        a['definition_revision'] += 1
        self.fails('prompt_version_conflict', self.competition, a, previous=self.c)
        a['prompt']['version'] += 1
        self.competition(a, previous=self.c)
        self.competition(previous=self.c)

    def test_revision_rollback_identity_and_nonprompt_changes(self):
        old = copy.deepcopy(self.c);old['definition_revision'] = 2
        self.fails('revision_rollback', self.competition, previous=old)
        old = dict(self.c, competition_id='22222222-2222-4222-8222-222222222222')
        self.fails('previous_identity_mismatch', self.competition, previous=old)
        current = dict(self.c, name='renamed')
        self.fails('revision_conflict', self.competition, current, previous=self.c)
        current['definition_revision'] = 2;self.competition(current, previous=self.c)
        current = copy.deepcopy(self.c);current['prompt']['version'] = 2
        self.fails('prompt_version_rollback', self.competition, dict(self.c, definition_revision=2), previous=current)

    def test_rubric_identity_hash_and_discipline_binding(self):
        for field, value in [('revision', 2), ('rubric_id', '22222222-2222-4222-8222-222222222222'), ('sha256', '0'*64)]:
            c = copy.deepcopy(self.c);c['rubric'][field] = value
            self.fails('rubric_hash_mismatch' if field=='sha256' else 'rubric_reference_mismatch', self.competition, c)
        registry = d.DisciplineRegistry((d.DEFAULT_REGISTRY.get('performance'),
            d.DisciplineProfile('synthetic', ('performance_checks',), d.DEFAULT_REGISTRY.get('performance').rules)))
        r = dict(self.r, discipline='synthetic')
        self.fails('rubric_discipline_mismatch', self.competition, rubric=r, registry=registry)

    def test_unavailable_and_unknown_disciplines(self):
        for value in ['coding', 'code_analysis', 'question_answer', 'unknown']:
            self.fails('discipline_unsupported', self.competition, dict(self.c, discipline=value))
        self.assertEqual(d.RESERVED_DISCIPLINES, {'coding', 'code_analysis', 'question_answer'})
        self.assertFalse(d.DEFAULT_REGISTRY.get('performance').executable)

    def test_previous_inventory_is_structurally_validated_without_old_files(self):
        previous = copy.deepcopy(self.c);previous['assets'] = ['not an asset']
        self.fails('object_required', self.competition, previous=previous)



class RubricTests(DefinitionCase):
    def validate(self, value=None, **kwargs):
        return d.validate_rubric(value if value is not None else self.r, **kwargs)

    def test_valid_definition_and_immutable_revision(self):
        self.assertEqual(self.validate(), self.r)
        self.validate(previous=self.r)
        old = copy.deepcopy(self.r);self.r['name'] = 'changed'
        self.fails('revision_conflict', self.validate, previous=old)
        self.r['revision'] = 2;self.validate(previous=old)

    def test_weight_sum_and_positive_maximum(self):
        value = d.load_json(FIXTURES/'invalid/rubric-weights.json')
        self.fails('weight_sum_invalid', self.validate, value)
        for field in ['max_points', 'weight_bps']:
            for bad in [0, -1, True, '10']:
                r = copy.deepcopy(self.r);r['categories'][0][field] = bad
                self.fails('integer_invalid', self.validate, r)

    def test_missing_duplicate_and_out_of_range_anchors(self):
        for anchors, code in [([], 'list_invalid'), ([{'points':0,'description':'zero'}], 'anchor_endpoints_missing'),
                              ([{'points':0,'description':'zero'}]*2, 'anchor_duplicate'),
                              ([{'points':11,'description':'beyond'}], 'anchor_out_of_range')]:
            r = copy.deepcopy(self.r);r['categories'][0]['anchors'] = anchors
            self.fails(code, self.validate, r)
        self.r['categories'][0]['anchors'][0]['points'] = False
        self.fails('integer_invalid', self.validate)

    def test_duplicate_categories_suites_and_tests(self):
        for field, code in [('categories', 'category_duplicate'), ('test_suites', 'suite_duplicate')]:
            r = copy.deepcopy(self.r);r[field].append(r[field][0])
            self.fails(code, self.validate, r)
        self.r['test_suites'][1]['checks'][0]['test_id'] = 'response_complete'
        self.fails('test_duplicate', self.validate)

    def test_mandatory_test_and_suite_references(self):
        for tests, code in [(['missing'], 'mandatory_test_missing'),
                            (['response_complete']*2, 'mandatory_test_duplicate')]:
            r = dict(self.r, mandatory_tests=tests)
            self.fails(code, self.validate, r)
        self.r['categories'][0]['test_suite_id'] = 'missing'
        self.fails('suite_reference_missing', self.validate)

    def test_test_adapter_metric_operator_and_decimal_restrictions(self):
        r = copy.deepcopy(self.r);r['test_suites'][0]['adapter'] = 'nonexistent'
        self.fails('test_adapter_unsupported', self.validate, r)
        for version in [True, 0, 2, '1']:
            r = copy.deepcopy(self.r);r['test_suites'][0]['version'] = version
            self.fails('test_adapter_version_unsupported', self.validate, r)
        for field, value, code in [('metric', 'free.command', 'metric_unsupported'),
                                    ('operator', 'shell', 'operator_unsupported'),
                                    ('expected', 'unknown', 'expected_invalid')]:
            r = copy.deepcopy(self.r);r['test_suites'][0]['checks'][0][field] = value
            self.fails(code, self.validate, r)
        r = d.load_json(FIXTURES/'invalid/rubric-decimal.json')
        self.fails('decimal_invalid', self.validate, r)

    def test_rubric_header_fields_sources_and_grading(self):
        for version in [False, '1', 2]:
            self.fails('schema_version_unsupported', self.validate, dict(self.r, schema_version=version))
        for field in ['revision', 'name', 'grading', 'categories']:
            value = dict(self.r);value.pop(field)
            self.fails('missing_field', self.validate, value)
        self.fails('grading_unsupported', self.validate, dict(self.r, grading={'mode': 'auto_grade'}))
        self.r['categories'][0]['source'] = 'unregistered'
        self.fails('source_invalid', self.validate)

    def test_all_nested_objects_reject_unknown_fields(self):
        for kind in ['category', 'anchor', 'suite', 'check', 'grading']:
            r = copy.deepcopy(self.r)
            target = {'category':r['categories'][0], 'anchor':r['categories'][0]['anchors'][0],
                      'suite':r['test_suites'][0], 'check':r['test_suites'][0]['checks'][0], 'grading':r['grading']}[kind]
            target['command'] = 'NOT_EXECUTED'
            self.fails('unknown_field', self.validate, r)

    def test_registry_extensible_without_dynamic_plugins_or_execution(self):
        registry = d.DisciplineRegistry()
        profile = d.DisciplineProfile('synthetic', ('checks',), (d.CheckRule('n', ('gte',), 'decimal'),))
        registry.register(profile);self.assertIs(registry.get('synthetic'), profile)
        self.fails('profile_duplicate', registry.register, profile)
        self.fails('profile_invalid', registry.register, replace(profile, executable=True))
        self.fails('profile_invalid', registry.register, replace(profile, name='other', rules=()))

    def test_total_asset_budget_is_shared_across_test_suites(self):
        a = dict(path='one',sha256='0'*64,size_bytes=2,role='test')
        b = dict(a,path='two')
        self.r['test_suites'][0]['assets']=[a];self.r['test_suites'][1]['assets']=[b]
        self.fails('asset_total_limit', self.validate,
                   limits=replace(d.DEFAULT_LIMITS,max_total_asset_bytes=3))



class AssetTests(DefinitionCase):
    def make_asset(self, data=b'fixture bytes', name='input.txt'):
        root = self.root/'assets';root.mkdir(exist_ok=True)
        path = root/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(data)
        asset = dict(path=name, sha256=hashlib.sha256(data).hexdigest(),size_bytes=len(data),role='input')
        return root, path, asset

    def test_exact_inventory_and_no_source_changes(self):
        root, path, asset = self.make_asset()
        before = (path.read_bytes(),path.stat().st_mtime_ns,path.stat().st_mode)
        d.validate_assets([asset],root)
        self.assertEqual(before,(path.read_bytes(),path.stat().st_mtime_ns,path.stat().st_mode))
        (root/'unexpected').write_text('extra')
        self.fails('asset_inventory_mismatch', d.validate_assets, [asset],root)

    def test_missing_asset_and_dedicated_root_required(self):
        root, path, asset = self.make_asset();path.unlink()
        self.fails('asset_inventory_mismatch', d.validate_assets,[asset],root)
        self.fails('asset_root_required',d.validate_assets,[asset])
        d.validate_assets([])

    def test_traversal_windows_paths_globs_components_and_duplicates(self):
        _,_,asset = self.make_asset()
        for name in ['../input.txt','/input.txt','a/../input.txt','./input.txt','a//b','a/a/file',
                     'a/','a\\file','C:/file','a/*','a/?','a/[x]','a\x00file','']:
            value = dict(asset,path=name)
            with self.subTest(name=name):self.fails('asset_path_invalid',d.validate_assets,[value],self.root)
        self.fails('asset_duplicate',d.validate_assets,[asset,asset],self.root)

    def test_mutated_bytes_size_digest_and_type(self):
        root,path,asset = self.make_asset();path.write_bytes(b'changed bytes')
        self.fails('asset_hash_mismatch',d.validate_assets,[asset],root)
        path.write_bytes(b'x')
        self.fails('asset_size_mismatch',d.validate_assets,[asset],root)
        self.fails('integer_invalid',d.validate_assets,[dict(asset,size_bytes=True)],root)
        self.fails('sha256_invalid',d.validate_assets,[dict(asset,sha256='x')],root)
        self.fails('unknown_field',d.validate_assets,[dict(asset,host_path='/not/used')],root)

    def test_asset_count_single_size_and_total_size_limits(self):
        root,path,asset = self.make_asset()
        self.fails('asset_size_limit',d.validate_assets,[asset],root,limits=replace(d.DEFAULT_LIMITS,max_asset_bytes=1))
        self.fails('asset_total_limit',d.validate_assets,[asset],root,limits=replace(d.DEFAULT_LIMITS,max_total_asset_bytes=1))
        second=dict(asset,path='second')
        self.fails('asset_count_limit',d.validate_assets,[asset,second],root,limits=replace(d.DEFAULT_LIMITS,max_assets=1))

    def test_symlink_file_directory_root_and_hardlink(self):
        root,path,asset=self.make_asset();outside=self.root/'outside';outside.write_bytes(path.read_bytes())
        path.unlink();path.symlink_to(outside)
        self.fails('file_unsafe',d.validate_assets,[asset],root)
        path.unlink();os.link(outside,path)
        self.fails('file_unsafe',d.validate_assets,[asset],root)
        path.unlink();path.write_bytes(outside.read_bytes())
        alias=self.root/'alias';alias.symlink_to(root,target_is_directory=True)
        self.fails('asset_access_failed',d.validate_assets,[asset],alias)
        (root/'directory-link').symlink_to(self.root,target_is_directory=True)
        self.fails('file_unsafe',d.validate_assets,[asset],root)

    def test_fifo_and_bounded_directory_traversal(self):
        root,path,asset=self.make_asset();path.unlink();os.mkfifo(path)
        self.fails('file_unsafe',d.validate_assets,[asset],root)
        path.unlink();path.write_bytes(b'fixture bytes');(root/'empty').mkdir()
        self.fails('asset_entry_limit',d.validate_assets,[asset],root,limits=replace(d.DEFAULT_LIMITS,max_directory_entries=1))

    def test_file_replacement_during_read_is_detected(self):
        root,path,asset=self.make_asset();read=os.read;swapped=False
        def swap(fd,n):
            nonlocal swapped
            data=read(fd,n)
            if not swapped:
                swapped=True;replacement=root/'replacement';replacement.write_bytes(path.read_bytes());replacement.replace(path)
            return data
        with patch.object(d.os,'read',side_effect=swap):
            self.fails('file_changed',d.validate_assets,[asset],root)

    def test_directory_replacement_after_reads_is_detected(self):
        root,path,asset=self.make_asset(name='nested/input.txt');read=d._read_fd
        def swap(*args,**kwargs):
            value=read(*args,**kwargs);(root/'nested').rename(root/'old');(root/'nested').mkdir();(root/'nested/input.txt').write_bytes(b'fixture bytes');return value
        with patch.object(d,'_read_fd',side_effect=swap):
            self.fails('file_changed',d.validate_assets,[asset],root)

    def test_rubric_test_assets_are_hashbound_and_need_separate_root(self):
        root,path,asset=self.make_asset();asset['role']='test'
        self.r['test_suites'][0]['assets']=[asset]
        self.rebind()
        self.fails('asset_root_required',self.competition)
        self.competition(rubric_asset_root=root)
        path.write_bytes(b'changed bytes')
        self.fails('asset_hash_mismatch',self.competition,rubric_asset_root=root)


class FileAndCliTests(DefinitionCase):
    def test_json_file_size_type_symlink_and_read_errors(self):
        path=self.root/'json';path.write_bytes(b' '*9)
        self.fails('file_size_limit',d.load_json,path,limits=replace(d.DEFAULT_LIMITS,max_json_bytes=8))
        path.write_text('{}');alias=self.root/'alias';alias.symlink_to(path)
        self.fails('file_access_failed',d.load_json,alias)
        alias.unlink();os.link(path,alias)
        self.fails('file_unsafe',d.load_json,path)
        self.fails('file_access_failed',d.load_json,self.root/'missing')

    def test_json_file_swap_during_decode_is_detected(self):
        path=self.root/'json';path.write_text('{}');parse=d.parse_json_bytes
        def swap(*args,**kwargs):
            value=parse(*args,**kwargs);other=self.root/'other';other.write_text('{}');other.replace(path);return value
        with patch.object(d,'parse_json_bytes',side_effect=swap):
            self.fails('file_changed',d.load_json,path)

    def test_cli_success_errors_no_private_paths_or_definition_text(self):
        args=[sys.executable,'-B',str(ROOT/'definitions.py')]
        for rest in [['rubric',str(FIXTURES/'valid/rubric.json')],
                     ['competition',str(FIXTURES/'valid/competition.json'),'--rubric',str(FIXTURES/'valid/rubric.json'),'--assets',str(self.assets)]]:
            result=subprocess.run(args+rest,capture_output=True,text=True,check=False)
            self.assertEqual(result.returncode,0,result.stderr)
            value=json.loads(result.stdout);self.assertTrue(value['ok']);self.assertFalse(value['executable'])
            self.assertNotIn(str(ROOT),result.stdout);self.assertNotIn(self.c['prompt']['text'],result.stdout)
        result=subprocess.run(args+['rubric',str(self.root/'PRIVATE_MISSING')],capture_output=True,text=True)
        self.assertEqual(result.returncode,2);self.assertEqual(json.loads(result.stdout)['code'],'file_access_failed')
        self.assertNotIn('PRIVATE_MISSING',result.stdout+result.stderr)

    def test_json_file_encoding_fifo_and_invalid_input_type(self):
        path=self.root/'invalid';path.write_bytes(b'\xff')
        self.fails('json_utf8_invalid',d.load_json,path)
        path.write_bytes(b'\xef\xbb\xbf{}');self.fails('json_bom_forbidden',d.load_json,path)
        path.unlink();os.mkfifo(path);self.fails('file_unsafe',d.load_json,path)
        self.fails('json_input_type',d.parse_json_bytes,'{}')

    def test_json_parent_replacement_during_decode_is_detected(self):
        folder=self.root/'data';folder.mkdir();path=folder/'definition.json';path.write_text('{}')
        parse=d.parse_json_bytes
        def swap(*args,**kwargs):
            value=parse(*args,**kwargs);folder.rename(self.root/'old');folder.mkdir();path.write_text('{}');return value
        with patch.object(d,'parse_json_bytes',side_effect=swap):
            self.fails('file_changed',d.load_json,path)

    def test_cli_explicit_history_check_and_corrupt_reference(self):
        args=[sys.executable,'-B',str(ROOT/'definitions.py'),'rubric',str(FIXTURES/'valid/rubric.json')]
        result=subprocess.run(args+['--previous',str(FIXTURES/'valid/rubric.json')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0);self.assertTrue(json.loads(result.stdout)['history_checked'])
        result=subprocess.run(args,capture_output=True,text=True)
        self.assertFalse(json.loads(result.stdout)['history_checked'])
        self.r['name']='renamed';path=self.root/'old.json';path.write_text(json.dumps(self.r))
        result=subprocess.run(args+['--previous',str(path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,2);self.assertEqual(json.loads(result.stdout)['code'],'revision_conflict')

    def test_docs_examples_stay_valid_and_formal_schemas_are_local_data(self):
        import re
        values={}
        for kind in ['COMPETITION','RUBRIC']:
            text=(ROOT/'docs'/(kind+'_CONTRACT.md')).read_text()
            values[kind]=d.parse_json_bytes(re.search(r'```json\n(.*?)\n```',text,re.S)[1].encode())
        d.validate_competition(values['COMPETITION'],values['RUBRIC'])
        for kind in ['competition','rubric']:
            schema=d.load_json(ROOT/'schemas'/(kind+'.schema.json'))
            self.assertEqual(schema['additionalProperties'],False)
            self.assertEqual(schema['properties']['schema_version']['const'],1)


if __name__=='__main__':unittest.main()
