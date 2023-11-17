# Authorization

> **Note:** (TODO) Functionality described on this page is not live yet.

Enabling authorization requires that you have an active
[Charmed Temporal K8s Operator](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777)
deployed as described in the tutorial. It is recommended that you first go
through the steps of enabling authentication as outlined
[here](/t/charmed-temporal-k8s-how-to-authentication/12586).

By default the Temporal Server doesn't offer any authorization, but it offers
the plugin mechanism to add a custom one. We have added an OAuth-based
[authentication](/t/charmed-temporal-k8s-how-to-authentication/12586) using
Google Cloud and an authorization mechanism that leverages
[Google Cloud](https://cloud.google.com) and [OpenFGA](https://openfga.dev/).
This custom build of the Temporal Server can be found
[here](https://github.com/canonical/charmed-temporal-image).

## Deploy OpenFGA

To deploy Charmed OpenFGA K8s, you need to run the following command, which will
fetch the charm from [Charmhub](https://charmhub.io/openfga-k8s) and deploy it
to your model:

```bash
juju deploy openfga-k8s --channel edge
```

Wait until the application is ready - when it is ready, `juju status` will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  12:35:24+03:00

App                 Version   Status    Scale  Charm                Channel    Rev  Address         Exposed  Message
openfga-k8s                   blocked      1   openfga-k8s          edge         9  10.152.183.144  no       installing agent
postgresql-k8s      14.7      active       1   postgresql-k8s       14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s            active       1   temporal-admin-k8s   stable       4  10.152.183.21   no
temporal-k8s                  active       1   temporal-k8s         stable       9  10.152.183.191  no

Unit                   Workload   Agent  Address      Ports  Message
openfga-k8s/0*         blocked    idle   10.1.232.7          Waiting for postgresql relation
postgresql-k8s/0*      active     idle   10.1.232.66         Primary
temporal-admin-k8s/0*  active     idle   10.1.232.71
temporal-k8s/0*        active     idle   10.1.232.64
```

## Relate OpenFGA K8s to PostgreSQL K8s

To relate the two charms together, run the following command:

```bash
juju relate openfga-k8s postgresql-k8s
```

Once the `openfga-k8s` unit settles, you will see a message
`Please run schema-upgrade action`. You must now run the following action:

```bash
juju run openfga-k8s/leader schema-upgrade --wait 30s
```

Wait until the charm has settled - when ready, `juju status --relations` will
show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  12:35:24+03:00

App                 Version   Status    Scale  Charm                Channel    Rev  Address         Exposed  Message
openfga-k8s                   active       1   openfga-k8s          edge         9  10.152.183.144  no
postgresql-k8s      14.7      active       1   postgresql-k8s       14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s            active       1   temporal-admin-k8s   stable       4  10.152.183.21   no
temporal-k8s                  active       1   temporal-k8s         stable       9  10.152.183.191  no

Unit                   Workload   Agent  Address      Ports  Message
openfga-k8s/0*         active     idle   10.1.232.7
postgresql-k8s/0*      active     idle   10.1.232.66         Primary
temporal-admin-k8s/0*  active     idle   10.1.232.71
temporal-k8s/0*        active     idle   10.1.232.64

Relation provider                 Requirer                       Interface          Type     Message
openfga-k8s:peer                  openfga-k8s:peer               openfga-peer       peer
postgresql-k8s:database           openfga-k8s:database           postgresql_client  regular
postgresql-k8s:database           temporal-k8s:db                postgresql_client  regular
postgresql-k8s:database           temporal-k8s:visibility        postgresql_client  regular
postgresql-k8s:database-peers     postgresql-k8s:database-peers  postgresql_peers   peer
postgresql-k8s:restart            postgresql-k8s:restart         rolling_op         peer
temporal-admin-k8s:admin          temporal-k8s:admin             temporal           regular
temporal-k8s:peer                 temporal-k8s:peer              temporal           peer
```

At this point, we have a functioning OpenFGA store which we can now use to store
namespace access rules.

## Relate Temporal K8s to OpenFGA K8s

To enable authorization, we must first configure the Temporal Server as follows:

```bash
juju config temporal-k8s auth-enabled=true
```

At this point, the `temporal-k8s` application should be in a `blocked` state
with a message `openfga:temporal relation not ready`. We can now relate the two
charms together by running the following command:

```bash
juju relate temporal-k8s openfga-k8s
```

Once the units settle, the `temporal-k8s` application should still be in a
`blocked` state, but with an updated message
`missing openfga authorization model`. We can now create an
[authorization model](../../temporal_auth_model.json) in the OpenFGA store by
running the following command:

```bash
juju run temporal-k8s/0 create-authorization-model  model="$(<temporal_auth_model.json)" --string-args=true
```

Wait until the charm has settled - when ready, `juju status --relations` will
show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  12:35:24+03:00

App                 Version   Status    Scale  Charm                Channel    Rev  Address         Exposed  Message
openfga-k8s                   active       1   openfga-k8s          edge         9  10.152.183.144  no
postgresql-k8s      14.7      active       1   postgresql-k8s       14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s            active       1   temporal-admin-k8s   stable       4  10.152.183.21   no
temporal-k8s                  active       1   temporal-k8s         stable       9  10.152.183.191  no

Unit                   Workload   Agent  Address      Ports  Message
openfga-k8s/0*         active     idle   10.1.232.7
postgresql-k8s/0*      active     idle   10.1.232.66         Primary
temporal-admin-k8s/0*  active     idle   10.1.232.71
temporal-k8s/0*        active     idle   10.1.232.64         auth enabled

Relation provider                 Requirer                       Interface          Type     Message
openfga-k8s:openfga               temporal-k8s:openfga           openfga            regular
openfga-k8s:peer                  openfga-k8s:peer               openfga-peer       peer
postgresql-k8s:database           openfga-k8s:database           postgresql_client  regular
postgresql-k8s:database           temporal-k8s:db                postgresql_client  regular
postgresql-k8s:database           temporal-k8s:visibility        postgresql_client  regular
postgresql-k8s:database-peers     postgresql-k8s:database-peers  postgresql_peers   peer
postgresql-k8s:restart            postgresql-k8s:restart         rolling_op         peer
temporal-admin-k8s:admin          temporal-k8s:admin             temporal           regular
temporal-k8s:peer                 temporal-k8s:peer              temporal           peer
```

At this point, our Temporal Server is active again with authorization enabled.
This means that any request made to the Temporal Server will need to be
[authenticted](/t/charmed-temporal-k8s-how-to-authentication/12586) using Google
OAuth.

## Create OpenFGA Authorization Rules

Once authorization is enabled, you will not be able to access any namespace in
Temporal. You must now create the necessary tuples in the OpenFGA store to
enable users read/write access to different namespaces.

The authorization model used is as follows:

```
model
  schema 1.1

type user
type group
  relations
    define member: [user]
type namespace
  relations
    define admin: [group#member]
    define reader: [group#member] or writer
    define writer: [group#member] or admin
```

The above model is a simple way of relating users to groups to namespaces. A
`user` can be related to a `group` as a `member`, and a `group` can be related
to a `namespace` as either a `reader`, `writer` or `admin`. For example, if user
`john` is a member of group `abc`, and group `abc` is related to namespace
`example` as a `writer`, then user `john` will be assigned write access on
namespace `example`.

To add authorization rules to our OpenFGA store, we can use the available
actions as follows:

```bash
# Add user to group:
juju run temporal-k8s/0 add-auth-rule user="<your_email>" group="test_group"

# Output:
Running operation 19 with 1 task
  - task 20 on unit-temporal-k8s-0

Waiting for task 20...
output: 'operation type "create" for user "<your_email>" on group "test_group" successful'
result: command succeeded

# Assign group 'writer' role to namespace:
juju run temporal-k8s/0 add-auth-rule group="test_group" namespace="default" role="writer"

# Output:
Running operation 19 with 1 task
  - task 20 on unit-temporal-k8s-0

Waiting for task 20...
output: 'operation type "create" for group "test_group" and role "writer" on namespace "default" successful'
result: command succeeded
```

And you're done! If the above actions ran successfully, you should be able to
access the `default` namespace in Temporal with the authenticated user
identified by `<your_email>`, whether through web UI login or the use of a
Google Cloud service account.

The following actions may also be used for removing auth rules, checking access
rules and for auditing purposes:

```bash
# Check auth rule
juju run temporal-k8s/0 check-auth-rule user="<your_email>" namespace="default" role="writer"

# Output:
output: "True"
result: command succeeded

# List auth rules
juju run temporal-k8s/0 list-auth-rule user="<your_email>"

# Output:
output: |
  admin: '[]'
  member: '[''group:test_group'']'
  reader: '[''namespace:default'']'
  writer: '[''namespace:default'']'
result: command succeeded

# Remove auth rule
juju run temporal-k8s/0 remove-auth-rule user="<your_email>" group="test_group"

# Output:
output: 'operation type "delete" for user "<your_email>" on group "test_group" successful'
result: command succeeded
```
