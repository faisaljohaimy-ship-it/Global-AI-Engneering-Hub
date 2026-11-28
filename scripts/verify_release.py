"""Read-only engineering release provenance: reviewed main ancestry and exact CI runs."""
import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import urllib.request

WORKFLOWS = {
    '.github/workflows/verify.yml': {'test', 'motion in Chromium'},
    '.github/workflows/operating-system.yml': {'operating system and motion unit tests', 'fresh Chromium and Motion Studio runtime evidence'},
    '.github/workflows/security.yml': {'Tracked secrets and Python execution hazards'},
    '.github/workflows/dependency-audit.yml': {'Audit exact tracked npm locks'},
    '.github/workflows/motion-cross-browser.yml': {'Motion Studio in firefox', 'Motion Studio in webkit'},
    '.github/workflows/nextgen-intelligence.yml': {'Original camera motions in Chromium'},
    # Observed green on a GitHub-hosted runner at 6a0330a (run 46134437218, job 140946479217).
    '.github/workflows/isolation.yml': {'Full sandbox tier with no skipped isolation test'},
}
# Workflows that run on a push to main without gating a release, each mapped to the reason.
# tests/test_release_provenance.py requires every push-triggered workflow to be in WORKFLOWS or here.
NOT_RELEASE_GATING = {}
# The only tag shape release.yml accepts; docs/specs/gaie-20-layers/RELEASE_CHECKLIST.md quotes it.
TAG_PATTERN = r'engineering-os-v[0-9]+\.[0-9]+\.[0-9]+'


def approved_runs(document, commit, repository, now=None):
    """Bind main CI and the latest fresh advisory audit to exact trusted workflows."""
    result={}
    current=now or datetime.datetime.now(datetime.timezone.utc)
    for path in WORKFLOWS:
        audit=path=='.github/workflows/dependency-audit.yml'
        events={'push','schedule','workflow_dispatch'} if audit else {'push'}
        candidates=[r for r in document['workflow_runs'] if r['path']==path and r['head_sha']==commit
                    and r['head_branch']=='main' and r['event'] in events
                    and r['repository']['full_name']==repository and r['head_repository']['full_name']==repository]
        if not candidates:raise ValueError('Missing required main push workflow')
        executions=[]
        for candidate in candidates:
            at=datetime.datetime.fromisoformat(candidate['updated_at'].replace('Z','+00:00'))
            if at.utcoffset()!=datetime.timedelta(0) or at>current:raise ValueError('Invalid workflow execution timestamp')
            executions.append((at,candidate))
        at,run=max(executions,key=lambda item:(item[0],item[1]['run_attempt'],item[1]['id']))
        if type(run['id']) is not int or run['id']<=0 or run['status']!='completed' or run['conclusion']!='success':
            raise ValueError('Latest exact-commit workflow did not succeed')
        if audit:
            if not 0<=(current-at).total_seconds()<=86400:
                raise ValueError('A successful advisory audit within24hours is required')
        result[path]=run['id']
    return result


def approved_jobs(document, path, run_id, commit):
    jobs=document['jobs']
    if document['total_count']!=len(jobs) or len(jobs)>100:raise ValueError('Incomplete job inventory')
    selected=[]
    for name in WORKFLOWS[path]:
        found=[r for r in jobs if r['name']==name]
        if len(found)!=1:raise ValueError('Missing or ambiguous required job')
        job=found[0]
        if job['run_id']!=run_id or job['head_sha']!=commit or job['status']!='completed' or job['conclusion']!='success':
            raise ValueError('Required job did not succeed at this exact run and commit')
        selected.append({'name':name,'job_id':job['id']})
    return sorted(selected,key=lambda r:r['name'])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        raise ValueError('Release API redirects refused')


def github_json(route, token):
    if not route.startswith('/repos/') or not token:raise ValueError('Explicit read-only API authorization required')
    request=urllib.request.Request('https://api.github.com'+route,headers={
        'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=20) as response:
        raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('Oversized workflow metadata')
    return json.loads(raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag',required=True)
    parser.add_argument('--repository',required=True)
    parser.add_argument('--output',required=True,type=pathlib.Path)
    args=parser.parse_args()
    if not re.fullmatch(TAG_PATTERN,args.tag):raise ValueError('Invalid engineering tag')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',args.repository):raise ValueError('Invalid repository')
    commit=subprocess.check_output(['git','rev-parse','--verify',f'refs/tags/{args.tag}^{{commit}}'],text=True,timeout=20).strip()
    if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('Invalid commit')
    subprocess.run(['git','merge-base','--is-ancestor',commit,'origin/main'],check=True,timeout=20)
    token=os.environ.get('GH_TOKEN','')
    base=f'/repos/{args.repository}'
    runs=approved_runs(github_json(f'{base}/actions/runs?head_sha={commit}&branch=main&per_page=100',token),commit,args.repository)
    verified=[]
    for path,run_id in runs.items():
        jobs=approved_jobs(github_json(f'{base}/actions/runs/{run_id}/jobs?filter=latest&per_page=100',token),path,run_id,commit)
        verified.append({'workflow':path,'run_id':run_id,'url':f'https://github.com/{args.repository}/actions/runs/{run_id}','jobs':jobs})
    result={'schema_version':1,'tag':args.tag,'commit':commit,'main_ancestor':True,
            'verified_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'workflows':verified,'product_deployment_performed':False}
    with args.output.open('x') as output:json.dump(result,output,indent=2);output.write('\n')
    print(json.dumps({'tag':args.tag,'commit':commit,'required_workflows':len(verified)}))


if __name__=='__main__':main()
