# How to enable monitoring

The Temporal server charm can be related to the
[Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack)
in order to collect logs and telemetry.

Enabling monitoring requires that you:

- Have an active [Charmed Temporal K8s operator](../tutorial/01-introduction.md)
  deployed.

## Deploy COS Lite Bundle

To enable monitoring, we will be deploying cos-lite to a separate model and
exposing the necessary endpoints as offers, relating them to the Temporal server
using cross-model relations. To get started, we must first deploy the COS Lite
bundle:

```bash
juju add-model cos
juju deploy cos-lite --trust
```

Wait until the applications are ready - when they are ready, `juju status` will
show:

```
Model  Controller           Cloud/Region        Version  SLA          Timestamp
cos    temporal-controller  microk8s/localhost  3.1.5    unsupported  11:10:19+03:00

App           Version  Status   Scale  Charm             Channel  Rev  Address         Exposed  Message
alertmanager  0.25.0   active       1  alertmanager-k8s  stable    76  10.152.183.185  no
catalogue              active       1  catalogue-k8s     stable    13  10.152.183.176  no
grafana       9.2.1    active       1  grafana-k8s       stable    81  10.152.183.78   no
loki          2.7.4    active       1  loki-k8s          stable    89  10.152.183.236  no
prometheus    2.33.5   active       1  prometheus-k8s    stable   103  10.152.183.69   no
traefik       2.9.6    waiting      1  traefik-k8s       stable   110  10.152.183.223  no       installing agent

Unit             Workload  Agent  Address       Ports  Message
alertmanager/0*  active    idle   10.1.232.120
catalogue/0*     active    idle   10.1.232.108
grafana/0*       active    idle   10.1.232.123
loki/0*          active    idle   10.1.232.121
prometheus/0*    active    idle   10.1.232.122
traefik/0*       waiting   idle   10.1.232.119         gateway address unavailable
```

Run the following commands to offer COS interfaces to be cross-model related
with the Charmed Temporal K8s model:

```bash
# Expose the cos integration endpoints
juju offer prometheus:metrics-endpoint
juju offer loki:logging
juju offer grafana:grafana-dashboard
```

Once done, the output of `juju status` should be updated to show the following
offers:

```
Offer       Application  Charm           Rev  Connected  Endpoint           Interface          Role
grafana     grafana      grafana-k8s     81   0/0        grafana-dashboard  grafana_dashboard  requirer
loki        loki         loki-k8s        89   0/0        logging            loki_push_api      provider
prometheus  prometheus   prometheus-k8s  103  0/0        metrics-endpoint   prometheus_scrape  requirer
```

## Relate Temporal Server to COS Lite Bundle

```bash
# Relate Temporal to the cos-lite apps
juju switch temporal-model
juju relate temporal-k8s admin/cos.grafana
juju relate temporal-k8s admin/cos.loki
juju relate temporal-k8s admin/cos.prometheus
```

Once done, the output of `juju status --relations` should be as follows:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  16:36:27+03:00

SAAS        Status  Store                URL
grafana     active  temporal-controller  admin/cos.grafana
loki        active  temporal-controller  admin/cos.loki
prometheus  active  temporal-controller  admin/cos.prometheus

App                 Version  Status  Scale  Charm               Channel    Rev  Address         Exposed  Message
postgresql-k8s      14.7     active      1  postgresql-k8s      14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s           active      1  temporal-admin-k8s  stable       4  10.152.183.21   no
temporal-k8s                 waiting     1  temporal-k8s        stable       9  10.152.183.191  no       installing agent
temporal-ui-k8s              active      1  temporal-ui-k8s     stable       8  10.152.183.135  no

Unit                   Workload  Agent  Address      Ports   Message
postgresql-k8s/0*      active    idle   10.1.232.66          Primary
temporal-admin-k8s/0*  active    idle   10.1.232.71
temporal-k8s/0*        error     idle   10.1.232.64          "log-proxy-relation-changed"
temporal-ui-k8s/0*     active    idle   10.1.232.72

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

After relating the Charmed Temporal K8s operator to cos-lite services, it will
temporarily be in an error state. For the time being, we need to attach the
promtail-bin resource so that Loki works without trying to download promtail
from the web:

```bash
# Download promtail binary
curl -O -L "https://github.com/grafana/loki/releases/download/v2.7.5/promtail-linux-amd64.zip"

# Extract the binary
unzip "promtail-linux-amd64.zip"

# Make sure it is executable
chmod a+x "promtail-linux-amd64"
juju attach-resource temporal-k8s promtail-bin=<PATH_TO_PROMTAIL_BINARY>/promtail-linux-amd64
```

Once done, the Charmed Temporal K8s operator should be back in an active state .
We can now access our Grafana dashboard as follows:

```bash
# Access Grafana with username "admin" and password:
juju run grafana/0 -m cos get-admin-password --wait 1m
```

Grafana can be accessed on port 3000 of the app IP address (in our case, it will
be `10.152.183.78:3000`). The dashboard can be accessed under "Temporal Server
Metrics", make sure to select the juju model which contains your Temporal charm.
