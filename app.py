
"""Crescendo Coin leaderboard proof of concept.

Python standard library only.
Artist photos and Spotify streaming data provided by Soundcharts.
"""

import argparse
import base64
import getpass
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


# ============================================================
# 1. CONFIGURATION
# ============================================================

TEAM_ID = "hharry-ehrlich-api"

API_BASE = "https://customer.api.soundcharts.com"

WEEKLY_REWARD_POOL = 10000

SONGS = [
    {
        "artist": "Mac Ayres",
        "song": "Slow Down",
        "trackId": "3XstzgzP0rp3bzElEnRVHv",
        "uuid": "11e840cd-9363-6c4a-ab2d-aa1c026db3d8",
        "artistUuid": "11e81bbb-fc54-d1a8-b744-a0369fe50396",
        "artistImage": (
            "https://assets.soundcharts.com/artist/4/5/c/"
            "11e81bbb-fc54-d1a8-b744-a0369fe50396.jpg"
        ),
    },
    {
        "artist": "Sunflower Bean",
        "song": None,
        "trackId": "5cnxbbs1MCRm6LiKrO37UR",
        "uuid": None,
        "artistUuid": None,
        "artistImage": None,
    },
]


# ============================================================
# 2. HISTORICAL DEMO DATA
# ============================================================

MAC = [
    ("2026-09-22", 97398934),
    ("2026-09-23", 97411507),
    ("2026-09-24", 97424137),
    ("2026-09-25", 97437060),
    ("2026-09-26", 97450186),
    ("2026-09-27", 97463539),
    ("2026-09-28", 97476033),
    ("2026-09-29", 97487924),
    ("2026-09-30", 97501009),
    ("2026-10-01", 97514277),
    ("2026-10-02", 97514277),
    ("2026-10-03", 97539470),
    ("2026-10-04", 97551705),
    ("2026-10-05", 97563022),
    ("2026-10-06", 97574099),
    ("2026-10-07", 97586350),
    ("2026-10-08", 97586350),
    ("2026-10-09", 97598628),
    ("2026-10-10", 97624465),
    ("2026-10-11", 97638161),
    ("2026-10-12", 97650925),
    ("2026-10-13", 97663267),
    ("2026-10-14", 97676238),
    ("2026-10-15", 97689186),
    ("2026-10-16", 97702699),
    ("2026-10-17", 97716123),
    ("2026-10-18", 97729093),
    ("2026-10-19", 97741253),
    ("2026-10-20", 97752104),
    ("2026-10-21", 97764180),
    ("2026-10-22", 97776387),
]



# ============================================================
# 3. SOUNDCHARTS API HELPERS
#
# Shared HTTP helper for Soundcharts and Instagram.
# Adds safe diagnostics for upstream API failures.
# ============================================================

def fetch_json(url, token=None, data=None, basic=None):
    headers = {
        "Accept": "application/json",
    }

    if token:
        headers["Authorization"] = "Bearer " + token

    if basic:
        headers["Authorization"] = "Basic " + basic
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded"
        )

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST" if data is not None else "GET",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=25,
        ) as response:
            return json.load(response)

    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        # Parse only safe diagnostic fields.
        try:
            payload = json.loads(raw_body)
            error = payload.get("error", {})

            if isinstance(error, dict):
                details = {
                    "message": error.get("message"),
                    "type": error.get("type"),
                    "code": error.get("code"),
                    "subcode": error.get("error_subcode"),
                }
            else:
                details = {
                    "message": "Unexpected API error format"
                }

        except (ValueError, AttributeError):
            details = {
                "message": "Non-JSON API error response"
            }

        # Never print request URLs, headers,
        # credentials, or access tokens.
        print(
            "[API HTTP ERROR]",
            "status:",
            exc.code,
            "details:",
            details,
            flush=True,
        )

        raise RuntimeError(
            "Upstream API returned HTTP "
            + str(exc.code)
        ) from None

    except urllib.error.URLError as exc:
        print(
            "[API NETWORK ERROR]",
            type(exc.reason).__name__,
            flush=True,
        )

        raise RuntimeError(
            "Unable to reach upstream API"
        ) from None


def access_token(client_id, client_secret):
    credentials = (
        client_id + ":" + client_secret
    ).encode()

    basic = base64.b64encode(
        credentials
    ).decode()

    payload = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "team_id": TEAM_ID,
    }).encode()

    response = fetch_json(
        "https://account.soundcharts.com/oauth/token",
        data=payload,
        basic=basic,
    )

    return response["access_token"]


# ============================================================
# 4. ARTIST METADATA
# ============================================================

def extract_artist_metadata(meta, fallback):
    """Extract artist information from Soundcharts song metadata."""

    main_artists = meta.get("mainArtists") or []
    artists = meta.get("artists") or []

    artist_data = (
        main_artists[0]
        if main_artists
        else artists[0]
        if artists
        else {}
    )

    return {
        "artist": (
            artist_data.get("name")
            or meta.get("creditName")
            or fallback.get("artist")
        ),
        "artistUuid": (
            artist_data.get("uuid")
            or fallback.get("artistUuid")
        ),
        "artistImage": (
            artist_data.get("imageUrl")
            or fallback.get("artistImage")
        ),
        "songImage": (
            meta.get("imageUrl")
            or fallback.get("songImage")
        ),
    }


# ============================================================
# 5. FETCH SONG + STREAMING HISTORY
# ============================================================

def fetch_song(song, token):
    spotify_id = song["trackId"]

    lookup_url = (
        API_BASE
        + "/api/v2.25/song/by-platform/spotify/"
        + urllib.parse.quote(spotify_id)
    )

    metadata_response = fetch_json(
        lookup_url,
        token=token,
    )

    meta = metadata_response["object"]

    uuid = meta["uuid"]

    artist_metadata = extract_artist_metadata(
        meta,
        song,
    )

    start = (
        date.today() - timedelta(days=36)
    ).isoformat()

    params = urllib.parse.urlencode({
        "startDate": start,
        "endDate": date.today().isoformat(),
        "limit": 100,
        "identifier": spotify_id,
    })

    audience_url = (
        API_BASE
        + "/api/v2/song/"
        + uuid
        + "/audience/spotify?"
        + params
    )

    audience = fetch_json(
        audience_url,
        token=token,
    )

    observations = {}

    for item in audience.get("items", []):
        for plot in item.get("plots", []):
            if (
                plot.get("identifier") == spotify_id
                and isinstance(
                    plot.get("value"),
                    (int, float),
                )
            ):
                observations[
                    item["date"][:10]
                ] = int(plot["value"])

    updated = dict(song)

    updated.update(artist_metadata)

    updated["song"] = (
        meta.get("name")
        or song.get("song")
        or "Unknown song"
    )

    updated["uuid"] = uuid

    return updated, sorted(observations.items())


# ============================================================
# 6. STREAMING METRICS
# ============================================================

def metric_at(rows, days):
    """Calculate streams gained over an exact date window."""

    by_date = dict(rows)

    latest = date.fromisoformat(
        rows[-1][0]
    )

    target = (
        latest - timedelta(days=days)
    ).isoformat()

    if target not in by_date:
        return None

    return (
        by_date[rows[-1][0]]
        - by_date[target]
    )


def analyze(song, rows, mode):
    result = dict(song)

    result.update({
        "mode": mode,
        "status": "ready" if rows else "pending",
        "asOf": rows[-1][0] if rows else None,
        "monthly": None,
        "weekly": None,
        "previousWeek": None,
        "wow": None,
        "score": None,
        "reward": None,
        "rank": None,
        "history": [],
        "note": None,
    })

    if not rows:
        result["note"] = (
            "Awaiting first Soundcharts lookup"
        )
        return result

    result["monthly"] = metric_at(rows, 30)
    result["weekly"] = metric_at(rows, 7)

    two_week_total = metric_at(
        rows,
        14,
    )

    if (
        two_week_total is not None
        and result["weekly"] is not None
    ):
        result["previousWeek"] = (
            two_week_total - result["weekly"]
        )

    if (
        result["weekly"] is not None
        and result["previousWeek"] is not None
        and result["previousWeek"] > 0
    ):
        result["wow"] = (
            result["weekly"]
            / result["previousWeek"]
            - 1
        ) * 100

    result["history"] = [
        {
            "date": d,
            "cumulative": v,
        }
        for d, v in rows
    ]

    if (
        result["monthly"] is None
        or result["wow"] is None
    ):
        result["status"] = "incomplete"
        result["note"] = (
            "Need observations exactly "
            "30, 14 and 7 days before "
            "the latest date"
        )

    return result


# ============================================================
# 7. CRESCENDO STREAM SCORE + REWARDS
# ============================================================

def assign_scores(rows):
    """Illustrative scoring and rewards simulation."""

    ready = [
        r for r in rows
        if (
            r["status"] == "ready"
            and r["monthly"] is not None
            and r["monthly"] >= 0
        )
    ]

    if not ready:
        return

    max_monthly = max(
        r["monthly"] for r in ready
    ) or 1

    for r in ready:
        volume = 25 * (
            r["monthly"] / max_monthly
        ) ** 0.5

        growth = max(
            0,
            min(
                55,
                27.5 + r["wow"] * 0.5,
            ),
        )

        r["score"] = round(
            20 + volume + growth
        )

    ready.sort(
        key=lambda r: (
            -r["score"],
            -r["monthly"],
            r["artist"],
        )
    )

    weight_sum = sum(
        r["score"] for r in ready
    )

    for i, r in enumerate(ready, 1):
        r["rank"] = i

        if weight_sum:
            base_reward = (
                WEEKLY_REWARD_POOL
                * 0.5
                / len(ready)
            )

            performance_reward = (
                WEEKLY_REWARD_POOL
                * 0.5
                * r["score"]
                / weight_sum
            )

            r["reward"] = round(
                base_reward
                + performance_reward
            )



# ============================================================
# 8. HTTP SERVER
# ============================================================

class Handler(BaseHTTPRequestHandler):

    # --------------------------------------------------------
    # 8A. STANDARD HTTP RESPONSE
    # --------------------------------------------------------

    def respond(
        self,
        body,
        code=200,
        content_type="application/json",
    ):

        data = (
            body
            if isinstance(body, bytes)
            else json.dumps(body).encode("utf-8")
        )

        self.send_response(code)

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Cache-Control",
            "no-store",
        )

        self.send_header(
            "Content-Length",
            str(len(data)),
        )

        self.end_headers()

        self.wfile.write(data)

    # --------------------------------------------------------
    # 8B. GET REQUEST ROUTER
    # --------------------------------------------------------

    def do_GET(self):

        from urllib.parse import urlsplit

        path = urlsplit(self.path).path

        # ====================================================
        # HEALTH CHECK
        # ====================================================

        if path in ("/health", "/health/"):

            return self.respond({
                "status": "ok",
                "service": "crescendo",
                "mode": (
                    "live"
                    if self.server.live
                    else "demo"
                ),
            })

        # ====================================================
        # SERVE CRESCENDO LEADERBOARD
        # ====================================================

        if path in ("/", "/index.html"):

            html_path = (
                Path(__file__)
                .with_name("index.html")
            )

            if not html_path.is_file():

                return self.respond(
                    {
                        "error": (
                            "Leaderboard HTML not found"
                        )
                    },
                    404,
                )

            return self.respond(
                html_path.read_bytes(),
                content_type=(
                    "text/html; charset=utf-8"
                ),
            )

        # ====================================================
        # SERVE CRESCENDO CAMPAIGNS JAVASCRIPT
        # ====================================================

        if path == "/crescendo_campaigns_addon.js":

            js_path = (
                Path(__file__)
                .with_name(
                    "crescendo_campaigns_addon.js"
                )
            )

            if not js_path.is_file():

                return self.respond(
                    {
                        "error": (
                            "Campaigns JavaScript not found"
                        )
                    },
                    404,
                )

            return self.respond(
                js_path.read_bytes(),
                content_type=(
                    "application/javascript; charset=utf-8"
                ),
            )

  
# ====================================================
# INSTAGRAM API CONNECTION TEST
# ====================================================

if path == "/api/instagram/test":

    instagram_token = os.getenv(
        "INSTAGRAM_ACCESS_TOKEN", ""
    )

    token_check = {
        "configured": bool(instagram_token),
        "length": len(instagram_token),
        "has_whitespace": any(
            c.isspace() for c in instagram_token
        ),
        "has_bearer_prefix": (
            instagram_token.lower().startswith("bearer ")
        ),
        "has_quotes": (
            instagram_token.startswith(("'", '"'))
            or instagram_token.endswith(("'", '"'))
        ),
    }

    print(
        "[INSTAGRAM TOKEN DIAGNOSTIC]",
        token_check,
        flush=True,
    )

    if not instagram_token:
        return self.respond({
            "connected": False,
            "error": "Instagram token not configured",
        }, 503)

    if (
        token_check["has_whitespace"]
        or token_check["has_bearer_prefix"]
        or token_check["has_quotes"]
    ):
        return self.respond({
            "connected": False,
            "error": "Instagram token formatting invalid",
        }, 503)

    try:
        url = (
            "https://graph.instagram.com/me"
            "?fields=id,username,account_type"
        )

        result = fetch_json(
            url,
            token=instagram_token,
        )

        print(
            "[INSTAGRAM API SUCCESS]",
            result.get("username"),
            flush=True,
        )

        return self.respond({
            "connected": True,
            "instagram": {
                "id": result.get("id"),
                "username": result.get("username"),
                "account_type": result.get(
                    "account_type"
                ),
            },
        })

    except Exception as exc:

        print(
            "[INSTAGRAM API FAILED]",
            type(exc).__name__,
            flush=True,
        )

        return self.respond({
            "connected": False,
            "error": "Instagram API request failed",
        }, 502)

        # ====================================================
        # API ROUTING
        # ====================================================

        if path != "/api/leaderboard":

            return self.respond(
                {"error": "Not found"},
                404,
            )

        # ====================================================
        # BUILD LEADERBOARD DATA
        # ====================================================

        entries = []
        token = None

        # ----------------------------------------------------
        # SOUNDCHARTS AUTHENTICATION
        # ----------------------------------------------------

        if self.server.live:

            try:

                token = access_token(
                    self.server.client_id,
                    self.server.client_secret,
                )

            except Exception as exc:

                print(
                    "Soundcharts authentication error:",
                    repr(exc),
                    flush=True,
                )

                return self.respond(
                    {
                        "error": (
                            "Soundcharts authentication failed"
                        )
                    },
                    502,
                )

        # ----------------------------------------------------
        # FETCH AND ANALYZE ARTISTS
        # ----------------------------------------------------

        for song in SONGS:

            # DEMO MODE

            if not self.server.live:

                demo_rows = (
                    MAC
                    if song["artist"] == "Mac Ayres"
                    else []
                )

                entries.append(
                    analyze(
                        song,
                        demo_rows,
                        "demo",
                    )
                )

                continue

            # LIVE MODE

            try:

                metadata, rows = fetch_song(
                    song,
                    token,
                )

                entries.append(
                    analyze(
                        metadata,
                        rows,
                        "live",
                    )
                )

            except Exception as exc:

                print(
                    "Soundcharts artist fetch error:",
                    song.get("artist", "Unknown"),
                    repr(exc),
                    flush=True,
                )

                entry = analyze(
                    song,
                    [],
                    "live",
                )

                entry["status"] = "error"

                # Avoid exposing internal API errors publicly.
                entry["note"] = (
                    "Unable to retrieve live data"
                )

                entries.append(entry)

        # ====================================================
        # CALCULATE CRESCENDO SCORES
        # ====================================================

        assign_scores(entries)

        entries.sort(
            key=lambda r: (
                r["rank"] is None,
                r["rank"] or 99,
            )
        )

        # ====================================================
        # RETURN LEADERBOARD JSON
        # ====================================================

        return self.respond({
            "mode": (
                "live"
                if self.server.live
                else "demo"
            ),
            "artists": entries,
            "pool": WEEKLY_REWARD_POOL,
            "rewardsAreIllustrative": True,
            "method": (
                "Prototype score: "
                "20 base + up to 25 volume "
                "+ up to 55 growth. "
                "Illustrative 10,000 CRES "
                "weekly reward pool."
            ),
        })



# ============================================================
# 9. START APPLICATION
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--live",
        action="store_true",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=None,
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # SERVER CONFIGURATION
    # --------------------------------------------------------

    # Railway supplies PORT through environment variables.
    # Local development defaults to port 8765.

    port = (
        args.port
        if args.port is not None
        else int(os.getenv("PORT", "8765"))
    )

    host = "0.0.0.0"

    # --------------------------------------------------------
    # SOUNDCHARTS AUTHENTICATION
    # --------------------------------------------------------

    client_id = None
    client_secret = None

    if args.live:

        client_id = os.getenv(
            "SOUNDCHARTS_CLIENT_ID"
        )

        client_secret = os.getenv(
            "SOUNDCHARTS_CLIENT_SECRET"
        )

        # Interactive credentials for local development only.
        # Never prompt for credentials in Railway.

        if not client_id or not client_secret:

            if not os.getenv("RAILWAY_ENVIRONMENT"):

                if not client_id:
                    client_id = input(
                        "Soundcharts Client ID: "
                    ).strip()

                if not client_secret:
                    client_secret = getpass.getpass(
                        "Soundcharts Client Secret: "
                    )

            else:
                raise RuntimeError(
                    "Missing Soundcharts credentials. "
                    "Configure SOUNDCHARTS_CLIENT_ID and "
                    "SOUNDCHARTS_CLIENT_SECRET in Railway."
                )

        if not os.getenv("SSL_CERT_FILE"):

            try:
                import certifi

                os.environ[
                    "SSL_CERT_FILE"
                ] = certifi.where()

            except ImportError:
                pass

    # --------------------------------------------------------
    # START HTTP SERVER
    # --------------------------------------------------------

    server = ThreadingHTTPServer(
        (host, port),
        Handler,
    )

    server.live = args.live
    server.client_id = client_id
    server.client_secret = client_secret

    print(
        "\nCRESCENDO COIN LEADERBOARD",
        flush=True,
    )

    print(
        f"Listening on: {host}:{port}",
        flush=True,
    )

    print(
        f"Local URL: http://127.0.0.1:{port}",
        flush=True,
    )

    print(
        "Mode:",
        "LIVE" if args.live else "DEMO",
        flush=True,
    )

    print(
        "Artist images: ENABLED",
        flush=True,
    )

    print(
        "Press Control+C to stop\n",
        flush=True,
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        print(
            "\nShutting down Crescendo...",
            flush=True,
        )

    finally:
        server.server_close()
