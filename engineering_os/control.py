"""Read-only operating-system projections over the established hub. SPDX-License-Identifier: MIT."""
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATES = ('DISCOVERED','REVIEWED','APPROVED','INSTALLED','OPERATIONAL','TESTED','PROJECT_VERIFIED')
LAYERS = [
 ('L01','Owner & governance',['governance/policies/capability-lifecycle.json','sdk/engineering_sdk.py']),
 ('L02','AI intelligence',['engineering_os/model_router.py','catalog/models/registry.json']),
 ('L03','Agent orchestration',['engineering_os/orchestration.py']),
 ('L04','Engineering control plane',['hub.py','hublink.py','sdk/engineering_sdk.py']),
 ('L05','Universal integrations',['sdk/engineering_sdk.py','integrations/PROGRAMS.json']),
 ('L06','Software engineering',['skills/system-builder/SKILL.md','skills/saas-platform/SKILL.md']),
 ('L07','Data & intelligence',['skills/ai-integration/SKILL.md']),
 ('L08','Cinematic & motion',['motion-library/runtime/hub-motion.mjs','packages/motion-sdk/index.mjs']),
 ('L09','Security & quality',['tests/test_security.py','.github/workflows/verify.yml']),
 ('L10','Independent products',['hublink.py','templates/capabilities.json']),
 ('L11','Cloud & delivery',['skills/release-engineering/SKILL.md','templates/RELEASE_MANIFEST.json']),
 ('L12','Continuous intelligence',['scripts/discover_technology.py','.github/dependabot.yml']),
]


def read(path):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    return json.loads(pathlib.Path(path).read_text(),object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid number')))


def architecture():
    return {'schema_version':1,'name':'Global AI Engineering Operating System',
            'standard':'10/10 target; not a measured certification',
            'runtime_dependency_on_hub':False,
            'layers':[{'id':key,'name':name,'target':True,
                       'available_source':[p for p in paths if (ROOT/p).is_file()],
                       'missing_source':[p for p in paths if not (ROOT/p).is_file()],
                       'operational_proof':'See module-specific receipts; file existence alone is not proof.'}
                      for key,name,paths in LAYERS]}


def capabilities(query='', state=None):
    if state is not None and state not in STATES: raise ValueError('unknown lifecycle state')
    rows=[]
    for entry in read(ROOT/'catalog/registry.json'):
        rows.append({'id':entry['id'],'kind':'external-tool','state':entry['status'].upper(),
                     'source':entry['source'],'revision':entry.get('revision'),
                     'installed':False,'operational':False,
                     'review':{k:entry.get(k) for k in ('license_review','security_review','commercial_review')}})
    for path in sorted((ROOT/'skills').glob('*/SKILL.md')):
        rows.append({'id':'skill:'+path.parent.name,'kind':'local-skill','state':'REVIEWED',
                     'source':str(path.relative_to(ROOT)),
                     'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                     'operational':False,'note':'Instructions are available; host invocation needs separate evidence.'})
    return [r for r in rows if query.casefold() in json.dumps(r).casefold() and (state is None or r['state']==state)]


def integrations():
    programs=read(ROOT/'integrations/PROGRAMS.json')['programs']
    evidence=read(ROOT/'integrations/EVIDENCE.json')
    by_name={r['program']:r for r in evidence.get('programs',[])}
    return {'schema_version':1,'evidence_date':evidence.get('tested_at'),
            'live_recheck_performed':False,
            'protocols':{'mcp':'local stdio implemented; host/provider auth separate',
                         'a2a':'candidate, not implemented','acp':'candidate, not implemented',
                         'cli':'implemented','rest':'provider-specific, not a universal authenticated adapter',
                         'graphql':'provider-specific','webhooks':'candidate','events':'local orchestration audit only'},
            'programs':[{'name':p['name'],'catalog_status':p['status'],
                         'last_probe':by_name.get(p['name']),
                         'current_authorization':'must be rechecked per environment'} for p in programs]}


def motions():
    legacy=read(ROOT/'motion-library/MOTION_CATALOG.json')['entries']
    result={'legacy':{'indexed':len(legacy),'runtime_verified':sum(x.get('runtime_verified') is True for x in legacy)},
            'expansion':{'indexed':0,'implemented':0,'tested':0,'runtime_verified':0}}
    path=ROOT/'motion-library/expansion/definitions.json'
    if path.is_file():
        document=read(path)
        rows=document if isinstance(document,list) else document.get('definitions',document.get('motions',[]))
        result['expansion']['indexed']=len(rows)
        result['expansion']['note']='Implementation and test counts require current runtime evidence; see expansion receipt.'
    return result


def health(project=None):
    findings=[]
    if project is not None:
        target=pathlib.Path(project).resolve()
        if not target.is_dir(): raise ValueError('existing project directory required')
        if (target/'.engineering').is_symlink(): raise ValueError('symlink engineering directory refused')
        from sdk.engineering_sdk import verify
        try:
            integrity=verify(target)
            findings.append({'check':'offline-capability-integrity','status':'passed','files':integrity['files']})
        except (OSError,ValueError,KeyError,TypeError):
            findings.append({'check':'offline-capability-integrity','status':'failed'})
        for name in ('capabilities.json','integration-manifest.json','release-manifest.json'):
            path=target/'.engineering'/name
            if path.is_symlink(): raise ValueError('symlink manifest refused')
            if not path.is_file():findings.append({'check':name,'status':'missing'})
            else:
                value=read(path)
                findings.append({'check':name,'status':'present-not-operational-proof','schema_version':value.get('schema_version')})
        contract=target/'.engineering/project.json'
        identity=read(contract).get('identity_verified') is True if contract.is_file() else False
        if not identity:findings.append({'check':'deployment-identity','status':'unverified'})
        return {'scope':'private project; do not publish this receipt','status':'attention',
                'findings':findings,'release_eligible':False,
                'note':'Run hub verify --strict and project invocation/release gates. Health does not deploy or read secrets.'}
    for name,path in [('sdk','sdk/engineering_sdk.py'),('orchestration','engineering_os/orchestration.py'),
                      ('routing','engineering_os/model_router.py'),('motion-sdk','packages/motion-sdk/index.mjs')]:
        findings.append({'module':name,'source_available':(ROOT/path).is_file()})
    return {'scope':'hub','status':'evidence-required','findings':findings,
            'external_runtime_installations_claimed':0,
            'note':'Runtime/test receipts are surface-specific. No provider credentials or private state inspected.'}
