"""Bounded upstream metadata discovery; never installs, approves or executes a tool.

SPDX-License-Identifier: MIT. Output only public GitHub repository metadata.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=re.compile(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)')


class SameOrigin(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed=urllib.parse.urlsplit(newurl)
        if parsed.scheme!='https' or parsed.netloc!='api.github.com':
            raise ValueError('cross-origin metadata redirect refused')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def probe(entry, token=None, opener=None):
    match=SOURCE.fullmatch(entry.get('source',''))
    if not match:raise ValueError('only canonical public GitHub repository sources are supported')
    headers={'Accept':'application/vnd.github+json','User-Agent':'engineering-hub-discovery/1.0'}
    if token:headers['Authorization']='Bearer '+token
    request=urllib.request.Request('https://api.github.com/repos/'+match[1]+'/'+match[2],headers=headers)
    client=opener or urllib.request.build_opener(SameOrigin())
    try:
        with client.open(request,timeout=15) as response:
            if response.status!=200:return {'id':entry['id'],'status':'unavailable','http_status':response.status}
            raw=response.read(1_000_001)
            if len(raw)>1_000_000:raise ValueError('metadata response exceeds budget')
            data=json.loads(raw)
        if data.get('private') is not False:raise ValueError('private upstream metadata refused')
        return {'id':entry['id'],'status':'metadata-discovered','source':entry['source'],
                'canonical_source':data.get('html_url'),'default_branch':data.get('default_branch'),
                'archived':data.get('archived'),'disabled':data.get('disabled'),
                'pushed_at':data.get('pushed_at'),'license_spdx':(data.get('license') or {}).get('spdx_id'),
                'adoption':'not-approved','license_review':'metadata-only, not a commercial-use opinion',
                'security_review':'not performed by this metadata probe',
                'installation':False,'invocation':False}
    except urllib.error.HTTPError as error:
        return {'id':entry['id'],'status':'blocked' if error.code in (401,403,429) else 'unavailable','http_status':error.code}
    except (urllib.error.URLError,TimeoutError,OSError,ValueError):
        return {'id':entry['id'],'status':'probe-failed','detail':'No raw upstream response, credentials or request headers recorded.'}


def discover(entries, limit=12, offset=0, token=None, probe_fn=probe):
    if type(limit) is not int or not 1<=limit<=128 or type(offset) is not int or offset<0:
        raise ValueError('bounded positive discovery limit/offset required')
    selected=entries[offset:offset+limit]
    rows=[]
    for start in range(0,len(selected),4):
        batch=selected[start:start+4]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda entry:probe_fn(entry,token),batch))
        rows.extend(results)
        if any(r.get('http_status') in (401,403,429) for r in results):break
    return {'schema_version':1,'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'selected':len(selected),'attempted':len(rows),'network_request_budget':limit,
            'stopped_on_authorization_or_rate_limit':len(rows)<len(selected),
            'automatic_installation':False,'automatic_approval':False,
            'findings':rows,'next_step':'Review immutable revisions, licenses, advisories, compatibility and cost in a separate PR.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=12)
    parser.add_argument('--offset',type=int,default=0)
    parser.add_argument('--output',type=pathlib.Path)
    args=parser.parse_args()
    entries=json.loads((ROOT/'catalog/registry.json').read_text())
    result=discover(entries,args.limit,args.offset,os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN'))
    data=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        if args.output.is_symlink() or any(p.is_symlink() for p in args.output.parents):raise ValueError('symlink output refused')
        with args.output.open('x') as stream:stream.write(data)
    else:print(data,end='')


if __name__=='__main__':main()
