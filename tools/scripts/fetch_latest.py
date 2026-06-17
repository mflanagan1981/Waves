# ODSL Top Times — rebuild when you upload a new CSV
#
# Replaces the old auto-fetch workflow (the ODSL site blocks GitHub's servers by IP,
# so a server-side download isn't possible). Instead: you download the CSV from the
# ODSL rankings page (one tap, from your own browser), drag it into this repo, and
# this workflow rebuilds index.html and publishes it automatically.
#
# Put this file at: .github/workflows/update_top_times.yml  (replace the old contents)
#
# Needs the build tooling in the repo under tools/ (already added) and
# Settings > Actions > General > Workflow permissions = "Read and write".
#
# When the 2026 All-Star standards are published: edit tools/references/cut_standards.csv
# with the new times, then add to the build step below:  --standards-label 2026 --official

name: Build ODSL Top Times

on:
  workflow_dispatch:            # lets you rebuild on demand from the Actions tab
  push:
    paths:                      # runs whenever you add/replace an ODSL CSV
      - 'odsl_top_times_*.csv'
      - '**/odsl_top_times_*.csv'

permissions:
  contents: write

concurrency:
  group: build-top-times
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies (for logo processing)
        run: pip install --quiet pillow numpy

      - name: Find the newest uploaded CSV
        id: pick
        run: |
          latest=$(
            for f in odsl_top_times_*.csv data/odsl_top_times_*.csv; do
              [ -e "$f" ] && printf '%s|%s\n' "$(basename "$f")" "$f"
            done | sort | tail -n1 | cut -d'|' -f2
          )
          if [ -z "$latest" ]; then
            echo "No odsl_top_times_*.csv found in the repo root or data/ folder."; exit 1
          fi
          echo "csv=$latest" >> "$GITHUB_OUTPUT"
          echo "Using: $latest"

      - name: Build index.html
        run: python tools/scripts/build_gadget.py --csv "${{ steps.pick.outputs.csv }}" --out index.html

      - name: Commit & push
        run: |
          git config user.name  "odsl-bot"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add index.html
          git diff --cached --quiet || git commit -m "Rebuild top times from $(basename '${{ steps.pick.outputs.csv }}')"
          git push
