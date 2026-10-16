# Upgrade Charmed Temporal from 1.23 to 1.31

This guide describes how to upgrade an existing Charmed Temporal deployment from `1.23` to `1.31` using charms published on Charmhub.

Temporal must be upgraded sequentially through each minor version. For each upgrade, the Temporal Admin charm must be refreshed before Temporal Server so that the database schema is migrated first.

> **Important:** Database schema migrations are forward-only. There is no supported in-place downgrade. Always create and verify a PostgreSQL backup before upgrading.

## Step 1: Check the current deployment

Verify that the Temporal Server and Admin charms are running version 1.23:

```bash
juju status
juju status temporal-k8s
juju status temporal-admin-k8s
```

Identify the deployed application names, channels, revisions, and Ubuntu bases.

The commands below assume the application names are `temporal-admin-k8s` and `temporal-k8s`. Replace these with the actual names if different.

## Step 2: Back up PostgreSQL

Before upgrading, follow the [PostgreSQL K8s backup documentation](https://charmhub.io/postgresql-k8s/docs/h-create-a-backup) to create and verify a restorable backup.

Where possible, stop new workflow executions, allow running workflows to finish, and shut down workers gracefully before taking the backup.

Repeat this backup step before each minor-version upgrade.

## Step 3: Upgrade sequentially from 1.23 to 1.30

Upgrade through the following versions, in order:

`1.24 → 1.25 → 1.26 → 1.27 → 1.28 → 1.29 → 1.30`

For each target version:

### 3.1 Refresh Temporal Admin

For example, to upgrade to 1.24:

```bash
juju refresh temporal-admin-k8s \
  --channel 1.24/edge
```

Wait for Admin to complete its schema migration and return to active status:

```bash
juju status
juju debug-log --include temporal-admin-k8s/0
```

Verify that the logs show successful migration of both the main and visibility schemas. Some releases may have no pending SQL schema changes.

Do not proceed to the Server refresh if the Admin upgrade or schema migration fails.

### 3.2 Refresh Temporal Server

After Admin becomes active:

```bash
juju refresh temporal-k8s \
  --channel 1.24/edge
```

Wait for Temporal Server to become active:

```bash
juju status
```

Allow approximately 10 minutes for the History Service to load shards and update shard metadata before proceeding to the next version.

### 3.3 Verify workflow execution

Start a test workflow using an existing worker and confirm that it completes successfully.

For an existing workflow named `GreetingWorkflow`:

```bash
juju run temporal-admin-k8s/0 cli \
  args='workflow start --type GreetingWorkflow --task-queue default --workflow-id upgrade-test-124 --input "world" --namespace temporal-system'
```

```bash
juju run temporal-admin-k8s/0 cli \
  args='workflow show --workflow-id upgrade-test-124 --namespace temporal-system'
```

Adapt the workflow type, task queue, namespace, and workflow ID to your deployment.

Repeat Steps 2 and 3 for every subsequent minor version, replacing `1.24/edge` with the matching version channel until both charms reach 1.30.

## Step 4: Upgrade from 1.30 to 1.31

Version 1.31 introduces a charm base transition to Ubuntu 26.04.

### 4.1 Refresh Temporal Admin

Create and verify another PostgreSQL backup.

```bash
juju refresh temporal-admin-k8s \
  --channel 1.31/stable \
  --base ubuntu@26.04
```

Wait for the charm to complete its upgrade hook and database schema migration:

```bash
juju status
juju debug-log --include temporal-admin-k8s/0
```

Verify that both database schemas have been migrated successfully before proceeding.

### 4.2 Refresh Temporal Server

Once Admin is active and the database schemas are verified:

```bash
juju refresh temporal-k8s \
  --channel 1.31/stable \
  --base ubuntu@26.04
```

Allow time for the server to become active and finish processing shard metadata.

## Step 5: Verify the upgrade

Check the final charm status:

```bash
juju status
```

Confirm that:

- Temporal Admin and Server report the expected 1.31 workload versions.
- Both applications are `active/idle`.
- The main and visibility database migrations completed successfully.
- The Temporal Server workload is healthy.
- Existing workflows can be queried and new workflows can execute successfully.

Also verify the deployed charm bases:

```bash
kubectl get pod temporal-admin-k8s-0 \
  -o jsonpath='{.spec.containers[?(@.name=="charm")].image}{"\n"}'

kubectl get pod temporal-k8s-0 \
  -o jsonpath='{.spec.containers[?(@.name=="charm")].image}{"\n"}'
```

Run these Kubernetes commands against the namespace corresponding to the Juju model, adding `-n <namespace>` as needed.

## Recovery

If an upgrade or schema migration fails, stop further refreshes. Capture the deployment status and Juju debug logs for investigation.

Do not downgrade the charms against a database that has already undergone a forward schema migration. Follow the PostgreSQL restore procedure using the backup taken before the failed upgrade.

## References

- [Temporal Server Upgrades](https://charmhub.io/temporal-k8s/docs/h-server-upgrades)
- [Upgrade from latest/stable to 1.23/stable](https://charmhub.io/temporal-k8s/docs/h-upgrade-1.23/stable)
- [PostgreSQL K8s documentation](https://charmhub.io/postgresql-k8s/docs)
