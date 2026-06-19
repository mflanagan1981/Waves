#!/usr/bin/env python3
"""
Find and download the newest ODSL "Individual Rankings" CSV from the public
rankings page (https://odsl.swimtopia.com/results).

Each week's file is a SwimTopia link of the form
    https://odsl.swimtopia.com/sites/s3_files/<ID>
New uploads always receive a higher <ID>, so the newest Individual Rankings file
is simply the link with the largest <ID> whose text contains "Individual" (and not
"Relay"). This avoids any fragile date/meet-number parsing.

Outputs (for GitHub Actions, written to $GITHUB_OUTPUT when present):
    changed   = true|false   (false when the newest ID matches the saved state)
    source_id = <ID>
    csv_path  = <path to the downloaded CSV>   (only when changed)

Usage:
    python fetch_latest.py --out data/odsl_top_times.csv --state .last_source_id
"""
import argparse, os, re, sys, urllib.request

PAGE = "https://odsl.swimtopia.com/results"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://odsl.swimtopia.com/",
}
ANCHOR = re.compile(r'<a[^>]+href="([^"]*?/sites/s3_files/(\d+))"[^>]*>(.*?)</a>', re.I | re.S)

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), r.headers

def newest_individual(html):
    """Return (id, url, label) for the highest-ID Individual (non-Relay) link, or None."""
    best = None
    for m in ANCHOR.finditer(html):
        url, sid = m.group(1), int(m.group(2))
        label = re.sub(r'<[^>]+>', '', m.group(3)).strip()
        t = label.lower()
        if 'individual' in t and 'relay' not in t:
            if best is None or sid > best[0]:
                best = (sid, url, label)
    return best

def set_output(key, val):
    go = os.environ.get('GITHUB_OUTPUT')
    if go:
        with open(go, 'a') as f:
            f.write(f"{key}={val}\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--page', default=PAGE)
    ap.add_argument('--out', default='data/odsl_top_times.csv',
                    help="Where to save the CSV (the real filename from the server is kept if available).")
    ap.add_argument('--state', default='.last_source_id',
                    help="File that records the last source ID built, for change detection.")
    ap.add_argument('--force', action='store_true', help="Download even if the ID is unchanged.")
    a = ap.parse_args()

    html, _ = fetch(a.page)
    html = html.decode('utf-8', 'replace')
    best = newest_individual(html)
    if not best:
        sys.exit("ERROR: no Individual Rankings link found on the page (layout may have changed).")
    sid, url, label = best
    print(f"Newest Individual Rankings: '{label}' (id {sid})\n  {url}")

    prev = open(a.state).read().strip() if os.path.exists(a.state) else None
    changed = a.force or (str(sid) != prev)
    set_output('changed', 'true' if changed else 'false')
    set_output('source_id', str(sid))
    if not changed:
        print(f"No new rankings since id {prev} — nothing to do.")
        return

    data, hdr = fetch(url)
    out = a.out
    cd = hdr.get('Content-Disposition', '') or ''
    fn = re.search(r'filename="?([^";]+\.csv)"?', cd, re.I)
    if fn:  # keep the real filename so the build can derive the "as of" date from it
        out = os.path.join(os.path.dirname(a.out) or '.', os.path.basename(fn.group(1)))
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    with open(out, 'wb') as f:
        f.write(data)
    with open(a.state, 'w') as f:
        f.write(str(sid))
    set_output('csv_path', out)
    print(f"Downloaded {len(data):,} bytes -> {out}")

if __name__ == '__main__':
    main()
