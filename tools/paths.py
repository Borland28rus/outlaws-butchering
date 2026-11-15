"""Where the generators find the game and the source mods.

Set them in ../local.paths.json (not committed):
    {"game": "C:/path/to/Vintagestory", "mods": "C:/path/to/VintagestoryData/Mods"}
or with the environment variables VINTAGE_STORY (game folder) and VS_MODS (folder with mod zips).
"""
import json, os, sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cfg = {}
_f = os.path.join(_ROOT, 'local.paths.json')
if os.path.exists(_f):
    with open(_f, encoding='utf-8') as fh:
        _cfg = json.load(fh)


def _get(key, env):
    v = os.environ.get(env) or _cfg.get(key)
    if not v:
        sys.exit(f'Set "{key}" in local.paths.json or the {env} environment variable (see tools/paths.py).')
    return v


GAME = _get('game', 'VINTAGE_STORY')   # game install folder (has VintagestoryAPI.dll and assets/)
MODS = _get('mods', 'VS_MODS')         # folder with the source mod zips (Outlaw Mod, Expanded Foods, ...)
