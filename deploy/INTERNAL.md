# The internal port

Each visdom instance serves `/_activity`, `/_metrics`, `/_evict`, `/_retire`
and `/_drop` on a second port,
`VISDOM_INTERNAL_PORT` (8098). nginx never forwards it and compose does not
publish it, so only containers on the stack's network can reach it. On top of
that, every request is signed and the port only speaks TLS.

## Signing

There are two keys. The gateway signs reads (`/_activity`) with
`VISDOM_INTERNAL_READ_KEY`, and everything that closes sockets or removes data
(`/_evict`, `/_retire`, `/_drop`) with `VISDOM_INTERNAL_ADMIN_KEY`. A read key
can never delete anything. Compose hands each key to the instances along with
its `_PREVIOUS` one. A signature is good for 60 seconds.

Make each key with `openssl rand -hex 32`. Compose refuses to start without
them, and the gateway sends nothing until the read key and `internal-ca.pem`
are in place; `/api/v1/health/components` names what is missing. To replace one:

1. Copy the current key into its `_PREVIOUS` setting and put a new one in its
   place.
2. `docker compose up -d` recreates the instances and the gateway with both.
3. Clear the `_PREVIOUS` setting and run `docker compose up -d` again.

## TLS

The instances share one self-signed certificate, and the gateway trusts only
that certificate. Make it before the first `docker compose up`:

```bash
deploy/internal-cert.sh new
```

It writes `deploy/internal-tls/`, which is not in git: the certificate and key
the instances serve, and `internal-ca.pem`, the certificates the gateway
trusts. The certificate is good for two years. `/api/v1/health/components`
reports the days left and turns degraded 30 days before the end.

To replace it:

1. `deploy/internal-cert.sh new`. The old certificate moves to
   `internal.previous.crt` and stays in `internal-ca.pem`, so the gateway trusts
   both. The gateway reads that file on every call, so it needs no restart.
2. `docker compose up -d --force-recreate visdom-1 visdom-2 visdom-3`, so the
   instances serve the new one.
3. `deploy/internal-cert.sh drop-previous`.
