#!/usr/bin/env python
"""Download USDA CDL national rasters into the local store.

    python download_cdl.py                     # 2018-2025
    python download_cdl.py --years 2020 2021
    python download_cdl.py --status

Roughly 1.8 GB zipped per year. Resumable, staged and verified: interrupting it
costs only the chunk in flight, and re-running skips whatever is already good.

The store lives outside the repository (``~/geodata/cdl``, or ``CDL_DIR``) so it
cannot be committed and so other projects on the machine share one copy.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
import zipfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fieldrs.cdl_local import (CDL_URL, TIF_GLOB, available_years,  # noqa: E402
                               cdl_root, readable, year_tif)

DEFAULT_YEARS = list(range(2018, 2026))
CHUNK = 1 << 20


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "fieldrs-cdl-download/1.0"
    return s


def fetch(year: int, session: requests.Session) -> Path | None:
    """Download one year's zip, resuming a partial file if there is one."""
    raw = cdl_root() / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    dest = raw / f"{year}_30m_cdls.zip"
    url = CDL_URL.format(year=year)

    head = session.head(url, allow_redirects=True, timeout=60)
    if head.status_code != 200:
        print(f"  {year}: HTTP {head.status_code} -- not published?", flush=True)
        return None
    total = int(head.headers.get("content-length", 0))

    have = dest.stat().st_size if dest.exists() else 0
    if total and have == total:
        print(f"  {year}: zip already complete ({total / 2**30:.2f} GB)", flush=True)
        return dest
    if have > total > 0:
        print(f"  {year}: local file larger than published -- restarting", flush=True)
        dest.unlink()
        have = 0

    headers = {"Range": f"bytes={have}-"} if have else {}
    mode = "ab" if have else "wb"
    if have:
        print(f"  {year}: resuming at {have / 2**30:.2f} of "
              f"{total / 2**30:.2f} GB", flush=True)

    t0, last = time.time(), have
    with session.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, mode) as fh:
            for chunk in r.iter_content(CHUNK):
                fh.write(chunk)
                have += len(chunk)
                if have - last > 256 * 2**20:
                    el = time.time() - t0
                    print(f"    {year}: {have / 2**30:.2f}/{total / 2**30:.2f} GB "
                          f"({have / 2**30 / max(el, 1) * 60:.1f} GB/min)", flush=True)
                    last = have

    # A truncated archive that unpacks "successfully" is the worst outcome, so
    # the size check happens before anything touches it.
    got = dest.stat().st_size
    if total and got != total:
        print(f"  {year}: SHORT -- {got} bytes, expected {total}. "
              f"Re-run to resume.", flush=True)
        return None
    return dest


def extract(year: int, zip_path: Path) -> bool:
    """Unpack the year's GeoTIFF via a staging directory."""
    root = cdl_root()
    tif_dir, tmp = root / "tif", root / "tmp" / str(year)
    tif_dir.mkdir(parents=True, exist_ok=True)
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".tif")]
            if not names:
                print(f"  {year}: no .tif inside the archive", flush=True)
                return False
            # Largest member is the national raster; smaller ones are ancillary.
            name = max(names, key=lambda n: zf.getinfo(n).file_size)
            zf.extract(name, tmp)
            src = tmp / name
    except zipfile.BadZipFile:
        print(f"  {year}: archive is corrupt -- delete {zip_path} and re-run",
              flush=True)
        return False

    staged = tif_dir / f"{year}_30m_cdls.tif"
    # Move into place only once it is whole, so nothing ever sees a partial file
    # at the final path.
    shutil.move(str(src), str(staged))
    shutil.rmtree(root / "tmp" / str(year), ignore_errors=True)

    if not readable(staged):
        print(f"  {year}: extracted file will not open -- removing", flush=True)
        staged.unlink(missing_ok=True)
        return False
    return True


def status() -> int:
    root = cdl_root()
    print(f"CDL store: {root}")
    if not root.exists():
        print("  (nothing downloaded yet)")
        return 0
    years = available_years()
    print(f"  usable years: {years or 'none'}")
    for sub in ("raw", "tif", "tmp"):
        d = root / sub
        if not d.is_dir():
            continue
        n = sum(1 for _ in d.rglob("*") if _.is_file())
        gb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 2**30
        print(f"  {sub + '/':6s} {n:3d} files, {gb:6.2f} GB")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs="+", type=int, default=DEFAULT_YEARS)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--keep-zip", action="store_true",
                    help="keep the archives after extracting (default: delete)")
    args = ap.parse_args(argv)

    if args.status:
        return status()

    root = cdl_root()
    root.mkdir(parents=True, exist_ok=True)
    print(f"CDL store: {root}\nYears: {args.years}\n", flush=True)

    session, failed = _session(), []
    for year in args.years:
        if readable(year_tif(year)):
            print(f"  {year}: already present", flush=True)
            continue
        print(f"  {year}: fetching {CDL_URL.format(year=year)}", flush=True)
        zip_path = fetch(year, session)
        if zip_path is None or not extract(year, zip_path):
            failed.append(year)
            continue
        if not args.keep_zip:
            zip_path.unlink(missing_ok=True)
        print(f"  {year}: ready", flush=True)

    print()
    status()
    if failed:
        print(f"\n{len(failed)} year(s) FAILED: {failed}. Re-run to resume.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
