#!/usr/bin/env python3
"""Create a new version of the CERFRES record on Zenodo from a folder of release files.

The access token is read from the ZENODO_TOKEN environment variable and needs the deposit:write
and deposit:actions scopes. Without --publish the new version stays a draft for review. Publishing
cannot be undone, because Zenodo does not allow published files to change.

Files of the previous version that are named in --keep stay in the new version. All others are
removed. Upload failures can be retried by running the script again with --draft-id.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import requests

API = "https://zenodo.org/api"
PREVIOUS_RECORD = 21479427


def session_from_env() -> requests.Session:
    token = os.environ.get("ZENODO_TOKEN")
    if not token:
        sys.exit("Set the ZENODO_TOKEN environment variable first.")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    return session


def check(response: requests.Response) -> dict:
    if not response.ok:
        sys.exit(f"Zenodo returned {response.status_code} for {response.url}: {response.text[:1000]}")
    return response.json() if response.content else {}


def file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fin:
        for block in iter(lambda: fin.read(1 << 24), b""):
            digest.update(block)
    return digest.hexdigest()


def create_draft(session: requests.Session) -> dict:
    version = check(session.post(f"{API}/deposit/depositions/{PREVIOUS_RECORD}/actions/newversion"))
    return check(session.get(version["links"]["latest_draft"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=Path, required=True, help="Folder with the files to upload")
    parser.add_argument("--version", required=True)
    parser.add_argument("--description", type=Path, required=True, help="HTML description")
    parser.add_argument("--publication-date", required=True)
    parser.add_argument("--keep", nargs="*", default=["validation.zip"])
    parser.add_argument("--draft-id", type=int, default=None, help="Continue an existing draft")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument(
        "--create-only",
        action="store_true",
        help="Create the draft and remove old files, then stop, so storage can be assigned before uploading",
    )
    args = parser.parse_args()
    if args.create_only and args.publish:
        sys.exit("--create-only and --publish cannot be combined.")

    uploads = sorted(path for path in args.files.iterdir() if path.is_file())
    if not uploads:
        sys.exit(f"No files in {args.files}")

    session = session_from_env()
    if args.draft_id:
        draft = check(session.get(f"{API}/deposit/depositions/{args.draft_id}"))
    else:
        draft = create_draft(session)
    print(f"Draft {draft['id']}: {draft['links']['html']}", flush=True)

    wanted = {path.name for path in uploads}
    existing = {item["filename"]: item for item in draft.get("files", [])}
    for name, item in existing.items():
        if name not in wanted and name not in args.keep:
            check(session.delete(item["links"]["self"]))
            print(f"Removed {name}", flush=True)

    if args.create_only:
        total = sum(path.stat().st_size for path in uploads)
        print(f"Draft id {draft['id']}. Files to upload: {len(uploads)}, {total / 1e9:.1f} GB.", flush=True)
        print(f"Kept from the previous version: {sorted(set(existing) & set(args.keep))}", flush=True)
        return

    bucket = draft["links"]["bucket"]
    for path in uploads:
        md5 = file_md5(path)
        present = existing.get(path.name)
        if present is not None and str(present.get("checksum", "")).removeprefix("md5:") == md5:
            print(f"Already uploaded: {path.name}", flush=True)
            continue
        with path.open("rb") as fin:
            result = check(session.put(f"{bucket}/{path.name}", data=fin, timeout=None))
        remote = str(result.get("checksum", "")).removeprefix("md5:")
        if remote != md5:
            sys.exit(f"Checksum mismatch for {path.name}: {md5} local, {remote} on Zenodo")
        print(f"Uploaded {path.name}", flush=True)

    metadata = draft["metadata"]
    metadata["version"] = args.version
    metadata["publication_date"] = args.publication_date
    metadata["description"] = args.description.read_text(encoding="utf-8")
    metadata.pop("doi", None)
    metadata.pop("prereserve_doi", None)
    check(
        session.put(
            draft["links"]["self"],
            data=json.dumps({"metadata": metadata}),
            headers={"Content-Type": "application/json"},
        )
    )
    print("Metadata updated.", flush=True)

    if args.publish:
        published = check(session.post(draft["links"]["publish"]))
        print(f"Published: https://doi.org/{published['doi']}", flush=True)
    else:
        print(f"Draft ready for review: {draft['links']['html']}", flush=True)


if __name__ == "__main__":
    main()
