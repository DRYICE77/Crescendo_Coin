# Crescendo — Artist Leaderboard MVP

Two-song proof of concept: Mac Ayres — Slow Down and a Sunflower Bean track identified by Spotify ID `5cnxbbs1MCRm6LiKrO37UR`.

## Run in VS Code

Open this folder. In the integrated terminal:

```bash
python3 app.py
```

Then open http://127.0.0.1:8765 in your browser.

Demo mode displays the verified Mac Ayres 2026-09-22 to 2026-10-22 snapshot. Sunflower Bean is deliberately shown as pending until its data is retrieved. **Do not interpret demo mode as a real two-artist ranking.**

## Live Soundcharts mode

Stop the server with Control+C, then:

```bash
python3 -m pip install certifi
SSL_CERT_FILE="$(python3 -m certifi)" python3 app.py --live
```

Enter the Soundcharts Client ID and Secret at the prompts. Secrets are never written to the frontend. The server authenticates, looks up both Spotify track IDs, and fetches Spotify cumulative stream history. Refresh the browser to fetch again. Watch your API call quota.

If port 8765 is occupied, stop the old server with Control+C or use `--port 8766` and open http://127.0.0.1:8766.

## Metrics and scoring (prototype only)

- Monthly streams: latest cumulative minus the observation exactly 30 days earlier.
- Weekly streams: latest cumulative minus 7 days earlier.
- WoW growth: current seven-day streams divided by preceding seven-day streams minus 1.
- Stream Score: 20 base points + up to 25 points based on monthly streams relative to the top measured song + up to 55 points for WoW growth (27.5 + 0.5 × WoW percentage points, clamped to 0–55).
- Illustrative rewards: 10,000 CRES per week split half equally among qualified songs and half weighted by their scores.

A row stays unranked if its exact-date history is insufficient. This is a **song-level**, not an artist-wide, ranking. No tokens are distributed. Scores and rewards are not financial claims. Production requires anti-fraud measures, eligibility rules, deduplication of Spotify song versions, legal/tokenomics review, and confirmation of Soundcharts data usage rights.
