"""Packs ../mod + the built DLL into ../dist/OutlawsHumanButchering_<version>.zip"""
import json, os, zipfile, json5
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
MOD = os.path.join(ROOT, 'mod'); DLL = os.path.join(ROOT, 'src', 'bin', 'OutlawsHumanButchering.dll')
ver = json.load(open(os.path.join(MOD, 'modinfo.json'), encoding='utf-8'))['version']
os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
out = os.path.join(ROOT, 'dist', f'OutlawsHumanButchering_{ver}.zip')
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for r, _, fs in os.walk(MOD):
        for f in fs:
            p = os.path.join(r, f); a = os.path.relpath(p, MOD).replace(os.sep, '/')
            if a.endswith('.json'): json5.load(open(p, encoding='utf-8'))
            z.write(p, a)
    z.write(DLL, 'OutlawsHumanButchering.dll')
    z.write(os.path.join(ROOT, 'LICENSE'), 'LICENSE')
print(out)
