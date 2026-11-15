"""Generates the JSON assets of the 'Outlaws x Butchering: humans' mod.

Reads the Outlaws mod zip (entities + shapes) and the vanilla game assets,
writes everything into ../mod/. Shapes in ../mod/assets/.../shapes are only
written when missing, so poses fixed by hand in VSMC are never overwritten
(pass --force-shapes to regenerate them).

Usage: python generate.py [--force-shapes]
"""
import json, math, os, sys, zipfile, copy
import json5
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.normpath(os.path.join(HERE, '..', 'mod'))
sys.path.insert(0, HERE)
import paths  # local game / mod folders, see tools/paths.py
GAME = os.path.join(paths.GAME, 'assets', 'survival')
OUTLAWS_ZIP = os.path.join(paths.MODS, 'OutlawsMod_1.2.8.zip')

D = 'outlawshumanbutchering'          # mod domain / modid
FORCE_SHAPES = '--force-shapes' in sys.argv
FORCE_DEAD = '--force-dead' in sys.argv

# kind code (no hyphens, safe for wildcards) -> Outlaws entity file name
KINDS = {
    'banditaxe': 'bandit-axe', 'banditknife': 'bandit-knife', 'banditspear': 'bandit-spear',
    'deserterarcher': 'deserter-archer', 'deserterbannerman': 'deserter-bannerman',
    'deserterfootman': 'deserter-footman', 'looter': 'looter',
    'poacherarcher': 'poacher-archer', 'poacherspear': 'poacher-spear', 'yeomanarcher': 'yeoman-archer',
}

# Drops on a carcass, taken from the vanilla wolf (meat, fat) + one hide.
HARVEST_DROPS = [
    {'type': 'item', 'code': f'{D}:longpork-raw', 'quantity': {'avg': 7, 'var': 1}},
    {'type': 'item', 'code': 'game:fat', 'quantity': {'avg': 1.25, 'var': 0}},
    {'type': 'item', 'code': 'game:hide-raw-human', 'quantity': {'avg': 1, 'var': 0}},
]
BUTCHERING_REWARDS = [  # same as Butchering's wolf
    {'type': 'item', 'code': 'butchering:sinew-wet', 'quantity': {'avg': 3, 'var': 1}},
    {'type': 'item', 'code': 'butchering:offal-bloody', 'quantity': {'avg': 1.6, 'var': 0.5}},
]
DEPENDS = [{'modid': 'outlawmod122'}, {'modid': 'butchering'}]


def write(rel, data):
    p = os.path.join(MOD, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def gp(path):
    """Prefix a game-domain asset path."""
    return path if ':' in path else 'game:' + path


# ---------------------------------------------------------------- shapes math
def rot(ax, deg):
    r = math.radians(deg or 0); c, s = math.cos(r), math.sin(r)
    if ax == 0: return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if ax == 1: return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def boxes(elements):
    """World-space AABB of every element: list of (name, min, max)."""
    out = []
    def walk(es, M, t):
        for e in es:
            f = np.array(e.get('from', [0, 0, 0]), float); to = np.array(e.get('to', f), float)
            ro = np.array(e.get('rotationOrigin', [0, 0, 0]), float)
            R = rot(0, e.get('rotationX')) @ rot(1, e.get('rotationY')) @ rot(2, e.get('rotationZ'))
            Mn = M @ R; tn = M @ (ro - R @ ro) + t
            pts = np.array([Mn @ np.array([x, y, z]) + tn for x in (f[0], to[0]) for y in (f[1], to[1]) for z in (f[2], to[2])])
            out.append((e['name'], pts.min(0), pts.max(0)))
            walk(e.get('children', []), Mn, Mn @ f + tn)
    walk(elements, np.eye(3), np.zeros(3))
    return out


def bbox(elements, name_filter=None):
    b = [x for x in boxes(elements) if name_filter is None or name_filter(x[0])]
    return np.min([x[1] for x in b], 0), np.max([x[2] for x in b], 0)


def strip_weapons(elements):
    """Weapons/tools are children of the forearms in every Outlaws shape."""
    for e in elements:
        if e['name'] in ('LowerArmR', 'LowerArmL'):
            e['children'] = []
        strip_weapons(e.get('children', []))


def wrap(elements, center, target, rx=0, rz=0):
    """Rotate the whole model around `center` and move `center` onto `target`."""
    kids = copy.deepcopy(elements)
    for e in kids:  # root elements become children of Origin -> relative coords
        for k in ('from', 'to', 'rotationOrigin'):
            if k in e:
                e[k] = [round(a - c, 4) for a, c in zip(e[k], center)]
    t = [round(x, 4) for x in target]
    origin = {'name': 'Origin', 'from': t, 'to': t, 'rotationOrigin': t,
              'faces': {s: {'texture': '#null', 'uv': [0, 0, 0, 0], 'enabled': False}
                        for s in ('north', 'east', 'south', 'west', 'up', 'down')},
              'children': kids}
    if rx: origin['rotationX'] = rx
    if rz: origin['rotationZ'] = rz
    return [origin]


def death_pose(shape):
    """Final pose of the entity's own "die" animation: element name -> keyframe values."""
    anim = next((a for a in shape.get('animations', []) if a.get('code') == 'die'), None)
    pose = {}
    if anim:
        for kf in sorted(anim['keyframes'], key=lambda k: k['frame']):
            for name, v in kf.get('elements', {}).items():
                pose.setdefault(name, {}).update(v)
    return pose


def apply_pose(elements, pose):
    """Bake keyframe rotations/offsets into the static elements (as the game's animator adds them)."""
    for e in elements:
        v = pose.get(e['name'])
        if v:
            for ax in 'XYZ':
                r = (e.get('rotation' + ax) or 0) + (v.get('rotation' + ax) or 0)
                if r: e['rotation' + ax] = round(r, 4)
            off = [v.get('offset' + ax) or 0 for ax in 'XYZ']
            if any(off):
                for k in ('from', 'to', 'rotationOrigin'):
                    if k in e: e[k] = [round(a + o, 4) for a, o in zip(e[k], off)]
        apply_pose(e.get('children', []), pose)


def make_shapes(shape):
    els = copy.deepcopy(shape['elements'])
    strip_weapons(els)
    is_foot = lambda n: 'Foot' in n
    fmin, fmax = bbox(els, is_foot)
    # hanging: upside down, the soles meet at the hook point (like the wolf)
    feet_top = [(fmin[0] + fmax[0]) / 2, fmin[1], (fmin[2] + fmax[2]) / 2]
    hanging = wrap(els, feet_top, [8, 9.8, 8], rz=180)
    # dead: the last frame of the outlaw's own death animation, centred, resting on the ground
    posed = copy.deepcopy(els)
    apply_pose(posed, death_pose(shape))
    mn, mx = bbox(posed)
    # rest the torso on the ground; the head/arm/boot it lies on sinks in a little instead of propping it up
    tmn, _ = bbox(posed, lambda n: n in ('UpperTorso', 'LowerTorso'))
    c = [(mn[0] + mx[0]) / 2, tmn[1], (mn[2] + mx[2]) / 2]
    dead = wrap(posed, c, [8, 0, 8])
    base = {k: shape[k] for k in ('textureWidth', 'textureHeight') if k in shape}
    if 'textureSizes' in shape: base['textureSizes'] = shape['textureSizes']
    base['textures'] = {k: gp(v) for k, v in shape.get('textures', {}).items()}
    return dict(base, elements=dead), dict(base, elements=hanging)


def used_textures(elements, acc=None):
    acc = set() if acc is None else acc
    for e in elements:
        for f in (e.get('faces') or {}).values():
            if isinstance(f, dict) and f.get('texture', '').startswith('#') and f.get('enabled', True) is not False:
                acc.add(f['texture'][1:])
        used_textures(e.get('children', []), acc)
    return acc


# ---------------------------------------------------------------- main parts
def load_outlaws():
    z = zipfile.ZipFile(OUTLAWS_ZIP)
    rd = lambda p: json5.loads(z.read(p).decode('utf-8-sig'))
    data = {}
    for kind, ent in KINDS.items():
        e = rd(f'assets/game/entities/mobs/{ent}.json')
        shp = e['client']['shape']['base']
        shape = rd(f'assets/game/shapes/{shp}.json')
        beh = e['server']['behaviors']
        assert beh[6]['code'] == 'harvestable', (ent, beh[6]['code'])
        head = beh[6]['drops'][0]['code']
        assert 'outlawhead' in head, (ent, head)
        data[kind] = dict(entity=ent, shape=shape, etex=e['client'].get('textures') or {}, head=gp(head))
    return data


def carcass_item(data):
    kinds = list(KINDS)
    tex_by_type, attr_by_type, shape_by_type, allowed = {}, {}, {}, []
    all_keys = set()
    for kind, d in data.items():
        dead, _ = make_shapes(d['shape'])
        keys = used_textures(dead['elements'])
        all_keys |= keys
        shape_tex = {k: gp(v) for k, v in d['shape'].get('textures', {}).items()}
        variants = {k: [v['base']] + [a['base'] for a in v.get('alternates', [])] for k, v in d['etex'].items()}
        n = max([len(v) for v in variants.values()] + [1])
        allowed.append(f'deadoutlaw-{kind}-*' if n == 4 else f'deadoutlaw-{kind}-1-*')
        assert n in (1, 4), (kind, n)
        for i in range(1, n + 1):
            m = {}
            for k in sorted(keys):
                if k in variants:
                    m[k] = {'base': gp(variants[k][(i - 1) % len(variants[k])])}
                elif k in shape_tex:
                    m[k] = {'base': shape_tex[k]}
            tex_by_type[f'deadoutlaw-{kind}-{i}-dead'] = m
        attr_by_type[f'deadoutlaw-{kind}-*'] = {
            'size': 0.5, 'mass': 0.03,
            'bloodType': 'butchering:bloodportion', 'bloodAmount': 100,
            'butcheringWorkLoad': 'medium',
            'handbookByType': {'*-rotten': {'exclude': False}, '*': {'exclude': True}},
            'excludeRewards': [], 'skinningRewards': [],
            'butcheringRewards': BUTCHERING_REWARDS,
            'hangingShape': {'base': f'{D}:creatures/{kind}-hanging'},
            'guaranteedHead': d['head'],
            'fallbackAnimalDrops': HARVEST_DROPS,
            'fallbackAnimalCarcass': 'game:carcass-human',
        }
        shape_by_type[f'deadoutlaw-{kind}-*'] = {'base': f'creatures/{kind}-dead'}
    for state, tex in (('skinned', 'butchering:item/butchercreatures/animalbushmeatbloody'),
                       ('bledout', 'butchering:item/butchercreatures/animalbushmeatbledout'),
                       ('rotten', 'game:block/creature/rot/rot')):
        tex_by_type[f'deadoutlaw-*-{state}'] = {k: {'base': tex} for k in sorted(all_keys)}
    return {
        'code': 'deadoutlaw', 'class': 'butcherable',
        'variantgroups': [
            {'code': 'kind', 'states': kinds},
            {'code': 'texture', 'states': ['1', '2', '3', '4']},
            {'code': 'state', 'states': ['dead', 'skinned', 'bledout', 'rotten']},
        ],
        'allowedVariants': allowed,
        'skipVariants': ['@deadoutlaw-.*-([2-9])-(skinned|bledout|rotten)'],
        'maxstacksize': 1,
        # same as Butchering's adult wolf: back slot only (2) + Butchering's carcass flag (32768); counts for its slowdown
        'storageFlagsByType': {'*-rotten': 1, '*': 32770},
        'behaviors': [{'name': 'GroundStorable', 'properties': {'layout': 'SingleCenter',
                       'collisionBox': {'x1': 0.1, 'y1': 0, 'z1': 0.1, 'x2': 0.9, 'y2': 0.5, 'z2': 0.9}}}],
        'texturesByType': tex_by_type,
        'attributesByType': attr_by_type,
        'shapeByType': shape_by_type,
        'transitionablePropsByType': {
            '*-rotten': [],
            '*': [{'type': 'perish', 'freshHours': {'avg': 80}, 'transitionHours': {'avg': 24},
                   'transitionedStack': {'type': 'item', 'code': f'{D}:deadoutlaw-{{kind}}-1-rotten'},
                   'transitionRatio': 1}],
        },
        'creativeinventory': {'general': ['*'], 'items': ['*']},
        'heldTpIdleAnimation': 'holdunderarm',
        'guiTransform': {'translation': {'x': 0, 'y': 0, 'z': 0}, 'rotation': {'x': -20, 'y': 21, 'z': 180},
                         'origin': {'x': 0.5, 'y': 0.3, 'z': 0.5}, 'scale': 0.7, 'rotate': True},
        'fpHandTransform': {'translation': {'x': 0, 'y': 0, 'z': 0}, 'rotation': {'x': -132, 'y': -180, 'z': -18}, 'scale': 0.8},
        'tpHandTransform': {'translation': {'x': -0.5, 'y': -0.3, 'z': -0.7}, 'rotation': {'x': -89, 'y': -12, 'z': 3}, 'scale': 0.7},
        'groundTransform': {'translation': {'x': 0, 'y': 0, 'z': 0}, 'rotation': {'x': 0, 'y': 0, 'z': 0},
                            'origin': {'x': 0.5, 'y': 0, 'z': 0.5}, 'scale': 1},
    }


def shapes(data):
    for kind, d in data.items():
        dead, hanging = make_shapes(d['shape'])
        for suffix, s in (('dead', dead), ('hanging', hanging)):
            rel = f'assets/{D}/shapes/creatures/{kind}-{suffix}.json'
            if FORCE_SHAPES or (suffix == 'dead' and FORCE_DEAD) or not os.path.exists(os.path.join(MOD, rel)):
                write(rel, s)


def entity_patches(data):
    out = []
    for kind, d in data.items():
        f = f'game:entities/mobs/{d["entity"]}.json'
        item = f'{D}:deadoutlaw-{kind}-1-dead'
        out += [
            {'op': 'replace', 'path': '/server/behaviors/6/drops', 'value': HARVEST_DROPS, 'file': f, 'dependsOn': DEPENDS},
            {'op': 'add', 'path': '/server/behaviors/-', 'value': {'code': 'butcherable', 'item': item}, 'file': f, 'dependsOn': DEPENDS},
            {'op': 'add', 'path': '/client/behaviors/-', 'value': {'code': 'butcherable', 'item': item}, 'file': f, 'dependsOn': DEPENDS},
            {'op': 'add', 'path': '/server/behaviors/-', 'value': {'code': f'{D}.guaranteedhead', 'head': d['head']}, 'file': f, 'dependsOn': DEPENDS},
        ]
    write(f'assets/{D}/patches/outlaws.json', out)


def longpork():
    s = json5.load(open(os.path.join(GAME, 'itemtypes', 'food', 'bushmeat.json'), encoding='utf-8'))
    s['code'] = 'longpork'
    a = s['attributes']
    a['inContainerTextureByType'] = {k: {'base': gp(v['base'])} for k, v in a['inContainerTextureByType'].items()}
    a['nutritionPropsWhenInMeal'] = {'satiety': 300, 'foodcategory': 'Protein'}
    a['handbook'] = {'extraSections': [{'title': 'handbook-item-sources', 'text': f'{D}:handbook-longpork-source'}]}
    a['inPiePropertiesByType'] = {'*-raw': {'texture': 'game:block/food/pie/fill-redmeat', 'partType': 'Filling', 'mixingCodes': ['potpie']}}
    s['shape'] = {'base': 'game:item/food/meat/bushmeat'}
    s['textures'] = {'meat': {'base': 'game:item/food/meat/{type}'}}
    s['nutritionPropsByType'] = {'*-cooked': {'satiety': 200, 'foodcategory': 'Protein'},
                                 '*-cured': {'satiety': 145, 'foodcategory': 'Protein'}}
    cp = s.pop('combustiblePropsByType')['bushmeat-raw']
    cp['smeltedStack'] = {'type': 'item', 'code': f'{D}:longpork-cooked'}
    s['combustiblePropsByType'] = {'longpork-raw': cp}
    for lst in s['transitionablePropsByType'].values():
        for t in lst:
            t['transitionedStack']['code'] = 'game:rot'
    write(f'assets/{D}/itemtypes/food/longpork.json', s)
    write(f'assets/{D}/recipes/barrel/curedlongpork.json', {
        'code': 'curedlongpork', 'sealHours': 480,
        'ingredients': [{'type': 'item', 'code': 'game:salt', 'quantity': 2},
                        {'type': 'item', 'code': f'{D}:longpork-raw', 'quantity': 1}],
        'output': {'type': 'item', 'code': f'{D}:longpork-cured', 'stackSize': 1}})
    # stews and soups: same slots as red meat
    stew = json5.load(open(os.path.join(GAME, 'recipes', 'cooking', 'meatystew.json'), encoding='utf-8'))
    soup = json5.load(open(os.path.join(GAME, 'recipes', 'cooking', 'soup.json'), encoding='utf-8'))
    patches = []
    for fname, recipe, idx, slot in (('meatystew', stew, 0, 'protein-base'), ('meatystew', stew, 3, 'meat-extra'),
                                     ('meatystew', stew, 4, 'meat-extra2'), ('soup', soup, 4, 'protein-extra')):
        ing = recipe['ingredients'][idx]
        assert ing['code'] == slot, (fname, idx, ing['code'])
        red = next(v for v in ing['validStacks'] if v['code'] == 'redmeat-raw')
        vals = [dict(red, code=f'{D}:longpork-{t}') for t in ('raw', 'cured')]
        patches.append({'op': 'addeach', 'path': f'/ingredients/{idx}/validStacks/-', 'value': vals,
                        'file': f'game:recipes/cooking/{fname}.json', 'side': 'Server'})
    write(f'assets/{D}/patches/cooking.json', patches)


def human_hide():
    """game:hide-<type>-human, built like vanilla's fox/raccoon species hides:
    its own item until soaking, scraping turns it into a normal medium hide."""
    h = json5.load(open(os.path.join(GAME, 'itemtypes', 'resource', 'hide.json'), encoding='utf-8'))
    tex = h['texturesByType']
    soaked = copy.deepcopy(h['behaviorsByType']['*-soaked-*'])
    soaked[0]['properties']['remainingItem']['code'] = 'hide-scraped-medium'
    item = {
        'code': 'hide',
        'variantgroups': [{'code': 'type', 'states': ['raw', 'oiled', 'pelt', 'soaked', 'salted']},
                          {'code': 'species', 'states': ['human']}],
        'tags': ['size-medium', 'color-brown'],
        'behaviors': copy.deepcopy(h['behaviors']),
        'behaviorsByType': {'*-soaked-*': soaked},
        'attributes': {'inContainerTextureByType': {f'hide-{t}-*': h['attributes']['inContainerTextureByType'][f'hide-{t}-*']
                                                    for t in ('raw', 'oiled', 'pelt', 'soaked', 'salted')}},
        'shape': {'base': 'item/resource/hide/medium1'},
        'texturesByType': {f'hide-{t}-*': tex[f'hide-{t}-*'] for t in ('raw', 'oiled', 'pelt', 'soaked', 'salted')},
        'creativeinventory': {'general': ['*'], 'items': ['*']},
        'materialDensity': 620,
        'maxstacksize': 32,
        'transitionablePropsByType': {
            'hide-oiled-*': [{'type': 'Cure', 'freshHours': {'avg': 0}, 'transitionHours': {'avg': 48},
                              'transitionedStack': {'type': 'item', 'code': 'hide-pelt-human'}, 'transitionRatio': 1}],
            'hide-raw-*': [{'type': 'Perish', 'freshHours': {'avg': 120}, 'transitionHours': {'avg': 24},
                            'transitionedStack': {'type': 'item', 'code': 'rot'}, 'transitionRatio': 2}],
            'hide-salted-*': [{'type': 'Perish', 'freshHours': {'avg': 2000}, 'transitionHours': {'avg': 592},
                               'transitionedStack': {'type': 'item', 'code': 'rot'}, 'transitionRatio': 2}],
        },
        'guiTransform': h['guiTransformByType']['*-medium'],
        'tpHandTransform': h['tpHandTransformbyType']['*-medium'],
        'groundTransform': h['groundTransformByType']['*-medium'],
    }
    # lives in the game domain so the vanilla wildcard recipes ("hide-raw-*") accept it
    write('assets/game/itemtypes/resource/hide-human.json', item)


def lang():
    ru, en = {}, {}
    who = {'bandit': ('бандита', 'brigand'), 'deserter': ('дезертира', 'deserter'), 'looter': ('мародёра', 'looter'),
           'poacher': ('браконьера', 'poacher'), 'yeoman': ('йомена', 'yeoman')}
    for kind in KINDS:
        r, e = next(v for k, v in who.items() if kind.startswith(k))
        for st, rs, es in (('dead', 'Тело', 'body'), ('skinned', 'Освежёванное тело', 'skinned body'),
                           ('bledout', 'Обескровленное тело', 'bled out body'), ('rotten', 'Гниющее тело', 'rotting body')):
            ru[f'item-deadoutlaw-{kind}-*-{st}'] = f'{rs} {r}'
            en[f'item-deadoutlaw-{kind}-*-{st}'] = f'{e.capitalize()} {es}' if st == 'dead' else f'{es.capitalize()} of a {e}'
    ru.update({
        'item-longpork-raw': 'Сырая человечина',
        'item-longpork-cooked': 'Жареная человечина',
        'item-longpork-cured': 'Вяленая человечина',
        'itemdesc-longpork-raw': 'Мясо ваших врагов. На островах южных морей его называли «длинной свининой».',
        'itemdesc-longpork-cooked': 'Вы же не собираетесь это есть?',
        'itemdesc-longpork-cured': 'Честно говоря, отвратительно.',
        'handbook-longpork-source': 'Добывается при разделке тел разбойников.',
        'game:item-hide-raw-human': 'Необработанная человеческая кожа',
        'game:item-hide-soaked-human': 'Вымоченная человеческая кожа',
        'game:item-hide-salted-human': 'Засоленная человеческая кожа',
        'game:item-hide-oiled-human': 'Намасленная человеческая кожа',
        'game:item-hide-pelt-human': 'Жированная человеческая кожа',
    })
    en.update({
        'item-longpork-raw': 'Raw "long pork"',
        'item-longpork-cooked': 'Cooked "long pork"',
        'item-longpork-cured': 'Cured "long pork"',
        'itemdesc-longpork-raw': 'The flesh of your enemies.',
        'itemdesc-longpork-cooked': "Wait, you're not going to eat that, right?",
        'itemdesc-longpork-cured': "That's honestly disgusting.",
        'handbook-longpork-source': 'Obtained by butchering the bodies of outlaws.',
        'game:item-hide-raw-human': 'Raw human skin',
        'game:item-hide-soaked-human': 'Soaked human skin',
        'game:item-hide-salted-human': 'Salted human skin',
        'game:item-hide-oiled-human': 'Oiled human skin',
        'game:item-hide-pelt-human': 'Greased human skin',
    })
    names = {'ru': ('человечина', 'человечиной', 'С человечиной', 'с человечиной', 'Пирог с человечиной'),
             'en': ('long pork', 'long pork', '"Long pork"', '"long pork"', '"Long pork" pie')}
    for code, L in (('ru', ru), ('en', en)):
        ing, instr, prim, sec, pie = names[code]
        for t in ('raw', 'cured'):
            for pre in ('game:', ''):
                L[f'{pre}recipeingredient-item-longpork-{t}'] = ing
                L[f'{pre}recipeingredient-item-longpork-{t}-insturmentalcase'] = instr
                for meal in ('soup', 'stew'):
                    L[f'{pre}meal-ingredient-{meal}-primary-longpork-{t}'] = prim
                    L[f'{pre}meal-ingredient-{meal}-secondary-longpork-{t}'] = sec
        suff = {'ru': {'raw': ' (сырой)', 'partbaked': ' (недопечённый)', 'perfect': '', 'charred': ' (обугленный)'},
                'en': {'raw': ' (raw)', 'partbaked': ' (part-baked)', 'perfect': '', 'charred': ' (charred)'}}[code]
        for st, sfx in suff.items():
            L[f'game:pie-single-{D}:longpork-raw-{st}'] = pie + sfx
            L[f'game:pie-single-longpork-raw-{st}'] = pie + sfx
        write(f'assets/{D}/lang/{code}.json', L)


def main():
    data = load_outlaws()
    write(f'assets/{D}/itemtypes/creatures/deadoutlaw.json', carcass_item(data))
    shapes(data)
    entity_patches(data)
    longpork()
    human_hide()
    lang()
    print('generated into', MOD)
    for kind, d in data.items():
        print(f'  {kind:18} head={d["head"]}')


if __name__ == '__main__':
    main()
