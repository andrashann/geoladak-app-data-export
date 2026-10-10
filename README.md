# Geoládák app data export

A small, self-contained Python script that downloads all of your data from the
**Geoládák felhőtárhely** (the cloud storage used by the Geoládák geocaching
app) and saves it to a JSON file.

The felhőtárhely holds the data the app backs up for you:

- `auth` – stored geocaching.hu login options
- `settings` – app settings
- `places` – your own saved points (saját pontok)
- `routes` – saved route plans (útvonaltervek)
- `tracks` – saved tracks (dropped by default, see below)
- `cacheAdditions` – per-cache additions (notes, stored passwords, etc.)

## Requirements

Python 3 only. The script uses nothing but the standard library, so there is
nothing to install.

## Usage

```
python3 geoladak_export.py
```

It asks for your felhőtárhely **email address** (the username) and **password**,
signs in, downloads everything, and writes a file named like:

```
geoladak_2026_10_10_20_42.json
```

(`geoladak_YYYY_MM_DD_HH_MM.json`, using the current date and time).

By default the `tracks` node is **dropped** from the output, because imported
tracks are often large and rarely worth keeping. To include them, add
`--keep-tracks`:

```
python3 geoladak_export.py --keep-tracks
```

## Cache password table (CSV)

Add `--cache-data-table` to also produce a spreadsheet-friendly CSV of cache
passwords in the same run, right after the download:

```
python3 geoladak_export.py --cache-data-table
```

Using the data just downloaded, it looks up each cache's code and name on the
public geocaching.hu API and writes a CSV next to the JSON, with the same
name (`...json` → `...csv`). The columns are:

- `id` – the cache's numeric geocaching.hu id (from the downloaded data)
- `code` – the cache code, e.g. `GCPAVM` (from the geocaching.hu API)
- `name` – the cache name, e.g. `Pázmándi vízimalom` (from the geocaching.hu API)
- `password` – the main stored password
- `mp1`, `mp2`, … – the per-multipoint password fragments (as many columns as
  the cache with the most fragments needs; a fragment stored with a rank is
  placed in the matching column, so gaps can occur)
- `caches1`, `caches2`, … – any extra points saved on the cache, each dumped as
  a JSON string (as many columns as the cache with the most of them needs)

The number of `mp` and `caches` columns is inferred from your own data, so it
varies from person to person. The lookups run in small batches with a short
pause between them, so this adds a little time for a large collection.

The CSV is written as UTF-8 with a BOM so spreadsheet programs open the
Hungarian text correctly.

## Notes

- **Your credentials are not stored.** The email and password you type are sent
  directly to the felhőtárhely login server to sign in, and nothing else. The
  password is never written to disk or saved anywhere by this script, and the
  output file contains no password or login token (only your account email and
  id as identifiers).
- The login username is the **email address** you registered the felhőtárhely
  with, together with its password.
- Accounts created with **"Sign in with Google"** or **"Sign in with Apple"**
  do not have a password and cannot be used with this script.
- The exported JSON, and the CSV if you generate one, contain sensitive
  information (including stored passwords). Keep the files somewhere safe.
