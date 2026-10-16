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
Wait until the application is ready, when it is ready, `juju status` will show `admin:temporal relation: database connections info not available` at the admin app and `admin:temporal relation: schema is not ready` on the server app.

## Relate Admin to Server

The admin charm in `1.31/stable` requires **two** relations to reach `active`:

- `admin` - schema management bridge between admin and server.
- `temporal-host-info` - supplies the Temporal frontend's gRPC host and port to the admin charm so that its `cli` action can reach the server.

Add both:

```bash
juju integrate temporal-k8s:admin              temporal-admin-k8s:admin
juju integrate temporal-k8s:temporal-host-info  temporal-admin-k8s:temporal-host-info
```

> **Deprecation notice: `server-name` is removed.** 
The `temporal-host-info` relation must be used.

Monitor relations until they settle:
```bash
juju status --relations
```
After a short while, all applications should be active.

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
