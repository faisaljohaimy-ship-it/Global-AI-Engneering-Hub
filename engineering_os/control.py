"""Read-only operating-system projections over the established hub. SPDX-License-Identifier: MIT."""
import hashlib
import json
import pathlib
import datetime
import re
import math

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


def read(path, expected_sha256=None):
    data=pathlib.Path(path).read_bytes()
    if expected_sha256 is not None:
        if not isinstance(expected_sha256,str) or not re.fullmatch('[a-f0-9]{64}',expected_sha256):raise ValueError('invalid receipt digest')
        if hashlib.sha256(data).hexdigest()!=expected_sha256:raise ValueError('changed receipt bytes')
    return _decode_json(data)


def _decode_json(data):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    def finite(value):
        number=float(value)
        if not math.isfinite(number):raise ValueError('invalid number')
        return number
    return json.loads(data.decode('utf-8'),object_pairs_hook=pairs,parse_float=finite,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid number')))


def safe_path(relative):
    """Resolve repository evidence without traversal or any symlink component."""
    if not isinstance(relative,str) or not relative or '\\' in relative:raise ValueError('unsafe receipt path')
    parts=pathlib.PurePosixPath(relative).parts
    if not parts or pathlib.PurePosixPath(relative).is_absolute() or '..' in parts or parts[0]=='.git':raise ValueError('unsafe receipt path')
    path=ROOT
    for part in parts:
        path=path/part
        if path.is_symlink():raise ValueError('symlink receipt path')
    return path


def source_matches(inputs):
    if not isinstance(inputs,dict) or not inputs:return False
    for name,expected in inputs.items():
        if not isinstance(expected,str) or not re.fullmatch('[a-f0-9]{64}',expected):return False
        if hashlib.sha256(safe_path(name).read_bytes()).hexdigest()!=expected:return False
    return True


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
        row={'id':entry['id'],'kind':'external-tool','state':entry['status'].upper(),
                     'source':entry['source'],'revision':entry.get('revision'),
                     'installed':False,'operational':False,
                     'review':{k:entry.get(k) for k in ('license_review','security_review','commercial_review')}}
        review_path=ROOT/'catalog/capabilities'/(entry['id'].replace('/','-')+'.json')
        if entry['id']=='microsoft/playwright':review_path=ROOT/'catalog/capabilities/playwright.json'
        if review_path.is_file():
            reviewed=runtime_review(read(review_path))
            if reviewed and entry['status']=='approved' and entry.get('revision')==reviewed['revision']:
                row.update(state='TESTED',installed=True,operational=True,scope=reviewed['scope'],
                           evidence_scope='source-bound recorded developer QA; not fresh provider/project activation',
                           receipt=reviewed['runtime_receipt'])
        rows.append(row)
    for path in sorted((ROOT/'skills').glob('*/SKILL.md')):
        rows.append({'id':'skill:'+path.parent.name,'kind':'local-skill','state':'REVIEWED',
                     'source':str(path.relative_to(ROOT)),
                     'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                     'operational':False,'note':'Instructions are available; host invocation needs separate evidence.'})
    return [r for r in rows if query.casefold() in json.dumps(r).casefold() and (state is None or r['state']==state)]


def runtime_review(record, now=None):
    """Withdraw a recorded runtime claim when source or time-bound evidence changes."""
    try:
        path=safe_path(record['runtime_receipt'])
        expected=record.get('runtime_receipt_sha256')
        if not isinstance(expected,str) or not re.fullmatch('[a-f0-9]{64}',expected):return None
        receipt=read(path,expected_sha256=expected)
        if receipt.get('status')!='passed' or receipt.get('functional_status')!='passed':return None
        required={'package.json','package-lock.json','options.mjs','native-probes.mjs','smoke.mjs','harness.html'}
        if set(receipt['inputs'])!=required or record['module_root']!='motion-library/chromium-stack':return None
        cases=receipt['cases']
        if len(cases)!=3 or {c['id'] for c in cases}!={'desktop-ltr','mobile-rtl','mobile-reduced-rtl'}:return None
        for case in cases:
            reduced=case['id']=='mobile-reduced-rtl'
            mobile=case['id']!='desktop-ltr'
            if case['reduced_motion'] is not reduced or case['direction']!=('rtl' if mobile else 'ltr'):return None
            if case['viewport']!={'width':390 if mobile else 1280,'height':844 if mobile else 720,'device_pixel_ratio':1}:return None
            checks={'canvas_pixel','webgl_shader_pixels','wasm_execution'}
            checks.update({'css_reduced_motion','waapi_reduced_motion','reduced_canvas_static','reduced_transform_static'}
                          if case['id']=='mobile-reduced-rtl' else {'css_interpolation','waapi_interpolation'})
            if case['status']!='passed' or not all(case['checks'].get(key) is True for key in checks):return None
            if case['page_errors']!=0 or case['external_requests']!=0:return None
            if not all(case['rendered'].get(key) is True for key in ('canvas2d','webgl_shader','offscreen_canvas')):return None
            if case['rendered'].get('css_animation') is not (not reduced) or case['rendered'].get('waapi') is not (not reduced):return None
            benchmark=case['benchmark'];p95=benchmark['p95_interval_ms'];budget=benchmark['frame_budget_ms']
            if set(benchmark)!={'scope','frames','median_interval_ms','p95_interval_ms','median_draw_ms','observed_median_fps','frame_budget_ms','within_configured_budget'}:return None
            numeric=[benchmark[key] for key in ('median_interval_ms','median_draw_ms','observed_median_fps')]
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in numeric):return None
            median,draw,fps=numeric
            if not 0<median<=p95 or draw<0 or abs(fps-1000/median)>.01:return None
            if type(p95) not in (int,float) or not math.isfinite(p95) or not 0<p95<=20:return None
            if type(budget) not in (int,float) or not 0<budget<=20 or p95>budget or type(benchmark['frames']) is not int or not 30<=benchmark['frames']<=600 or benchmark['within_configured_budget'] is not True:return None
        if receipt['network']!={'bind':'127.0.0.1','external_requests':0,'authenticated_profiles':False}:return None
        if receipt['browser']['engine']!='chromium':return None
        if receipt['webgpu_rendering_cases']!=0 or any(c['webgpu']['rendering_tested'] is not False for c in cases):return None
        at=datetime.datetime.fromisoformat(receipt['recorded_at_utc'].replace('Z','+00:00'))
        age=((now or datetime.datetime.now(datetime.timezone.utc))-at).total_seconds()
        maximum=record['maximum_receipt_age_seconds']
        if type(maximum) is not int or not 0<maximum<=86400 or not 0<=age<=maximum:return None
        module=safe_path(record['module_root'])
        if not source_matches({str(module.relative_to(ROOT)/name):expected for name,expected in receipt['inputs'].items()}):return None
        if not receipt['inputs'] or receipt['toolchain']['playwright']!=record['version']:return None
        return record
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return None


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


def _motion_toolchain_review(receipt, historical=False):
    """Separate a reviewed immutable historical proof from the current driver."""
    policy=read(safe_path('catalog/capabilities/playwright.json'))
    if historical:
        digest=hashlib.sha256(json.dumps(receipt,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        for review in policy.get('historical_reviews',[]):
            if (review.get('review_status')=='approved' and review.get('version')==receipt['playwright_version']
                and re.fullmatch('[a-f0-9]{40}',review.get('revision',''))
                and re.fullmatch('[a-f0-9]{40}',review.get('hub_revision',''))
                and review['motion_receipt']['canonical_sha256']==digest):return review
        return None
    version=policy['version']
    catalog=next(r for r in read(safe_path('catalog/registry.json')) if r['id']=='microsoft/playwright')
    if catalog['status']!='approved' or catalog['revision']!=policy['revision'] or policy['requested_state'] not in ('APPROVED','INSTALLED','OPERATIONAL','TESTED','PROJECT_VERIFIED'):return None
    if any(catalog.get(field)!='approved' for field in ('license_review','security_review','commercial_review')):return None
    if not re.fullmatch('[a-f0-9]{40}',policy['revision']) or receipt['playwright_version']!=version:return None
    current=policy.get('motion_runtime_receipt')
    expected=policy.get('motion_runtime_receipt_sha256')
    if not isinstance(current,str) or not isinstance(expected,str) or not re.fullmatch('[a-f0-9]{64}',expected):return None
    approved=safe_path(current)
    if hashlib.sha256(approved.read_bytes()).hexdigest()!=expected or read(approved)!=receipt:return None
    for scope in ('verify','chromium-stack','quality'):
        if read(safe_path(f'motion-library/{scope}/package.json'))['devDependencies']['playwright']!=version:return None
        packages=read(safe_path(f'motion-library/{scope}/package-lock.json'))['packages']
        for name in ('playwright','playwright-core'):
            entry=packages['node_modules/'+name]
            if entry['version']!=version or entry['integrity']!=policy['npm_integrities'][name]:return None
    return policy


def motions():
    legacy=read(ROOT/'motion-library/MOTION_CATALOG.json')['entries']
    result={'legacy':{'indexed':len(legacy),'runtime_verified':sum(x.get('runtime_verified') is True for x in legacy)},
            'expansion':{'indexed':0,'implemented':0,'tested':0,'runtime_verified':0}}
    path=ROOT/'motion-library/expansion/definitions.json'
    if path.is_file():
        document=read(path)
        rows=document if isinstance(document,list) else document.get('definitions',document.get('motions',[]))
        result['expansion']['indexed']=len(rows)
        result['expansion']['note']='Counts require reviewed source-bound evidence, not source presence alone.'
        policy=read(safe_path('catalog/capabilities/playwright.json'))
        current=policy.get('motion_runtime_receipt')
        result['expansion']['current_runtime']={'playwright':policy['version'],'runtime_verified':0,'receipt':current,'state':'evidence-required'}
        candidates=[(current,False)] if current else []
        candidates.extend((r['motion_receipt']['path'],True) for r in policy.get('historical_reviews',[]) if r.get('review_status')=='approved')
        for name,historical in candidates:
            try:
                receipt_path=safe_path(name)
                receipt=read(receipt_path)
                review=_motion_toolchain_review(receipt,historical)
                valid=review is not None and motion_receipt_valid(receipt,rows,historical=historical)
                if historical and review is not None and hashlib.sha256(receipt_path.read_bytes()).hexdigest()!=review['motion_receipt']['sha256']:valid=False
                if valid:
                    result['expansion'].update(implemented=400,tested=400,basic=200,advanced=200,
                        live_recheck_performed=False,engine='Canvas2D reference',production_fps_verified=False,gpu_runtime_verified=False,
                        note='Implementation/test counts retain reviewed dated proof for unchanged sources. Current-driver runtime requires its own reviewed receipt.')
                    if historical:
                        result['expansion']['historical_tested_toolchain']={'playwright':receipt['playwright_version'],'recorded_at_utc':receipt['recorded_at_utc'],'hub_revision':review['hub_revision'],'receipt':name}
                        if not result['expansion']['runtime_verified']:
                            result['expansion'].update(recorded_at_utc=receipt['recorded_at_utc'],receipt=name)
                    else:
                        result['expansion'].update(runtime_verified=400,recorded_at_utc=receipt['recorded_at_utc'],receipt=name)
                        result['expansion']['current_runtime'].update(runtime_verified=400,state='recorded-source-bound',recorded_at_utc=receipt['recorded_at_utc'])
            except (OSError,ValueError,KeyError,TypeError,AttributeError):pass
    return result


def motion_receipt_valid(receipt, rows, *, historical=False):
    """Validate recorded, reviewed-source evidence; this is not evaluator authentication."""
    expected={r['id'] for r in rows}
    required={'packages/motion-sdk/index.mjs','motion-studio/index.html','motion-studio/studio.mjs',
              'motion-studio/styles.css','motion-library/expansion/catalog.mjs','motion-library/expansion/definitions.json',
              'motion-library/expansion/families.mjs','motion-library/expansion/systems.mjs',
              'motion-library/expansion/geometry.mjs','tests/test_motion_studio_browser.mjs'}
    if receipt['schema_version']!=1 or receipt['status']!='passed' or len(rows)!=400 or len(expected)!=400:return False
    if set(receipt['source_sha256'])!=required or not source_matches(receipt['source_sha256']):return False
    if not isinstance(receipt['raw_receipt_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',receipt['raw_receipt_sha256']):return False
    if receipt['engine']!='chromium-canvas2d' or not isinstance(receipt['browser'],str) or not re.fullmatch(r'\d+\.\d+\.\d+\.\d+',receipt['browser']):return False
    if _motion_toolchain_review(receipt,historical) is None:return False
    if receipt['production_fps_verified'] is not False or receipt['gpu_runtime_verified'] is not False:return False
    at=datetime.datetime.fromisoformat(receipt['recorded_at_utc'].replace('Z','+00:00'))
    if at.utcoffset()!=datetime.timedelta(0) or at>datetime.datetime.now(datetime.timezone.utc):return False
    for key,value in {'definitions':400,'basic':200,'advanced':200,'frame_samples':2400,'reduced_motion_cases':800,'benchmark_draws':9600}.items():
        if type(receipt[key]) is not int or receipt[key]!=value:return False
    profiles=receipt['profiles']
    if len(profiles)!=2:return False
    actual=[]
    for profile in profiles:
        actual.append((profile['direction'],profile['language'],profile['viewport']['width'],profile['viewport']['height']))
        if set(profile['viewport'])!={'width','height'}:return False
        definitions=profile['definitions']
        if len(definitions)!=400 or {r['id'] for r in definitions}!=expected:return False
        for row in definitions:
            if type(row['frame_samples']) is not int or row['frame_samples']!=3 or type(row['benchmark_frames']) is not int or row['benchmark_frames']!=12:return False
            if type(row['distinct_sampled_frames']) is not int or not 2<=row['distinct_sampled_frames']<=3:return False
            if type(row['minimum_changed_pixels']) is not int or row['minimum_changed_pixels']<=0 or row['reduced_motion_stable'] is not True:return False
            p95,budget=row['cpu_p95_ms'],row['cpu_budget_ms']
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (p95,budget)) or not 0<budget<=16.67 or not 0<=p95<=budget:return False
    return set(actual)=={('rtl','ar',390,844),('ltr','en',1280,900)}


def health(project=None):
    findings=[]
    if project is not None:
        target=pathlib.Path(project).resolve()
        if not target.is_dir(): raise ValueError('existing project directory required')
        if (target/'.engineering').is_symlink(): raise ValueError('symlink engineering directory refused')
        from sdk.engineering_sdk import read_audit_file, verify
        try:
            integrity=verify(target)
            findings.append({'check':'offline-capability-integrity','status':'passed','files':integrity['files']})
        except (OSError,ValueError,KeyError,TypeError):
            findings.append({'check':'offline-capability-integrity','status':'failed'})
        for name in ('capabilities.json','integration-manifest.json','release-manifest.json'):
            path=target/'.engineering'/name
            if path.is_symlink(): raise ValueError('symlink manifest refused')
            try:
                value=_decode_json(read_audit_file(target, f'.engineering/{name}'))
            except FileNotFoundError:
                findings.append({'check':name,'status':'missing'})
            else:
                findings.append({'check':name,'status':'present-not-operational-proof','schema_version':value.get('schema_version')})
        contract=target/'.engineering/project.json'
        if contract.is_symlink(): raise ValueError('symlink project identity refused')
        try:
            identity=_decode_json(read_audit_file(target, '.engineering/project.json')).get('identity_verified') is True
        except FileNotFoundError:
            identity=False
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
