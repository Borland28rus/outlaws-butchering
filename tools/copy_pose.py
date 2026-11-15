"""Copy the bone angles of one hand-tuned hanging model onto the other human hanging models.
Usage: python tools/copy_pose.py [source=looter-hanging.json]
Only rotationX/Y/Z of the skeleton bones change; geometry, clothes, beards and textures stay."""
import json, json5, os, sys, glob
HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(os.path.dirname(HERE), 'mod', 'assets', 'outlawshumanbutchering', 'shapes', 'creatures')
BONES = {'Origin', 'LowerTorso', 'UpperTorso', 'Neck', 'Head', 'UpperArmL', 'LowerArmL', 'UpperArmR', 'LowerArmR',
         'UpperFootL', 'LowerFootL', 'UpperFootR', 'LowerFootR'}
K = ('rotationX', 'rotationY', 'rotationZ')
def walk(els, path, out):
    for e in els or []:
        n = e.get('name'); p = path + '/' + n
        if n in BONES: out[p] = e; walk(e.get('children'), p, out)
src_name = sys.argv[1] if len(sys.argv) > 1 else 'looter-hanging.json'
src = {}; walk(json5.load(open(os.path.join(DIR, src_name), encoding='utf-8'))['elements'], '', src)
assert len(src) == len(BONES), sorted(src)
for f in sorted(glob.glob(os.path.join(DIR, '*-hanging.json'))):
    if os.path.basename(f) == src_name: continue
    shape = json5.load(open(f, encoding='utf-8')); dst = {}; walk(shape['elements'], '', dst)
    assert set(dst) == set(src), (f, set(src) ^ set(dst))
    for p, e in dst.items():
        so = src[p].get('rotationOrigin'); do = e.get('rotationOrigin')
        if so and do and max(abs(a - b) for a, b in zip(so, do)) > 0.01: print('  warn: origin differs', p, so, do)
        for k in K:
            if src[p].get(k): e[k] = src[p][k]
            else: e.pop(k, None)
    with open(f, 'w', encoding='utf-8', newline='\r\n') as out:  # the generated shapes use CRLF
        json.dump(shape, out, ensure_ascii=False, indent=2)
    print('posed', os.path.basename(f))
