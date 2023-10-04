# Authorization

> **Note:** Functionality described on this page is not live yet.

Enabling authorization requires that you have an active
[Charmed Temporal K8s Operator](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777)
deployed as described in the tutorial. It is recommended that you first go
through the steps of enabling authentication as outlined
[here](./authentication.md).

By default the Temporal Server doesn't offer any authorization, but it offers
the plugin mechanism to add a custom one. We have added an OAuth-based
[authentication](./authentication.md) using Google Cloud and an authorization
mechanism that leverages [Google Cloud](https://cloud.google.com) and
[OpenFGA](https://openfga.dev/). This custom build of the Temporal Server can be
found [here](https://github.com/canonical/charmed-temporal-image).

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

To view your OpenFGA store's information, you can run the command below. Make
note of the store's information, as this will enable us to connect to it through
a client to add the necessary tuples in the following section.

```bash
juju show-unit temporal-k8s/0

# Output:
temporal-k8s/0:
  opened-ports: []
  charm: local:jammy/temporal-k8s-6
  leader: true
  life: alive
  relation-info:
    ...
      openfga: '{"store_id": "<store_id>", "token": "<token>",
        "address": "10.152.183.144", "port": "8080", "scheme": "http", "auth_model_id": "<model_id>"}'
```

At this point, our Temporal Server is active again with authorization enabled.
This means that any request made to the Temporal Server will need to be
[authenticted](./authentication.md) using Google OAuth.

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
    define writer: [group#member]
```

The above model is a simple way of relating users to groups to namespaces. A
`user` can be related to a `group` as a `member`, and a `group` can be related
to a `namespace` as either a `reader`, `writer` or `admin`.For example, If user
`john` is a member of group `abc`, and group `abc` is related to namespace
`example` as a `writer`, then user `john` will be assigned write access on
namespace `example`.

To add tuples to our OpenFGA store, we can use an
[OFGA client](https://github.com/canonical/ofga) as follows:

```go
package main

import (
	"context"
	"fmt"

	"github.com/canonical/ofga"
)

func main() {
	ctx := context.Background()

	// Create a new ofga client
	client, err := ofga.NewClient(ctx, ofga.OpenFGAParams{
		Scheme:      "http", // defaults to `https` if not specified.
		Host:        "10.152.183.144",
		Port:        "8080",
		Token:       "<token>",
		StoreID:     "<store_id>",
		AuthModelID: "<model_id>",
	})
	if err != nil {
		// Handle error
		fmt.Printf("Error connecting to OpenFGA store: %v \n", err)
	}

    // Add your email as a member of group 'test'
	err = client.AddRelation(ctx, ofga.Tuple{
		Object:   &ofga.Entity{Kind: "user", ID: "<your_email>"},
		Relation: "member",
		Target:   &ofga.Entity{Kind: "group", ID: "test"},
	})
	if err != nil {
		// Handle error
		fmt.Printf("Error adding relations: %v", err)
	}

    // Assign all members of group 'test' write access to the 'default' namespace in Temporal.
	err = client.AddRelation(ctx, ofga.Tuple{
		Object:   &ofga.Entity{Kind: "group", ID: "test#member"},
		Relation: "writer",
		Target:   &ofga.Entity{Kind: "namespace", ID: "default"},
	})
	if err != nil {
		// Handle error
		fmt.Printf("Error adding relations: %v", err)
	}
}
```

And you're done! If the above program ran successfully, you should be able to
access the `default` namespace in Temporal with the authenticated user
identified by `<your_email>`, whether through web UI login or the use of a
Google Cloud service account.
