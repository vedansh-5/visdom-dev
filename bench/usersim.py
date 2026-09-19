#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Several people using visdom.dev at once, driven from your own machine.

Each simulated person registers (or signs back in), makes a workspace, mints an API
key, and then runs training-shaped experiments through the visdom python client, which
is what a real training script runs. While the experiments write, the same session
polls the console the way an open dashboard does. Nothing here talks to the database
or the box: it is the public API and the public visdom endpoint, so the load lands on
the deployment and the generator's own CPU stays on your laptop.

  python bench/usersim.py run --users 4 --minutes 10
  python bench/usersim.py teardown

`run` prints the sign-in details and the visualization URL for every person it made,
so you can open two browsers and watch different workspaces fill at the same time.
Ctrl-C stops early and still prints the summary.

The manifest (default ~/.visdom-loadgen.json) holds API keys in plain text. It stays
outside the repository for that reason, and `teardown` revokes the keys and trashes
the workspaces it names. The accounts themselves stay: there is no delete-account
endpoint yet, and they are free-tier accounts with a recognisable email domain.

Needs the client from the tester quickstart, the same one testers install:

  python3 -m venv ~/.venvs/visdom-client
  source ~/.venvs/visdom-client/bin/activate
  python -m pip install "git+https://github.com/vedansh-5/visdom.git@dev" numpy requests
"""

import argparse
import json
import os
import random
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

try:
    import numpy as np
    import requests
except ImportError as exc:
    sys.exit("usersim: %s. See the install lines at the top of this file." % exc)

try:
    import visdom
except ImportError:
    sys.exit(
        "usersim: no visdom client on this python. Install the fork's dev branch:\n"
        "  python3 -m venv ~/.venvs/visdom-client\n"
        "  source ~/.venvs/visdom-client/bin/activate\n"
        '  python -m pip install "git+https://github.com/vedansh-5/visdom.git@dev" numpy requests'
    )

TIMEOUT = 20
STOP = threading.Event()
DEFAULT_MANIFEST = os.path.expanduser("~/.visdom-loadgen.json")


class Totals:
    """Writes and failures across every experiment, counted under one lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.writes = 0
        self.failures = 0
        self.reasons = {}

    def wrote(self, n=1):
        with self.lock:
            self.writes += n

    def failed(self, reason):
        with self.lock:
            self.failures += 1
            short = str(reason)[:120]
            self.reasons[short] = self.reasons.get(short, 0) + 1

    def snapshot(self):
        with self.lock:
            return self.writes, self.failures, dict(self.reasons)


class Person:
    """One account, its session, its workspaces and their keys."""

    def __init__(self, base, email, password):
        self.base = base.rstrip("/")
        self.api = self.base + "/api/v1"
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.token = None
        self.workspaces = []

    def headers(self):
        return {"Authorization": "Bearer %s" % self.token}

    def sign_up_or_in(self):
        created = self.session.post(
            self.api + "/auth/register",
            json={"email": self.email, "password": self.password},
            timeout=TIMEOUT,
        )
        if created.status_code not in (201, 400):
            raise RuntimeError("register %s -> %d: %s" % (self.email, created.status_code, created.text[:200]))
        signed_in = self.session.post(
            self.api + "/auth/login",
            data={"username": self.email, "password": self.password},
            timeout=TIMEOUT,
        )
        if signed_in.status_code != 200:
            raise RuntimeError(
                "sign in as %s -> %d: %s. If this account exists with another password, "
                "pass --password." % (self.email, signed_in.status_code, signed_in.text[:200])
            )
        self.token = signed_in.json()["access_token"]
        return created.status_code == 201

    def mine(self):
        listed = self.session.get(self.api + "/workspaces", headers=self.headers(), timeout=TIMEOUT)
        listed.raise_for_status()
        return listed.json()

    def workspace(self, slug):
        for existing in self.mine():
            if existing["slug"] == slug:
                return existing["id"]
        made = self.session.post(
            self.api + "/workspaces",
            json={"name": slug, "slug": slug},
            headers=self.headers(),
            timeout=TIMEOUT,
        )
        if made.status_code == 402:
            raise RuntimeError(
                "%s is at its plan's workspace limit. Lower --workspaces, or raise this "
                "account's plan in the admin console." % self.email
            )
        if made.status_code != 201:
            raise RuntimeError("create %s -> %d: %s" % (slug, made.status_code, made.text[:200]))
        return made.json()["id"]

    def key_for(self, slug, workspace_id):
        made = self.session.post(
            self.api + "/keys",
            json={"name": slug, "scope": "workspace", "workspace_ids": [workspace_id]},
            headers=self.headers(),
            timeout=TIMEOUT,
        )
        if made.status_code == 402:
            raise RuntimeError(
                "%s is at its plan's API key limit. Revoke old keys, or run teardown "
                "from an earlier run." % self.email
            )
        if made.status_code != 201:
            raise RuntimeError("create key for %s -> %d: %s" % (slug, made.status_code, made.text[:200]))
        body = made.json()
        return body["id"], body["raw_key"]

    def set_up(self, prefix, per_user, index):
        fresh = self.sign_up_or_in()
        for n in range(per_user):
            slug = "%s-%d-%d" % (prefix, index, n) if per_user > 1 else "%s-%d" % (prefix, index)
            workspace_id = self.workspace(slug)
            key_id, raw_key = self.key_for(slug, workspace_id)
            self.workspaces.append(
                {"slug": slug, "workspace_id": workspace_id, "key_id": key_id, "key": raw_key}
            )
        return fresh

    def browse(self, totals):
        """What an open console asks for while someone watches their plots."""
        while not STOP.is_set():
            for path in ("/workspaces", "/usage"):
                try:
                    answered = self.session.get(self.api + path, headers=self.headers(), timeout=TIMEOUT)
                    if answered.status_code == 401:
                        self.sign_up_or_in()
                    elif answered.status_code >= 400:
                        totals.failed("console %s -> %d" % (path, answered.status_code))
                except requests.RequestException as exc:
                    totals.failed("console %s: %s" % (path, exc))
            STOP.wait(15)


class Checked(visdom.Visdom):
    """The stock client reads the body without looking at the status, so a run of
    refusals would report throughput. Raise on anything that is not a 200."""

    def _handle_post(self, url, data=None):
        answered = self.session.post(url, data=data or {}, timeout=(TIMEOUT, None))
        if answered.status_code != 200:
            raise RuntimeError("POST %s -> %d: %s" % (url, answered.status_code, answered.text[:200]))
        return answered.text


def client_for(base, workspace):
    parts = base.rstrip("/").split("://")
    scheme = parts[0] if len(parts) == 2 else "http"
    host = parts[-1].split("/")[0]
    port = 443 if scheme == "https" else 80
    if ":" in host:
        host, _, given = host.partition(":")
        port = int(given)
    return Checked(
        server="%s://%s" % (scheme, host),
        port=port,
        base_url="/vis",
        api_key=workspace["key"],
        workspace=workspace["slug"],
        use_incoming_socket=False,
        raise_exceptions=True,
    )


def experiment(base, workspace, env, rate, until, totals):
    """One training script: two curves, a status panel, a heatmap and sample images."""
    try:
        client = client_for(base, workspace)
    except Exception as exc:
        totals.failed("connect %s: %s" % (workspace["slug"], exc))
        return

    step = 0
    loss = 1.2 + random.random()
    accuracy = 0.15 + random.random() / 10
    while not STOP.is_set() and time.time() < until:
        started = time.time()
        loss = max(0.01, loss * (0.99 + random.uniform(-0.012, 0.006)))
        accuracy = min(0.995, accuracy + random.uniform(0, 0.008))
        try:
            client.line(
                X=[step], Y=[loss], win="loss", update="append", env=env,
                opts={"title": "training loss", "xlabel": "step"},
            )
            client.line(
                X=[step], Y=[accuracy], win="accuracy", update="append", env=env,
                opts={"title": "validation accuracy", "xlabel": "step"},
            )
            written = 2
            if step % 10 == 0:
                client.text(
                    "step %d<br>loss %.4f<br>accuracy %.3f" % (step, loss, accuracy),
                    win="status", env=env,
                )
                written += 1
            if step % 25 == 0:
                client.heatmap(
                    np.random.rand(16, 16), win="attention", env=env,
                    opts={"title": "attention, layer 3"},
                )
                written += 1
            if step % 50 == 0:
                client.image(
                    np.random.rand(3, 64, 64), win="sample", env=env,
                    opts={"title": "sample batch"},
                )
                written += 1
            totals.wrote(written)
        except Exception as exc:
            totals.failed(exc)
            STOP.wait(2)
        step += 1
        STOP.wait(max(0.0, (1.0 / rate) - (time.time() - started)))


def progress(totals, until):
    last = 0
    while not STOP.is_set() and time.time() < until:
        STOP.wait(10)
        writes, failures, _ = totals.snapshot()
        left = max(0, int(until - time.time()))
        print(
            "  %5d writes (%4.1f/s over the last 10s), %d failed, %ds left"
            % (writes, (writes - last) / 10.0, failures, left),
            flush=True,
        )
        last = writes


def save(manifest, payload):
    with open(manifest, "w") as handle:
        json.dump(payload, handle, indent=2)
    os.chmod(manifest, 0o600)


def run(args):
    base = args.base.rstrip("/")
    people = []
    print("Setting up %d %s on %s" % (args.users, "person" if args.users == 1 else "people", base))
    for index in range(args.users):
        person = Person(base, "%s-%d@%s" % (args.prefix, index, args.email_domain), args.password)
        try:
            fresh = person.set_up(args.prefix, args.workspaces, index)
        except (RuntimeError, requests.RequestException) as exc:
            if people:
                save(args.manifest, manifest_of(base, args.password, people))
                print("Saved what was created to %s; run teardown to remove it." % args.manifest)
            sys.exit("usersim: %s" % exc)
        people.append(person)
        print("  %s (%s)" % (person.email, "new account" if fresh else "existing account"))

    save(args.manifest, manifest_of(base, args.password, people))

    print("\nSign in at %s/login with the password %r:" % (base, args.password))
    for person in people:
        for workspace in person.workspaces:
            print("  %-34s %s/vis/w/%s/" % (person.email, base, workspace["slug"]))

    streams = [
        (person, workspace, "%s-%d" % (args.env_name, n))
        for person in people
        for workspace in person.workspaces
        for n in range(args.envs)
    ]
    until = time.time() + args.minutes * 60
    totals = Totals()
    print(
        "\nRunning %d experiments at ~%g updates a second each for %g minutes. Ctrl-C to stop.\n"
        % (len(streams), args.rate, args.minutes),
        flush=True,
    )

    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    started = time.time()
    with ThreadPoolExecutor(max_workers=len(streams) + len(people) + 1) as pool:
        for person in people:
            pool.submit(person.browse, totals)
        for person, workspace, env in streams:
            pool.submit(experiment, base, workspace, env, args.rate, until, totals)
        pool.submit(progress, totals, until)
        while not STOP.is_set() and time.time() < until:
            time.sleep(0.5)
        STOP.set()

    writes, failures, reasons = totals.snapshot()
    elapsed = max(1e-6, time.time() - started)
    print(
        "\n%d writes in %.0fs (%.1f/s), %d failed" % (writes, elapsed, writes / elapsed, failures)
    )
    for reason, count in sorted(reasons.items(), key=lambda pair: -pair[1])[:5]:
        print("  %4d x %s" % (count, reason))
    print("\nWorkspaces and keys are in %s. Remove them with:" % args.manifest)
    print("  python bench/usersim.py teardown --manifest %s" % args.manifest)
    return 1 if failures else 0


def manifest_of(base, password, people):
    return {
        "base": base,
        "password": password,
        "people": [
            {"email": person.email, "workspaces": person.workspaces} for person in people
        ],
    }


def teardown(args):
    try:
        with open(args.manifest) as handle:
            saved = json.load(handle)
    except OSError as exc:
        sys.exit("usersim: cannot read %s: %s" % (args.manifest, exc))

    base = saved["base"]
    failures = 0
    removed = 0
    for entry in saved["people"]:
        person = Person(base, entry["email"], saved["password"])
        try:
            person.sign_up_or_in()
        except (RuntimeError, requests.RequestException) as exc:
            failures += 1
            print("  %s: %s" % (entry["email"], exc))
            continue
        for workspace in entry["workspaces"]:
            for path in ("/keys/%s" % workspace["key_id"], "/workspaces/%s" % workspace["workspace_id"]):
                answered = person.session.delete(
                    person.api + path, headers=person.headers(), timeout=TIMEOUT
                )
                if answered.status_code not in (204, 404):
                    failures += 1
                    print("  DELETE %s -> %d: %s" % (path, answered.status_code, answered.text[:160]))
            removed += 1

    print("Removed %d workspaces and their keys, %d failures." % (removed, failures))
    print("The accounts stay; there is no delete-account endpoint yet.")
    if not failures:
        os.remove(args.manifest)
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description="Drive visdom.dev as several people at once.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="where the keys are recorded")
    sub = parser.add_subparsers(dest="command", required=True)

    runner = sub.add_parser("run")
    runner.add_argument("--base", default="https://visdom.dev")
    runner.add_argument("--users", type=int, default=3)
    runner.add_argument("--workspaces", type=int, default=1, help="per person; the free plan allows 1")
    runner.add_argument("--envs", type=int, default=2, help="experiments per workspace")
    runner.add_argument("--rate", type=float, default=2.0, help="updates a second per experiment")
    runner.add_argument("--minutes", type=float, default=10.0)
    runner.add_argument("--prefix", default="loadgen")
    runner.add_argument("--email-domain", default="loadgen.visdom.dev")
    runner.add_argument("--password", default="loadgen-password")
    runner.add_argument("--env-name", default="run")
    runner.set_defaults(func=run)

    remover = sub.add_parser("teardown")
    remover.set_defaults(func=teardown)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
