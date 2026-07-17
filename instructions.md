#### Env setup

1. Install concierte
```
sudo snap install --classic concierge
```

2. Write a ~/concierge-local.yaml with these configs

```
juju:
  channel: 3.6/stable
  model-defaults:
    test-mode: "true"
    automatically-retry-hooks: "false"
providers:
  lxd:
    enable: true
    bootstrap: true
  k8s:
    enable: true
    bootstrap: true
    channel: 1.33-classic/stable
    bootstrap-constraints:
      root-disk: "2G"
    features:
      load-balancer: { l2-mode: "true", cidrs: "10.43.45.0/28" }
      local-storage: {}
      network: {}
host:
  snaps:
    charmcraft:
      channel: 4.x/stable
    temporal:
      channel: latest/stable
```

3. Prepare env

```
concierge prepare -c ~/concierge-local.yaml
```

4. Save some env vars to make commands easier later on

```
  juju controllers
  LXD=concierge-lxd        # adjust to your actual names
  K8S=container-k8s
```


#### Build & deploy Temporal Server

1. Clone the `temporal-k8s` repo and checkout to branch `WF-454-add-ingress-interface`

2. Pack and deploy `temporal-k8s`

```
charmcraft pack
juju switch $K8S:testing
juju deploy ./temporal-k8s_*.charm temporal-k8s --resource temporal-server-image=ubuntu/temporal-server@sha256:9cb05815c868bdf566b6a5a822d4d338709a96c3bd7b9ba0de0932773458266f --config num-history-shards=1
```

3. Deploy the rest of the charms that belong to the solution and integrate

NOTE: we're in the middle of the transition betwen 1.23 and 1.31, when the latter is available,
replace 1.23 with it. Functionality-wise, it shouldn't matter rn.

```
juju deploy postgresql-k8s --channel 14/stable --trust
juju deploy temporal-admin-k8s --channel 1.23/stable
juju deploy temporal-admin-k8s --channel 1.23/stable
juju integrate temporal-k8s:db postgresql-k8s:database
juju integrate temporal-k8s:visibility postgresql-k8s:database
juju integrate temporal-k8s:admin temporal-admin-k8s:admin
juju integrate temporal-k8s:ui              temporal-ui-k8s:ui
juju integrate temporal-k8s:temporal-host-info  temporal-ui-k8s:temporal-host-info
```

#### Enable frontend TLS

1. Deploy required charms and integrate

```
juju deploy self-signed-certificates
juju integrate temporal-k8s:frontend-certificates self-signed-certificates:certificates
```

#### Deploy ingress-configurator

1. Deploy and integrate required charms

```
juju deploy ingress-configurator --channel latest/edge --trust
juju integrate temporal-k8s:ingress ingress-configurator:ingress
juju config ingress-configurator hostname=temporal-k8s.test backend-protocol=https
```

---

#### Deploy and configure HAProxy for a gRPC server

This step is better explained in [the docs](https://canonical.com/juju/docs/ingress-configurator-charm/latest/how-to/haproxy-loadbalancing-grpc/), but I'll leave the commands I ran here:


1. Deploy HAProxy (machine model)

```
juju switch $LXD:testing
juju deploy haproxy --channel 2.8/edge
juju deploy self-signed-certificates
juju integrate haproxy:certificates self-signed-certificates
juju config haproxy external-hostname=temporal-k8s.test   # REQUIRED, or :443 fails to validate
```

2. Cross-model wiring

```
# Route: ingress-configurator -> haproxy
juju switch $LXD:testing
juju offer haproxy:haproxy-route
juju switch $K8S:testing
juju consume $LXD:admin/testing.haproxy haproxy-cmr
juju integrate ingress-configurator:haproxy-route haproxy-cmr
```

3. Make the HAProxy trust the frontend's CA

```
juju switch $K8S:testing
juju offer self-signed-certificates:send-ca-cert
juju switch $LXD:testing
juju consume $K8S:admin/testing.self-signed-certificates frontend-ca
juju integrate haproxy:receive-ca-certs frontend-ca
```

---

#### Verify

1. Add the temporal-server hostname to /etc/hosts

```
juju switch $LXD:testing
HAPROXY_IP=$(juju show-unit haproxy/0 | grep -m1 public-address | awk '{print $2}')
grep -q temporal-k8s.test /etc/hosts || echo "$HAPROXY_IP temporal-k8s.test" | sudo tee -a /etc/hosts
```

2. Get HAProxy's CA and save it

```
juju run -m concierge-lxd:testing self-signed-certificates/0 get-ca-certificate | tee ha-ca.pem
```
3. Verify that you can connect, for example, listing namespaces

```
temporal operator namespace list --address temporal-k8s.test:443 --tls --tls-ca-path ~/ha-ca.pem

# Should result in

  NamespaceInfo.Name                    temporal-system
  NamespaceInfo.Id                      32049b68-7872-4094-8e63-d0dd59896a83
  NamespaceInfo.Description             Temporal internal system namespace
  NamespaceInfo.OwnerEmail              temporal-core@temporal.io
  NamespaceInfo.State                   Registered
  NamespaceInfo.Data                    map[]
  Config.WorkflowExecutionRetentionTtl  168h0m0s
  ReplicationConfig.ActiveClusterName   active
  ReplicationConfig.Clusters            [{"clusterName":"active"}]
  ReplicationConfig.State               Unspecified
  Config.HistoryArchivalState           Disabled
  Config.VisibilityArchivalState        Disabled
  IsGlobalNamespace                     false
  FailoverVersion                       0
  FailoverHistory                       []
  Config.HistoryArchivalUri              
  Config.VisibilityArchivalUri           
  Config.CustomSearchAttributeAliases   map[]
```
