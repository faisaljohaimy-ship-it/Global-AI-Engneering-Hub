import copy
import unittest
import datetime
from scripts.verify_release import WORKFLOWS, approved_runs, approved_jobs


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


if __name__=='__main__':unittest.main()
