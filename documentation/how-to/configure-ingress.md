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
