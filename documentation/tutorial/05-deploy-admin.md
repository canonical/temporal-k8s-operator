# Deploy Temporal Admin

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

The Temporal Admin Tools are a set of command-line utilities used to configure
and support the Temporal server.

## Requirements

- You have completed [Environment Setup](./02-environment.md).
- You have completed [Deploy Temporal Server](./03-deploy-server.md).
- You have completed [Deploy PostgreSQL Database](./04-deploy-db.md).

## Deploy

To deploy Charmed Temporal Admin, you need to run the following command, which
will fetch the charm from [Charmhub](https://charmhub.io/temporal-admin-k8s) and
deploy it to your model:

```bash
juju deploy temporal-admin-k8s --channel 1.31/stable --base ubuntu@26.04
```

Check status:
```bash
juju status
```
Wait until the application is ready, when it is ready, `juju status` will show:
```
Model           Controller           Cloud/Region  Version  SLA          Timestamp
temporal-model  temporal-controller  ck8s          3.6.9    unsupported  22:36:50Z

App                 Version  Status   Scale  Charm               Channel       Rev  Address         Exposed  Message
postgresql-k8s      14.15    active       1  postgresql-k8s      14/stable     495  10.152.183.200  no
temporal-admin-k8s           blocked      1  temporal-admin-k8s  1.31/stable    27  10.152.183.97   no       admin:temporal relation: database connections info not available
temporal-k8s                 blocked      1  temporal-k8s        1.31/stable    68  10.152.183.120  no       admin:temporal relation: schema is not ready

Unit                   Workload  Agent  Address     Ports  Message
postgresql-k8s/0*      active    idle   10.1.0.36          Primary
temporal-admin-k8s/0*  blocked   idle   10.1.0.168         admin:temporal relation: database connections info not available
temporal-k8s/0*        blocked   idle   10.1.0.152         admin:temporal relation: schema is not ready
```
## Relate Admin to Server

The admin charm in `1.31/stable` requires **two** relations to reach `active`:

- `admin` - schema management bridge between admin and server.
- `temporal-host-info` - supplies the Temporal frontend's gRPC host and port to the admin charm so that its `cli` action can reach the server.

Add both:

```bash
juju integrate temporal-k8s:admin              temporal-admin-k8s:admin
juju integrate temporal-k8s:temporal-host-info  temporal-admin-k8s:temporal-host-info
```

> **Deprecation notice: `server-name` config.** Earlier versions of `temporal-admin-k8s` used the `server-name` config option to discover the Temporal frontend. **`server-name` is deprecated in `1.31/stable`** and will be removed in a future release; it is only consulted as a fallback when the `temporal-host-info` relation is absent. The relation is the supported path - do not introduce new dependencies on `server-name`.

Monitor relations until they settle:
```bash
juju status --relations
```
After a short while, all applications should be active:
```
Model           Controller           Cloud/Region  Version  SLA          Timestamp
temporal-model  temporal-controller  ck8s          3.6.9    unsupported  22:37:09Z

App                 Version  Status       Scale  Charm               Channel       Rev  Address         Exposed  Message
postgresql-k8s      14.15    active           1  postgresql-k8s      14/stable     495  10.152.183.200  no
temporal-admin-k8s  1.31.2   active           1  temporal-admin-k8s  1.31/stable    27  10.152.183.97   no       
temporal-k8s                 active           1  temporal-k8s        1.31/stable    68  10.152.183.120  no       

Unit                   Workload     Agent  Address     Ports  Message
postgresql-k8s/0*      active       idle   10.1.0.36          Primary
temporal-admin-k8s/0*  active       idle   10.1.0.168
temporal-k8s/0*        active       idle   10.1.0.152         

Integration provider              Requirer                            Interface           Type     Message
postgresql-k8s:database           temporal-k8s:db                     postgresql_client   regular
postgresql-k8s:database           temporal-k8s:visibility             postgresql_client   regular
postgresql-k8s:database-peers     postgresql-k8s:database-peers       postgresql_peers    peer
postgresql-k8s:restart            postgresql-k8s:restart              rolling_op          peer
postgresql-k8s:upgrade            postgresql-k8s:upgrade              upgrade             peer
temporal-admin-k8s:admin          temporal-k8s:admin                  temporal            regular
temporal-admin-k8s:peer           temporal-admin-k8s:peer             temporal-admin      peer
temporal-k8s:temporal-host-info   temporal-admin-k8s:temporal-host-info  temporal-host-info  regular
temporal-k8s:peer                 temporal-k8s:peer                   temporal            peer
```

## Create the initial namespace

You can run the following command to create the initial Temporal namespace:

```bash
# Create default namespace:
juju run temporal-admin-k8s/0 cli args="operator namespace create --namespace default --retention 3d" --wait 1m

# Output:
Running operation 19 with 1 task
  - task 20 on unit-temporal-admin-k8s-0

Waiting for task 20...
output: |
  Namespace default successfully registered.
result: command succeeded
```

[note]
The command above uses the `cli` action with the modern [`temporal` CLI](https://docs.temporal.io/cli) grammar. **In `1.23/stable`, the legacy `tctl` action was renamed to `cli`** and the underlying binary changed from the older `tctl` to the newer `temporal` CLI. Operator scripts that previously called `juju run temporal-admin-k8s/0 tctl args="..."` (with the old grammar like `--namespace X namespace register --retention 72h`) must be updated.

If you are upgrading an existing deployment, see the [`latest/stable` → `1.23/stable` upgrade guide](https://charmhub.io/temporal-k8s/docs/h-upgrade-1.23/stable).
[/note]

> **See next:
> [Deploy Temporal Web UI](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-web-ui/11782)**
