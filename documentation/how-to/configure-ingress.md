# Configure Ingress with Nginx Ingress Integrator

Charmed Temporal components can be exposed through an ingress solution for both making them available
to clients outside of the cluster, as well as to handle TLS termination.
In the Charming ecosystem, the [Nginx Ingress Integrator](https://charmhub.io/nginx-ingress-integrator)
operator allows different applications to request `Ingress` resources from an underlying ingress controller.

## Enable Ingress

### Pre requisites

To follow this guide, consider having a Kubernetes cluster with the following enabled/configured:

* Ingress controller - If using `k8s`, the [nginx ingress controller](https://docs.nginx.com/nginx-ingress-controller/installation/installing-nic/installation-with-manifests) can be installed; if using `microk8s`, the `ingress` addon should suffice.
* LoadBalancer - If using `k8s`, the [default LoadBalancer](https://documentation.ubuntu.com/canonical-kubernetes/latest/snap/howto/networking/default-loadbalancer/) works; on `microk8s` the `metallb` addon should suffice.
* [temporal CLI snap](https://snapcraft.io/temporal)

[note]

The `nginx-ingress-integrator` only allows one integration per `ingress` and `nginx-route` integration.
Charmed Temporal is not designed to share the same integrator instance, and thus, an integrator
charm per application must be deployed.
Please refer to [Support multiple relations](https://charmhub.io/nginx-ingress-integrator/docs/support-multiple-relations).

[/note]

### Expose the Temporal Server

1. Deploy the integrator charm

```
juju deploy nginx-ingress-integrator temporal-server-ingress --trust
```

2. Configure the integrator's `ingress-class`

```
# Check your cluster's IngressClass
# For the sake of this guide, it's assumed just one IngressClass is present
kubectl get ingressclass

NAME             CONTROLLER                  PARAMETERS   AGE
nginx            k8s.io/ingress-nginx        <none>       12d

# Use the name of the IngressClass
juju config temporal-server-ingress ingress-class nginx
```

4. Configure the `backend-protocol` - Temporal (the server, specifically the `frontend`) is a gRPC server

```
juju config temporal-server-ingress backend-protocol GRPC
```

5. Integrate

```
# This is an old implementation of TLS secrets, it must be kept as ""
juju config temporal-k8s tls-secret-name=""
juju integrate temporal-k8s temporal-server-ingress
```

6. Connect with clients - Assuming a `LoadBalancer` is enabled, and because the Temporal Server works with
host-based routing, DNS resolution must be set up. For example:

```
# cat /etc/hosts/
[...]
<LOADBALANCER-IP> temporal-k8s

# Use the temporal snap CLI to list namespaces
temporal operator namespace list --address temporal-k8s:80
[...]
```

### Expose the Temporal UI

1. Deploy the integrator charm

```
juju deploy nginx-ingress-integrator temporal-ui-ingress --trust
```

2. Configure the integrator's `ingress-class`

```
# Check your cluster's IngressClass
# For the sake of this guide, it's assumed just one IngressClass is present
kubectl get ingressclass

NAME             CONTROLLER                  PARAMETERS   AGE
nginx            k8s.io/ingress-nginx        <none>       12d

# Use the name of the IngressClass
juju config temporal-ui-ingress ingress-class nginx
```

4. Configure the `backend-protocol` - Temporal (the server, specifically the `frontend`) is a gRPC server

```
juju config temporal-ui-ingress backend-protocol HTTP
```

5. Integrate

```
# This is an old implementation of TLS secrets, it must be kept as ""
juju config temporal-ui-k8s tls-secret-name=""
juju integrate temporal-ui-k8s temporal-ui-ingress
```

6. Access the Temporal UI on a web browser - Assuming a `LoadBalancer` is enabled, and because of Temporal's
host-based routing, DNS resolution must be set up. For example:

```
# cat /etc/hosts/
[...]
<LOADBALANCER-IP> temporal-ui-k8s

# Use the DNS name in the web browser
http://temporal-ui-k8s:80/
```

## Enable TLS termination at ingress

The integrator charm provides means to do TLS termination at ingress in conjunction with the ecosystem's TLS providers.
Please refer to [Security with X.509 certificates](https://charmhub.io/topics/security-with-x-509-certificates) to understand
each certificate use case and decide on a solution that fits each of them.

### Temporal Server

1. Re-configure the integrator charm for a secured backend


```
juju config temporal-server-ingress backend-protocol GRPCS
```

2. Integrate the integrator charm with a TLS certificate provider


```
juju integrate temporal-server-ingress <tls-certificate-provider>
```

3. Get the CA certificate from the TLS certificate provider charm and use it in further requests. For example,
using the temporal CLI snap:

```
temporal operator namespace list --address temporal-k8s:443 --tls-ca-path <path to CA cert>
```

### Temporal UI
1. Re-configure the integrator charm for a secured backend


```
juju config temporal-ui-ingress backend-protocol HTTPS
```

2. Integrate the integrator charm with a TLS certificate provider


```
juju integrate temporal-ui-ingress <tls-certificate-provider>
```

3. Use `https` when browsing and do the proper adjustments for trusting certificates if necessary.
