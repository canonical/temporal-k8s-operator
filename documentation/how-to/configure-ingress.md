# Configure ingress with the `ingress` interface

Charmed Temporal's frontend can be exposed to clients outside the cluster through the
standard `ingress` interface. The recommended provider is the
[Gateway API Integrator](https://charmhub.io/gateway-api-integrator), which manages
external access through Kubernetes `Gateway` and `HTTPRoute` resources.

## Prerequisites

This guide is agnostic to the underlying Kubernetes distribution. Before you start, make
sure your environment provides:

* A **Gateway API implementation** that exposes a `GatewayClass` (for example Cilium,
  Istio or Envoy Gateway). See the
  [Gateway API implementations list](https://gateway-api.sigs.k8s.io/implementations/) to
  choose and install one, and note the name of the `GatewayClass` it provides.
* A **load balancer**, so the `Gateway` is assigned an external IP address.
* A **TLS certificate provider** charm (for example
  [self-signed-certificates](https://charmhub.io/self-signed-certificates)) to terminate
  TLS at the gateway.
* The [Temporal CLI snap](https://snapcraft.io/temporal) for connecting as a client.

[note]

Only the `frontend` service can be exposed through ingress. Integrating a non-frontend
deployment sends the charm into a blocked state, and only one ingress solution can be
used at a time.

The Temporal frontend is a gRPC (HTTP/2) server, so over the `ingress` relation the charm
advertises the `h2c` (HTTP/2 cleartext) scheme: the frontend serves cleartext gRPC and
TLS is terminated at the ingress. Terminating TLS at the frontend instead (the
`frontend-certificates` relation) is **not compatible** with the `ingress` relation - the
provider forwards cleartext to the backend, so a TLS-terminating frontend would reject
those connections. Relating both `ingress` and `frontend-certificates` therefore blocks
the charm; terminate TLS at the ingress **or** at the frontend, but not both. See
[Frontend TLS](https://charmhub.io/temporal-k8s/docs/h-frontend-tls) for the
frontend-terminated option.

[/note]

## Expose the Temporal Server with the Gateway API Integrator

Because the Temporal frontend is a gRPC server that needs host-based routing, it is
exposed through the [Ingress Configurator](https://charmhub.io/ingress-configurator),
which sits between the charm and the Gateway API Integrator and configures the hostname
and gRPC routing. The integrator terminates TLS and creates the `Gateway` and `HTTPRoute`
resources.

1. Deploy the ingress chain:

```
juju deploy gateway-api-integrator --trust
juju deploy ingress-configurator
juju deploy self-signed-certificates
```

2. Configure the gateway class and the routing hostname. Set `gateway-class` to the
`GatewayClass` provided by your cluster (for example `ck-gateway` on Canonical Kubernetes,
or `cilium` for an upstream Cilium install):

```
juju config gateway-api-integrator gateway-class=<your-gateway-class> external-hostname=temporal-k8s.test
juju config ingress-configurator hostname=temporal-k8s.test backend-protocol=http
```

3. Integrate the chain:

```
juju integrate self-signed-certificates:certificates gateway-api-integrator:certificates
juju integrate ingress-configurator:gateway-route     gateway-api-integrator:gateway-route
juju integrate temporal-k8s:ingress                   ingress-configurator:ingress
```

4. The gateway's external IP address is shown in the integrator's status message
(`Gateway addresses: <ip>` in `juju status`). TLS is terminated at the gateway, so clients
connect over TLS using the configured hostname (resolve it to the gateway IP). For example,
with the Temporal CLI snap:

```
temporal operator namespace list --address temporal-k8s.test:443 --tls-server-name temporal-k8s.test --tls-ca-path <gateway CA>
```

## Other ingress providers

The `ingress` interface is provider-agnostic, so `temporal-k8s:ingress` can be related to
any charm that implements it, such as [traefik-k8s](https://charmhub.io/traefik-k8s):

```
juju integrate temporal-k8s:ingress traefik-k8s:ingress
```

[note]

traefik-k8s is approaching end-of-life. This path may work, but configuring it (for
example, enabling host-based routing for the gRPC frontend) is left to the user, and it is
not part of our test suite.

[/note]
