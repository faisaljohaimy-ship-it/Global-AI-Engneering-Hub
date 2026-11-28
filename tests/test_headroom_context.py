"""Optional Headroom tool tests. Mock responses are synthetic unit fixtures only.

HEADROOM_CONTEXT_INTEGRATION=1 enables a real, installed 0.45.0 SDK test. The
default suite never installs packages or treats a mock as SDK execution proof.
"""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('headroom_context_under_test', ROOT / 'tools/headroom_context.py')
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class HeadroomContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='headroom-unit-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / 'private-originals'
        self.input = self.root / 'selected.json'
        # No customer data. The response below is a mock, not a lossless format.
        self.payload = {'id': 'unit-fixture', 'sha': 'a' * 64, 'path': 'src/unit_fixture.py',
                        'error': 'unit-error', 'tests': 987654321, 'items': ['padding ' * 100] * 20}
        self.original = json.dumps(self.payload)
        self.input.write_text(self.original)
        self.compact = json.dumps({key: value for key, value in self.payload.items() if key != 'items'})

    def response(self, **changes):
        value = {'ok': True, 'content': self.compact, 'sdk_version': '0.45.0', 'lossless': True,
                 'ccr_roundtrip': True, 'protected_messages_unchanged': True,
                 'tokens_before': 9000, 'tokens_after': 150, 'network_boundary': 'linux-seccomp-no-ip',
                 'compression_latency_ms': 1.25}
        return {**value, **changes}

    def run_mock(self, response=None):
        with mock.patch.object(tool, '_run_worker', return_value=response if response is not None else self.response()):
            return tool.optimize(self.input, self.store, 'tool-json')

    def entry(self, result):
        return self.store / 'entries' / result['id']

    def test_synthetic_response_persists_original_before_worker_and_reuses(self):
        def worker(original, directory):
            identity = hashlib.sha256(original.encode()).hexdigest()
            self.assertEqual((self.store / 'entries' / identity / 'original.utf8').read_text(), original)
            return self.response()
        with mock.patch.object(tool, '_run_worker', side_effect=worker) as call:
            result = tool.optimize(self.input, self.store, 'tool-json')
            reused = tool.optimize(self.input, self.store, 'tool-json')
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result['status'], 'optimized')
        self.assertTrue(reused['reused_immutable_result'])
        self.assertEqual(result['exact_tokens'], {'before': None, 'after': None})
        self.assertEqual(result['estimated_tokens']['before'], 9000)
        self.assertIsNone(result['context_usage'])
        self.assertIsNone(result['billing'])
        self.assertFalse(result['native_agent_interception'])
        self.assertEqual(tool.retrieve(self.store, result['id'], full=True)['content'], self.original)
        for path in self.store.rglob('*'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)

    def test_kind_and_content_are_immutable(self):
        result = self.run_mock()
        with self.assertRaises(ValueError):
            tool.optimize(self.input, self.store, 'code')
        self.assertEqual(self.entry(result).joinpath('original.utf8').read_text(), self.original)

    def test_short_code_policy_and_instructions_do_not_launch_sdk(self):
        cases = [('tiny', 'log', 'short-input'), ('x' * 2048, 'code', 'protected-kind'),
                 ('x' * 2048, 'policy', 'protected-kind'),
                 ('System: retained governing text\n' + 'x' * 2048, 'log', 'protected-instructions')]
        for number, (content, kind, expected) in enumerate(cases):
            with self.subTest(kind=kind, reason=expected):
                path = self.root / ('input-' + str(number))
                path.write_text(content)
                with mock.patch.object(tool, '_run_worker', side_effect=AssertionError('SDK must not run')):
                    result = tool.optimize(path, self.root / ('store-' + str(number)), kind)
                self.assertEqual((result['status'], result['reason'], result['content']), ('passthrough', expected, content))

    def test_governing_file_and_embedded_message_roles_are_protected(self):
        for number, role in enumerate(('system', 'user', 'developer')):
            self.input.write_text(json.dumps({'messages': [{'role': role, 'content': 'x' * 2000}]}))
            with mock.patch.object(tool, '_run_worker', side_effect=AssertionError('SDK must not run')):
                result = tool.optimize(self.input, self.root / ('role-' + str(number)), 'tool-json')
            self.assertEqual(result['reason'], 'protected-message-role')
        instructions = self.root / 'AGENTS.md'
        instructions.write_text('x' * 2000)
        with mock.patch.object(tool, '_run_worker', side_effect=AssertionError('SDK must not run')):
            self.assertEqual(tool.optimize(instructions, self.root / 'agents-store', 'log')['reason'], 'protected-instructions')

    def test_strict_json_and_complexity_are_rejected_without_original_creation(self):
        cases = ['{"id":1,"id":2}', '{"value":NaN}', '{"value":Infinity}', '{"value":1e9999}',
                 '[' * 42 + '0' + ']' * 42, '{not-json}']
        for content in cases:
            with self.subTest(content=content[:30]):
                self.input.write_text(content)
                with self.assertRaises((ValueError, RecursionError)):
                    tool.optimize(self.input, self.store, 'tool-json')
                self.assertFalse(self.store.exists())

    def test_secret_field_and_path_rejection_does_not_echo_values(self):
        synthetic = ''.join(['unit-', 'sensitive-', 'sentinel'])
        self.input.write_text(json.dumps({'api_key': synthetic}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = tool.main(['optimize', '--input', str(self.input), '--store', str(self.store), '--kind', 'tool-json'])
        self.assertEqual(code, 1)
        self.assertNotIn(synthetic, output.getvalue())
        self.assertFalse(self.store.exists())
        for field in ('apiKey', 'API-KEY', 'accessToken', 'clientSecret', 'private_key', 'token'):
            self.input.write_text(json.dumps({field: synthetic}))
            with self.subTest(field=field), self.assertRaises(ValueError):
                tool.optimize(self.input, self.store, 'tool-json')
        for name in ('.env.local', 'auth.json', 'credentials.json', 'private.key'):
            path = self.root / name
            path.write_text('non-sensitive unit text')
            with self.subTest(name=name), self.assertRaises(ValueError):
                tool.optimize(path, self.store, 'log')
        private = self.root / '.aws'
        private.mkdir()
        (private / 'config').write_text('non-sensitive unit text')
        with self.assertRaises(ValueError):
            tool.optimize(private / 'config', self.store, 'log')

    def test_symlinks_hardlinks_traversal_and_special_files_rejected(self):
        linked = self.root / 'selected-link.json'
        linked.symlink_to(self.input)
        with self.assertRaises(ValueError):
            tool.optimize(linked, self.store, 'tool-json')
        hard = self.root / 'selected-hard.json'
        os.link(self.input, hard)
        with self.assertRaises(ValueError):
            tool.optimize(hard, self.store, 'tool-json')
        with self.assertRaises(ValueError):
            tool.optimize(self.root / 'unused' / '..' / 'selected.json', self.store, 'tool-json')
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            tool.optimize(fifo, self.store, 'log')

    def test_store_must_be_absolute_private_outside_git_and_not_symlink(self):
        self.store.mkdir(mode=0o755)
        self.store.chmod(0o755)
        with self.assertRaises(ValueError):
            tool.optimize(self.input, self.store, 'tool-json')
        with self.assertRaises(ValueError):
            tool.optimize(self.input, Path('relative-private'), 'tool-json')
        repository = self.root / 'repository'
        repository.mkdir()
        (repository / '.git').write_text('gitdir: /nonexistent/unit-test')
        with self.assertRaises(ValueError):
            tool.optimize(self.input, repository / 'store', 'tool-json')
        alias = self.root / 'alias'
        alias.symlink_to(repository, target_is_directory=True)
        with self.assertRaises(ValueError):
            tool.optimize(self.input, alias / 'store', 'tool-json')

    def test_input_bound_rejects_without_persisting(self):
        self.input.write_bytes(b'x' * (tool.MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            tool.optimize(self.input, self.store, 'log')
        self.assertFalse(self.store.exists())

    def test_git_directory_rejected_and_empty_readonly_sandbox_stub_distinguished(self):
        boundary = self.root / 'boundary'
        boundary.mkdir()
        marker = boundary / '.git'
        marker.mkdir()
        with self.assertRaises(ValueError):
            tool._private_directory(boundary / 'originals', True)
        marker.chmod(0o555)
        try:
            accepted = tool._private_directory(boundary / 'originals', True)
            self.assertEqual(accepted.name, 'originals')
        finally:
            marker.chmod(0o700)
        (marker / 'HEAD').write_text('ref: refs/heads/unit-main\n')
        marker.chmod(0o555)
        try:
            with self.assertRaises(ValueError):
                tool._private_directory(boundary / 'other-originals', True)
        finally:
            marker.chmod(0o700)

    def test_actual_cli_two_process_persisted_resume_and_exclusive_publication(self):
        self.input.write_text('Explicit code-contract unit text.\n' * 100)
        command = [sys.executable, '-I', str(ROOT / 'tools/headroom_context.py'), 'optimize',
                   '--input', str(self.input), '--store', str(self.store), '--kind', 'code']
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        try:
            results = []
            for child in children:
                stdout, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, stderr)
                results.append(json.loads(stdout))
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=5)
        self.assertEqual(results[0]['id'], results[1]['id'])
        self.assertEqual(sorted(result['reused_immutable_result'] for result in results), [False, True])
        self.assertEqual(len(list((self.store / 'entries').iterdir())), 1)
        completed = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/headroom_context.py'), 'retrieve',
                                    '--store', str(self.store), '--id', results[0]['id'], '--full'],
                                   capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0)
        retrieved = json.loads(completed.stdout)
        self.assertTrue(retrieved['source_hash_verified'])
        self.assertEqual(retrieved['content'], self.input.read_text())

    def test_concurrent_nonexistent_root_and_entries_initialization_is_idempotent(self):
        # Force both independent callers past the old existence check before
        # either mkdir, deterministically exposing the pre-lock EEXIST race.
        actual_mkdir = Path.mkdir
        entries_parent = self.root / 'entries-parent'
        entries_parent.mkdir(mode=0o700)
        for target in (self.root / 'new-store-root', entries_parent / 'entries'):
            with self.subTest(target=target.name):
                barrier = threading.Barrier(2)
                self.assertFalse(target.exists())
                def simultaneous_mkdir(path, *args, **kwargs):
                    if path == target:
                        barrier.wait(timeout=5)
                    return actual_mkdir(path, *args, **kwargs)
                with mock.patch.object(Path, 'mkdir', simultaneous_mkdir):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        tasks = [executor.submit(tool._private_directory, target, True) for _ in range(2)]
                        self.assertEqual([task.result(timeout=10) for task in tasks], [target, target])
                self.assertEqual(target.lstat().st_mode & 0o777, 0o700)
                self.assertFalse(target.is_symlink())

    def test_creation_race_rechecks_symlink_mode_and_git_boundary(self):
        actual_mkdir = Path.mkdir
        for attack in ('symlink', 'public-mode', 'new-git-marker'):
            with self.subTest(attack=attack):
                target = self.root / attack
                destination = self.root / ('destination-' + attack)
                destination.mkdir(mode=0o700)
                def substituted_mkdir(path, *args, **kwargs):
                    if path == target:
                        if attack == 'symlink':
                            path.symlink_to(destination, target_is_directory=True)
                        else:
                            actual_mkdir(path, mode=0o700)
                            if attack == 'public-mode':
                                path.chmod(0o755)
                            else:
                                (path / '.git').write_text('gitdir: /synthetic-unit-repository\n')
                    return actual_mkdir(path, *args, **kwargs)
                with mock.patch.object(Path, 'mkdir', substituted_mkdir):
                    with self.assertRaises(ValueError):
                        tool._private_directory(target, True)

    def test_binary_utf8_preserves_crlf_and_rejects_invalid_encoding(self):
        original = ('Exact source bytes\r\nالنص الأصلي\r\n' * 100).encode('utf-8')
        self.input.write_bytes(original)
        with mock.patch.object(tool, '_run_worker', side_effect=AssertionError('Code must pass through')):
            result = tool.optimize(self.input, self.store, 'code')
        self.assertEqual(result['id'], hashlib.sha256(original).hexdigest())
        self.assertEqual((self.entry(result) / 'original.utf8').read_bytes(), original)
        self.assertEqual(result['content'].encode('utf-8'), original)
        self.assertEqual(tool.retrieve(self.store, result['id'], full=True)['content'].encode('utf-8'), original)
        self.input.write_bytes(b'invalid UTF-8: ' + bytes([255]))
        with self.assertRaises(UnicodeError):
            tool.optimize(self.input, self.root / 'invalid-encoding', 'log')
        self.assertFalse((self.root / 'invalid-encoding').exists())

    def test_worker_failure_and_unavailable_boundary_return_original(self):
        for number, failure in enumerate((OSError('synthetic spawn failure'), subprocess.TimeoutExpired('unit-worker', 30))):
            with self.subTest(failure=type(failure).__name__):
                with mock.patch.object(tool, '_run_worker', side_effect=failure):
                    result = tool.optimize(self.input, self.root / ('failure-' + str(number)), 'tool-json')
                self.assertEqual(result['status'], 'fallback')
                self.assertEqual(result['content'], self.original)
        with mock.patch.object(tool.platform, 'system', return_value='Unsupported'):
            self.assertEqual(tool._run_worker(self.original, self.root)['ok'], False)

    def test_unreviewed_or_nonpreserving_runtime_falls_back(self):
        changes = [{'ok': 1}, {'sdk_version': '0.44.0'}, {'network_boundary': 'environment-flag-only'},
                   {'lossless': False}, {'ccr_roundtrip': False}, {'protected_messages_unchanged': False},
                   {'tokens_before': 0}, {'tokens_after': 0}, {'tokens_after': True}, {'tokens_after': 9000},
                   {'content': self.original + 'larger'}, {'compression_latency_ms': float('nan')},
                   {'compression_latency_ms': -1}, {'compression_latency_ms': 30001}]
        for change in changes:
            with self.subTest(change=change):
                content, state, _ = tool._choose_result(self.original, self.response(**change), set())
                self.assertEqual((content, state), (self.original, 'fallback'))
        for response in (None, [], {'ok': False}):
            self.assertEqual(tool._choose_result(self.original, response, set())[1], 'fallback')

    def test_sha_path_error_id_and_test_count_must_survive(self):
        _, _, _, facts = tool._inspect_input(self.input, 'tool-json')
        for original, replacement in [('a' * 64, 'b' * 64), ('src/unit_fixture.py', 'src/other.py'),
                                      ('unit-error', 'omitted'), ('unit-fixture', 'unit-fixture-extra'),
                                      ('987654321', '19876543210')]:
            with self.subTest(fact=original[:20]):
                response = self.response(content=self.compact.replace(original, replacement))
                content, state, reason = tool._choose_result(self.original, response, facts)
                self.assertEqual((state, reason), ('fallback', 'critical-fact-missing'))
                self.assertEqual(content, self.original)

    def test_log_error_lines_and_source_paths_must_survive(self):
        self.input.write_text('padding\n' * 200 + 'Tests: 17 passed, 1 failed\nERROR unit-failure src/task.py\n/workspace/unit/task.py\n')
        raw, original, _, facts = tool._inspect_input(self.input, 'log')
        self.assertGreater(len(raw), tool.SHORT_BYTES)
        self.assertIn('Tests: 17 passed, 1 failed', facts)
        self.assertIn('/workspace/unit/task.py', facts)
        self.assertEqual(tool._choose_result(original, self.response(content='all tests successful'), facts)[1], 'fallback')

    def test_original_tampering_missing_original_and_unsafe_modes_rejected(self):
        result = self.run_mock()
        original = self.entry(result) / 'original.utf8'
        original.write_text('tampered')
        with self.assertRaises(ValueError):
            tool.retrieve(self.store, result['id'], full=True)
        original.write_text(self.original)
        original.chmod(0o644)
        with self.assertRaises(ValueError):
            tool.retrieve(self.store, result['id'])
        original.unlink()
        with self.assertRaises(OSError):
            tool.retrieve(self.store, result['id'])

    def test_manifest_and_optimized_output_tampering_rejected(self):
        result = self.run_mock()
        entry = self.entry(result)
        manifest = entry / 'manifest.json'
        original_manifest = manifest.read_bytes()
        data = json.loads(original_manifest)
        data['input_bytes'] += 1
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            tool.retrieve(self.store, result['id'])
        manifest.write_bytes(original_manifest)
        (entry / 'optimized.utf8').write_text('changed output')
        with self.assertRaises(ValueError):
            tool.optimize(self.input, self.store, 'tool-json')

    def test_cache_removal_does_not_remove_durable_original(self):
        result = self.run_mock()
        shutil.rmtree(self.store / 'jobs')
        (self.entry(result) / 'optimized.utf8').unlink()
        (self.entry(result) / 'result.json').unlink()
        with mock.patch.object(tool, '_run_worker', side_effect=AssertionError('Retrieval must not invoke SDK')):
            self.assertEqual(tool.retrieve(self.store, result['id'], full=True)['content'], self.original)

    def test_query_is_literal_bounded_and_verifies_whole_source_first(self):
        self.input.write_text('first\n' + 'padding\n' * 1000 + 'needle [.*] unit\n' + 'after\n' * 1000)
        with mock.patch.object(tool, '_run_worker', return_value={'ok': False}):
            result = tool.optimize(self.input, self.store, 'log')
        default = tool.retrieve(self.store, result['id'])
        self.assertEqual(len(default['content']), tool.CONTEXT_CHARS)
        self.assertFalse(default['complete'])
        selected = tool.retrieve(self.store, result['id'], query='[.*]')
        self.assertTrue(selected['query_found'])
        self.assertIn('needle [.*] unit', selected['content'])
        self.assertEqual(tool.retrieve(self.store, result['id'], query='missing')['content'], '')
        for query in ('', 'x' * 129, 'line\nnext'):
            with self.assertRaises(ValueError):
                tool.retrieve(self.store, result['id'], query=query)
        with self.assertRaises(ValueError):
            tool.retrieve(self.store, result['id'], query='needle', full=True)
        for identity in ('../entry', 'A' * 64, 'a' * 63):
            with self.assertRaises(ValueError):
                tool.retrieve(self.store, identity)
        # Even a query near the beginning cannot bypass hash checking elsewhere.
        (self.entry(result) / 'original.utf8').write_text(self.input.read_text() + 'changed tail')
        with self.assertRaises(ValueError):
            tool.retrieve(self.store, result['id'], query='first')

    def test_sanitized_environment_contains_no_inherited_keys_or_home_changes(self):
        job = self.root / 'job'
        job.mkdir(mode=0o700)
        with mock.patch.dict(os.environ, {'UNRELATED_PROVIDER_KEY': 'unit-only', 'HTTPS_PROXY': 'unit-only',
                                          'HEADROOM_MODEL': 'unreviewed-model', 'HOME': '/unit-home'}):
            environment = tool._worker_environment(job)
        self.assertNotIn('UNRELATED_PROVIDER_KEY', environment)
        self.assertNotIn('HTTPS_PROXY', environment)
        self.assertNotIn('HEADROOM_MODEL', environment)
        self.assertNotIn('HOME', environment)
        self.assertNotIn('CODEX_HOME', environment)
        self.assertEqual(environment['HEADROOM_OFFLINE'], '1')
        self.assertEqual(environment['HEADROOM_BEACON'], 'off')
        self.assertEqual(environment['HEADROOM_TELEMETRY'], 'off')
        self.assertEqual(environment['HEADROOM_CCR_BACKEND'], 'memory')

    def test_kernel_ip_denial_in_real_child_before_sdk_import(self):
        if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'aarch64'):
            self.skipTest('Linux libseccomp boundary is unavailable on this platform; optimization fails closed')
        job = self.root / 'probe'
        job.mkdir(mode=0o700)
        environment = tool._worker_environment(job)
        completed = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/headroom_worker.py')],
                                   input=json.dumps({'operation': 'probe'}), text=True, capture_output=True,
                                   env=environment, cwd=job, timeout=20, close_fds=True)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout), {'ok': True, 'network_boundary': 'linux-seccomp-no-ip'})
        # Missing mandatory switches prevents even the boundary/SDK path.
        environment.pop('HEADROOM_OFFLINE')
        denied = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/headroom_worker.py')],
                                input='{"operation":"probe"}', text=True, capture_output=True,
                                env=environment, cwd=job, timeout=20, close_fds=True)
        self.assertFalse(json.loads(denied.stdout)['ok'])

    def test_two_file_vendoring_status_has_no_hub_or_sdk_import(self):
        destination = self.root / 'standalone'
        destination.mkdir()
        for name in ('headroom_context.py', 'headroom_worker.py'):
            shutil.copyfile(ROOT / 'tools' / name, destination / name)
        completed = subprocess.run([sys.executable, '-I', str(destination / 'headroom_context.py'), 'status'],
                                   cwd=destination, capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0)
        result = json.loads(completed.stdout)
        self.assertFalse(result['sdk_imported'])
        self.assertFalse(result['runtime_verified'])
        self.assertIsNone(result['billing'])

    def require_actual_sdk(self):
        if os.environ.get('HEADROOM_CONTEXT_INTEGRATION') != '1':
            self.skipTest('Set HEADROOM_CONTEXT_INTEGRATION=1 only in the separately reviewed SDK environment')
        try:
            installed = importlib.metadata.version('headroom-ai')
        except importlib.metadata.PackageNotFoundError:
            self.skipTest('Optional reviewed headroom-ai SDK is not installed; no installation attempted')
        self.assertEqual(installed, '0.45.0')

    def actual_sdk_rows(self):
        return [
            {'id': 'fixture-tool-' + str(i), 'category': 'unit-candidate', 'status': 'discovered',
             'source': 'https://example.invalid/tool/' + str(i), 'description': 'Repeated non-sensitive tool discovery metadata.'}
            for i in range(122)]

    def test_actual_sdk_flat_table_integration_when_explicitly_enabled(self):
        self.require_actual_sdk()
        # 0.45.0 densifies a flat JSON table. This is not a promise that every
        # JSON shape is eligible; the nested-table negative test checks that.
        self.input.write_text(json.dumps(self.actual_sdk_rows(), indent=2))
        result = tool.optimize(self.input, self.store, 'tool-json')
        self.assertEqual(result['status'], 'optimized', result['reason'])
        self.assertEqual(result['sdk_version'], '0.45.0')
        self.assertTrue(result['ccr_roundtrip'])
        self.assertTrue(result['lossless'])
        self.assertEqual(result['network_boundary'], 'linux-seccomp-no-ip')
        self.assertLess(result['output_bytes'], result['input_bytes'])
        for i in range(122):
            self.assertIn('fixture-tool-' + str(i), result['content'])
        self.assertEqual(tool.retrieve(self.store, result['id'], full=True)['content'], self.input.read_text())
        self.assertIsNone(result['exact_tokens']['before'])
        self.assertIsNone(result['billing'])

    def test_actual_sdk_nested_nonbeneficial_input_returns_original(self):
        self.require_actual_sdk()
        # Reviewed 0.45.0 tries this nested shape, then lossless verification
        # reverts it. Equal counters must remain a fallback, not a success.
        self.input.write_text(json.dumps({'tools': self.actual_sdk_rows()}, indent=2))
        result = tool.optimize(self.input, self.store, 'tool-json')
        self.assertEqual(result['status'], 'fallback')
        self.assertEqual(result['reason'], 'zero-or-nonreducing-counters')
        self.assertEqual(result['content'].encode(), self.input.read_bytes())
        self.assertEqual(result['byte_reduction'], 0)
        self.assertFalse(result['ccr_roundtrip'])  # No accepted optimization proof.
        self.assertIsNone(result['lossless'])
        self.assertEqual(result['estimated_tokens'], {'before': None, 'after': None, 'source': None})
        self.assertEqual(tool.retrieve(self.store, result['id'], full=True)['content'].encode(), self.input.read_bytes())


if __name__ == '__main__':
    unittest.main()
