import argparse,json,pathlib,re
ROOT=pathlib.Path(__file__).resolve().parent

def registry():
    rows=json.loads((ROOT/'catalog/registry.json').read_text())
    ids=[x['id'] for x in rows]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate catalog IDs')
    for x in rows:
        if not x['source'].startswith('https://github.com/'): raise ValueError('Invalid source')
        if x['status']=='approved' and (not re.fullmatch(r'[a-f0-9]{40}',x.get('revision') or '') or any(x[k]!='approved' for k in ('license_review','security_review','commercial_review'))): raise ValueError('Unreviewed approval')
    return rows

def onboard(target,revision,apply=False):
    if not re.fullmatch(r'[a-f0-9]{40}',revision): raise ValueError('Full reviewed commit SHA required')
    target=pathlib.Path(target).resolve()
    if not target.is_dir(): raise ValueError('Existing directory required')
    dest=target/'.engineering'
    if dest.is_symlink(): raise ValueError('Symlink refused')
    files={'capabilities.json':json.dumps({'schema_version':1,'hub_revision':revision,'capabilities':[],'budget_additional_sar':0},indent=2)+'\n','README.md':(ROOT/'docs/ONBOARDING.md').read_text()}
    result={}
    for name,data in files.items():
        path=dest/name
        if path.exists() or path.is_symlink(): result[name]='preserved';continue
        result[name]='created' if apply else 'would create'
        if apply:
            dest.mkdir(exist_ok=True)
            with path.open('x') as f:f.write(data)
    return result

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True)
    s.add_parser('audit');q=s.add_parser('search');q.add_argument('query');o=s.add_parser('onboard');o.add_argument('target');o.add_argument('--revision',required=True);o.add_argument('--apply',action='store_true');a=p.parse_args()
    if a.cmd=='audit':
        rows=registry();result={'catalog_entries':len(rows),'approved':sum(x['status']=='approved' for x in rows),'local_skills':len(list((ROOT/'skills').glob('*/SKILL.md'))),'runtime_verified':0}
    elif a.cmd=='search':result=[x for x in registry() if a.query.lower() in json.dumps(x).lower()]
    else:result=onboard(a.target,a.revision,a.apply)
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
