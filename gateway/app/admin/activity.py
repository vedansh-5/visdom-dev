# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Asks the visdom instances who is connected to each workspace right now.

A workspace is "active" when someone is reading from or writing to it, which is
socket state living in the visdom processes rather than anything in this
database. The proxy hashes each workspace onto exactly one instance, so no
instance sees the whole picture and the answer is the concatenation of all of
them. Instances are asked directly over the internal network rather than through
the proxy, which would hash the request onto a single one.
"""

import concurrent.futures
import json
import logging
import re
import time
import urllib.error
import urllib.request

from app.config import settings

_SERVER_PATTERN = re.compile(r"server\s+([^\s;]+)")


def instance_addresses() -> list[str]:
    """The visdom instances to ask, read from the nginx upstream block.

    `VISDOM_SERVERS` is nginx syntax ("server visdom-1:8097 resolve;") because
    the proxy config is generated from it. Parsing it here keeps one list of
    instances rather than a second one that can drift out of step with the first.
    """
    return _SERVER_PATTERN.findall(settings.VISDOM_SERVERS or "")


def _ask(address: str, timeout: float) -> tuple[bool, list[dict]]:
    """One instance's answer, and whether it gave one at all.

    The two are separate because an instance that answers with nothing about a
    workspace is saying the workspace has never been written to, while an
    instance that does not answer is saying nothing at all. A page that cannot
    tell those apart has to call both of them unknown.
    """
    url = f"http://{address}/vis/_activity"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read() or b"{}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logging.warning("could not read activity from %s: %s", address, exc)
        return False, []
    return True, payload.get("workspaces", [])


_CACHE_TTL = 2.0
_cache: dict = {"at": 0.0, "value": {"answered": False, "workspaces": {}}}


def cached_snapshot() -> dict:
    """`activity_snapshot` behind a short cache.

    One list page renders many rows and each wants the same answer, so without
    this a fifty row page would fan out fifty times. The window is short enough
    that a page still shows what is happening now.
    """
    now = time.monotonic()
    if now - _cache["at"] < _CACHE_TTL:
        return _cache["value"]
    value = activity_snapshot()
    _cache["at"] = now
    _cache["value"] = value
    return value


def cached_activity() -> dict[str, dict]:
    """Just the per-workspace part of the cached snapshot."""
    return cached_snapshot()["workspaces"]


def _combine(merged: dict[str, dict], workspace_id: str, entry: dict) -> None:
    """Fold one instance's answer for a workspace into the running total.

    Every instance shares the env volume, so all of them report every workspace
    that has a directory, while only the one serving it has any sockets. Letting
    the last answer win would therefore overwrite real viewer counts with the
    zeroes reported by the instances that merely see the files.

    Counts add up, since a workspace is served by one instance and the others
    contribute nothing. That holds for the running totals as well as the live
    counts: a workspace moves between instances when one restarts, and the work
    each did is a share of the same total rather than a rival answer to it.
    Everything else takes the most informative answer: the latest write, the
    largest size, and a slug from whichever instance has actually bound the
    workspace and knows it.

    A counter absent from every instance stays absent, so a deployment running a
    visdom that predates them reports nothing rather than a fabricated zero.
    """
    current = merged.get(workspace_id)
    if current is None:
        merged[workspace_id] = dict(entry)
        return

    for key in ("viewers", "writers", "writes", "broadcasts", "broadcast_bytes"):
        mine, theirs = current.get(key), entry.get(key)
        if mine is None and theirs is None:
            continue
        current[key] = (mine or 0) + (theirs or 0)
    current["slug"] = current.get("slug") or entry.get("slug")
    for key in ("last_active_at", "bytes"):
        mine, theirs = current.get(key), entry.get(key)
        if theirs is not None and (mine is None or theirs > mine):
            current[key] = theirs


def activity_snapshot(timeout: float | None = None) -> dict:
    """What the instances collectively know, and whether any of them answered.

    An instance that does not answer is skipped rather than failing the whole
    call, so one sick instance costs its workspaces' counts instead of the page.
    `answered` is true once any instance has replied, which is what lets a
    caller read a missing workspace as one nobody has written to. Every instance
    shares the env volume, so any one of them reports every workspace that has a
    directory, and a workspace missing from an answer really has none.
    """
    addresses = instance_addresses()
    if not addresses:
        return {"answered": False, "workspaces": {}}
    if timeout is None:
        timeout = settings.VISDOM_ACTIVITY_TIMEOUT

    answered = False
    merged: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(addresses)) as pool:
        for ok, entries in pool.map(lambda a: _ask(a, timeout), addresses):
            answered = answered or ok
            for entry in entries:
                workspace_id = entry.get("workspace_id")
                if workspace_id:
                    _combine(merged, workspace_id, entry)
    return {"answered": answered, "workspaces": merged}


def activity_by_workspace(timeout: float | None = None) -> dict[str, dict]:
    """Live viewer/writer counts keyed by workspace id, across all instances."""
    return activity_snapshot(timeout)["workspaces"]


def evict_workspace(slug: str, reason: str | None = None, timeout: float | None = None) -> int:
    """Ask every instance to close the sockets it holds for a workspace.

    Every instance is asked rather than only the one the proxy currently hashes
    the workspace onto. Sockets outlive a reassignment, so the instance holding
    them may no longer be the one serving new connections, and asking the wrong
    one would leave exactly the sockets this is meant to close.

    Best effort on purpose. The refusal at resolve time is what actually
    withdraws a workspace; this only decides whether it takes effect now or at
    the next resolve, so an instance that cannot be reached costs promptness
    rather than correctness.
    """
    addresses = instance_addresses()
    if not addresses or not slug:
        return 0
    if timeout is None:
        timeout = settings.VISDOM_ACTIVITY_TIMEOUT

    payload = {"workspace_slug": slug}
    if reason:
        payload["reason"] = reason
    body = json.dumps(payload).encode()

    closed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(addresses)) as pool:
        for count in pool.map(lambda a: _tell(a, body, timeout), addresses):
            closed += count
    return closed


def _tell(address: str, body: bytes, timeout: float) -> int:
    """One instance's answer to an eviction, or zero when it did not give one."""
    request = urllib.request.Request(
        f"http://{address}/vis/_evict",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(json.loads(response.read() or b"{}").get("closed", 0))
    except (urllib.error.URLError, OSError, ValueError, TypeError) as exc:
        logging.warning("could not evict %s on %s: %s", body, address, exc)
        return 0
