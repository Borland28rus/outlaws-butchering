"""Draws the dead poses (side and top view) of a few kinds to preview.png next to this script.
Usage: python preview_pose.py generate.py
"""
import os
import sys, json, importlib.util
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

spec = importlib.util.spec_from_file_location('gen', sys.argv[1])
gen = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[1]]
spec.loader.exec_module(gen)

shp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mod', 'assets', 'outlawshumanbutchering', 'shapes', 'creatures') + os.sep
kinds = ['banditaxe', 'looter', 'deserterfootman', 'yeomanarcher']
fig, axs = plt.subplots(len(kinds), 2, figsize=(10, 3.2 * len(kinds)))
for row, k in zip(axs, kinds):
    els = json.load(open(shp_dir + k + '-dead.json', encoding='utf-8'))['elements']
    bx = gen.boxes(els)
    for ax, (i, j, lab) in zip(row, [(0, 1, 'side X-Y'), (0, 2, 'top X-Z')]):
        for name, mn, mx in bx:
            if name == 'Origin': continue
            ax.add_patch(Rectangle((mn[i], mn[j]), mx[i] - mn[i], mx[j] - mn[j], fill=False, lw=0.5,
                                   color='red' if 'Head' in name else 'k'))
        ax.axhline(0, color='g', lw=0.5)
        ax.set_aspect('equal'); ax.autoscale(); ax.set_title(f'{k} {lab}')
plt.tight_layout()
plt.savefig(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'preview.png'), dpi=80)
print('saved')
