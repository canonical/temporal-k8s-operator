# ADR 0001: Make in-model frontend clients TLS-aware

- **Date:** 2026-10-02
- **Issue:** [#152](https://github.com/canonical/temporal-k8s-operator/issues/152)
- **Affects:** temporal-k8s, temporal-ui-k8s, temporal-admin-k8s, temporal-worker-k8s

## Context

PR #141 exposed Temporal's gRPC frontend through the `ingress` interface and
made `frontend-certificates` mandatory whenever `ingress` is related, because
ingress-configurator + HAProxy only proxy HTTP/2 to a TLS backend
(`backend-protocol=https`).

The frontend has a single gRPC listener (`:7233`) with a single TLS setting.
Turning TLS on for the ingress hop turns it on for **every** client of that
listener, including the in-model ones:

- **temporal-ui-k8s**, which learns the frontend address over
  `temporal-host-info`. The interface only carried `host` and `port`, so the UI
  kept dialling plaintext and failed with
  `error reading server preface: EOF` (HTTP 503).
- **temporal-admin-k8s**, whose `tctl`/`temporal` actions dial the same
  frontend and fail the same way.
- **temporal-worker-k8s**, which also takes the frontend address from
  `temporal-host-info`. The charm doesn't read a TLS signal; it passes its
  `tls-root-cas` config to the worker workload (`TEMPORAL_TLS_ROOT_CAS`), and
  the workload dials the frontend accordingly.

Relations stay healthy, so `juju status` reports everything `active`; only the
runtime gRPC dial fails, which no test exercised.

Two further defects block any client that does switch to TLS:

1. The frontend certificate's SANs were `frontend-cert-sans-dns` **or** the unit
   FQDN, never the in-cluster service name that internal clients dial.
2. When no ingress address was available, `temporal-host-info` published the
   pod IP from `binding.network.bind_address`. A pod IP is unstable across
   restarts and cannot be covered by a DNS SAN.

Facts that shaped the decision:

- **This is server-side TLS, not mTLS.** `FRONTEND_TLS_CONFIGURATION` pins
  `TEMPORAL_TLS_REQUIRE_CLIENT_AUTH: "false"`. Clients must dial TLS and trust
  the CA; they never present a certificate.
- **TLS is not always required for ingress.** It is required by the HAProxy
  path, but Traefik's ingress library accepts an `h2c` scheme, so a Traefik
  deployment can keep the frontend plaintext. The HAProxy limitation lives in
  the charm, not in HAProxy itself, which supports cleartext HTTP/2 backends.
- **internal-frontend (`:7236`) bypasses authorization.** It skips the
  Authorizer and ClaimMapper and grants admin access. Upstream's Helm chart
  points admin tooling at it by default; it is not meant for user-facing
  clients.

## Decision

### 1. TLS is a published signal, not an assumption

The frontend serves TLS if, and only if, a frontend certificate is
**available** (not merely related), and that state is published to every
consumer that needs it:

- `temporal-host-info` gains a `tls` boolean (library LIBPATCH 1 → 2). The
  provider accepts `tls` as a callable, because the certificates relation is
  unknown at charm init, and exposes a public `publish()` that the charm calls
  whenever TLS state changes. A missing field reads as `False`, so requirers
  talking to an older provider keep today's plaintext behaviour.
- The ingress scheme is derived from the same state: `https` when the
  certificate is available, `h2c` otherwise.
- `_update` republishes both `temporal-host-info` and the ingress requirements,
  because neither library observes the certificates relation.
- `_validate_ingress` **warns** instead of blocking when `ingress` is related
  without `frontend-certificates`, so the Traefik/h2c topology is valid again.

Keying on availability rather than relation presence means clients are never
told `tls=true` while the frontend is still serving plaintext.

"Available" means precisely: `frontend-certificates` is related **and** the
certificates library returns both a certificate and a private key assigned to
the charm's *current* certificate request (`get_assigned_certificate` with the
current CSR attributes).

The flip side: whenever the library reports no assigned certificate, the
frontend falls back to plaintext and `tls=false` is published with it. The
previously stored certificate files are not used. This happens on a transient
library failure, and also while a new certificate is being issued after the
request changes (for example, after `frontend-cert-sans-dns` is updated).

### 2. The UI keeps dialling the public frontend (`:7233`)

An in-tree `FIXME` had pointed `temporal-host-info` at internal-frontend
(`:7236`). That fixed the admin CLI but routed the UI around the Authorizer,
inverting `auth-enabled` for a client that acts on behalf of human users. It is
reverted: `temporal-host-info` publishes `:7233` again.

### 3. The CA reaches the UI over `certificate_transfer`

temporal-ui-k8s gains an optional `receive-ca-cert` relation
(`certificate_transfer`, `limit: 1`), integrated directly with the `send-ca-cert`
endpoint of the TLS provider that issues the frontend certificate (for example
`self-signed-certificates:send-ca-cert`). The CA is the public half of the
issuer, not secret material. temporal-k8s does not forward it.

This mirrors how HAProxy already receives the frontend CA over
`receive-ca-certs`, keeps temporal-k8s out of CA distribution, and leaves
rotation to the provider and the standard interface.

The operator must integrate the UI with the same provider that issues the
frontend certificate. Nothing in the charms enforces that pairing; a mismatch
surfaces as `x509: certificate signed by unknown authority` and is covered in
the documentation.

`temporal-host-info` carries only the `tls` boolean, because the UI needs to know
*whether* to dial TLS even when no CA is related. The CA itself travels over the
standard interface, which already handles distribution and rotation.

On the UI side, the CA bundle is written to a fixed path and referenced via
`caFile` in the rendered config, with `enableHostVerification: true` so the UI
verifies both the CA and the hostname it dials (which decision 4 makes
possible). A hash of the bundle is added to the Pebble
environment so that a rotated CA restarts the workload even though the path
does not change. The relation is optional so that a plaintext deployment stays
valid; the charm blocks only when `tls=true` and no CA is present.

### 4. The charm owns both the published address and the certificate SANs

`temporal-host-info` serves in-model clients, so it publishes the frontend's
in-cluster address: `<app>.<model>.svc.cluster.local` and `:7233`. The published
host and the names in the frontend certificate must agree, or hostname
verification fails, so both come from the charm:

- By default, the frontend certificate requests the unit FQDN and
  `<app>.<model>.svc.cluster.local`.
- `frontend-cert-sans-dns` still **replaces** the defaults rather than adding to
  them. Some certificate providers (public CAs, Vault roles restricted by
  `allowed_domains`) refuse internal names such as `*.svc.cluster.local` and
  reject the whole request, so operators using them must be able to request
  public names only. Operators whose provider allows internal names add
  `<app>.<model>.svc.cluster.local` to the list themselves, and the charm logs a
  warning when it is missing.
- `TemporalHostInfoProvider` accepts an optional `host` (a value or a callable,
  like `tls`), and the charm passes `<app>.<model>.svc.cluster.local`. The
  library stops reading `external-hostname`: that option exists for the
  `nginx-route` interface only and is due to be removed. Without a `host`, the
  library falls back to the binding address, so it carries no Kubernetes
  naming assumptions.

This is a prerequisite for any TLS client to verify the frontend, and is
tracked as a follow-up to the `tls` signal rather than shipped with it.

Requirers outside the cluster, such as workers related from another
Kubernetes cluster, cannot reach the in-cluster address. They need the ingress
endpoint, which has its own host, port and CA. Publishing it alongside the
internal address is planned as a separate, additive change to
`temporal-host-info`; see "Out of scope".

## Delivery

The decisions land as separate, independently safe changes, in this order:

1. **Library `tls` signal:** `temporal_host_info` LIBPATCH 2 adds the `tls`
   field and `publish()`. Nothing changes for existing requirers (decision 1).
2. **Certificate SANs:** the frontend certificate defaults to the unit FQDN and
   the in-cluster service FQDN (decision 4).
3. **Published host:** `temporal_host_info` LIBPATCH 3 accepts a charm-supplied
   `host` and stops reading `external-hostname`; the charm publishes the
   in-cluster service FQDN (decision 4).
4. **Ingress scheme:** the scheme follows TLS state and ingress without
   `frontend-certificates` warns instead of blocking, so Traefik works without
   certificates. Independent of the other steps (decision 1).
5. **Documentation:** relating the UI to the TLS provider's `send-ca-cert`,
   including the service FQDN when setting `frontend-cert-sans-dns`, and the
   published host (decisions 3 and 4).
6. **UI:** temporal-ui-k8s consumes `tls` and receives the CA from the TLS
   provider (decision 3).
7. **Charm wiring:** temporal-k8s publishes `:7233` and passes `tls`
   (decisions 1 and 2).
8. **Admin:** temporal-admin-k8s gets the same changes as the UI: it reads `tls`
   from `temporal-host-info` and receives the CA over `certificate_transfer`
   directly from the TLS provider (decisions 1 and 3).

Steps 2 and 3 must land before the UI can verify the frontend. The UI (step 6)
must be released before the charm wiring (step 7) turns the `tls` signal on.
The admin CLI fails against a TLS frontend from step 7 until step 8 is
released.

## Consequences

### Positive

- The UI works against a TLS frontend, which closes #152 once the
  temporal-ui-k8s change ships.
- Both ingress topologies are supported: HAProxy with end-to-end TLS, and
  Traefik with h2c.
- The UI keeps going through the Authorizer, so `auth-enabled` keeps its
  meaning.
- Older providers and requirers keep working, because absent fields default to
  plaintext.

### Negative

- Operators running a TLS frontend relate one extra integration
  (`<tls-provider>:send-ca-cert` → `temporal-ui-k8s:receive-ca-cert`).
- The UI only works with TLS providers that offer `send-ca-cert`, and nothing
  ties the CA it trusts to the certificate the frontend serves; pairing them
  correctly is left to the operator.
- The fix spans three repositories. temporal-ui-k8s must re-vendor
  `temporal_host_info` at LIBPATCH 2 before it can read `tls`.
- Operators who set `frontend-cert-sans-dns` must include
  `<app>.<model>.svc.cluster.local` for the UI to verify the frontend. With a
  certificate provider that refuses internal names, in-model clients can't
  verify the frontend by hostname at all; a `tls_server_name` on
  `temporal-host-info` would be needed, and is deferred until someone needs it.
- Once decision 4 lands, requirers receive the service DNS name instead of the
  pod IP or `external-hostname`. A requirer outside the cluster that relied on
  `external-hostname` loses its only reachable address until the external
  endpoint is published.
- Until temporal-admin-k8s gets the same changes as the UI (Delivery step 8),
  its CLI actions fail against a TLS frontend, since `temporal-host-info` no
  longer points it at internal-frontend.
- After the charm wiring (Delivery step 7), a temporal-worker-k8s in the same
  cluster is pointed at the frontend (`:7233`) instead of internal-frontend
  (`:7236`), and fails against a TLS frontend unless it dials TLS. Operators
  must set `tls-root-cas` on the worker to the PEM bundle of the CA that issued
  the frontend certificate, so the workload dials TLS and trusts it:
  `juju config temporal-worker-k8s tls-root-cas="$(cat ca-bundle.pem)"`. The
  worker dials the published in-cluster service FQDN, which the frontend
  certificate names by default (decision 4). Giving the worker the same `tls`
  signal and `certificate_transfer` relation as the UI is a possible follow-up.

### Failure modes

The changes are coupled; shipping only some of them moves the error rather than
removing it:

| State | Error |
|---|---|
| UI plaintext, server TLS | `error reading server preface: EOF` → HTTP 503 |
| UI TLS, server plaintext | `transport: authentication handshake failed` |
| UI TLS, no CA | `x509: certificate signed by unknown authority` |
| UI TLS, CA present, SAN mismatch | `x509: certificate is valid for A, not B` |

Each row needs a test on the UI side, plus an integration test asserting
`GET /api/v1/namespaces` returns 200, in both TLS and plaintext variants.

## Alternatives considered

- **Publish the CA on `temporal-host-info`.** Fewer relations, but it
  reimplements CA distribution and rotation that `certificate_transfer` already
  provides. Rejected.
- **Point the UI at internal-frontend (`:7236`).** Avoids TLS entirely but
  bypasses authorization for user-driven requests. Rejected.
- **Skip certificate verification in the UI.** Weak, and not cleanly exposed by
  the UI's configuration. Rejected.
- **Keep blocking ingress without `frontend-certificates`.** Correct for
  HAProxy, but makes the working Traefik/h2c topology impossible. Rejected.
- **Forward the CA from temporal-k8s over its own `send-ca-cert`.** Guarantees
  the CA matches the certificate the frontend serves and works with providers
  that lack `send-ca-cert`, but adds CA distribution to temporal-k8s and departs
  from the pattern HAProxy already uses. Rejected.
- **Always add the in-cluster names to the certificate, on top of
  `frontend-cert-sans-dns`.** Removes a configuration step, but any provider
  that refuses internal names would then reject every request, leaving the
  frontend with no certificate at all. Rejected.
- **Hard-code the service-name fallback in the library.** Simpler, but it puts
  Kubernetes naming in a shared library while the SAN list lives in the charm,
  so the two could drift. It also changes the published host for every
  requirer as a side effect of a library bump. Rejected in favour of a
  charm-supplied `host`.
- **Have HAProxy talk h2c to the backend.** Would make frontend TLS optional
  for every topology, but needs a `backend-protocol=h2c` option in
  ingress-configurator that does not exist yet. To be requested upstream; not a
  substitute for this fix.

## Out of scope

- **An external endpoint on `temporal-host-info`.** Requirers outside the
  cluster need the ingress address (host and port from the ingress, and the
  ingress's CA), published alongside the internal one. Each requirer chooses
  which to use: the UI and admin always use the internal endpoint, while the
  worker gets a config option. Tracked separately.
