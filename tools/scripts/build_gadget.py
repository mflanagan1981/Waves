#!/usr/bin/env python3
"""
Build the interactive ODSL Top Times gadget (single self-contained index.html)
from an ODSL top-times CSV export.

Usage:
    python build_gadget.py --csv <path-to-odsl_top_times.csv> [options]

Options:
    --out PATH            Output HTML file (default: ./index.html)
    --cuts PATH           Cut-standards CSV (default: ../references/cut_standards.csv)
    --standards-label STR Year/label shown on the cut line, e.g. "2025" or "2026"
                          (default: 2025)
    --official            Treat the cut standards as the official current-season
                          standards (changes wording from "reference only / TBD"
                          to "official standard"). Default is provisional.
    --asof STR            "Top times as of" date shown in the masthead
                          (default: auto-derived from the CSV filename, else the
                          latest meet date in the data).
    --season STR          Season label in the eyebrow (default: "2026 ODSL season").
    --team-abbr STR       team_abbr value to highlight (default: WWNOR).
    --team-name STR       Full team name (default: "Willowsford North Waves").
    --team-short STR      Short team label for chips (default: "Willowsford North").

The CSV is expected to be the standard ODSL top-times export with columns:
    age_group, distance, stroke, place, converted_time, converted_hundredths,
    original_time, last_name, first_name, age, team_abbr, team_name, date, swim_meet
"""
import argparse, base64, csv, io, json, re, sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
ASSETS = SKILL / "assets"
REFS = SKILL / "references"

# League skin: deeper marine navy + league blue; hide the per-team logo badge (text header).
ODSL_CSS = (
    ":root{--navy:#00004A;--navy-dk:#000033;--blue:#2350A8;--blue-dk:#173C82;"
    "--blue-tint:#E8ECF7;--blue-soft:#CCD8F0;--rope:#D30000;--rope-dk:#960000}"
    "body.compact .masthead{border-bottom-color:#FE0000}"
)
SKIN_DEFAULTS = {
    'waves': dict(brand_name='Willowsford North Waves', brand_short='Willowsford North',
                  default_team='WWNOR', logo=str(ASSETS / 'waves_logo.png'), brandcss=''),
    'odsl':  dict(brand_name='', brand_short='ODSL',
                  default_team='',  logo=str(ASSETS / 'odsl_logo.png'), brandcss=ODSL_CSS),
}

BRACKET_ORDER = ['6 & Under','7-8','8 & Under','9-10','10 & Under','11-12','13-14','15-18']
STROKE_ORDER  = ['Freestyle','Backstroke','Breaststroke','Butterfly','Individual Medley']
MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December']

def clean_time(t): return re.sub(r'[A-Za-z]+$', '', str(t)).strip()

def to_h(t):
    """Convert a time string (SS.hh or M:SS.hh) to integer hundredths."""
    t = clean_time(t)
    if ':' in t:
        m, s = t.split(':'); return int(round((int(m)*60 + float(s)) * 100))
    return int(round(float(t) * 100))

def sex_of(ag):     return 'Girls' if ag.startswith(('Girls', 'Women')) else 'Boys'
def bracket_of(ag): return re.sub(r'^(Girls|Boys|Women|Men)\s+', '', ag).strip()

def derive_asof(csv_path, records):
    # filename pattern: ..._YYMMDDHHMMSS.csv
    m = re.search(r'_(\d{2})(\d{2})(\d{2})\d*\.csv$', Path(csv_path).name)
    if m:
        yy, mm, dd = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            return f"{MONTHS[mm-1]} {dd}, {2000+yy}"
    # fallback: latest meet date in data (MM/DD/YY)
    best = None
    for r in records:
        m = re.match(r'(\d{2})/(\d{2})/(\d{2})', str(r['dt']))
        if m:
            key = (int(m.group(3)), int(m.group(1)), int(m.group(2)))
            if best is None or key > best[0]:
                best = (key, f"{MONTHS[int(m.group(1))-1]} {int(m.group(2))}, {2000+int(m.group(3))}")
    return best[1] if best else ''

def load_records(csv_path):
    records = []
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            ag = r['age_group']
            records.append({
                'sex': sex_of(ag), 'br': bracket_of(ag), 'agl': ag,
                'd': int(r['distance']), 'st': r['stroke'], 'pl': int(r['place']),
                'nm': f"{r['first_name']} {r['last_name']}", 'a': int(r['age']),
                'tm': r['team_name'], 'ab': r['team_abbr'],
                't': clean_time(r['converted_time']), 'h': int(r['converted_hundredths']),
                'mt': r['swim_meet'], 'dt': r['date'],
            })
    return records

def load_cuts(cuts_path):
    """Return {f'{sex}|{bracket}|{stroke}': {'t':label,'h':hundredths}}."""
    cuts = {}
    with open(cuts_path, newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            ag = r['age_group'].strip(); st = r['stroke'].strip()
            ct = clean_time(r['cut_time'])
            if not ct: continue
            key = f"{sex_of(ag)}|{bracket_of(ag)}|{st}"
            cuts[key] = {'t': ct, 'h': to_h(ct)}
    return cuts

def load_names(names_path):
    """Return {abbr: display_name} for cleaning up raw team labels; empty if file absent."""
    names = {}
    p = Path(names_path)
    if not p.exists():
        return names
    with open(p, newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            ab = (r.get('abbr') or '').strip()
            nm = (r.get('name') or '').strip()
            if ab and nm:
                names[ab] = nm
    return names

def encode_logo(logo_path, target_w=260):
    """Crop near-white border, resize, return data: URI. Falls back to raw encode."""
    raw = Path(logo_path).read_bytes()
    try:
        from PIL import Image
        import numpy as np
        im = Image.open(io.BytesIO(raw)).convert('RGBA')
        arr = np.array(im)
        mask = ~((arr[:,:,0]>245)&(arr[:,:,1]>245)&(arr[:,:,2]>245))
        ys, xs = np.where(mask)
        if len(xs):
            im = im.crop((xs.min(), ys.min(), xs.max()+1, ys.max()+1))
        h = round(im.height * target_w / im.width)
        im = im.resize((target_w, h), Image.LANCZOS)
        buf = io.BytesIO(); im.save(buf, 'PNG', optimize=True)
        raw = buf.getvalue()
    except Exception as e:
        print(f"  (logo: using raw image, no resize — {e})", file=sys.stderr)
    return 'data:image/png;base64,' + base64.b64encode(raw).decode()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True)
    ap.add_argument('--out', default='index.html')
    ap.add_argument('--cuts', default=str(REFS / 'cut_standards.csv'))
    ap.add_argument('--names', default=str(REFS / 'team_names.csv'),
                    help="CSV of abbr,name to clean up raw team labels in the picklist/rows.")
    ap.add_argument('--template', default=str(ASSETS / 'template.html'))
    ap.add_argument('--logo', default=None,
                    help="Logo image. Default: the skin's logo (Waves crest for 'waves', none for 'odsl').")
    ap.add_argument('--standards-label', default='2025')
    ap.add_argument('--official', action='store_true')
    ap.add_argument('--asof', default=None)
    ap.add_argument('--season', default='2026 ODSL season')
    ap.add_argument('--skin', choices=['waves', 'odsl'], default='waves',
                    help="Brand skin. 'waves' = Willowsford North; 'odsl' = league-wide.")
    ap.add_argument('--brand-name', default=None, help="Header brand name (defaults per skin).")
    ap.add_argument('--brand-short', default=None, help="Short brand label (defaults per skin).")
    ap.add_argument('--default-team', default=None,
                    help="Team abbr highlighted on load ('' = none). Defaults per skin; "
                         "any visitor can change it via the picklist or a ?team= URL param.")
    ap.add_argument('--header', choices=['full', 'compact'], default='full',
                    help="Masthead style. 'compact' = slim strip for embedding under a site header.")
    a = ap.parse_args()

    sk = SKIN_DEFAULTS[a.skin]
    brand_name   = a.brand_name   if a.brand_name   is not None else sk['brand_name']
    brand_short  = a.brand_short  if a.brand_short  is not None else sk['brand_short']
    default_team = a.default_team if a.default_team is not None else sk['default_team']
    logo_path    = a.logo         if a.logo         is not None else sk['logo']
    brandcss     = sk['brandcss']

    records = load_records(a.csv)
    if not records:
        sys.exit("No rows parsed from CSV — check the file.")
    cuts = load_cuts(a.cuts)
    names = load_names(a.names)
    asof = a.asof or derive_asof(a.csv, records)

    meta = {
        'asof': asof, 'season': a.season,
        'brand_nm': brand_name, 'brand_short': brand_short,
        'default_team': default_team, 'skin': a.skin,
        'names': names,
        'year': a.standards_label, 'provisional': (not a.official),
        'header': a.header,
        'bracket_order': BRACKET_ORDER, 'stroke_order': STROKE_ORDER,
    }

    html = Path(a.template).read_text()
    html = html.replace('/*DATA*/', json.dumps(records, separators=(',', ':')))
    html = html.replace('/*CUTS*/', json.dumps(cuts, separators=(',', ':')))
    html = html.replace('/*META*/', json.dumps(meta, separators=(',', ':')))
    html = html.replace('/*BRANDCSS*/', brandcss)
    html = html.replace('/*LOGO*/', encode_logo(logo_path) if logo_path else '')

    left = sum(html.count(p) for p in ('/*DATA*/', '/*CUTS*/', '/*META*/', '/*LOGO*/'))
    if left:
        sys.exit(f"Build error: {left} placeholder(s) not filled — template mismatch.")

    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    n_cut = sum(1 for r in records if f"{r['sex']}|{r['br']}|{r['st']}" in cuts)
    events = len({(r['sex'], r['br'], r['st']) for r in records})
    print(f"Wrote {a.out} ({len(html):,} bytes)")
    print(f"  {len(records)} swimmers · {events} events · standards label '{a.standards_label}'"
          f" ({'official' if a.official else 'provisional/reference'})")
    print(f"  as of: {asof or '(unknown)'} · skin: {a.skin} · default highlight: {default_team or '(none)'}")
    miss = sorted({f"{r['sex']} {r['br']} {r['st']}" for r in records
                   if f"{r['sex']}|{r['br']}|{r['st']}" not in cuts})
    if miss:
        print(f"  NOTE: {len(miss)} event(s) have no cut standard (no cut line shown): "
              + ", ".join(miss[:6]) + (" …" if len(miss) > 6 else ""))

if __name__ == '__main__':
    main()
