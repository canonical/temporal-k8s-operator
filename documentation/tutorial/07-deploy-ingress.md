# Deploy Nginx Ingress Integrator

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

The Charmed Temporal K8s operator exposes its service ports using the
[Nginx Ingress Integrator](https://charmhub.io/nginx-ingress-integrator)
operator, which requires us to deploy an
[Nginx Ingress Controller](https://docs.nginx.com/nginx-ingress-controller/) as
described below.

## Enable TLS

To enable TLS connections, you must have a TLS certificate stored as a k8s
secret (default name is "temporal-tls"). The secret name can be configured using
the `tls-secret-name` config property in the charm. A self-signed certificate
for development purposes can be created as follows:

```bash
# Generate private key
openssl genrsa -out server.key 2048

# Generate a certificate signing request
openssl req -new -key server.key -out server.csr -subj "/CN=temporal-k8s"

# Create self-signed certificate
openssl x509 -req -days 365 -in server.csr -signkey server.key -out server.crt -extfile <(printf "subjectAltName=DNS:temporal-k8s")

# Create a k8s secret
kubectl -n temporal-model create secret tls temporal-tls --cert=server.crt --key=server.key
```

## Deploy

To deploy Charmed Temporal Web UI, you need to run the following commands, which
will enable ingress in your microk8s, fetch the charm from
[Charmhub](https://charmhub.io/nginx-ingress-integrator) and deploy it to your
model:

```bash
# Deploy ingress controller.
sudo microk8s enable ingress:default-ssl-certificate=temporal-model/temporal-tls

juju deploy nginx-ingress-integrator --channel edge --revision 71 --trust
```

Wait until the application is ready - when it is ready, `juju status` will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  16:46:18+03:00

App                       Version  Status  Scale  Charm                     Channel    Rev  Address         Exposed  Message
nginx-ingress-integrator  25.3.0   active      1  nginx-ingress-integrator  edge        71  10.152.183.203  no
postgresql-k8s            14.7     active      1  postgresql-k8s            14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s                 active      1  temporal-admin-k8s        stable       4  10.152.183.21   no
temporal-k8s                       active      1  temporal-k8s              stable       9  10.152.183.191  no
temporal-ui-k8s                    active      1  temporal-ui-k8s           stable       8  10.152.183.135  no

Unit                         Workload  Agent  Address      Ports   Message
nginx-ingress-integrator/0*  active    idle   10.1.232.73
postgresql-k8s/0*            active    idle   10.1.232.66          Primary
temporal-admin-k8s/0*        active    idle   10.1.232.71
temporal-k8s/0*              active    idle   10.1.232.64
temporal-ui-k8s/0*           active    idle   10.1.232.72
```

## Relate Temporal Server and Web UI to Nginx Ingress Integrator

To relate the two charms together, run the following command:

```bash
juju relate temporal-k8s nginx-ingress-integrator
juju relate temporal-ui-k8s nginx-ingress-integrator
```

Wait until the two charms have been related and settled - when ready,
`juju status` will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  16:56:43+03:00

App                       Version  Status  Scale  Charm                     Channel    Rev  Address         Exposed  Message
nginx-ingress-integrator  25.3.0   active      1  nginx-ingress-integrator  edge        71  10.152.183.203  no       Ingress IP(s): 127.0.0.1, 127.0.0.1, Service IP(s): 10.152.183.172, 10.152.183.235
postgresql-k8s            14.7     active      1  postgresql-k8s            14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s                 active      1  temporal-admin-k8s        stable       4  10.152.183.21   no
temporal-k8s                       active      1  temporal-k8s              stable       9  10.152.183.191  no
temporal-ui-k8s                    active      1  temporal-ui-k8s           stable       8  10.152.183.135  no

Unit                         Workload  Agent  Address      Ports   Message
nginx-ingress-integrator/0*  active    idle   10.1.232.73          Ingress IP(s): 127.0.0.1, 127.0.0.1, Service IP(s): 10.152.183.172, 10.152.183.235
postgresql-k8s/0*            active    idle   10.1.232.66          Primary
temporal-admin-k8s/0*        active    idle   10.1.232.71
temporal-k8s/0*              active    idle   10.1.232.64
temporal-ui-k8s/0*           active    idle   10.1.232.72

Relation provider                     Requirer                       Interface          Type     Message
nginx-ingress-integrator:nginx-route  temporal-k8s:nginx-route       nginx-route        regular
nginx-ingress-integrator:nginx-route  temporal-ui-k8s:nginx-route    nginx-route        regular
postgresql-k8s:database               temporal-k8s:db                postgresql_client  regular
postgresql-k8s:database               temporal-k8s:visibility        postgresql_client  regular
postgresql-k8s:database-peers         postgresql-k8s:database-peers  postgresql_peers   peer
postgresql-k8s:restart                postgresql-k8s:restart         rolling_op         peer
temporal-admin-k8s:admin              temporal-k8s:admin             temporal           regular
temporal-k8s:peer                     temporal-k8s:peer              temporal           peer
temporal-ui-k8s:peer                  temporal-ui-k8s:peer           temporal           peer
temporal-ui-k8s:ui                    temporal-k8s:ui                temporal           regular
```

## Verify Ingress Resource

To verify the ingress resources were correctly created, you can run the
following command:

```bash
kubectl describe ingress -n temporal-model
```

The output should look similar to the following (with the exception of the
service IP addresses):

```
Name:             temporal-k8s-ingress
Labels:           app.juju.is/created-by=nginx-ingress-integrator
                  nginx-ingress-integrator.charm.juju.is/managed-by=nginx-ingress-integrator
Namespace:        temporal-model
Address:          127.0.0.1
Ingress Class:    public
Default backend:  <default>
TLS:
  temporal-tls terminates temporal-k8s
Rules:
  Host          Path  Backends
  ----          ----  --------
  temporal-k8s
                /   temporal-k8s-service:7233 (10.1.232.64:7233)
Annotations:    nginx.ingress.kubernetes.io/backend-protocol: GRPC
                nginx.ingress.kubernetes.io/proxy-body-size: 20m
                nginx.ingress.kubernetes.io/proxy-read-timeout: 60
                nginx.ingress.kubernetes.io/rewrite-target: /
Events:         <none>


Name:             temporal-ui-k8s-ingress
Labels:           app.juju.is/created-by=nginx-ingress-integrator
                  nginx-ingress-integrator.charm.juju.is/managed-by=nginx-ingress-integrator
Namespace:        temporal-model
Address:          127.0.0.1
Ingress Class:    public
Default backend:  <default>
TLS:
  temporal-tls terminates temporal-ui-k8s
Rules:
  Host             Path  Backends
  ----             ----  --------
  temporal-ui-k8s
                   /   temporal-ui-k8s-service:8080 (10.1.232.72:8080)
Annotations:       nginx.ingress.kubernetes.io/backend-protocol: HTTP
                   nginx.ingress.kubernetes.io/proxy-body-size: 20m
                   nginx.ingress.kubernetes.io/proxy-read-timeout: 60
                   nginx.ingress.kubernetes.io/rewrite-target: /
Events:            <none>
```

## Connect Ingress

Once deployed and related, find the IP of the ingress controller by running the
following command:

```bash
kubectl get pods -n ingress -o wide
```

You should see something similar to the following output:

```
NAME                                      READY   STATUS    RESTARTS          AGE    IP           NODE      NOMINATED NODE   READINESS GATES
nginx-ingress-microk8s-controller-mfmtx   1/1     Running   512 (3h15m ago)   145d   10.1.232.8   ubuntu   <none>           <none>
```

Take note of the ingress controller IP address and add the IP-to-hostname
mapping in your `/etc/hosts` file as follows:

```bash
sudo nano /etc/hosts

# Add the following entries
10.1.232.8     temporal-k8s
10.1.232.8     temporal-ui-k8s
```

By default, the hostname will be set to the respective application names
`temporal-k8s` and `temporal-ui-k8s`. You can then connect a Temporal client
through this hostname as follows, where `[CERTIFICATE]` is the `.crt` file generated previously:

```python
from temporalio.client import Client, TLSConfig

tls_root_cas = """
-----BEGIN CERTIFICATE-----
[CERTIFICATE]
-----END CERTIFICATE-----
"""

enc_tls_root_cas = tls_root_cas.encode()
tls = TLSConfig(server_root_ca_cert=enc_tls_root_cas, domain="temporal-k8s")

client = await Client.connect("temporal-k8s", tls=tls)
```

> **See next:
> [Deploy Temporal Worker](/t/charmed-temporal-k8s-tutorial-deploy-temporal-worker/11784)**
