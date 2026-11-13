# ADR 0002: Publish external frontend connection details through a separate relation endpoint

- **Date:** 2026-11-10
- **Issue:** [#156](https://github.com/canonical/temporal-k8s-operator/issues/156)
- **PR:** [#209](https://github.com/canonical/temporal-k8s-operator/pull/209) (open at the time of writing)
- **Affects:** temporal-k8s, temporal-worker-k8s, temporal-admin-k8s

## Context

[ADR 0001](0001-tls-aware-in-model-frontend-clients.md) made
`temporal-host-info` publish the public frontend's in-cluster service address,
`<app>.<model>.svc.cluster.local:7233`, and whether that listener serves TLS.
That address works for clients on the same Kubernetes cluster, including
clients in another Juju model, but is not reachable from a different cluster.

Cross-model relations distribute connection details; they do not make
cluster-local DNS or networking accessible to a remote worker or admin charm.
Those clients need the ingress listener's host, port and TLS state, which can
differ from the backend frontend listener's settings.

Replacing the address on `temporal-host-info` would change the route used by
existing in-cluster clients. Publishing two addresses in one relation would
instead require every consumer to understand a new schema and choose an
address. The existing `temporal-host-info` interface already carries the three
fields needed to describe either listener.

## Decision

### 1. Add a separate endpoint using the existing interface

`temporal-k8s` provides two endpoints implementing `temporal-host-info`:

| Provider endpoint | Intended clients | Published listener |
|---|---|---|
| `temporal-host-info` | Same Kubernetes cluster, in the same or another model | In-cluster frontend, port `7233` |
| `temporal-external-host-info` | Different Kubernetes cluster | HTTPS ingress listener (TLS required) |

Operators choose the route by choosing the provider endpoint to integrate or
offer. A worker or admin charm keeps its existing `temporal-host-info` requirer
endpoint when consuming either one. No consumer-side address-selection config
or second connection-data schema is introduced.

The internal endpoint's host, port and frontend TLS signal remain unchanged.
The external route still reaches the public frontend through ingress; it does
not expose the authorization-bypassing internal-frontend listener.

HTTPS/TLS is mandatory for this external ingress deployment: it serves
Temporal's gRPC API over HTTP/2, so the ingress listener must support HTTP/2
over TLS and external clients must dial TLS. This is a requirement of the
external ingress path, not of gRPC itself, which can also run over cleartext
HTTP/2 (`h2c`).

### 2. Derive external connection details from ready ingress

The external endpoint uses the URL returned by the `ingress` relation only
when ingress reports that it is ready. It publishes application relation data
in the existing wire format:

| Field | Source | Example |
|---|---|---|
| `host` | Ingress URL hostname, without scheme or path | `temporal.example.com` |
| `port` | Explicit URL port, otherwise `443` for HTTPS or `80` for HTTP | `"443"` |
| `tls` | Whether the ingress URL scheme is `https` | `"true"` |

An explicit listener port is preserved, and bracketed IPv6 URLs are parsed
into a host without brackets. Only HTTP and HTTPS URLs with a hostname are
accepted. Malformed URLs, including invalid ports, are logged and treated as
an unavailable endpoint.

Although the parser accepts HTTP URLs and publishes their corresponding port
and `tls=false`, that does not make plaintext ingress a supported deployment
for this external gRPC endpoint. Operators must configure HTTPS ingress;
the expected external signal is `tls=true`.

The external `tls` signal describes the client-to-ingress connection, not the
ingress-to-frontend connection. Frontend certificate availability must not
independently change that signal.

### 3. Withdraw unavailable connection details instead of publishing a fallback

Before ingress is ready, the external endpoint publishes no connection details.
When ingress is revoked or its URL becomes unavailable or malformed, the
provider removes `host`, `port` and `tls` from existing relation data. Ingress
ready and revoked events refresh the external details and publish or withdraw
them without requiring an event on the host-info relation.

There is no fallback to a relation binding address, pod IP, internal service
DNS name or `external-hostname` config. Such a fallback would advertise an
address that is not necessarily reachable from another cluster and could leave
clients using the wrong port or TLS mode.

The requirer emits `temporal_host_info_unavailable` when required connection
fields are missing, including when previously published data is withdrawn.
Consumers can therefore react to loss of ingress instead of retaining stale
connection details.

### 4. Extend the shared provider without changing its default endpoint

`temporal_host_info` LIBPATCH 4 adds an optional `relation_name` argument to
`TemporalHostInfoProvider`, defaulting to `temporal-host-info`. Separate
provider instances have distinct framework object keys and publish only to
their configured endpoints.

An omitted or empty literal `host` retains the library's binding-address
fallback. A supplied host callable returning no host instead means the endpoint
is unavailable and withdraws its connection details. The charm uses this
callable for the external endpoint and refreshes host, port and TLS together
before publishing. Publication remains leader-only and limited to applications
configured to serve the frontend.

### 5. Keep certificate trust distribution separate

The relation carries a TLS signal, not a CA certificate. External clients must
trust the CA that signed the ingress listener's certificate and verify the
published hostname, which must be covered by that certificate.

For the worker, operators set `tls-root-cas` to the ingress CA bundle. For the
admin charm, operators integrate `receive-ca-cert` with the ingress
certificate's CA provider. The frontend's backend CA is not necessarily the
correct trust root for an external client.

## Delivery and validation

PR #209 adds the endpoint to charm metadata and the Terraform `provides` output
as `temporal_external_host_info`, extends the shared library, and wires ingress
events to publication. The [worker tutorial](../tutorial/07-deploy-worker.md)
and [admin tutorial](../tutorial/05-deploy-admin.md) describe endpoint selection,
cross-model offers and ingress CA configuration.

The PR adds scenario and unit coverage for URL parsing, default and explicit
ports, IPv6, TLS state, ingress changes and removal, unavailable endpoints,
stale-data withdrawal, and requirer unavailable events. It also checks that
the internal endpoint remains independent. An ingress integration test asserts
the advertised host, port and TLS fields seen by an admin requirer.

## Consequences

### Positive

- Remote clients can discover the ingress listener using the existing
  interface, without changing the route for in-cluster clients.
- Listener address, port and TLS mode follow ingress changes together.
- Loss of ingress is explicit rather than hidden behind a cluster-local
  fallback or stale relation data.
- Juju offers and Terraform outputs expose the same endpoint choice.

### Negative

- Operators must choose the endpoint appropriate to the client's cluster;
  being in another Juju model alone does not imply that ingress is needed.
- External discovery depends on ready ingress. Direct externally routable
  frontend addresses without ingress are not supported by this endpoint.
- External ingress requires HTTPS/TLS and HTTP/2 support for the gRPC API;
  accepting an HTTP URL in relation data does not validate that requirement.
- Certificate trust still requires separate operator configuration.
- Relation data describes a listener; it does not guarantee that remote DNS,
  network access, certificate trust or authorization is correctly configured.

## Alternatives considered

- **Replace the internal address with ingress on `temporal-host-info`.**
  Changes existing clients' routing and makes them depend on ingress. Rejected.
- **Publish both addresses in one relation and add consumer selection config.**
  Requires a new schema and consumer changes for information the existing
  interface can already represent. Rejected in favour of endpoint selection.
- **Fall back to a pod IP or binding address when ingress is absent.**
  Does not establish external reachability and obscures endpoint loss. Rejected.
- **Derive external TLS from frontend certificates.**
  Confuses the backend listener with the client-facing ingress listener.
  Rejected.
- **Carry the ingress CA in host-info.**
  Adds certificate distribution to a connection-discovery interface. Rejected
  in favour of the existing trust-configuration mechanisms.

## Out of scope

- Making cluster-local addresses reachable across clusters.
- Exposing internal-frontend or changing frontend authorization.
- Automatic CA distribution, consumer TLS support changes, or certificate SAN
  management for the ingress listener.
- Publishing externally routable addresses without the `ingress` relation.
