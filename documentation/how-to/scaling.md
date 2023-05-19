The Temporal Server consists of four independently scalable services:

- Frontend gateway: for rate limiting, routing, authorizing.
- History subsystem: maintains data (mutable state, queues, and timers).
- Matching subsystem: hosts Task Queues for dispatching.
- Worker Service: for internal background Workflows.

For example, a real-life production deployment can have 5 Frontend, 15 History,
17 Matching, and 3 Worker Services per cluster.

The Temporal Server services can run independently or be grouped together into
shared processes on one or more physical or virtual machines. For live
(production) environments, we recommend that each service runs independently,
because each one has different scaling requirements and troubleshooting becomes
easier. The History, Matching, and Worker Services can scale horizontally within
a Cluster. The Frontend Service scales differently than the others because it
has no sharding or partitioning; it is just stateless.

(The above was extracted from
[Temporal's documentation](https://docs.temporal.io/clusters#temporal-server))

The Temporal server charm is designed such that each service can be deployed as
a separate application which can then be connected together by integrating with
the same database. These services can then be scaled according to your needs.

To deploy the services separately in a scalable way, you must deploy the
application as follows:

```bash
juju deploy temporal-k8s --config services="frontend"
juju deploy temporal-k8s-matching --config services="matching"
juju deploy temporal-k8s-history --config services="history"
juju deploy temporal-k8s-worker --config services="worker"

# Deploy database charm and relate to the frontend service
juju deploy postgresql-k8s --channel 14/stable --trust
juju relate temporal-k8s:db postgresql-k8s:database
juju relate temporal-k8s:visibility postgresql-k8s:database

# Deploy Temporal admin charm and relate to the frontend service
juju deploy temporal-admin-k8s
juju relate temporal-k8s:admin temporal-admin-k8s:admin
```

Once the temporal-k8s frontend service is active, we can relate the other three
services to the same database and admin charms:

```bash
juju relate temporal-k8s-history:db postgresql-k8s:database
juju relate temporal-k8s-history:visibility postgresql-k8s:database
juju relate temporal-k8s-history:admin temporal-admin-k8s:admin

juju relate temporal-k8s-matching:db postgresql-k8s:database
juju relate temporal-k8s-matching:visibility postgresql-k8s:database
juju relate temporal-k8s-matching:admin temporal-admin-k8s:admin

juju relate temporal-k8s-worker:db postgresql-k8s:database
juju relate temporal-k8s-worker:visibility postgresql-k8s:database
juju relate temporal-k8s-worker:admin temporal-admin-k8s:admin
```

Once deployed, you can run `juju status --watch 1s` to watch the status of your
applications. It may take a few minutes to see the following output where all
nodes are showing `Workload=Active` and `Agent=idle`:

```
Model         Controller           Cloud/Region        Version  SLA          Timestamp
temporal      temporal-controller  microk8s/localhost  3.1.2    unsupported  14:31:41+03:00

App                    Version  Status  Scale  Charm               Channel    Rev  Address         Exposed  Message
postgresql-k8s         14.7     active      1  postgresql-k8s      14/stable   73  10.152.183.171  no       Primary
temporal-admin-k8s              active      1  temporal-admin-k8s  edge         4  10.152.183.35   no
temporal-k8s                    active      1  temporal-k8s                     0  10.152.183.95   no
temporal-k8s-history            active      1  temporal-k8s                     1  10.152.183.52   no
temporal-k8s-matching           active      1  temporal-k8s                     2  10.152.183.122  no
temporal-k8s-worker             active      1  temporal-k8s                     3  10.152.183.134  no

Unit                      Workload  Agent  Address      Ports  Message
postgresql-k8s/0*         active    idle   10.1.232.60         Primary
temporal-admin-k8s/0*     active    idle   10.1.232.20
temporal-k8s-history/0*   active    idle   10.1.232.6
temporal-k8s-matching/0*  active    idle   10.1.232.61
temporal-k8s-worker/0*    active    idle   10.1.232.42
temporal-k8s/0*           active    idle   10.1.232.26
```

To confirm the four services can reach other, you can run
`juju run temporal-admin-k8s/0 tctl args="adm cl d"`, you should see the
following:

```
output: |
  {
    "supportedClients": {
      "temporal-cli": "\u003c2.0.0",
      "temporal-go": "\u003c2.0.0",
      "temporal-java": "\u003c2.0.0",
      "temporal-php": "\u003c2.0.0",
      "temporal-server": "\u003c2.0.0",
      "temporal-typescript": "\u003c2.0.0",
      "temporal-ui": "\u003c3.0.0"
    },
    "serverVersion": "1.17.3",
    "membershipInfo": {
      "currentHost": {
        "identity": "10.1.232.26:7233"
      },
      "reachableMembers": [
        "10.1.232.42:6939",
        "10.1.232.61:6935",
        "10.1.232.6:6934",
        "10.1.232.26:6933"
      ],
      "rings": [
        {
          "role": "frontend",
          "memberCount": 1,
          "members": [
            {
              "identity": "10.1.232.26:7233"
            }
          ]
        },
        {
          "role": "history",
          "memberCount": 1,
          "members": [
            {
              "identity": "10.1.232.6:7234"
            }
          ]
        },
        {
          "role": "matching",
          "memberCount": 1,
          "members": [
            {
              "identity": "10.1.232.61:7235"
            }
          ]
        },
        {
          "role": "worker",
          "memberCount": 1,
          "members": [
            {
              "identity": "10.1.232.42:7239"
            }
          ]
        }
      ]
    },
    "clusterId": "514dd854-eb26-4e93-9f3c-1355cb8aa99a",
    "clusterName": "active",
    "historyShardCount": 4,
    "persistenceStore": "postgres",
    "visibilityStore": "postgres",
    "failoverVersionIncrement": "10",
    "initialFailoverVersion": "1"
  }
result: command succeeded
```

## Adding Replicas

To add more replicas you can use the juju scale-application functionality i.e.

```
juju scale-application temporal-k8s -n <num_of_replicas_required_replicas>
```

To scale all four services to two units each, you can run the following
commands:

```
juju scale-application temporal-k8s -n 2
juju scale-application temporal-k8s-history -n 2
juju scale-application temporal-k8s-matching -n 2
juju scale-application temporal-k8s-worker -n 2
```

You can then run `juju status --watch 1s` to watch the status of your
applications. It may take a few minutes to see the following output where all
nodes are showing `Workload=Active` and `Agent=idle`:

```
Model     Controller           Cloud/Region        Version  SLA          Timestamp
temporal  temporal-controller  microk8s/localhost  3.1.0    unsupported  15:18:19+03:00

App                    Version  Status  Scale  Charm               Channel    Rev  Address         Exposed  Message
postgresql-k8s         14.7     active      1  postgresql-k8s      14/stable   73  10.152.183.171  no       Primary
temporal-admin-k8s              active      1  temporal-admin-k8s  edge         4  10.152.183.35   no
temporal-k8s                    active      2  temporal-k8s                     0  10.152.183.95   no
temporal-k8s-history            active      2  temporal-k8s                     1  10.152.183.52   no
temporal-k8s-matching           active      2  temporal-k8s                     2  10.152.183.122  no
temporal-k8s-worker             active      2  temporal-k8s                     3  10.152.183.134  no

Unit                      Workload  Agent  Address      Ports  Message
postgresql-k8s/0*         active    idle   10.1.232.60         Primary
temporal-admin-k8s/0*     active    idle   10.1.232.20
temporal-k8s-history/0*   active    idle   10.1.232.6
temporal-k8s-history/1    active    idle   10.1.232.51
temporal-k8s-matching/0*  active    idle   10.1.232.61
temporal-k8s-matching/1   active    idle   10.1.232.38
temporal-k8s-worker/0*    active    idle   10.1.232.42
temporal-k8s-worker/1     active    idle   10.1.232.23
temporal-k8s/0*           active    idle   10.1.232.26
temporal-k8s/1            active    idle   10.1.232.25
```

To confirm the four scaled services can reach other, you can run
`juju run temporal-admin-k8s/0 tctl args="adm cl d"`, you should see the
following:

```
output: |
  {
    "supportedClients": {
      "temporal-cli": "\u003c2.0.0",
      "temporal-go": "\u003c2.0.0",
      "temporal-java": "\u003c2.0.0",
      "temporal-php": "\u003c2.0.0",
      "temporal-server": "\u003c2.0.0",
      "temporal-typescript": "\u003c2.0.0",
      "temporal-ui": "\u003c3.0.0"
    },
    "serverVersion": "1.17.3",
    "membershipInfo": {
      "currentHost": {
        "identity": "10.1.232.25:7233"
      },
      "reachableMembers": [
        "10.1.232.42:6939",
        "10.1.232.6:6934",
        "10.1.232.25:6933",
        "10.1.232.51:6934",
        "10.1.232.23:6939",
        "10.1.232.38:6935",
        "10.1.232.61:6935",
        "10.1.232.26:6933"
      ],
      "rings": [
        {
          "role": "frontend",
          "memberCount": 2,
          "members": [
            {
              "identity": "10.1.232.26:7233"
            },
            {
              "identity": "10.1.232.25:7233"
            }
          ]
        },
        {
          "role": "history",
          "memberCount": 2,
          "members": [
            {
              "identity": "10.1.232.6:7234"
            },
            {
              "identity": "10.1.232.51:7234"
            }
          ]
        },
        {
          "role": "matching",
          "memberCount": 2,
          "members": [
            {
              "identity": "10.1.232.61:7235"
            },
            {
              "identity": "10.1.232.38:7235"
            }
          ]
        },
        {
          "role": "worker",
          "memberCount": 2,
          "members": [
            {
              "identity": "10.1.232.42:7239"
            },
            {
              "identity": "10.1.232.23:7239"
            }
          ]
        }
      ]
    },
    "clusterId": "514dd854-eb26-4e93-9f3c-1355cb8aa99a",
    "clusterName": "active",
    "historyShardCount": 4,
    "persistenceStore": "postgres",
    "visibilityStore": "postgres",
    "failoverVersionIncrement": "10",
    "initialFailoverVersion": "1"
  }
result: command succeeded
```

## Removing Replicas

To scale down the number of replicas, you can again use the juju
scale-application functionality i.e.

```
juju scale-application temporal-k8s -n <num_of_replicas_required_replicas>
```

To scale all four services back down to one unit each, you can run the following
commands:

```
juju scale-application temporal-k8s -n 1
juju scale-application temporal-k8s-history -n 1
juju scale-application temporal-k8s-matching -n 1
juju scale-application temporal-k8s-worker -n 1
```

You can then run `juju status --watch 1s` to watch the status of your
applications. It may take a few minutes to see the following output where all
nodes are showing `Workload=Active` and `Agent=idle`:

```
Model     Controller           Cloud/Region        Version  SLA          Timestamp
temporal  temporal-controller  microk8s/localhost  3.1.0    unsupported  15:18:19+03:00

App                    Version  Status  Scale  Charm               Channel    Rev  Address         Exposed  Message
postgresql-k8s         14.7     active      1  postgresql-k8s      14/stable   73  10.152.183.171  no       Primary
temporal-admin-k8s              active      1  temporal-admin-k8s  edge         4  10.152.183.35   no
temporal-k8s                    active      2  temporal-k8s                     0  10.152.183.95   no
temporal-k8s-history            active      2  temporal-k8s                     1  10.152.183.52   no
temporal-k8s-matching           active      2  temporal-k8s                     2  10.152.183.122  no
temporal-k8s-worker             active      2  temporal-k8s                     3  10.152.183.134  no

Unit                      Workload  Agent  Address      Ports  Message
postgresql-k8s/0*         active    idle   10.1.232.60         Primary
temporal-admin-k8s/0*     active    idle   10.1.232.20
temporal-k8s-history/0*   active    idle   10.1.232.6
temporal-k8s-history/1    active    idle   10.1.232.51         agent lost, see 'juju show-status-log temporal-k8s-history/1'
temporal-k8s-matching/0*  active    idle   10.1.232.61
temporal-k8s-matching/1   active    idle   10.1.232.38         agent lost, see 'juju show-status-log temporal-k8s-matching/1'
temporal-k8s-worker/0*    active    idle   10.1.232.42
temporal-k8s-worker/1     active    idle   10.1.232.23         agent lost, see 'juju show-status-log temporal-k8s-worker/1'
temporal-k8s/0*           active    idle   10.1.232.26
temporal-k8s/1            active    idle   10.1.232.25         agent lost, see 'juju show-status-log temporal-k8s/1'
```
