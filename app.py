
"""Crescendo Coin leaderboard proof of concept.

Python standard library only.
Artist photos and Spotify streaming data provided by Soundcharts.
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import secrets
import time
from http.cookies import SimpleCookie
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
    headers = {"Accept": "application/json"}

    if token:
        headers["Authorization"] = "Bearer " + token

    if basic:
        headers["Authorization"] = "Basic " + basic
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST" if data is not None else "GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.load(response)

    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
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
                details = {"message": "Unexpected API error format"}
        except (ValueError, AttributeError):
            details = {"message": "Non-JSON API error response"}

        print(
            "[API HTTP ERROR]",
            "status:", exc.code,
            "details:", details,
            flush=True,
        )
        raise RuntimeError("Upstream API returned HTTP " + str(exc.code)) from None

    except urllib.error.URLError as exc:
        print(
            "[API NETWORK ERROR]",
            type(exc.reason).__name__,
            flush=True,
        )
        raise RuntimeError("Unable to reach upstream API") from None


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
# 7B. INSTAGRAM OAUTH HELPERS
# ============================================================

OAUTH_CALLBACK = (
    "https://crescendocoin-production.up.railway.app"
    "/auth/instagram/callback"
)
OAUTH_STATE_COOKIE = "crescendo_ig_oauth_state"
OAUTH_RESULT_COOKIE = "crescendo_ig_oauth_result"


def oauth_sign(payload, secret):
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    mac = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return raw + "." + mac


def oauth_unsign(value, secret, max_age):
    try:
        raw, mac = value.rsplit(".", 1)
        expected = hmac.new(
            secret.encode(), raw.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(mac, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(
            raw + "=" * (-len(raw) % 4)
        ))
        if not isinstance(payload, dict):
            return None
        issued = int(payload.get("iat", 0))
        if issued > time.time() + 60 or time.time() - issued > max_age:
            return None
        return payload
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def cookie_value(header, name):
    jar = SimpleCookie()
    try:
        jar.load(header or "")
        return jar[name].value if name in jar else None
    except Exception:
        return None


def meta_oauth_json(url, *, data=None, token=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(
        url, data=data, headers=headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(65537)
            if len(body) > 65536:
                raise ValueError("Meta response too large")
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError("Unexpected Meta JSON response")
            return result
    except urllib.error.HTTPError as exc:
        print("[IG OAUTH] Meta HTTP status:", exc.code, flush=True)
        raise RuntimeError("Meta authorization request failed") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print("[IG OAUTH] Upstream failure:", type(exc).__name__, flush=True)
        raise RuntimeError("Meta authorization request failed") from None


def discover_instagram_accounts(access_token):
    """Probe an explicitly configured IG test asset, then Page discovery.

    These probes confirm token access only, not artist identity or consent
    to claim an artist profile. Never fall back to the server's system token.
    """
    accounts = []
    diagnostics = []
    known_id = os.getenv("CRESCENDO_TEST_INSTAGRAM_ID", "17841457229549813").strip()

    if known_id and known_id.isdecimal():
        url = (
            "https://graph.facebook.com/v24.0/"
            + known_id
            + "?"
            + urllib.parse.urlencode({"fields": "id,username"})
        )
        try:
            payload = meta_oauth_json(url, token=access_token)
            returned_id = str(payload.get("id", ""))
            if returned_id == known_id:
                accounts.append({
                    "id": returned_id,
                    "username": payload.get("username"),
                    "source": "direct_asset_probe",
                })
                diagnostics.append({"probe": "direct_asset", "result": "matched"})
            else:
                diagnostics.append({"probe": "direct_asset", "result": "no_match"})
        except RuntimeError:
            diagnostics.append({"probe": "direct_asset", "result": "api_error"})
    else:
        diagnostics.append({"probe": "direct_asset", "result": "not_configured"})

    # Pages are useful for Facebook Login, but may be empty for
    # Instagram business assets authorized through Unified Login.
    url = (
        "https://graph.facebook.com/v24.0/me/accounts?"
        + urllib.parse.urlencode({
            "fields": "id,instagram_business_account{id,username}",
            "limit": 100,
        })
    )
    try:
        payload = meta_oauth_json(url, token=access_token)
        pages = payload.get("data", [])
        if not isinstance(pages, list):
            pages = []
        diagnostics.append({"probe": "pages", "result": "ok", "page_count": len(pages)})
        for page in pages:
            if not isinstance(page, dict):
                continue
            ig = page.get("instagram_business_account")
            if isinstance(ig, dict) and ig.get("id"):
                ig_id = str(ig["id"])
                if not any(a["id"] == ig_id for a in accounts):
                    accounts.append({
                        "id": ig_id,
                        "username": ig.get("username"),
                        "source": "facebook_page",
                    })
    except RuntimeError:
        diagnostics.append({"probe": "pages", "result": "api_error"})

    print("[IG OAUTH] Discovery diagnostics:", diagnostics, flush=True)
    return accounts, diagnostics


# ============================================================
# 8. HTTP SERVER
# ============================================================

class Handler(BaseHTTPRequestHandler):

    # Never log OAuth authorization codes, state, or any query strings.
    def log_message(self, format, *args):
        if args and isinstance(args[0], str):
            parts = args[0].split(" ")
            if len(parts) >= 2:
                parts[1] = parts[1].split("?", 1)[0]
                args = (" ".join(parts),) + args[1:]
        super().log_message(format, *args)

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

    def redirect(self, location, cookies=()):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def oauth_cookie(self, name, value, max_age):
        return (
            f"{name}={value}; Path=/; Max-Age={max_age}; "
            "HttpOnly; Secure; SameSite=Lax"
        )

    def oauth_clear_cookie(self, name):
        return self.oauth_cookie(name, "", 0)

    # --------------------------------------------------------
    # 8B. GET REQUEST ROUTER
    # --------------------------------------------------------

    def do_GET(self):

        from urllib.parse import urlsplit

        path = urlsplit(self.path).path

        # ====================================================
        # INSTAGRAM UNIFIED LOGIN (USER-INITIATED OAUTH)
        # ====================================================
        if path == "/auth/instagram/start":
            login_url = os.getenv("META_LOGIN_URL", "").strip()
            secret = os.getenv("CRESCENDO_SESSION_SECRET", "")
            if not login_url or len(secret) < 32:
                return self.respond({
                    "error": "Instagram OAuth is not configured",
                    "required": ["META_LOGIN_URL", "CRESCENDO_SESSION_SECRET"],
                }, 503)

            parsed = urllib.parse.urlsplit(login_url)
            if parsed.scheme != "https" or parsed.hostname not in (
                "www.facebook.com", "facebook.com"
            ) or parsed.path != "/dialog/oauth":
                return self.respond({"error": "Invalid Meta login configuration"}, 503)

            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            app_id = os.getenv("META_APP_ID", "")
            if not app_id or query.get("client_id", [None])[0] != app_id:
                return self.respond({"error": "Meta app ID mismatch"}, 503)

            nonce = secrets.token_urlsafe(32)
            signed = oauth_sign({"state": nonce, "iat": int(time.time())}, secret)
            query["state"] = [nonce]
            query["redirect_uri"] = [OAUTH_CALLBACK]
            destination = urllib.parse.urlunsplit((
                parsed.scheme, parsed.netloc, parsed.path,
                urllib.parse.urlencode(query, doseq=True), "",
            ))
            return self.redirect(destination, cookies=[
                self.oauth_cookie(OAUTH_STATE_COOKIE, signed, 600)
            ])

        if path == "/auth/instagram/callback":
            query = urllib.parse.parse_qs(
                urllib.parse.urlsplit(self.path).query
            )
            secret = os.getenv("CRESCENDO_SESSION_SECRET", "")
            signed = cookie_value(self.headers.get("Cookie"), OAUTH_STATE_COOKIE)
            state = oauth_unsign(signed, secret, 600) if secret and signed else None
            supplied_state = query.get("state", [None])[0]
            clear_state = self.oauth_clear_cookie(OAUTH_STATE_COOKIE)

            if not state or not supplied_state or not hmac.compare_digest(
                str(state.get("state", "")), supplied_state
            ):
                return self.redirect("/?instagram=invalid_state", [clear_state])

            if "error" in query:
                return self.redirect("/?instagram=cancelled", [clear_state])

            code = query.get("code", [None])[0]
            app_id = os.getenv("META_APP_ID", "")
            app_secret = os.getenv("META_APP_SECRET", "")
            if not code or not app_id or not app_secret:
                return self.respond({"error": "Missing authorization code or configuration"}, 400)

            try:
                exchange_url = (
                    "https://graph.facebook.com/v24.0/oauth/access_token?"
                    + urllib.parse.urlencode({
                        "client_id": app_id,
                        "client_secret": app_secret,
                        "redirect_uri": OAUTH_CALLBACK,
                        "code": code,
                    })
                )
                exchange = meta_oauth_json(exchange_url)
                user_token = exchange.get("access_token")
                if not isinstance(user_token, str) or not user_token:
                    raise RuntimeError("No user token returned")
                accounts, diagnostics = discover_instagram_accounts(user_token)
            except RuntimeError:
                return self.redirect("/?instagram=error", [clear_state])

            # Only persist a short-lived, signed RESULT, never the access token.
            # No public verified badge is awarded by this proof of concept.
            result = {
                "iat": int(time.time()),
                "accounts": accounts[:8],
                "diagnostics": diagnostics,
                "status": "connected_test" if accounts else "no_accounts",
                "artist_verified": False,
            }
            result_cookie = oauth_sign(result, secret)
            print("[IG OAUTH] Login callback completed; accounts:", len(accounts), flush=True)
            return self.redirect("/?instagram=connected" if accounts else "/?instagram=no_accounts", [
                clear_state,
                self.oauth_cookie(OAUTH_RESULT_COOKIE, result_cookie, 1800),
            ])

        if path == "/api/instagram/session":
            secret = os.getenv("CRESCENDO_SESSION_SECRET", "")
            signed = cookie_value(self.headers.get("Cookie"), OAUTH_RESULT_COOKIE)
            result = oauth_unsign(signed, secret, 1800) if signed and secret else None
            if not result:
                return self.respond({"connected": False, "artist_verified": False})
            return self.respond({
                "connected": result.get("status") == "connected_test",
                "status": result.get("status"),
                "accounts": result.get("accounts", []),
                "diagnostics": result.get("diagnostics", []),
                "artist_verified": False,
                "note": "OAuth test only; no artist identity has been verified",
            })

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
        # META EAA TOKEN DIAGNOSTIC (NOT ARTIST VERIFICATION)
        # ====================================================

        if path == "/api/instagram/test":
            # This is a temporary diagnostic. Do not use a
            # shared server token to verify individual artists.
            instagram_token = os.getenv(
                "INSTAGRAM_ACCESS_TOKEN", ""
            )

            if not instagram_token:
                return self.respond({
                    "connected": False,
                    "test": "facebook_graph_token",
                    "error": "INSTAGRAM_ACCESS_TOKEN is not configured",
                }, 503)

            if (
                any(c.isspace() for c in instagram_token)
                or instagram_token.lower().startswith("bearer ")
                or instagram_token.startswith(("'", '"'))
                or instagram_token.endswith(("'", '"'))
            ):
                return self.respond({
                    "connected": False,
                    "test": "facebook_graph_token",
                    "error": "Token formatting appears invalid",
                }, 503)

            # A Facebook Graph /me result may be a Facebook
            # identity, NOT the connected Instagram account.
            # This test does not set an artist's verified status.
            url = (
                "https://graph.facebook.com/v24.0/me"
                "?fields=id,name"
            )
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": "Bearer " + instagram_token,
                },
                method="GET",
            )

            try:
                with urllib.request.urlopen(
                    request, timeout=25
                ) as response:
                    raw_body = response.read()
                    print(
                        "[META RAW RESPONSE]",
                        "status:", response.status,
                        "content_type:", response.headers.get("Content-Type", ""),
                        "body_length:", len(raw_body),
                        flush=True,
                    )
                    result = json.loads(raw_body)
                    print(
                        "[META PARSED RESPONSE]",
                        "type:", type(result).__name__,
                        "is_empty_list:", isinstance(result, list) and not result,
                        flush=True,
                    )

             
                # ============================================
                # META TOKEN RESPONSE VALIDATION
                # ============================================

                print(
                    "[META TOKEN TEST] Response type:",
                    type(result).__name__,
                    flush=True,
                )

                # Meta should return a dictionary containing
                # the authenticated identity.

                if isinstance(result, dict):
                    print(
                        "[META TOKEN TEST] Response keys:",
                        list(result.keys()),
                        flush=True,
                    )

                    account = result

                elif isinstance(result, list):
                    print(
                        "[META TOKEN TEST] Unexpected list response",
                        "item_count:",
                        len(result),
                        flush=True,
                    )

                    return self.respond({
                        "connected": False,
                        "test": "facebook_graph_token",
                        "response_type": "list",
                        "item_count": len(result),
                        "error": (
                            "Meta returned a list instead "
                            "of an account identity"
                        ),
                    }, 502)

                else:
                    print(
                        "[META TOKEN TEST] Unexpected response type:",
                        type(result).__name__,
                        flush=True,
                    )

                    return self.respond({
                        "connected": False,
                        "test": "facebook_graph_token",
                        "response_type": type(result).__name__,
                        "error": "Unexpected Meta response",
                    }, 502)

                # ============================================
                # VALIDATE ACCOUNT ID
                # ============================================

                account_id = account.get("id")

                if not account_id:
                    print(
                        "[META TOKEN TEST] Missing identity in response",
                        flush=True,
                    )

                    return self.respond({
                        "connected": False,
                        "test": "facebook_graph_token",
                        "response_keys": list(account.keys()),
                        "error": "Meta returned no account ID",
                    }, 502)

                # ============================================
                # TOKEN ACCEPTED
                # ============================================

                print(
                    "[META TOKEN TEST] Accepted; identity returned",
                    flush=True,
                )

                return self.respond({
                    "connected": True,
                    "test": "facebook_graph_token",
                    "identity_type": "unconfirmed_facebook_graph_identity",
                    "id": account_id,
                    "name": account.get("name"),
                    "instagram_verified": False,
                    "note": (
                        "Token accepted by Facebook Graph API; "
                        "Instagram account ownership not yet verified"
                    ),
                })


            except urllib.error.HTTPError as exc:
                # Only expose the numeric Meta error codes.
                # Do not log raw response bodies or tokens.
                error_code = None
                error_subcode = None
                try:
                    payload = json.loads(exc.read().decode("utf-8"))
                    meta_error = payload.get("error", {})
                    if isinstance(meta_error, dict):
                        error_code = meta_error.get("code")
                        error_subcode = meta_error.get("error_subcode")
                except (ValueError, UnicodeDecodeError, AttributeError):
                    pass

                print(
                    "[META TOKEN TEST] HTTP", exc.code,
                    "Meta code", error_code,
                    "subcode", error_subcode,
                    flush=True,
                )
                return self.respond({
                    "connected": False,
                    "test": "facebook_graph_token",
                    "upstream_status": exc.code,
                    "meta_error_code": error_code,
                    "meta_error_subcode": error_subcode,
                    "error": "Meta rejected the diagnostic request",
                }, 502)

            except (urllib.error.URLError, TimeoutError) as exc:
                print(
                    "[META TOKEN TEST] Network failure:",
                    type(exc).__name__, flush=True,
                )
                return self.respond({
                    "connected": False,
                    "test": "facebook_graph_token",
                    "error": "Unable to reach Meta API",
                }, 502)

            except (ValueError, TypeError, KeyError) as exc:
                print(
                    "[META TOKEN TEST] Unexpected response:",
                    type(exc).__name__, flush=True,
                )
                return self.respond({
                    "connected": False,
                    "test": "facebook_graph_token",
                    "error": "Unexpected Meta API response",
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
