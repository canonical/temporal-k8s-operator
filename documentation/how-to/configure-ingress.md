# Configure ingress with Nginx Ingress Integrator

Charmed Temporal components can be exposed through an ingress solution to make them available to clients outside the cluster and to handle TLS termination.
In the Charming ecosystem, the [Nginx Ingress Integrator](https://charmhub.io/nginx-ingress-integrator)
operator allows different applications to request `Ingress` resources from an underlying ingress controller.

## Enable ingress

### Requirements

To follow this guide, consider having a Kubernetes cluster with the following configured:

* Ingress controller: If using Kubernetes (K8s), the [nginx ingress controller](https://docs.nginx.com/nginx-ingress-controller/installation/installing-nic/installation-with-manifests) can be installed; if using MicroK8s, the `ingress` addon should suffice.
* LoadBalancer: If using K8s, the [default LoadBalancer](https://documentation.ubuntu.com/canonical-kubernetes/latest/snap/howto/networking/default-loadbalancer/) works; on MicroK8s, the `metallb` addon should suffice.
* [Temporal Command Line Interface (CLI) snap](https://snapcraft.io/temporal).

[note]

The `nginx-ingress-integrator` only allows one integration per `ingress` and `nginx-route` integration.
Charmed Temporal is not designed to share the same integrator instance, and thus, an integrator
charm per application must be deployed.

See [Support multiple relations](https://charmhub.io/nginx-ingress-integrator/docs/support-multiple-relations) for more details.

[/note]

### Expose the Temporal Server

1. Deploy the integrator charm:

```
juju deploy nginx-ingress-integrator temporal-server-ingress --trust
```

2. Check your cluster's `IngressClass`:

```
kubectl get ingressclass

NAME             CONTROLLER                  PARAMETERS   AGE
nginx            k8s.io/ingress-nginx        <none>       12d
```

3. Configure the integrator's `ingress-class` using the name from the previous step:

```
juju config temporal-server-ingress ingress-class nginx
```

4. Configure `backend-protocol`. Temporal server, specifically its frontend, is a `gRPC` server:

```
juju config temporal-server-ingress backend-protocol GRPC
```

5. Integrate and configure:

```
juju config temporal-k8s tls-secret-name=""
juju integrate temporal-k8s temporal-server-ingress
```

6. Connect with clients. Assuming a `LoadBalancer` is enabled, and because the Temporal Server works with
host-based routing, DNS resolution must be set up. For example:

```
cat /etc/hosts/
[...]
<LOADBALANCER-IP> temporal-k8s

temporal operator namespace list --address temporal-k8s:80
[...]
```

### Expose Temporal UI

1. Deploy the integrator charm:

```
juju deploy nginx-ingress-integrator temporal-ui-ingress --trust
```

2. Check your cluster's `IngressClass`:

```
kubectl get ingressclass

NAME             CONTROLLER                  PARAMETERS   AGE
nginx            k8s.io/ingress-nginx        <none>       12d
```

3. Configure the integrator's `ingress-class` using the name from the previous step:

```
juju config temporal-server-ingress ingress-class nginx
```

4. Configure the integrator's `backend-protocol`:

```
juju config temporal-ui-ingress backend-protocol HTTP
```

5. Integrate:

```
juju config temporal-ui-k8s tls-secret-name=""
juju integrate temporal-ui-k8s temporal-ui-ingress
```

6. Access the Temporal UI on a web browser. Assuming a `LoadBalancer` is enabled, and because of Temporal's
host-based routing, DNS resolution must be set up. For example:

```
cat /etc/hosts/
[...]
<LOADBALANCER-IP> temporal-ui-k8s

http://temporal-ui-k8s:80/
```

## Enable TLS termination at ingress

The integrator charm provides a way to perform TLS termination at ingress in conjunction with the ecosystem's TLS providers.
Please refer to [Security with X.509 certificates](https://charmhub.io/topics/security-with-x-509-certificates) to understand
the different certificate use cases and choose the solution that best fits each one.

### Temporal Server

1. Reconfigure the integrator charm for a secured backend:


```
juju config temporal-server-ingress backend-protocol GRPCS
```

2. Integrate the integrator charm with a TLS certificate provider:

```
juju integrate temporal-server-ingress <tls-certificate-provider>
```

3. Get the Certificate Authority (CA) certificate from the TLS certificate provider charm and use it in further requests. For example,
using the temporal CLI snap:

```
temporal operator namespace list --address temporal-k8s:443 --tls-ca-path <path to CA cert>
```

### Temporal UI

1. Reconfigure the integrator charm for a secured backend

```
juju config temporal-ui-ingress backend-protocol HTTPS
```

2. Integrate the integrator charm with a TLS certificate provider:

```
juju integrate temporal-ui-ingress <tls-certificate-provider>
```

3. Use `https` when browsing, and and configure certificate trust settings as needed.

## Configure ingress through the `ingress` interface (Traefik / Gateway API)

As an alternative to the `nginx-route` interface, the Temporal Server frontend can
be exposed through the standard `ingress` interface. This works with any provider
that implements it, such as [Traefik](https://charmhub.io/traefik-k8s) and the
[Gateway API Integrator](https://charmhub.io/gateway-api-integrator), which manages
external access via Kubernetes `Gateway` and `HTTPRoute` resources.

[note]

Only the `frontend` service can be exposed through ingress. Integrating a non-frontend
deployment will send the charm into a blocked state. As with `nginx-route`, only one
ingress solution can be used at a time - relating both `ingress` and `nginx-route`
blocks the charm.

The Temporal frontend is a gRPC (HTTP/2) server. Over the `ingress` relation the charm
advertises the `h2c` (HTTP/2 cleartext) scheme, meaning the frontend serves cleartext
gRPC and TLS is terminated at the ingress. Terminating TLS at the frontend instead (the
`frontend-certificates` relation) is **not compatible** with the `ingress` relation:
providers such as Traefik and the Gateway API Integrator forward cleartext to the
backend, so a TLS-terminating frontend would reject those connections. Relating both
`ingress` and `frontend-certificates` therefore blocks the charm - terminate TLS at the
ingress or at the frontend, but not both. See [Frontend TLS](https://charmhub.io/temporal-k8s/docs/h-frontend-tls)
for the frontend-terminated option.

[/note]

### Expose the Temporal Server with the Gateway API Integrator

Because the Temporal frontend is a gRPC server that needs host-based routing, it is
exposed through the [Ingress Configurator](https://charmhub.io/ingress-configurator),
which sits between the charm and the
[Gateway API Integrator](https://charmhub.io/gateway-api-integrator) and configures the
hostname and gRPC routing. The integrator terminates TLS and creates the Kubernetes
`Gateway` and `HTTPRoute` resources.

1. On Canonical Kubernetes, enable the Gateway API and a load balancer so the gateway
gets an external IP:

```
sudo k8s enable gateway        # provides the "ck-gateway" GatewayClass
sudo k8s enable load-balancer
```

2. Deploy the ingress chain (a TLS provider such as `self-signed-certificates` supplies
the gateway certificate):

```
juju deploy gateway-api-integrator --trust
juju deploy ingress-configurator
juju deploy self-signed-certificates
```

3. Configure the gateway class and the routing hostname:

```
juju config gateway-api-integrator gateway-class=ck-gateway external-hostname=temporal-k8s.test
juju config ingress-configurator hostname=temporal-k8s.test backend-protocol=http
```

4. Integrate the chain:

```
juju integrate self-signed-certificates:certificates gateway-api-integrator:certificates
juju integrate ingress-configurator:gateway-route     gateway-api-integrator:gateway-route
juju integrate temporal-k8s:ingress                   ingress-configurator:ingress
```

5. The gateway's external IP appears in the integrator's status message
(`Gateway addresses: <ip>` in `juju status`). TLS is terminated at the gateway, so
clients connect over TLS using the configured hostname (resolve it to the gateway IP).
For example, with the temporal CLI snap:

```
temporal operator namespace list --address temporal-k8s.test:443 --tls-server-name temporal-k8s.test --tls-ca-path <gateway CA>
```

Do not enable the `frontend-certificates` relation at the same time - TLS is terminated
at the gateway, and the frontend must stay cleartext (`h2c`); see the note above.

The interface (`ingress`) is what matters, so the same `temporal-k8s:ingress` endpoint
can instead be related to any other provider that implements it, for example
`traefik-k8s:ingress`.
