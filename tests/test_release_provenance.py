import copy
import itertools
import pathlib
import re
import tempfile
import unittest
import datetime
from scripts.verify_release import NOT_RELEASE_GATING, TAG_PATTERN, WORKFLOWS, approved_runs, approved_jobs

ROOT = pathlib.Path(__file__).resolve().parents[1]
MATRIX_VALUE = re.compile(r'\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}')


def _scalar(text):
    text = re.sub(r'\s+#.*$', '', text).strip()
    return text[1:-1] if len(text) > 1 and text[0] == text[-1] and text[0] in '\'"' else text


def _blocks(lines, indent):
    """Keys at exactly this indent as {key: (inline value, deeper lines)}; any other shape is refused."""
    result, current = {}, None
    for line in lines:
        if not line.strip() or line.lstrip(' ').startswith('#'):
            continue
        depth = len(line) - len(line.lstrip(' '))
        if depth > indent and current is not None:
            result[current][1].append(line)
            continue
        match = re.fullmatch(r'([\'"]?)([A-Za-z0-9_.-]+)\1:(?:\s+(.*))?', line[indent:]) if depth == indent else None
        if match is None or match.group(2) in result:
            raise ValueError(f'unmodelled workflow line: {line!r}')
        current = match.group(2)
        result[current] = (_scalar(match.group(3) or ''), [])
    return result


def _values(inline, lines):
    if inline:
        if not (inline.startswith('[') and inline.endswith(']')):
            raise ValueError(f'unmodelled list: {inline!r}')
        return [_scalar(item) for item in inline[1:-1].split(',') if item.strip()]
    if not all(line.strip().startswith('- ') for line in lines if line.strip()):
        raise ValueError('unmodelled block list')
    return [_scalar(line.strip()[2:]) for line in lines if line.strip()]


def triggers(text):
    top = _blocks(text.splitlines(), 0)
    key = next((name for name in ('on', 'true') if name in top), None)  # YAML 1.1 reads a bare on as true
    if key is None:
        raise ValueError('workflow has no on: block')
    inline, lines = top[key]
    if inline:
        return {name: ('', []) for name in (_values(inline, []) if inline.startswith('[') else [inline])}
    return _blocks(lines, 2)


def runs_on_every_main_push(text):
    """True only for a push trigger that includes main and has no path or branch exclusions."""
    event = triggers(text).get('push')
    if event is None:
        return False
    if event[0] not in ('', '{}'):
        raise ValueError('unmodelled push trigger')
    filters = _blocks(event[1], 4)
    if {'paths', 'paths-ignore', 'branches-ignore'} & set(filters):
        return False
    if 'branches' in filters:
        return 'main' in _values(*filters['branches'])
    return not {'tags', 'tags-ignore'} & set(filters)


def check_names(text):
    """The check-run names GitHub gives each job, expanding single-axis list matrices."""
    names = []
    for job, (inline, body) in _blocks(_blocks(text.splitlines(), 0)['jobs'][1], 2).items():
        fields = _blocks(body, 4)
        if inline:
            raise ValueError('unmodelled job')
        name = fields['name'][0] if 'name' in fields else job
        if '${{' in MATRIX_VALUE.sub('', name):
            raise ValueError(f'unmodelled expression in job name: {name!r}')
        axes = {}
        if 'strategy' in fields:
            strategy = _blocks(fields['strategy'][1], 6)
            if fields['strategy'][0] or strategy.get('matrix', ('', []))[0]:
                raise ValueError('unmodelled strategy expression')
            for axis, (value, lines) in _blocks(strategy.get('matrix', ('', []))[1], 8).items():
                if axis in ('include', 'exclude'):
                    raise ValueError('matrix include/exclude is not modelled')
                axes[axis] = _values(value, lines)
        if set(MATRIX_VALUE.findall(name)) - set(axes):
            raise ValueError('job name references an undeclared matrix axis')
        for combination in itertools.product(*axes.values()):
            values = dict(zip(axes, combination))
            if MATRIX_VALUE.search(name):
                names.append(MATRIX_VALUE.sub(lambda match: values[match.group(1)], name))
            else:
                names.append(f"{name} ({', '.join(combination)})" if combination else name)
    return names


def ungated_push_workflows(root):
    """Workflows with any push trigger that are neither release-gating nor a named exception."""
    found = []
    for path in sorted((root / '.github/workflows').iterdir()):
        relative = path.relative_to(root).as_posix()
        if path.suffix in ('.yml', '.yaml') and 'push' in triggers(path.read_text(encoding='utf-8')):
            if relative not in WORKFLOWS and relative not in NOT_RELEASE_GATING:
                found.append(relative)
    return found


class ReleaseProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.sha='a'*40
        self.repo='owner/public-hub'
        self.now=datetime.datetime.now(datetime.timezone.utc)
        self.runs={'workflow_runs':[{'path':path,'head_sha':self.sha,'head_branch':'main','event':'push',
            'repository':{'full_name':self.repo},'head_repository':{'full_name':self.repo},
            'id':index,'run_number':index,'run_attempt':1,'status':'completed','conclusion':'success','updated_at':self.now.isoformat()}
            for index,path in enumerate(WORKFLOWS,1)]}

    def test_expected_workflow_paths_bind_complete_main_push_runs(self):
        result=approved_runs(self.runs,self.sha,self.repo)
        self.assertEqual(set(result),set(WORKFLOWS))

    def test_spoofed_same_name_workflow_pull_request_fork_and_wrong_commit_cannot_substitute(self):
        for field,value in [('path','.github/workflows/imposter.yml'),('event','pull_request'),
                            ('head_branch','feature'),('head_sha','b'*40),('head_repository',{'full_name':'fork/public-hub'})]:
            data=copy.deepcopy(self.runs);data['workflow_runs'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):approved_runs(data,self.sha,self.repo)

    def test_failed_or_pending_latest_attempt_cannot_fall_back_to_older_success(self):
        for status,conclusion in [('completed','failure'),('in_progress',None)]:
            data=copy.deepcopy(self.runs);latest=copy.deepcopy(data['workflow_runs'][0])
            latest.update(run_attempt=2,status=status,conclusion=conclusion);data['workflow_runs'].append(latest)
            with self.assertRaises(ValueError):approved_runs(data,self.sha,self.repo)

    def test_required_jobs_are_bound_to_unique_run_and_commit(self):
        path='.github/workflows/verify.yml'
        jobs={'total_count':2,'jobs':[{'name':name,'id':index,'run_id':12,'head_sha':self.sha,
              'status':'completed','conclusion':'success'} for index,name in enumerate(sorted(WORKFLOWS[path]),1)]}
        self.assertEqual(len(approved_jobs(jobs,path,12,self.sha)),2)
        for field,value in [('run_id',99),('head_sha','b'*40),('conclusion','failure')]:
            data=copy.deepcopy(jobs);data['jobs'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):approved_jobs(data,path,12,self.sha)
        duplicate=copy.deepcopy(jobs);duplicate['jobs'].append(duplicate['jobs'][0]);duplicate['total_count']=3
        with self.assertRaises(ValueError):approved_jobs(duplicate,path,12,self.sha)
        incomplete=copy.deepcopy(jobs);incomplete['total_count']=101
        with self.assertRaises(ValueError):approved_jobs(incomplete,path,12,self.sha)

    def test_later_failed_or_stale_advisory_audit_cannot_use_an_old_green_push(self):
        path='.github/workflows/dependency-audit.yml'
        for event in ('schedule','workflow_dispatch'):
            data=copy.deepcopy(self.runs)
            later=copy.deepcopy(next(r for r in data['workflow_runs'] if r['path']==path))
            later.update(event=event,run_number=99,id=99,conclusion='failure')
            data['workflow_runs'].append(later)
            with self.assertRaises(ValueError):approved_runs(data,self.sha,self.repo,self.now)
        data=copy.deepcopy(self.runs)
        audit=next(r for r in data['workflow_runs'] if r['path']==path)
        audit['updated_at']=(self.now-datetime.timedelta(days=2)).isoformat()
        with self.assertRaises(ValueError):approved_runs(data,self.sha,self.repo,self.now)
        audit.update(event='workflow_dispatch',updated_at=self.now.isoformat())
        self.assertIn(path,approved_runs(data,self.sha,self.repo,self.now))

    def test_later_failed_rerun_of_older_numbered_audit_blocks_newer_numbered_green_run(self):
        data=copy.deepcopy(self.runs)
        old=next(r for r in data['workflow_runs'] if r['path']=='.github/workflows/dependency-audit.yml')
        newer=copy.deepcopy(old)
        newer.update(id=99,run_number=99,updated_at=(self.now-datetime.timedelta(seconds=10)).isoformat())
        data['workflow_runs'].append(newer)
        old.update(run_attempt=2,conclusion='failure',updated_at=self.now.isoformat())
        with self.assertRaises(ValueError):approved_runs(data,self.sha,self.repo,self.now)



class ReleaseGatingWorkflowTests(unittest.TestCase):
    NEXTGEN = '.github/workflows/nextgen-intelligence.yml'

    def test_every_push_triggered_workflow_gates_release_or_is_a_named_exception(self):
        self.assertEqual(ungated_push_workflows(ROOT), [])
        self.assertFalse(set(WORKFLOWS) & set(NOT_RELEASE_GATING))
        for path, reason in NOT_RELEASE_GATING.items():
            self.assertTrue((ROOT / path).is_file(), path)
            self.assertTrue(isinstance(reason, str) and reason.strip(), path)

    def test_required_workflows_run_on_every_main_push_and_name_each_required_job_once(self):
        for path, required in WORKFLOWS.items():
            text = (ROOT / path).read_text(encoding='utf-8')
            with self.subTest(path=path):
                self.assertTrue(runs_on_every_main_push(text))
                names = check_names(text)
                for name in required:
                    self.assertEqual(names.count(name), 1, name)

    def test_next_generation_camera_job_is_release_gating_by_its_exact_name(self):
        text = (ROOT / self.NEXTGEN).read_text(encoding='utf-8')
        self.assertEqual(check_names(text), ['Original camera motions in Chromium'])
        self.assertEqual(WORKFLOWS[self.NEXTGEN], set(check_names(text)))
        sha, repo, now = 'a' * 40, 'owner/public-hub', datetime.datetime.now(datetime.timezone.utc)
        runs = {'workflow_runs': [{'path': path, 'head_sha': sha, 'head_branch': 'main', 'event': 'push',
                'repository': {'full_name': repo}, 'head_repository': {'full_name': repo}, 'id': index,
                'run_number': index, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'success',
                'updated_at': now.isoformat()} for index, path in enumerate(WORKFLOWS, 1)]}
        self.assertIn(self.NEXTGEN, approved_runs(runs, sha, repo, now))
        red = copy.deepcopy(runs)
        next(run for run in red['workflow_runs'] if run['path'] == self.NEXTGEN)['conclusion'] = 'failure'
        missing = copy.deepcopy(runs)
        missing['workflow_runs'] = [run for run in missing['workflow_runs'] if run['path'] != self.NEXTGEN]
        for document in (red, missing):
            with self.assertRaises(ValueError):
                approved_runs(document, sha, repo, now)
        jobs = {'total_count': 1, 'jobs': [{'name': 'Original camera motions in Chromium', 'id': 7, 'run_id': 3,
                'head_sha': sha, 'status': 'completed', 'conclusion': 'success'}]}
        self.assertEqual(approved_jobs(jobs, self.NEXTGEN, 3, sha), [{'name': 'Original camera motions in Chromium', 'job_id': 7}])
        renamed = copy.deepcopy(jobs)
        renamed['jobs'][0]['name'] = 'camera-runtime'
        with self.assertRaises(ValueError):
            approved_jobs(renamed, self.NEXTGEN, 3, sha)

    def test_filtered_or_non_main_push_triggers_do_not_count_as_every_main_push(self):
        head = 'name: x\non:\n  push:\n'
        jobs = '\njobs:\n  a:\n    runs-on: ubuntu-24.04\n'
        self.assertTrue(runs_on_every_main_push(head + '    branches: [main]\n' + jobs))
        self.assertTrue(runs_on_every_main_push(head + '    branches:\n      - main\n' + jobs))
        self.assertTrue(runs_on_every_main_push('on: [push, pull_request]\n' + jobs))
        self.assertTrue(runs_on_every_main_push(head + jobs))
        for extra in ('    branches: [main]\n    paths: [docs/**]\n', '    branches: [main]\n    paths-ignore: [x]\n',
                      '    branches-ignore: [feature]\n', '    branches: [release]\n', '    tags: [v*]\n'):
            with self.subTest(extra=extra):
                self.assertFalse(runs_on_every_main_push(head + extra + jobs))
        self.assertFalse(runs_on_every_main_push('on:\n  workflow_dispatch:\n' + jobs))
        for broken in ('jobs:\n  a: {}\n', 'on:\n\tpush:\n', 'on:\n  push:\n  push:\n'):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                runs_on_every_main_push(broken)

    def test_job_names_expand_list_matrices_and_refuse_shapes_the_reader_does_not_model(self):
        matrix = ('jobs:\n  studio:\n    name: Studio in ${{ matrix.browser }}\n    strategy:\n'
                  '      matrix:\n        browser: [firefox, webkit]\n    steps:\n      - run: true\n')
        self.assertEqual(check_names(matrix), ['Studio in firefox', 'Studio in webkit'])
        self.assertEqual(check_names(matrix.replace('    name: Studio in ${{ matrix.browser }}\n', '')),
                         ['studio (firefox)', 'studio (webkit)'])
        self.assertEqual(check_names('jobs:\n  test:\n    runs-on: x\n  other:\n    name: "Quoted name" # note\n'),
                         ['test', 'Quoted name'])
        for broken in (matrix.replace('browser: [firefox, webkit]', 'include: [{browser: firefox}]'),
                       matrix.replace('matrix.browser', 'matrix.os'),
                       matrix.replace('${{ matrix.browser }}', '${{ github.ref }}'),
                       matrix.replace('      matrix:\n        browser: [firefox, webkit]\n',
                                      '      matrix: ${{ fromJSON(needs.plan.outputs.matrix) }}\n')):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                check_names(broken)

    def test_new_unlisted_push_workflow_is_reported_and_dispatch_only_workflow_is_not(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as folder:
            root = pathlib.Path(folder)
            (root / '.github/workflows').mkdir(parents=True)
            for path in WORKFLOWS:
                (root / path).write_bytes((ROOT / path).read_bytes())
            (root / '.github/workflows/manual.yml').write_text('on:\n  workflow_dispatch:\njobs:\n  a:\n    runs-on: x\n')
            self.assertEqual(ungated_push_workflows(root), [])
            (root / '.github/workflows/imposter.yml').write_text('on:\n  push:\n    branches: [main]\njobs:\n  a:\n    runs-on: x\n')
            self.assertEqual(ungated_push_workflows(root), ['.github/workflows/imposter.yml'])


class ReleaseChecklistTests(unittest.TestCase):
    CHECKLIST = ROOT / 'docs/specs/gaie-20-layers/RELEASE_CHECKLIST.md'

    def test_only_engineering_os_semantic_version_tags_are_accepted(self):
        for tag in ('engineering-os-v0.2.0', 'engineering-os-v1.0.0', 'engineering-os-v10.20.30'):
            self.assertTrue(re.fullmatch(TAG_PATTERN, tag), tag)
        for tag in ('engineering-os-v1.0.0-rc.1', 'v1.0.0', 'engineering-sdk-v1.0.1', 'engineering-os-v1.0',
                    'engineering-os-v1.0.0 ', 'engineering-os-vX.Y.Z'):
            self.assertIsNone(re.fullmatch(TAG_PATTERN, tag), tag)

    def test_checklist_quotes_the_tag_shape_and_lists_exactly_the_required_jobs(self):
        text = self.CHECKLIST.read_text(encoding='utf-8')
        self.assertIn(f'`{TAG_PATTERN}`', text)
        self.assertIn('recorded, tag pending', text)
        self.assertIn('merge_method=merge', text)
        self.assertNotIn('--squash', text)
        rows = [line.strip() for line in text.splitlines() if line.strip().startswith('| `.github/workflows/')]
        listed = {}
        for row in rows:
            cells = row.split('|')
            listed[cells[1].strip().strip('`')] = re.findall(r'`([^`]+)`', cells[2])
        self.assertEqual(len(rows), len(WORKFLOWS))
        self.assertEqual(set(listed), set(WORKFLOWS))
        for path, jobs in listed.items():
            self.assertEqual(sorted(jobs), sorted(WORKFLOWS[path]), path)


if __name__=='__main__':unittest.main()
