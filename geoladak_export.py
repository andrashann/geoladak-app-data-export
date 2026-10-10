#!/usr/bin/env python3
"""Export all user data from the Geoládák "felhőtárhely" (cloud storage).

The Geoládák Android/iOS app (package com.tamaspetro.geoladak) stores a backup
of the user's own data in a Firebase Realtime Database, reachable through the
Firebase email/password login that the app calls "Geoládák felhőtárhely". This
script logs in with that email/password, reads the whole /users/<uid> subtree,
and dumps it to a timestamped JSON file.

With --cache-data-table the same run also writes a CSV beside the JSON (same
filename, .csv): it looks up each cache's GCxxxx code and name on the public
geocaching.hu API and tabulates the stored passwords, the per-multipoint
password fragments, and any extra saved caches, one column per item.

Only the Python standard library is used, so the script is fully self-contained
and needs no dependency manager.

Your credentials are never stored: the email and password you enter are sent
only to the felhőtárhely login server to sign in. The password is not written
to disk or kept anywhere, and the output file contains no password or login
token (only your account email and id as identifiers).

What gets exported, under /users/<uid>:
  auth          - stored geocaching.hu login options / credentials
  settings      - app settings
  places        - the user's own saved points ("saját pontok")
  routes        - saved route plans ("útvonaltervek")
  tracks        - saved tracks (dropped by default; pass --keep-tracks to keep)
  cacheAdditions- per-cache additions (notes, stored passwords, etc.)

Note: the login is an EMAIL address plus a password. Accounts created with
"Sign in with Google" or "Sign in with Apple" have no password and cannot be
used here; that is a limitation of those providers, not of this script.
"""

import argparse
import csv
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

# --- Geoládák felhőtárhely Firebase backend (project geoladak-d7e69) ---
FIREBASE_API_KEY = "AIzaSyBZudBH23ti6dXwEUou2Kyabe20hgR5wSc"
DATABASE_URL = "https://geoladak-d7e69.firebaseio.com"
PROJECT_ID = "geoladak-d7e69"

IDENTITY_TOOLKIT = "https://identitytoolkit.googleapis.com/v1"

# The six child nodes stored under /users/<uid> (used as an explicit fallback
# if a single whole-subtree read is refused by the database rules).
USER_NODES = ["auth", "settings", "places", "routes", "tracks", "cacheAdditions"]

# --- Public geocaching.hu API (used only by --cache-data-table) ---
GEOCACHING_API = "https://api.geocaching.hu/cachesbyid"
# cachesbyid returns `waypoint` as the GCxxxx code and `nickname` as the full
# cache name (the two are the reverse of what the published swagger implies).
CACHE_BATCH_SIZE = 50  # cache ids per request: not all at once, not one by one
CACHE_BATCH_DELAY = 0.34  # seconds to wait between requests, to be gentle

TIMEOUT = 30  # seconds
USER_AGENT = "geoladak-export/1.0 (+https://api.geocaching.hu)"


def _post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sign_in(email, password):
    """Firebase email/password sign-in. Returns the auth response dict."""
    url = f"{IDENTITY_TOOLKIT}/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    try:
        return _post_json(url, payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        message = ""
        try:
            message = json.loads(body).get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            message = body
        friendly = {
            "EMAIL_NOT_FOUND": "No felhőtárhely account exists for this email.",
            "INVALID_PASSWORD": "Wrong password.",
            "INVALID_LOGIN_CREDENTIALS": "Wrong email or password.",
            "INVALID_EMAIL": "That is not a valid email address.",
            "USER_DISABLED": "This account has been disabled.",
        }
        hint = friendly.get(message.split(":")[0].strip(), message or "unknown error")
        sys.exit(f"Login failed: {hint}")


def fetch_subtree(uid, id_token):
    """Fetch the whole /users/<uid> subtree; fall back to per-node reads."""
    base = f"{DATABASE_URL}/users/{urllib.parse.quote(uid)}"
    auth_q = urllib.parse.urlencode({"auth": id_token})
    try:
        whole = _get_json(f"{base}.json?{auth_q}")
        if whole is not None:
            return whole
        # None can mean "empty" or "readable only per child"; try per-child too.
    except urllib.error.HTTPError:
        whole = None  # whole-node read refused by rules; fall back below

    data = {}
    for node in USER_NODES:
        try:
            value = _get_json(f"{base}/{node}.json?{auth_q}")
        except urllib.error.HTTPError as exc:
            value = {"__error__": f"HTTP {exc.code} reading /{node}"}
        if value is not None:
            data[node] = value
    return data


# ---------------------------------------------------------------------------
# --cache-data-table: turn the cacheAdditions node of an export into a CSV
# ---------------------------------------------------------------------------

def fetch_cache_info(ids):
    """Look up GCxxxx code and name for cache ids via the public geocaching.hu
    API, in batches. Returns {id(str): {"code": ..., "name": ...}}."""
    info = {}
    batches = [ids[i:i + CACHE_BATCH_SIZE] for i in range(0, len(ids), CACHE_BATCH_SIZE)]
    for n, batch in enumerate(batches, 1):
        query = urllib.parse.urlencode(
            {"id_list": ",".join(batch), "fields": "id,waypoint,nickname"}
        )
        url = f"{GEOCACHING_API}?{query}"
        rows = None
        for attempt in (1, 2):  # one retry on transient failure
            try:
                rows = _get_json(url)
                break
            except (urllib.error.URLError, ValueError) as exc:
                if attempt == 2:
                    print(f"  batch {n}/{len(batches)} failed ({exc}); skipping.")
                else:
                    time.sleep(1.0)
        for row in rows or []:
            cid = str(row.get("id"))
            info[cid] = {
                "code": row.get("waypoint") or "",
                "name": row.get("nickname") or "",
            }
        print(f"  fetched {n}/{len(batches)} batches "
              f"({min(n * CACHE_BATCH_SIZE, len(ids))}/{len(ids)} caches)")
        if n < len(batches):
            time.sleep(CACHE_BATCH_DELAY)
    return info


def _mp_fragments(mps):
    """Return {0-based position: fragment} for a gc.mps value, which is either
    a list (fill sequentially) or a dict keyed by the multipoint rank/id."""
    out = {}
    if isinstance(mps, list):
        for i, item in enumerate(mps):
            out[i] = item.get("password", "") if isinstance(item, dict) else item
    elif isinstance(mps, dict):
        for key, item in mps.items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            out[idx] = item.get("password", "") if isinstance(item, dict) else item
    return out


def _caches_cells(caches):
    """Return each entry of a gc caches list dumped as a compact JSON string."""
    if not isinstance(caches, list):
        return []
    return [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in caches]


def write_cache_table(additions, out_path):
    """Build the cache-password CSV from an in-memory cacheAdditions dict,
    looking up each cache's code and name on the public geocaching.hu API."""
    if not isinstance(additions, dict) or not additions:
        print("No cacheAdditions in the downloaded data; skipping CSV.")
        return

    # Pre-compute per-cache fragments and the column counts, inferred from this
    # user's data (they vary from user to user), before touching the network.
    rows = {}
    mp_cols = 0
    cache_cols = 0
    for cid, obj in additions.items():
        if not isinstance(obj, dict):
            obj = {}
        gc = obj.get("gc")
        if not isinstance(gc, dict):
            gc = {}
        main = gc.get("main")
        main_pw = main.get("password", "") or "" if isinstance(main, dict) else ""
        frags = _mp_fragments(gc.get("mps"))
        cells = _caches_cells(obj.get("caches"))
        rows[cid] = {"password": main_pw, "frags": frags, "caches": cells}
        if frags:
            mp_cols = max(mp_cols, max(frags) + 1)
        cache_cols = max(cache_cols, len(cells))

    ids = sorted(additions, key=lambda c: int(c) if str(c).isdigit() else c)
    print(f"Looking up {len(ids)} caches on the geocaching.hu public API "
          f"in batches of {CACHE_BATCH_SIZE} ...")
    info = fetch_cache_info([str(c) for c in ids])

    header = (["id", "code", "name", "password"]
              + [f"mp{i + 1}" for i in range(mp_cols)]
              + [f"caches{i + 1}" for i in range(cache_cols)])

    # utf-8-sig so spreadsheets open the Hungarian text with the right encoding.
    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for cid in ids:
            cid = str(cid)
            meta = info.get(cid, {})
            row = rows[cid]
            line = [cid, meta.get("code", ""), meta.get("name", ""), row["password"]]
            line += [row["frags"].get(i, "") for i in range(mp_cols)]
            line += [row["caches"][i] if i < len(row["caches"]) else ""
                     for i in range(cache_cols)]
            writer.writerow(line)

    missing = sum(1 for cid in ids if str(cid) not in info)
    print(f"\nSaved {out_path}")
    print(f"{len(ids)} caches, {mp_cols} mp columns, {cache_cols} caches columns.")
    if missing:
        print(f"Note: {missing} cache id(s) returned no code/name from the API "
              "(archived or removed); those columns are left blank.")


def export_felhotarhely(keep_tracks=False, cache_data_table=False):
    print("Geoládák felhőtárhely export")
    print("Log in with your felhőtárhely email address and password.\n")
    try:
        email = input("Email (username): ").strip()
        password = getpass.getpass("Password: ")
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nAborted.")

    if not email or not password:
        sys.exit("Email and password are both required.")

    print("\nSigning in ...")
    auth = sign_in(email, password)
    uid = auth["localId"]
    id_token = auth["idToken"]
    print(f"Signed in as {auth.get('email', email)} (uid {uid}).")

    print("Downloading cloud storage data ...")
    data = fetch_subtree(uid, id_token)

    dropped_tracks = False
    if not keep_tracks and isinstance(data, dict) and "tracks" in data:
        del data["tracks"]
        dropped_tracks = True

    export = {
        "exported_at": datetime.now().astimezone().isoformat(),
        "firebase_project": PROJECT_ID,
        "account": {"email": auth.get("email", email), "uid": uid},
        "source": f"{DATABASE_URL}/users/{uid}",
        "data": data,
    }

    filename = "geoladak_" + datetime.now().strftime("%Y_%m_%d_%H_%M") + ".json"
    with open(filename, "w", encoding="utf-8") as fh:
        json.dump(export, fh, ensure_ascii=False, indent=2)

    nodes = ", ".join(sorted(data)) if isinstance(data, dict) and data else "(none)"
    print(f"\nSaved {filename}")
    print(f"Top-level nodes exported: {nodes}")
    if dropped_tracks:
        print("Dropped 'tracks' from the output (use --keep-tracks to keep it).")

    if cache_data_table:
        print("\nBuilding cache password table ...")
        additions = data.get("cacheAdditions") if isinstance(data, dict) else None
        csv_path = os.path.splitext(filename)[0] + ".csv"
        write_cache_table(additions, csv_path)


def main():
    parser = argparse.ArgumentParser(
        description="Export your Geoládák felhőtárhely data to JSON, optionally "
                    "also writing a CSV cache-password table in the same run.")
    parser.add_argument(
        "--cache-data-table", action="store_true", dest="cache_data_table",
        help="In the same run, after downloading, also look up each cache's "
             "code and name on the public geocaching.hu API and write a CSV of "
             "the stored passwords next to the JSON (same name, .csv).")
    parser.add_argument(
        "--keep-tracks", action="store_true", dest="keep_tracks",
        help="Keep the 'tracks' node in the export. By default it is dropped, "
             "since imported tracks are often large and rarely wanted.")
    args = parser.parse_args()

    export_felhotarhely(
        keep_tracks=args.keep_tracks,
        cache_data_table=args.cache_data_table,
    )


if __name__ == "__main__":
    main()
