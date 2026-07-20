# Configure ingress with the `ingress` interface

Charmed Temporal's frontend can be exposed to clients outside the cluster through the
standard `ingress` interface. The Temporal frontend is a **gRPC (HTTP/2)** server, so it
is exposed through the [Ingress Configurator](https://charmhub.io/ingress-configurator)
fronted by [HAProxy](https://charmhub.io/haproxy), which handles gRPC load balancing over
TLS.

[note]

**gRPC through ingress requires TLS end-to-end.** The supported providers do **not**
support plaintext HTTP/2 (h2c) to the backend, so the Temporal frontend must terminate
TLS itself. Concretely: the `frontend-certificates` relation is **required** alongside
`ingress` (the frontend then serves gRPC over TLS and the charm always advertises the
`https` scheme), and the proxy re-encrypts to it. The charm enforces this: relating
`ingress` without `frontend-certificates` blocks the unit rather than falling back to a
cleartext (h2c) scheme the supported providers can't use. Only the `frontend` service can
be exposed, and only one ingress solution can be used at a time.

[/note]

## Prerequisites

* A **TLS certificate provider** charm (for example
  [self-signed-certificates](https://charmhub.io/self-signed-certificates)) - one instance
  on the Kubernetes model (for the frontend cert) and one where HAProxy runs (for the
  client-facing cert).
* **HAProxy** (`2.8/edge` or later). HAProxy is a machine charm, so it runs on a separate
  machine model and is related to the Kubernetes applications through a **cross-model
  integration**.
* Network reachability from HAProxy to the Temporal frontend's Kubernetes endpoint (see
  [Backend reachability](#backend-reachability)).
* The [Temporal CLI snap](https://snapcraft.io/temporal) for connecting as a client.

Throughout this guide the routing hostname is `temporal-k8s.test`; substitute your own.

## 1. Make the frontend serve gRPC over TLS

On the Kubernetes model, give the Temporal frontend a certificate so it terminates TLS on
its gRPC port:

```
juju deploy self-signed-certificates
juju integrate temporal-k8s:frontend-certificates self-signed-certificates:certificates
```

Verify the frontend is now serving TLS (ALPN negotiates HTTP/2):

```
juju ssh --container temporal temporal-k8s/0 grep -nE 'certFile|keyFile' /etc/temporal/config/charm.yaml
```

## 2. Deploy and configure the Ingress Configurator (Kubernetes model)

```
juju deploy ingress-configurator --channel latest/edge --trust
juju integrate temporal-k8s:ingress ingress-configurator:ingress
juju config ingress-configurator hostname=temporal-k8s.test backend-protocol=https
```

`backend-protocol=https` tells the proxy to connect to the frontend over TLS. Setting
`external-grpc-port` is optional (gRPC is served on `443` by default).

## 3. Deploy and configure HAProxy (machine model)

On the machine model:

```
juju deploy haproxy --channel 2.8/edge
juju deploy self-signed-certificates
juju integrate haproxy:certificates self-signed-certificates
juju config haproxy external-hostname=temporal-k8s.test
```

[note]

`external-hostname` is required - without it HAProxy never requests its own client-facing
certificate and its `:443` listener fails to validate ("unable to stat SSL certificate").

[/note]

## 4. Wire the cross-model integrations

HAProxy (machine) and the Kubernetes applications live on different models, so use offers.
`juju offer` is run from the offering model (no controller prefix); `juju consume` uses the
fully-qualified `<controller>:admin/<model>.<application>` offer URL.

Route the ingress traffic to HAProxy:

```
# machine model
juju offer haproxy:haproxy-route
# kubernetes model
juju consume <machine-controller>:admin/<machine-model>.haproxy haproxy-cmr
juju integrate ingress-configurator:haproxy-route haproxy-cmr
```

Let HAProxy trust the **frontend's** CA so the re-encrypted backend hop verifies (the CA is
the certificate provider on the Kubernetes model):

```
# kubernetes model
juju offer self-signed-certificates:send-ca-cert
# machine model
juju consume <k8s-controller>:admin/<k8s-model>.self-signed-certificates frontend-ca
juju integrate haproxy:receive-ca-certs frontend-ca
```

## Backend reachability

HAProxy must be able to reach the Temporal frontend's Kubernetes address. If HAProxy cannot
route to the frontend's `ClusterIP`, expose the frontend on a routable address (for example
a `NodePort` or `LoadBalancer` service) and point the configurator at it:

```
juju config ingress-configurator backend-addresses=<node-ip> backend-ports=<node-port>
```

## 5. Connect a client

Map the routing hostname to HAProxy's public address, then connect over TLS. Fetch the CA
that signed HAProxy's client-facing certificate (the certificate provider on the machine
model) and pass it to the client:

```
echo "<haproxy-ip> temporal-k8s.test" | sudo tee -a /etc/hosts

temporal operator namespace list \
  --address temporal-k8s.test:443 \
  --tls \
  --tls-ca-path <haproxy-ca>
```

The full path is TLS end-to-end: client → HAProxy (TLS) → Temporal frontend (TLS), with
HAProxy verifying the frontend against the CA received in step 4.

## Other ingress providers

The `ingress` interface is provider-agnostic, so `temporal-k8s:ingress` can be related to
any charm that implements it.

* [traefik-k8s](https://charmhub.io/traefik-k8s) is approaching end-of-life; it may work
  but is not part of our test suite and is left to the user to configure.
* The [Gateway API Integrator](https://charmhub.io/gateway-api-integrator) implements the
  same interface, but gRPC over TLS additionally needs the gateway to negotiate the `h2`
  ALPN protocol. On Canonical Kubernetes the bundled Cilium gateway does not currently
  expose ALPN configuration, so this path is not supported there.
