# Upgrade Charmed Temporal from 1.23 to 1.31

This guide describes how to upgrade an existing Charmed Temporal deployment from `1.23` to `1.31` using charms published on Charmhub.

Temporal Server and Admin must be upgraded sequentially through each minor version. For each upgrade, refresh Temporal Admin first to perform the database schema migrations, then refresh Temporal Server.

The Temporal UI and Worker upgrades are performed after Server and Admin reach version 1.31.

> **Important:** Database schema migrations are forward-only. There is no supported in-place downgrade. Always create and verify a PostgreSQL backup before upgrading.

## Step 1: Check the current deployment

Verify that the Temporal Server and Admin charms are running version 1.23:

```bash
juju status
```

Identify the deployed application names, channels, revisions, and Ubuntu bases.

The commands below assume the following application names:

- `temporal-admin-k8s`
- `temporal-k8s`
- `temporal-ui-k8s`
- `temporal-worker-k8s`

Replace these with your actual application names if different.

If the charms were originally deployed using locally built `.charm` files, transitioning to Charmhub requires `--switch <charm-name>` during the first refresh. This is not necessary for applications already deployed from Charmhub.

## Step 2: Back up PostgreSQL

Before upgrading, follow the [PostgreSQL K8s backup documentation](https://charmhub.io/postgresql-k8s/docs/h-create-a-backup) to create and verify a restorable backup.

Where possible, stop new workflow executions, allow running workflows to finish, and shut down workers gracefully before taking the backup.

Repeat this backup step before each minor-version upgrade.

## Step 3: Upgrade sequentially from 1.23 to 1.30

Upgrade through the following versions in order:

`1.24 → 1.25 → 1.26 → 1.27 → 1.28 → 1.29 → 1.30`

Before starting, verify that the corresponding channels are published for both Temporal Server and Admin on Charmhub. The examples below use the `edge` risk level; use the appropriate published risk level for your deployment.

For each target version:

### 3.1 Refresh Temporal Admin

For example, to upgrade to 1.24:

```bash
juju refresh temporal-admin-k8s \
  --channel 1.24/edge
```

Wait for Admin to complete its schema migration and return to active status.

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

Start a test workflow using an existing Temporal worker and confirm that it completes.

For example, with a deployed `GreetingWorkflow` worker:

```bash
juju run temporal-admin-k8s/0 cli \
  args='workflow start --type GreetingWorkflow --task-queue default --workflow-id <workflow_id> --input "world" --namespace temporal-system'
```

```bash
juju run temporal-admin-k8s/0 cli \
  args='workflow show --workflow-id <workflow_id> --namespace temporal-system'
```

Adapt the workflow type, task queue, namespace, and workflow ID to your deployment.

Repeat Steps 2 and 3 for each subsequent minor version, replacing `1.24/edge` with the corresponding channel until both charms reach 1.30.

## Step 4: Upgrade from 1.30 to 1.31

Version 1.31 supports the transition to Ubuntu 26.04.

### 4.1 Refresh Temporal Admin

Create and verify another PostgreSQL backup.

```bash
juju refresh temporal-admin-k8s \
  --channel 1.31/stable \
  --base ubuntu@26.04
```

Wait for the charm to complete the upgrade hook and schema migration.

```bash
juju status
juju debug-log --include temporal-admin-k8s/0
```

Verify the following messages appear after the refresh:

```text
Starting schema migration to 1.31.x
Schema db migrated using database user ...
Schema visibility migrated using database user ...
```

Do not proceed until both schemas have been successfully migrated and the Admin application is active.

### 4.2 Refresh Temporal Server

Once Admin is active and the database schemas are verified:

```bash
juju refresh temporal-k8s \
  --channel 1.31/stable \
  --base ubuntu@26.04
```

Wait for Server to become active and finish processing shard metadata.

```bash
juju status
```

## Step 5: Upgrade Temporal UI

Once Server and Admin are running version 1.31, upgrade Temporal UI to the corresponding 1.31 channel.

```bash
juju refresh temporal-ui-k8s \
  --channel 1.31/stable \
  --base ubuntu@26.04
```

Wait for the UI to become active:

```bash
juju status
```

Verify that the UI workload is running the expected release, and confirm that the UI can connect to Temporal Server, display workflows, and access workflow execution details.

## Step 6: Migrate Temporal Worker from 1.0 to 2.0

**Worker 2.0 must be deployed as a new application rather than refreshed in place**

### 6.1 Record the existing Worker configuration

Before migrating, inspect and preserve the current configuration, resources, and integrations.

```bash
juju config temporal-worker-k8s --format yaml \
  > worker-config-before-upgrade.yaml
```

```bash
juju resources temporal-worker-k8s
juju status --relations
```

Identify the OCI image containing the existing worker application.

```bash
kubectl get pod temporal-worker-k8s-0 \
  -o jsonpath='{range .spec.containers[*]}{.name}{": "}{.image}{"\n"}{end}'
```

Run the command in the model's Kubernetes namespace.

Record the worker image, configured namespace, task queue, and any custom authentication, environment, or integration settings.

### 6.2 Deploy Worker 2.0 as a new application

Deploy Worker 2.0 alongside the existing Worker 1.0 application.

For example:

```bash
juju deploy temporal-worker-k8s temporal-worker-v2 \
  --channel 2.0/stable \
  --base ubuntu@24.04 \
  --resource temporal-worker-image=<worker-image> \
  --config namespace=temporal-system \
  --config queue=default
```

Replace `<worker-image>` with the OCI image containing your worker code. Ensure the image is accessible and compatible with Worker 2.0.

Use the namespace and task queue from your existing deployment rather than copying the example values blindly.

Restore any additional configuration needed by the worker.

### 6.3 Integrate Worker 2.0 with Temporal Server

```bash
juju integrate \
  temporal-k8s:temporal-host-info \
  temporal-worker-v2:temporal-host-info
```

Recreate any other required integrations that were present on Worker 1.0.

Wait for Worker 2.0 to become active.

```bash
juju status
```

Verify that the new worker is listening to the expected Temporal namespace and task queue.

### 6.4 Verify Worker 2.0

Because both worker applications may initially consume tasks from the same queue, first verify Worker 2.0 is healthy, then stop Worker 1.0 from polling.

For a single-unit Worker 1.0 deployment:

```bash
juju scale-application temporal-worker-k8s 0
```

Wait until the old worker unit has stopped.

Start a new test workflow:

```bash
juju run temporal-admin-k8s/0 cli \
  args='workflow start --type GreetingWorkflow --task-queue default --workflow-id upgrade-test-worker-v2 --input "world" --namespace temporal-system'
```

Verify its execution:

```bash
juju run temporal-admin-k8s/0 cli \
  args='workflow show --workflow-id upgrade-test-worker-v2 --namespace temporal-system'
```

Expected result:

```text
WorkflowExecutionCompleted
Status COMPLETED
```

Since Worker 1.0 has been scaled to zero, successful workflow execution confirms that Worker 2.0 can process tasks against the upgraded Temporal Server, assuming no other worker is consuming the same task queue.

Verify the expected workflow result as well as the completed status.

Once the new Worker has been validated, the old Worker application can be removed as part of the migration cutover. Keep it available for recovery until validation is complete.

## Step 7: Verify the complete upgrade

Check the final deployment:

```bash
juju status
```

Confirm that:

- Temporal Admin and Server are running the expected 1.31 workload versions.
- Admin and Server are `active/idle`.
- Both database schemas have been migrated successfully.
- Temporal Server is healthy.
- Temporal UI is active and can connect to the Server.
- Temporal Worker 2.0 is active and connected to the correct namespace and task queue.
- Existing workflows can be queried and new workflows execute successfully.

Verify the deployed Admin and Server charm bases:

```bash
kubectl get pod temporal-admin-k8s-0 \
  -o jsonpath='{.spec.containers[?(@.name=="charm")].image}{"\n"}'

kubectl get pod temporal-k8s-0 \
  -o jsonpath='{.spec.containers[?(@.name=="charm")].image}{"\n"}'
```

Run the commands against the Kubernetes namespace corresponding to the Juju model.

## Recovery

If an upgrade or schema migration fails, stop further refreshes. Capture the deployment status and Juju debug logs for investigation.

```bash
juju status
juju debug-log --include temporal-admin-k8s/0
juju debug-log --include temporal-k8s/0
```

For a failed `upgrade-charm` hook, inspect the traceback and resolve the underlying issue before retrying.

Juju can be configured to automatically retry failed hooks:

```bash
juju model-config automatically-retry-hooks=true
```

Enable this only after correcting the underlying failure; it does not repair incompatible charm packages or failed database operations.

Do not downgrade charms against a database that has already undergone a forward schema migration. Follow the PostgreSQL restore procedure using a validated backup taken before the failed upgrade.

For a failed Worker 2.0 cutover, retain Worker 1.0 at zero units until the new Worker has been verified or a controlled rollback is required.

## References

- [Temporal Server Upgrades](https://charmhub.io/temporal-k8s/docs/h-server-upgrades)
- [Upgrade from latest/stable to 1.23/stable](https://charmhub.io/temporal-k8s/docs/h-upgrade-1.23/stable)
- [Temporal UI on Charmhub](https://charmhub.io/temporal-ui-k8s)
- [Temporal Worker on Charmhub](https://charmhub.io/temporal-worker-k8s)
- [PostgreSQL K8s documentation](https://charmhub.io/postgresql-k8s/docs)
- [Juju refresh documentation](https://documentation.ubuntu.com/juju/3.6/reference/juju-cli/list-of-juju-cli-commands/refresh/)