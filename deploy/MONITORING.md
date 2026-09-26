# Knowing when something is broken

Today the deployment being down is discovered by a person noticing. These are
the two checks that replace noticing, and both are free.

## 1. Is the site up and usable

There are two endpoints, and they answer different questions.

| Endpoint | Asks | Use it for |
|---|---|---|
| `/api/v1/health` | is the gateway up and is the database reachable | a frequent, cheap poll |
| `/api/v1/health/components` | that, plus is every visdom instance answering | the alert that matters |

The second one exists because the first stays green in a state that is useless
to a user: the console loads, sign-in works, and not one plot does, because the
visdom instances behind nginx are down. `/components` answers **503** when any
part is unhealthy, so an uptime check that only looks at the status code still
catches it.

A healthy answer:

```json
{"status": "healthy", "checks": {"database": "ok", "visdom": "3 of 3 answering"}}
```

**Setting it up**, about five minutes: make a free account at uptimerobot.com or
betterstack.com, add an HTTPS monitor on
`https://visdom.dev/api/v1/health/components`, every 5 minutes, alert on any
non-200, and put your email and a phone number on it. Nothing else to configure,
and no credentials involved.

## 2. Did the backup run

An uptime check cannot tell you the box is alive but the nightly backup stopped.
That needs a dead man's switch: something that expects to hear from the job, and
shouts when it does not.

Make a check at healthchecks.io, period 1 day, grace 6 hours, and put its ping
URL in `PING_URL` in `/etc/visdom-backup.env`. The backup script pings it on
success and pings the `/fail` variant on failure, so you hear about a broken run
and about a run that never happened. See `BACKUPS.md`.

## When an alert fires

```bash
ssh ubuntu@140.245.2.74
cd ~/app/visdom-dev
curl -s localhost:8080/api/v1/health/components   # which part is unhappy
docker compose ps                                  # what is not running
docker compose logs --since 30m gateway | tail -50
docker compose logs --since 30m visdom-1 | tail -50
df -h /                                            # a full disk looks like everything else
```

Most of what has gone wrong so far has been one container down or the disk
filling with build cache. `docker compose up -d` brings back the first;
`docker builder prune -f` fixes the second.

## What is still not watched

- **The usage sampler.** If it stops, metering silently stops with it, and
  nothing here would say so. Catching it needs the last tick recorded somewhere
  a check can read, which means a migration, so it is a separate piece of work.
- **Certificate expiry.** Caddy renews on its own, and an expired certificate
  would show up as the uptime check failing, which is late but not silent.
- **Slow.** These checks are up or down only. A deployment that answers every
  request in nine seconds is "up" to both of them.
