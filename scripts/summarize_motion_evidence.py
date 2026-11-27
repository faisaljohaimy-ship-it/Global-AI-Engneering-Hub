"""Publish a bounded, source-checked summary of the actual 400-motion browser run."""
import argparse
import hashlib
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engineering_os.control import read, safe_path

REQUIRED_SOURCES = {
    'packages/motion-sdk/index.mjs', 'motion-studio/index.html',
    'motion-studio/studio.mjs', 'motion-studio/styles.css',
    'motion-library/expansion/catalog.mjs', 'motion-library/expansion/definitions.json',
    'motion-library/expansion/families.mjs', 'motion-library/expansion/systems.mjs',
    'motion-library/expansion/geometry.mjs', 'tests/test_motion_studio_browser.mjs',
}


def summarize(report):
    if report.get('status') != 'passed' or report.get('engine') != 'chromium-canvas2d':
        raise ValueError('A successful real Chromium run is required')
    if set(report['source_sha256']) != REQUIRED_SOURCES:
        raise ValueError('Incomplete source closure')
    for name, digest in report['source_sha256'].items():
        if hashlib.sha256(safe_path(name).read_bytes()).hexdigest() != digest:
            raise ValueError('Runtime source differs from this checkout')
    definitions = read(ROOT/'motion-library/expansion/definitions.json')['definitions']
    expected = {row['id'] for row in definitions}
    if len(definitions) != 400 or len(expected) != 400:
        raise ValueError('Expected exactly 400 unique definitions')
    if report['playwright_version'] != read(ROOT/'motion-library/verify/package.json')['devDependencies']['playwright']:
        raise ValueError('Unreviewed browser driver')
    profiles = []
    if len(report['results']) != 2:
        raise ValueError('Both desktop and mobile profiles are required')
    for profile in report['results']:
        rows, reduced = profile['results'], profile['reduced_motion']
        if profile['errors'] or len(rows) != 400 or {r['id'] for r in rows} != expected:
            raise ValueError('Missing/failed runtime definitions')
        if len(reduced) != 400 or {r['id'] for r in reduced} != expected or not all(r['stable'] is True and r['primitives'] > 0 for r in reduced):
            raise ValueError('Missing reduced-motion proof')
        compact=[]
        for row in rows:
            frames, bench = row['frames'], row['benchmark']
            if len(frames)!=3 or [f['progress'] for f in frames] != [.17,.5,.83] or not all(f['changed_pixels']>0 and f['primitives']>0 for f in frames):
                raise ValueError('Missing actual nonblank frame samples')
            if len({f['pixel_fnv32'] for f in frames})<2:
                raise ValueError('A moving recipe needs distinct sampled pixel output')
            duration=bench['p95_ms']
            if type(duration) not in (int,float) or not math.isfinite(duration) or duration<0 or bench['production_fps_verified'] is not False or bench['frames']!=12 or bench['kind']!='synchronous-sampling-and-draw':
                raise ValueError('Invalid scoped benchmark')
            if bench['within_cpu_budget'] is not True or not 0<bench['budget_ms']<=16.67 or duration>bench['budget_ms']:
                raise ValueError('CPU sampling/draw budget failed')
            compact.append({'id':row['id'],'frame_samples':3,
                            'minimum_changed_pixels':min(f['changed_pixels'] for f in frames),
                            'distinct_sampled_frames':len({f['pixel_fnv32'] for f in frames}),
                            'reduced_motion_stable':True,'cpu_p95_ms':duration,
                            'benchmark_frames':12,'cpu_budget_ms':bench['budget_ms']})
        profiles.append({'viewport':profile['viewport'],'direction':profile['direction'],
                         'language':profile['language'],'definitions':compact})
    if {(p['direction'],p['viewport']['width']) for p in profiles}!={('rtl',390),('ltr',1280)}:
        raise ValueError('Expected the tested mobile RTL and desktop LTR profiles')
    return {'schema_version':1,'status':'passed','recorded_at_utc':report['recorded_at_utc'],
            'engine':report['engine'],'browser':report['browser'],
            'playwright_version':report['playwright_version'],
            'source_sha256':report['source_sha256'],'definitions':400,'basic':200,'advanced':200,
            'frame_samples':2400,'reduced_motion_cases':800,'benchmark_draws':9600,
            'production_fps_verified':False,'gpu_runtime_verified':False,
            'scope':'Recorded source-bound Canvas2D reference behavior, desktop and emulated mobile. CPU sampling/draw timings are not presentation FPS or production Web Vitals.',
            'limitations':['No actual quantum simulation, live digital twin, hardware GPU, physical mobile or Safari proof.',
                          '3D/shader/lighting categories are illustrative 2D analytic scenes, not third-party engine integrations.',
                          'Native WebKit launch was blocked by missing host libraries; Firefox was not installed.'],
            'profiles':profiles}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt',type=pathlib.Path)
    parser.add_argument('--output',required=True,type=pathlib.Path)
    args=parser.parse_args()
    raw=args.receipt.read_bytes()
    if len(raw)>8*1024*1024:raise ValueError('Oversized browser receipt')
    result=summarize(read(args.receipt))
    result['raw_receipt_sha256']=hashlib.sha256(raw).hexdigest()
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2,ensure_ascii=False);stream.write('\n')


if __name__=='__main__':main()
