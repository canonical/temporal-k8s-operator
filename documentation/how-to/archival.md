# Enable Archival

Excerpt from
[Temporal's documentation](https://docs.temporal.io/clusters#archival):

> Archival is a feature that automatically backs up Event Histories and
> Visibility records from Temporal Cluster persistence to a custom blob store.
>
> Workflow Execution Event Histories are backed up after the Retention Period is
> reached. Visibility records are backed up immediately after a Workflow
> Execution reaches a Closed status.

> Archival enables Workflow Execution data to persist as long as needed, while
> not overwhelming the Cluster's persistence store.

> This feature is helpful for compliance and debugging. Temporal's Archival
> feature is considered **experimental** and not subject to normal versioning
> and support policy.

The archival feature can be enabled for Charmed Temporal K8s by relating it with
the [Charmed S3 Integrator](https://charmhub.io/s3-integrator), which provides
it with the necessary credentials it needs to store event histories in S3
storage.

## Deploy S3 Integrator

To deploy Charmed S3 Integrator, you need to run the following command, which
will fetch the charm from [Charmhub](https://charmhub.io/s3-integrator) and
deploy it to your model:

```bash
juju deploy s3-integrator
```

Wait until the application is ready - when it is ready,
`juju status --relations` will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  12:35:24+03:00

App                 Version   Status    Scale  Charm                Channel    Rev  Address         Exposed  Message
s3-integrator                 blocked      1   s3-integrator        stable      13  10.152.183.171  no       installing agent
postgresql-k8s      14.7      active       1   postgresql-k8s       14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s            active       1   temporal-admin-k8s   stable       4  10.152.183.21   no
temporal-k8s                  active       1   temporal-k8s         stable       9  10.152.183.191  no

Unit                   Workload   Agent  Address      Ports  Message
s3-integrator/0*       blocked    idle   10.1.232.2          Missing parameters: ['access-key', 'secret-key']
postgresql-k8s/0*      active     idle   10.1.232.66         Primary
temporal-admin-k8s/0*  active     idle   10.1.232.71
temporal-k8s/0*        active     idle   10.1.232.64

Integration provider               Requirer                           Interface            Type     Message
postgresql-k8s:database            openfga-k8s:database               postgresql_client    regular
postgresql-k8s:database            temporal-k8s:db                    postgresql_client    regular
postgresql-k8s:database            temporal-k8s:visibility            postgresql_client    regular
postgresql-k8s:database-peers      postgresql-k8s:database-peers      postgresql_peers     peer
postgresql-k8s:restart             postgresql-k8s:restart             rolling_op           peer
postgresql-k8s:upgrade             postgresql-k8s:upgrade             upgrade              peer
s3-integrator:s3-integrator-peers  s3-integrator:s3-integrator-peers  s3-integrator-peers  peer
temporal-admin-k8s:admin           temporal-k8s:admin                 temporal             regular
temporal-admin-k8s:peer            temporal-admin-k8s:peer            temporal-admin       peer
temporal-k8s:peer                  temporal-k8s:peer                  temporal             peer
```

## Configure S3 Integrator and Relate to Temporal K8s

Archival can be configured on any S3-compatible storage. S3 access and
configurations are managed with the
[Charmed S3 Integrator](https://charmhub.io/s3-integrator/configure):

```bash
juju config s3-integrator \
    endpoint="https://s3.us-west-2.amazonaws.com" \
    bucket="test-bucket-1" \
    path="/temporal-archival" \
    region="us-west-2"

juju run s3-integrator/leader sync-s3-credentials access-key=<access-key> secret-key=<secret-key> --wait 1m
juju relate temporal-k8s s3-integrator
```

Wait until the application is ready - when it is ready,
`juju status --relations` will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  12:35:24+03:00

App                 Version   Status    Scale  Charm                Channel    Rev  Address         Exposed  Message
s3-integrator                 active       1   s3-integrator        stable      13  10.152.183.171  no
postgresql-k8s      14.7      active       1   postgresql-k8s       14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s            active       1   temporal-admin-k8s   stable       4  10.152.183.21   no
temporal-k8s                  active       1   temporal-k8s         stable       9  10.152.183.191  no

Unit                   Workload   Agent  Address      Ports  Message
s3-integrator/0*       active     idle   10.1.232.2
postgresql-k8s/0*      active     idle   10.1.232.66         Primary
temporal-admin-k8s/0*  active     idle   10.1.232.71
temporal-k8s/0*        active     idle   10.1.232.64

Integration provider               Requirer                           Interface            Type     Message
postgresql-k8s:database            openfga-k8s:database               postgresql_client    regular
postgresql-k8s:database            temporal-k8s:db                    postgresql_client    regular
postgresql-k8s:database            temporal-k8s:visibility            postgresql_client    regular
postgresql-k8s:database-peers      postgresql-k8s:database-peers      postgresql_peers     peer
postgresql-k8s:restart             postgresql-k8s:restart             rolling_op           peer
postgresql-k8s:upgrade             postgresql-k8s:upgrade             upgrade              peer
s3-integrator:s3-credentials       temporal-k8s:s3-parameters         s3                   regular
s3-integrator:s3-integrator-peers  s3-integrator:s3-integrator-peers  s3-integrator-peers  peer
temporal-admin-k8s:admin           temporal-k8s:admin                 temporal             regular
temporal-admin-k8s:peer            temporal-admin-k8s:peer            temporal-admin       peer
temporal-k8s:peer                  temporal-k8s:peer                  temporal             peer
```

Note: Make sure to observe the the output of `juju debug-log` to ensure that
there are no errors when configuring the S3 bucket as the destination for
Temporal event histories archival.

## Enable Namespace Archival

Once the S3 relation is set up, namespace archival can be enabled using
[tctl](https://github.com/canonical/charmed-temporal-image/tree/main/tctl-snap)
as follows:

```bash
tctl namespace update --history_archival_state enabled <namespace>
tctl namespace update --visibility_archival_state enabled <namespace>
```
