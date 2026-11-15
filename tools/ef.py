"""
Expanded Foods compatibility for Outlaws x Butchering - humans.

Long pork is treated exactly like bushmeat everywhere in Expanded Foods and its add-ons:
  * long pork itself gets EF's extra states/baking/aging (mirrors EF's patch of vanilla bushmeat);
  * EF meat products (meat nuggets, aged meat, breaded meat, sausages, sauced meats, sausage dogs)
    get a "longpork" meat variant (and "longporkcheese" for sausages);
  * every recipe that makes a bushmeat product gets a long pork twin, every ingredient list that
    accepts bushmeat (stews, soups, meals, mixing) also accepts the long pork equivalent;
  * names: "... дичи" -> "... человечины", "bushmeat" -> "\"long pork\"".

Nutrition of long pork variants is the average of the bushmeat and red meat values, the same rule
as the base mod (long pork sits between bushmeat and red meat).

Output: ../mod/assets/outlawshumanbutcheringef/ and ../mod/assets/sandwich/ inside the main mod
(since 2026-11-15 there is no separate EF add-on). Expanded Foods is optional: every patch gets
dependsOn expandedfoods (plus Sauce-a-lot / Sammiches / EF: Meals where needed), the recipe files
are empty lists filled by those patches, so without EF nothing of this applies.

Usage: python ef.py
"""
import copy, io, json, os, re, shutil, sys, zipfile
from collections import OrderedDict

import json5

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'mod')
sys.path.insert(0, HERE)
import paths  # local game / mod folders, see tools/paths.py
GAME = paths.GAME
BASE = 'outlawshumanbutchering'
D = 'outlawshumanbutcheringef'
VERSION = '1.0.0'

SOURCES = OrderedDict([  # modid -> (zip, domain)
    ('expandedfoods', ('ExpandedFoods_2.0.0-dev.17.zip', 'expandedfoods')),
    ('efmealsmodule', ('ExpandedFoods_MealsModule_1.0.0-dev.9.zip', 'efmealsmodule')),
    ('saucealot', ('Saucealot_2.3.4.zip', 'saucealot')),
    ('sandwich', ('Sammiches_v1.3.1.zip', 'sandwich')),
])
# mods we never target (not part of this compat): their sub-folders/patches are skipped
SKIP_PARTS = ('/acorns/', '/ancienttools/', '/primitivesurvival/', '/alchemy/')

# item families that get a long pork variant: (domain, code) -> (owning modid, item file in that mod)
FAMILIES = OrderedDict([
    (('expandedfoods', 'meatnugget'), ('expandedfoods', 'assets/expandedfoods/itemtypes/food/meatnugget.json')),
    (('expandedfoods', 'agedmeat'), ('expandedfoods', 'assets/expandedfoods/itemtypes/food/agedmeat.json')),
    (('expandedfoods', 'breadedmeatnugget'), ('expandedfoods', 'assets/expandedfoods/itemtypes/food/mixing/breadedmeatnugget.json')),
    (('expandedfoods', 'sausage'), ('expandedfoods', 'assets/expandedfoods/itemtypes/food/mixing/sausage.json')),
    (('saucealot', 'bbqmeat'), ('saucealot', 'assets/saucealot/itemtypes/food/bbqmeat.json')),
    (('saucealot', 'coloneltsomeat'), ('saucealot', 'assets/saucealot/itemtypes/food/coloneltsomeat.json')),
    (('saucealot', 'winereductionmeat'), ('saucealot', 'assets/saucealot/itemtypes/food/winereductionmeat.json')),
    (('sandwich', 'sausagedog'), ('sandwich', 'assets/sandwich/itemtypes/sandwich/sausagedog.json')),
])
LONGPORK_STATES = {'raw', 'partbaked', 'cooked', 'cured', 'charred'}  # after EF's patch
# long pork = between bushmeat and red meat; fallback ratio when no red meat value exists
SATIETY_RATIO = 300 / 180

warnings = []


def warn(msg):
    warnings.append(msg)


# ---------------------------------------------------------------- io
zips = {m: zipfile.ZipFile(os.path.join(paths.MODS, z)) for m, (z, _) in SOURCES.items()}


def rd(mod, path):
    return json5.loads(zips[mod].read(path).decode('utf-8-sig'))


def write(rel, data):
    p = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with io.open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def asset_bytes(domain, rel):
    """rel like 'shapes/item/food/x.json'. Looks in the source mods, then the game."""
    for m, (_, dom) in SOURCES.items():
        n = f'assets/{domain}/{rel}'
        if n in zips[m].namelist():
            return zips[m].read(n)
    for sub in ('survival', 'creative', 'game'):
        p = os.path.join(GAME, 'assets', sub, rel.replace('/', os.sep))
        if domain == 'game' and os.path.exists(p):
            return open(p, 'rb').read()
    return None


# ---------------------------------------------------------------- code mapping
def split_code(code, ctx):
    if ':' in code:
        d, p = code.split(':', 1)
        return d, p
    return ctx, code


def family_of(domain, path):
    return domain, path.split('-', 1)[0]


def map_code(code, ctx):
    """bushmeat code -> long pork code (full, with domain), or None when not supported/not bushmeat."""
    if not isinstance(code, str) or 'bushmeat' not in code:
        return None
    d, p = split_code(code, ctx)
    if d == 'game' and p.startswith('bushmeat-'):
        state = p[len('bushmeat-'):]
        if state != '*' and state not in LONGPORK_STATES:
            return None
        return f'{BASE}:longpork-{state}'
    if family_of(d, p) in FAMILIES and 'bushmeat' in p:
        return f'{d}:{p.replace("bushmeat", "longpork")}'
    return None


def is_supported_bush(code, ctx):
    return map_code(code, ctx) is not None


def map_stack(st, ctx):
    """Item stack dict -> long pork twin, or None."""
    if not isinstance(st, dict) or 'code' not in st:
        return None
    c = map_code(st['code'], ctx)
    if c is None:
        return None
    t = copy.deepcopy(st)
    t['code'] = c
    if isinstance(t.get('name'), str) and 'bushmeat' in t['name']:
        t['name'] = t['name'].replace('bushmeat', 'longpork')
    return t


def mentions_bush(x):
    return 'bushmeat' in json.dumps(x)


# ---------------------------------------------------------------- satiety
def blend_satiety(bush_val, red_val):
    if isinstance(bush_val, dict) and isinstance(red_val, dict):
        out = copy.deepcopy(bush_val)
        for k, v in bush_val.items():
            if k.lower() == 'satiety' and isinstance(v, (int, float)) and isinstance(red_val.get(k), (int, float)):
                out[k] = round((v + red_val[k]) / 2)
            elif isinstance(v, dict) and isinstance(red_val.get(k), dict):
                out[k] = blend_satiety(v, red_val[k])
            else:
                out[k] = scale_satiety(v)
        return out
    return scale_satiety(bush_val)


def scale_satiety(v):
    if isinstance(v, dict):
        return {k: (round(x * SATIETY_RATIO) if k.lower() == 'satiety' and isinstance(x, (int, float)) else scale_satiety(x))
                for k, x in v.items()}
    if isinstance(v, list):
        return [scale_satiety(x) for x in v]
    return v


# ---------------------------------------------------------------- item values
KEEP_KEYS = ('mixingcodes', 'texture', 'base', 'textures', 'texturesbytype', 'shape', 'shapebytype',
             'shapeelement', 'texturemapping', 'overlays', 'alternates')


def map_value(v, ctx, key=''):
    """Twin of a bushmeat value inside an item definition: codes to long pork, assets kept."""
    if key.lower() in KEEP_KEYS:
        return copy.deepcopy(v)
    if isinstance(v, dict):
        return OrderedDict((k, map_value(x, ctx, k)) for k, x in v.items())
    if isinstance(v, list):
        return [map_value(x, ctx, key) for x in v]
    if isinstance(v, str) and 'bushmeat' in v:
        if key in ('code', 'resultCode', 'initialCode') or re.match(r'^[\w-]+:[\w*{}-]+$|^[\w*{}-]+$', v):
            m = map_code(v, ctx)
            if m:
                return m
            if '{' in v:  # e.g. "saucealot:bbqmeat-{meat}-x" never contains bushmeat; keep
                return v
            warn(f'unmapped code in item value: {v} (ctx {ctx})')
        return v
    return v


def twin_key(k):
    return k.replace('bushmeat', 'longpork')


def transform_bytype(d, ctx):
    """Rebuild a *ByType map with long pork keys right before their bushmeat originals."""
    out = OrderedDict()
    changed = False
    for k, v in d.items():
        if 'bushmeat' in k:
            red = d.get(k.replace('bushmeat', 'redmeat'))
            tv = map_value(v, ctx)
            tv = blend_satiety(tv, red) if red is not None else scale_satiety(tv) if is_nutrition(v) else tv
            out[twin_key(k)] = tv
            changed = True
        out[k] = v
    return out, changed


def is_nutrition(v):
    return 'satiety' in json.dumps(v).lower()


def item_patches(mod, path, depends):
    """Patches adding the long pork variant to an item type of another mod."""
    dom = SOURCES[mod][1]
    it = rd(mod, path)
    file = f'{dom}:{path.split("/", 2)[2]}'
    ops = []

    def op(o, p, value=None):
        x = OrderedDict([('op', o), ('path', p)])
        if value is not None:
            x['value'] = value
        x['file'] = file
        if depends:
            x['dependsOn'] = [{'modid': m} for m in depends]
        ops.append(x)

    for i, g in enumerate(it.get('variantgroups', [])):
        st = g.get('states', [])
        for s in list(st):
            if 'bushmeat' in s:
                op('add', f'/variantgroups/{i}/states/-', s.replace('bushmeat', 'longpork'))
    for key in ('allowedVariants', 'skipVariants'):
        if key in it:
            for i, s in enumerate(list(it[key])):
                if 'bushmeat' in s:
                    op('add', f'/{key}/-', s.replace('bushmeat', 'longpork'))

    def walk(node, ptr):
        if isinstance(node, dict):
            for k, v in node.items():
                p = f'{ptr}/{k.replace("~", "~0").replace("/", "~1")}'
                if k.lower().endswith('bytype') and isinstance(v, dict):
                    nv, changed = transform_bytype(v, dom)
                    if changed:
                        op('replace', p, nv)
                    # values inside may contain nested ByType maps too (rare); not needed for these items
                else:
                    walk(v, p)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f'{ptr}/{i}')

    walk(it, '')
    asset_refs(it, op, ops, file)
    return ops


def vs_match(key, code):
    """Vintage Story's ByType key match (WildcardUtil): '@' = regex, otherwise '*' wildcards."""
    if key.startswith('@'):
        rx = key[1:]
        if rx.startswith('*'):  # EF writes "@*-(raw|cured)" and means "anything ending in -raw/-cured"
            rx = '.' + rx
        return re.fullmatch(rx, code) is not None
    return re.fullmatch('.*'.join(re.escape(p) for p in key.split('*')), code) is not None


def lp_codes(it):
    """All long pork variant codes of an item type, with their state per variant group."""
    groups = it.get('variantgroups', [])
    if any('states' not in g for g in groups):
        return None
    combos = [[]]
    for g in groups:
        st = [s.replace('bushmeat', 'longpork') for s in g['states']]
        if any('bushmeat' in s for s in g['states']):
            st = [s for s in st if 'longpork' in s]
        combos = [c + [(g['code'], s)] for c in combos for s in st]
    return [('-'.join([it['code']] + [s for _, s in c]), dict(c)) for c in combos]


def asset_refs(it, op, ops, file):
    """
    Shapes and textures named after the meat variant ("item/food/meat/{meat}-smash") would need
    long pork copies of other mods' files. Instead, give every long pork variant an exact key in the
    shape/texture ByType map that points at the bushmeat file, so nothing is copied.
    """
    groups = {g['code'] for g in it.get('variantgroups', []) if any('bushmeat' in s for s in g.get('states', []))}
    codes = lp_codes(it)
    for key in list(it.keys()):
        if key.lower() in ('shape', 'texture', 'textures') and mentions_placeholder(it[key], groups):
            warn(f'{file}: plain "{key}" uses the meat variant; long pork would need a copied asset')
        if key.lower() not in ('shapebytype', 'texturesbytype', 'texturebytype'):
            continue
        # start from the map as our earlier patch (if any) left it
        cur = it[key]
        for o in ops:
            if o['op'] == 'replace' and o['path'].lower() == '/' + key.lower():
                cur = o['value']
        if codes is None or not any(mentions_placeholder(v, groups) for v in cur.values()):
            continue
        exact = OrderedDict()
        for code, states in codes:
            hit = next((k for k in cur if vs_match(k, code)), None)
            if hit is None or not mentions_placeholder(cur[hit], groups):
                continue
            exact[code] = resolve(copy.deepcopy(cur[hit]), groups, states)
        if not exact:
            continue
        new = OrderedDict(list(exact.items()) + [(k, v) for k, v in cur.items() if k not in exact])
        ops[:] = [o for o in ops if not (o['op'] == 'replace' and o['path'].lower() == '/' + key.lower())]
        op('replace', '/' + key, new)


def mentions_placeholder(v, groups):
    s = json.dumps(v)
    return any('{' + g + '}' in s for g in groups)


def resolve(v, groups, states):
    """Fill {group} placeholders: the meat group gets the bushmeat state, other groups their own state."""
    if isinstance(v, dict):
        return OrderedDict((k, resolve(x, groups, states)) for k, x in v.items())
    if isinstance(v, list):
        return [resolve(x, groups, states) for x in v]
    if isinstance(v, str):
        for g, s in states.items():
            v = v.replace('{' + g + '}', s.replace('longpork', 'bushmeat') if g in groups else s)
    return v


# ---------------------------------------------------------------- long pork itself (mirror EF's bushmeat patch)
def longpork_patches():
    bush = rd('expandedfoods', 'assets/game/patches/bushmeat.json')
    red = rd('expandedfoods', 'assets/game/patches/redmeat.json')
    red_by_path = {o['path'].replace('redmeat', 'X'): o for o in red}
    ops = []
    for o in bush:
        if any(x.get('modid') for x in o.get('dependsOn', []) if x.get('modid') not in SOURCES):
            continue
        n = OrderedDict()
        n['op'] = o['op']
        n['path'] = o['path'].replace('bushmeat', 'longpork')
        if 'value' in o:
            v = lp_value(o['value'])
            r = red_by_path.get(o['path'].replace('bushmeat', 'X'))
            if r is not None and is_nutrition(o['value']):
                v = blend_satiety(v, r.get('value'))
            elif is_nutrition(o['value']):
                v = scale_satiety(v)
            n['value'] = v
        n['file'] = f'{BASE}:itemtypes/food/longpork.json'
        ops.append(n)
    return ops


def lp_value(v, key=''):
    if key.lower() in ('mixingcodes', 'texture'):
        return copy.deepcopy(v)
    if isinstance(v, dict):
        return OrderedDict((k, lp_value(x, k)) for k, x in v.items())
    if isinstance(v, list):
        return [lp_value(x, key) for x in v]
    if isinstance(v, str) and key == 'code' and 'bushmeat' not in v and ':' not in v:
        return 'game:' + v  # e.g. rot: EF's patch targets a game file, ours a file in our domain
    if isinstance(v, str) and 'bushmeat' in v:
        if key in ('groupBy',) or v.startswith('bushmeat-*'):
            return v.replace('bushmeat', 'longpork')
        m = map_code(v, 'game')
        if m:
            return m
        warn(f'longpork patch: unmapped {v}')
    return v


# ---------------------------------------------------------------- recipes
def recipe_files(mod):
    dom = SOURCES[mod][1]
    for n in zips[mod].namelist():
        if n.startswith(f'assets/{dom}/recipes/') and n.endswith('.json') and not any(s in n for s in SKIP_PARTS):
            yield n


def recipe_type(n, dom):
    return n[len(f'assets/{dom}/recipes/'):].split('/')[0]


def output_mentions_bush(r):
    keys = ('output', 'Output', 'Simmering', 'simmering', 'smeltedStack')
    return any(mentions_bush(r[k]) for k in keys if k in r)


def ingredient_lists(r):
    """Yield (pointer, list) for every list of alternative stacks in a recipe."""
    ings = r.get('ingredients', r.get('Ingredients'))
    key = 'ingredients' if 'ingredients' in r else 'Ingredients'
    if isinstance(ings, list):
        for i, ing in enumerate(ings):
            if isinstance(ing, dict):
                for lk in ('inputs', 'validStacks'):
                    if isinstance(ing.get(lk), list):
                        yield f'/{key}/{i}/{lk}', ing[lk]


def single_stacks(r):
    """Yield (container, key) for single-stack ingredient slots."""
    ings = r.get('ingredients', r.get('Ingredients'))
    if isinstance(ings, dict):  # grid
        for k, v in ings.items():
            yield ings, k
    elif isinstance(ings, list):
        for i, v in enumerate(ings):
            if isinstance(v, dict) and 'code' in v:  # simmering / barrel style
                yield ings, i


def twin_recipe(r, ctx):
    """Full long pork copy of a recipe, or None if something can't be mapped."""
    t = copy.deepcopy(r)
    ok = [True]

    for ptr, lst in ingredient_lists(t):
        if any(isinstance(s, dict) and 'bushmeat' in str(s.get('code', '')) for s in lst):
            new = [map_stack(s, ctx) for s in lst if isinstance(s, dict) and 'bushmeat' in str(s.get('code', ''))]
            new = [s for s in new if s]
            if not new:
                return None
            lst[:] = new
    for cont, k in single_stacks(t):
        s = cont[k]
        if isinstance(s, dict) and 'bushmeat' in str(s.get('code', '')):
            m = map_stack(s, ctx)
            if m is None:
                return None
            cont[k] = m

    def fix_out(o):
        if isinstance(o, dict):
            for k, v in list(o.items()):
                if k == 'code' and isinstance(v, str) and 'bushmeat' in v:
                    m = map_code(v, ctx)
                    if m is None:
                        ok[0] = False
                    else:
                        o[k] = m
                else:
                    fix_out(v)
        elif isinstance(o, list):
            for v in o:
                fix_out(v)

    for k in ('output', 'Output', 'Simmering', 'simmering'):
        if k in t:
            fix_out(t[k])
    for k in ('name', 'code'):
        if isinstance(t.get(k), str):
            t[k] = t[k].replace('bushmeat', 'longpork') if 'bushmeat' in t[k] else t[k] + '-longpork'
    if not ok[0] or 'bushmeat' in json.dumps({k: v for k, v in t.items() if k not in ('ingredients', 'Ingredients')}):
        if not ok[0]:
            return None
    # anything left that still says bushmeat is an unsupported code
    leftovers = re.findall(r'"code":\s*"([^"]*bushmeat[^"]*)"', json.dumps(t))
    if leftovers:
        warn(f'twin recipe still has bushmeat codes: {leftovers[:3]}')
        return None
    return t


def recipes():
    dup = OrderedDict()   # (type, mod) -> [recipes]
    patches = []
    stats = OrderedDict()
    for mod in SOURCES:
        dom = SOURCES[mod][1]
        for n in recipe_files(mod):
            raw = zips[mod].read(n).decode('utf-8-sig', 'ignore')
            if 'bushmeat' not in raw:
                continue
            data = json5.loads(raw)
            is_arr = isinstance(data, list)
            rlist = data if is_arr else [data]
            rtype = recipe_type(n, dom)
            file = f'{dom}:{n.split("/", 2)[2]}'
            for ri, r in enumerate(rlist):
                if not mentions_bush(r):
                    continue
                pre = f'/{ri}' if is_arr else ''
                lists = [(p, l) for p, l in ingredient_lists(r)
                         if any(isinstance(s, dict) and is_supported_bush(s.get('code'), dom) for s in l)]
                single = [1 for c, k in single_stacks(r)
                          if isinstance(c[k], dict) and 'bushmeat' in str(c[k].get('code', ''))]
                if not output_mentions_bush(r) and lists and not single:
                    # generic output, bushmeat is one of many choices: add long pork choices
                    for p, l in lists:
                        have = {json.dumps(s, sort_keys=True) for s in l}
                        vals = []
                        for s in l:
                            m = map_stack(s, dom)
                            if m and json.dumps(m, sort_keys=True) not in have:
                                vals.append(m)
                        if vals:
                            patches.append(OrderedDict([('op', 'addeach'), ('path', pre + p + '/-'), ('value', vals),
                                                        ('file', file), ('side', 'server'),
                                                        ('dependsOn', [{'modid': mod}])]))
                    stats[rtype + ' (patched lists)'] = stats.get(rtype + ' (patched lists)', 0) + 1
                else:
                    t = twin_recipe(r, dom)
                    if t is None:
                        continue
                    dup.setdefault((rtype, mod), []).append(t)
                    stats[rtype + ' (twins)'] = stats.get(rtype + ' (twins)', 0) + 1
    # twin recipe files: an empty list each, filled by dependsOn patches (so missing add-ons just skip)
    for (rtype, mod), lst in dup.items():
        rel = f'recipes/{rtype}/{mod}-longpork.json'
        write(f'assets/{D}/{rel}', [])
        for r in lst:
            patches.append(OrderedDict([('op', 'add'), ('path', '/-'), ('value', r), ('file', f'{D}:{rel}'),
                                        ('side', 'server'), ('dependsOn', [{'modid': mod}])]))
    return patches, stats


# ---------------------------------------------------------------- patches of other mods that add bushmeat things
def mirrored_patches(base_cooking):
    out = []
    for mod in SOURCES:
        dom = SOURCES[mod][1]
        for n in zips[mod].namelist():
            if '/patches/' not in n or not n.endswith('.json') or any(s in n for s in SKIP_PARTS):
                continue
            if n.endswith('game/patches/bushmeat.json'):
                continue  # long pork itself, handled separately
            raw = zips[mod].read(n).decode('utf-8-sig', 'ignore')
            if 'bushmeat' not in raw:
                continue
            for o in json5.loads(raw):
                if 'bushmeat' not in json.dumps(o):
                    continue
                deps = o.get('dependsOn', [])
                if any(d.get('modid') not in (None, *SOURCES, 'game', 'survival', 'aculinaryartillery') for d in deps):
                    continue
                file = o.get('file', '')
                tdom, tpath = split_code(file, dom)
                tdom = tdom if ':' in file else 'game' if '/game/' in n else dom
                path = o.get('path', '')
                val = o.get('value')
                n2 = OrderedDict((k, v) for k, v in o.items())
                n2['file'] = f'{tdom}:{tpath}'  # unprefixed files would otherwise resolve to our domain
                n2['dependsOn'] = deps + [{'modid': mod}] if mod != 'expandedfoods' else deps
                if 'bushmeat' in path:
                    # e.g. pot texture mappings keyed by item code path
                    mp = re.sub(r'(?<=/)bushmeat-', 'longpork-', path).replace('-bushmeat-', '-longpork-')
                    if mp == path:
                        continue
                    n2['path'] = mp
                    out.append(n2)
                    # vanilla bushmeat key -> long pork lives in our domain: add the full-code key as well
                    if re.search(r'/longpork-[^/]*$', mp):
                        n3 = copy.deepcopy(n2)
                        n3['path'] = re.sub(r'/longpork-([^/]*)$', lambda m: '/' + BASE + ':longpork-' + m.group(1), mp)
                        out.append(n3)
                    continue
                if o.get('op') in ('addeach', 'add') and path.endswith('/-'):
                    items = val if o['op'] == 'addeach' else [val]
                    if not all(isinstance(s, dict) for s in items):
                        continue  # mixing codes and the like: long pork reuses bushmeat's
                    ctx = 'game' if tdom == 'game' else tdom
                    twins = [m for m in (map_stack(s, ctx) for s in items) if m]
                    key = (f'{tdom}:{tpath}'.replace('.json', ''), path)
                    twins = [t for t in twins if t['code'] not in base_cooking.get(key, set())]
                    if not twins:
                        continue
                    n2['op'] = 'addeach'
                    n2['value'] = twins
                    out.append(n2)
    return out


def base_cooking_codes():
    """Codes the base mod already adds to vanilla meals (avoid duplicates)."""
    p = os.path.join(ROOT, 'mod', 'assets', BASE, 'patches', 'cooking.json')
    res = {}
    for o in json.load(open(p, encoding='utf-8')):
        key = (o['file'].replace('.json', ''), o['path'])
        vals = o['value'] if o['op'] == 'addeach' else [o['value']]
        res.setdefault(key, set()).update(v['code'] for v in vals if isinstance(v, dict))
    return res


# ---------------------------------------------------------------- lang
RU_WORD = 'человечины'


# EF calls bushmeat "мясо дичи" (neuter). "Человечина" is feminine, so the adjectives in
# front of it and the state suffix after it, e.g. "(недопечённое)", change gender too.
_ADJ = r'((?:[А-ЯЁа-яё]+(?:ое|ого|ым)\s+)*)'
_CASES = (  # EF noun, our noun, adjective ending EF -> ours
    ('мясо', 'человечина', 'ое', 'ая'),
    ('мяса', 'человечины', 'ого', 'ой'),
    ('мясом', 'человечиной', 'ым', 'ой'),
)


def ru_text(s):
    s = re.sub(r'\b([Сс]) мясо дичи', r'\1 мясом дичи', s)  # EF typo: "с мясо дичи"
    feminine = False
    for noun, ours, a, b in _CASES:
        def sub(m, ours=ours, a=a, b=b):
            adj = re.sub(a + r'(\s)', b + r'\1', m.group(1))
            word = m.group(2)
            if not adj and word[0].isupper():
                return ours[0].upper() + ours[1:]
            return adj + ours
        s, n = re.subn(_ADJ + '(' + noun + ') дичи', sub, s, flags=re.IGNORECASE)
        feminine |= bool(n) and noun == 'мясо'
    if feminine:
        s = re.sub(r'\(([а-яё]+)ое\)', r'(\1ая)', s)
    return re.sub(r'дичи', RU_WORD, s)


def en_text(s):
    s = s.replace('Bushmeat', '"Long pork"').replace('bushmeat', '"long pork"')
    return s


def lang_keys(k, dom):
    """Long pork keys for a bushmeat lang key of `dom`'s lang file."""
    if ':' in k.split('-', 1)[0] or re.match(r'^[a-z]+:', k):
        kd, kp = k.split(':', 1)
    else:
        kd, kp = dom, k
    keys = []
    if kd == 'game' and re.match(r'^item-bushmeat-', kp):
        keys.append(f'{BASE}:' + kp.replace('bushmeat', 'longpork'))
        return keys
    keys.append(f'{kd}:{kp.replace("bushmeat", "longpork")}')
    # vanilla bushmeat inside a composed key (pies/meals): also the form with our domain
    if re.search(r'(single-|primary-|secondary-|item-)bushmeat-', kp):
        keys.append(f'{kd}:' + re.sub(r'(single-|primary-|secondary-|item-)bushmeat-', r'\1' + BASE + ':longpork-', kp))
    return keys


def lang():
    res = {'ru': OrderedDict(), 'en': OrderedDict()}
    for mod in SOURCES:
        dom = SOURCES[mod][1]
        for lg in ('ru', 'en'):
            n = f'assets/{dom}/lang/{lg}.json'
            if n not in zips[mod].namelist():
                continue
            d = json5.loads(zips[mod].read(n).decode('utf-8-sig'))
            for k, v in d.items():
                if 'bushmeat' not in k or any(s.strip('/') + '-' in k for s in ()):
                    continue
                txt = ru_text(v) if lg == 'ru' else en_text(v)
                for nk in lang_keys(k, dom):
                    res[lg].setdefault(nk, txt)
    # EF names the new long pork states itself only for bushmeat; give ours explicit names
    res['ru'].update({
        f'{BASE}:item-longpork-partbaked': 'Недожаренная человечина',
        f'{BASE}:item-longpork-charred': 'Подгоревшая человечина',
    })
    res['en'].update({
        f'{BASE}:item-longpork-partbaked': 'Cooked "long pork" (part-baked)',
        f'{BASE}:item-longpork-charred': 'Cooked "long pork" (charred)',
    })
    for lg, d in res.items():
        write(f'assets/{D}/lang/{lg}.json', d)
    return {lg: len(d) for lg, d in res.items()}


# ---------------------------------------------------------------- sammiches cutting board
def sammiches_config():
    for sub in ('cuttingboard_properties/bushmeatslice.json', 'cuttingboard_storable/bushmeat.json'):
        src = rd('sandwich', f'assets/sandwich/config/sandwich/{sub}')
        out = OrderedDict()
        for k, v in src.items():
            if k.startswith('bushmeat-'):
                st = k[len('bushmeat-'):]
                out[f'longpork-{st}'] = v
                out[f'{BASE}:longpork-{st}'] = v
        write(f'assets/sandwich/config/sandwich/{sub.replace("bushmeat", "longpork")}', out)


# ---------------------------------------------------------------- main
def require_ef(ops):
    """EF is optional for the main mod: no patch of ours may apply without it."""
    for o in ops:
        deps = o.get('dependsOn', [])
        if not any(d.get('modid') == 'expandedfoods' for d in deps):
            o['dependsOn'] = [{'modid': 'expandedfoods'}] + deps
    return ops


def main():
    for sub in (f'assets/{D}', 'assets/sandwich'):  # only our generated parts of the main mod
        if os.path.exists(os.path.join(OUT, sub)):
            shutil.rmtree(os.path.join(OUT, sub))
    lp = require_ef(longpork_patches())
    write(f'assets/{D}/patches/longpork.json', lp)

    items = []
    for (dom, fam), (mod, path) in FAMILIES.items():
        deps = [] if mod == 'expandedfoods' else [mod]
        ops = item_patches(mod, path, deps)
        items += ops
        print(f'  item {dom}:{fam:20s} {len(ops)} patch ops')
    write(f'assets/{D}/patches/items.json', require_ef(items))

    rpatches, stats = recipes()
    write(f'assets/{D}/patches/recipes.json', require_ef(rpatches))
    for k, v in stats.items():
        print(f'  recipes {k}: {v}')

    mp = mirrored_patches(base_cooking_codes())
    write(f'assets/{D}/patches/meals.json', require_ef(mp))
    print(f'  mirrored patches (meals, pots): {len(mp)}')

    sammiches_config()
    print('  lang keys:', lang())
    n_assets = sum(len(f) for r, _, f in os.walk(os.path.join(OUT, 'assets')) if os.sep + 'lang' not in r and os.sep + 'patches' not in r)
    print(f'  files in mod: {n_assets}')
    for w in sorted(set(warnings)):
        print('  WARN', w)


if __name__ == '__main__':
    main()
