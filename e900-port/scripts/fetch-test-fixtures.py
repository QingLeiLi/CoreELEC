#!/usr/bin/env python3
"""Fetch public pinned GPL source fixtures; verify both Git SHA-1 and SHA-256."""
import base64
import concurrent.futures
import hashlib
import json
import os
import pathlib
import time
import urllib.request

root = pathlib.Path(__file__).resolve().parents[1]
audit = pathlib.Path(os.environ["E900_AUDIT_ROOT"])
manifest = json.loads((root / "tests/source-fixtures.json").read_text())
audit.mkdir(parents=True, exist_ok=True)


def fetch(row):
    destination = audit / "sources" / row["path"].replace("/", "__")
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == row["sha256"]:
        return
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "e900-coreelec-ci"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    url = f'https://api.github.com/repos/{row["repo"]}/git/blobs/{row["git_blob_sha1"]}'
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=45) as response:
                obj = json.load(response)
            data = base64.b64decode(obj["content"])
            actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            assert actual == row["git_blob_sha1"]
            assert hashlib.sha256(data).hexdigest() == row["sha256"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    list(executor.map(fetch, manifest))
(audit / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"Verified {len(manifest)} public source fixtures")
