#!/usr/bin/env python3
"""The restore drill's data, and the performance pass's numbers. The deployment.

CI's "Clean machine" job brings the stack up by following docs/deploy/README.md
step by step. This script is the part a stranger would do with a browser: put
something into the app before the backup, and check it is all there after the
restore. It is the only part of that job that is not the guide's own commands.

    python3 scripts/drill.py write --base https://localhost --cacert cert.pem --state drill.json
    python3 scripts/drill.py verify --base https://localhost --cacert cert.pem --state drill.json
    python3 scripts/drill.py measure --base https://localhost --cacert cert.pem --out perf.md

``write`` creates a specimen, uploads a photograph of it through
``POST /specimens/{id}/photos``, and completes a task, then records the ids and
the photograph's SHA-256 in the state file. ``verify`` reads them back through
the API and fails, naming what is missing, unless the specimen, the
photograph's exact bytes and the task's completion all came back.

``measure`` times the routes an earlier release names against the live stack and writes p50
and p95 as a Markdown table. No target is applied: the numbers are the result.

Standard library only, so it runs on a bare runner or a bare server. It reads
no secret and prints no response body that could hold one; the API it talks to
holds no credential of the household's in any response these routes give.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import statistics
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib
from pathlib import Path

API = "/api/v1"

#: The routes the earlier performance pass names, and the web app's first load.
MEASURED = [
    ("GET /tending/rounds", f"{API}/tending/rounds"),
    ("GET /specimens", f"{API}/specimens"),
    ("GET /journal/plates", f"{API}/journal/plates"),
    ("GET /hub/lunette", f"{API}/hub/lunette"),
    ("web app, first load (GET /)", "/"),
]


class Client:
    def __init__(self, base: str, cacert: str | None) -> None:
        self.base = base.rstrip("/")
        self.context = ssl.create_default_context(cafile=cacert) if cacert else None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        expect: tuple[int, ...] = (200,),
    ) -> tuple[int, bytes]:
        req = urllib.request.Request(
            self.base + path, data=body, method=method, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=30) as resp:
                status, data = resp.status, resp.read()
        except urllib.error.HTTPError as error:
            status, data = error.code, error.read()
        if status not in expect:
            # The status and the first of the body: enough to act on. These
            # routes carry no credential, and a 422's detail is the useful bit.
            raise SystemExit(
                f"{method} {path} answered {status}, expected {expect}: "
                f"{data[:400].decode('utf-8', 'replace')}"
            )
        return status, data

    def json(self, method: str, path: str, payload=None, expect=(200,)):
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"} if body is not None else {}
        _, data = self.request(method, path, body=body, headers=headers, expect=expect)
        return json.loads(data) if data else None


def png(seed: bytes) -> bytes:
    """A small, valid PNG whose pixels come from ``seed``, so its bytes are unique."""
    width = height = 16
    pixels = hashlib.shake_256(seed).digest(width * height * 3)
    rows = b"".join(
        b"\x00" + pixels[y * width * 3 : (y + 1) * width * 3] for y in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def multipart(fields: dict[str, str], name: str, filename: str, data: bytes):
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
        f'filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), {
        "Content-Type": f"multipart/form-data; boundary={boundary}"
    }


def write(client: Client, state_path: Path) -> None:
    mark = uuid.uuid4().hex[:12]

    # A species and a location the household already has, so the new plant is
    # schedulable. Taken from an existing specimen rather than hard-coded.
    page = client.json("GET", f"{API}/specimens?limit=50")
    existing = [s for s in page["items"] if s.get("species", {}) and s.get("location")]
    if not existing:
        raise SystemExit("No specimen with a species and a location to copy from.")
    model = existing[0]
    specimen = client.json(
        "POST",
        f"{API}/specimens",
        {
            "name": model["species"]["accepted_name"],
            "species_id": model["species"]["id"],
            "location_id": model["location"]["id"],
            "nickname": f"Restore drill {mark}",
        },
        expect=(201,),
    )

    image = png(mark.encode())
    body, headers = multipart(
        {"caption": f"restore drill {mark}"}, "file", "drill.png", image
    )
    _, raw = client.request(
        "POST",
        f"{API}/specimens/{specimen['id']}/photos",
        body=body,
        headers=headers,
        expect=(201,),
    )
    photo = json.loads(raw)

    # Any task that is due. The round generates them from the household's care
    # values; the fixture household always has some.
    client.json("GET", f"{API}/tending/rounds")
    due = client.json("GET", f"{API}/tending/tasks?status=due")
    if not due:
        raise SystemExit("No task is due, so there is nothing to complete.")
    task = client.json(
        "POST",
        f"{API}/tending/tasks/{due[0]['id']}/complete",
        {"notes": f"restore drill {mark}"},
    )
    if task["status"] != "done":
        raise SystemExit(f"Completing task {task['id']} left it {task['status']!r}.")

    state = {
        "specimen_id": specimen["id"],
        "nickname": specimen["nickname"],
        "photo_id": photo["id"],
        "photo_url": photo["url"],
        "photo_sha256": hashlib.sha256(image).hexdigest(),
        "photo_bytes": len(image),
        "task_id": task["id"],
        "task_completed_at": task.get("completed_at"),
    }
    state_path.write_text(json.dumps(state, indent=2))
    print(
        f"wrote specimen {state['specimen_id']}, photograph {state['photo_id']} "
        f"({state['photo_bytes']} bytes), completed task {state['task_id']}"
    )


def photo_path(url: str) -> str:
    """The photograph's URL as a path under this origin."""
    if url.startswith("http"):
        url = "/" + url.split("://", 1)[1].split("/", 1)[1]
    return url if url.startswith((API, "/api/")) else API + url


def verify(client: Client, state_path: Path) -> None:
    state = json.loads(state_path.read_text())
    failures = []

    specimen = client.json(
        "GET", f"{API}/specimens/{state['specimen_id']}", expect=(200, 404)
    )
    if not specimen or specimen.get("id") != state["specimen_id"]:
        failures.append(f"specimen {state['specimen_id']} did not come back")
    elif specimen.get("nickname") != state["nickname"]:
        failures.append(f"specimen came back as {specimen.get('nickname')!r}")

    photos = client.json(
        "GET", f"{API}/specimens/{state['specimen_id']}/photos", expect=(200, 404)
    )
    if not photos or state["photo_id"] not in {p["id"] for p in photos}:
        failures.append(f"photograph {state['photo_id']} is not listed")
    status, data = client.request(
        "GET", photo_path(state["photo_url"]), expect=(200, 404, 503)
    )
    digest = hashlib.sha256(data).hexdigest()
    if status != 200:
        failures.append(f"the photograph's image answers {status}")
    elif digest != state["photo_sha256"]:
        failures.append(
            f"the photograph's bytes differ ({len(data)} bytes, sha256 {digest[:12]}…)"
        )

    tasks = client.json("GET", f"{API}/tending/tasks?status=done")
    done = {t["id"]: t for t in tasks}
    if state["task_id"] not in done:
        failures.append(f"task {state['task_id']} is no longer done")

    if failures:
        raise SystemExit("The restore lost data:\n  " + "\n  ".join(failures))
    print(
        f"restored: specimen {state['specimen_id']} ({state['nickname']}), "
        f"photograph {state['photo_id']} byte-identical "
        f"(sha256 {state['photo_sha256'][:12]}…), task {state['task_id']} done"
    )


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, round(fraction * len(ordered)) - 1))
    return ordered[index]


def measure(client: Client, out: Path, runs: int, warmup: int) -> None:
    lines = [
        "| Route | p50 (ms) | p95 (ms) | max (ms) | runs |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for label, path in MEASURED:
        for _ in range(warmup):
            client.request("GET", path)
        samples = []
        for _ in range(runs):
            start = time.perf_counter()
            client.request("GET", path)
            samples.append((time.perf_counter() - start) * 1000)
        lines.append(
            f"| {label} | {statistics.median(samples):.1f} | "
            f"{percentile(samples, 0.95):.1f} | {max(samples):.1f} | {runs} |"
        )
    table = "\n".join(lines) + "\n"
    out.write_text(table)
    print(table)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=["write", "verify", "measure"])
    parser.add_argument("--base", default="https://localhost")
    parser.add_argument("--cacert", default=os.environ.get("MOH_DRILL_CACERT"))
    parser.add_argument("--state", type=Path, default=Path("drill.json"))
    parser.add_argument("--out", type=Path, default=Path("perf.md"))
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=10)
    args = parser.parse_args()

    client = Client(args.base, args.cacert)
    if args.action == "write":
        write(client, args.state)
    elif args.action == "verify":
        verify(client, args.state)
    else:
        measure(client, args.out, args.runs, args.warmup)
    return 0


if __name__ == "__main__":
    sys.exit(main())
