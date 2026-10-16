# Upgrade Charmed Temporal `latest/stable` to `1.23/stable`

This guide describes how to upgrade an existing Charmed Temporal deployment from the `latest/stable` channel to the `1.23/stable` channel. It is intended for operators who already have a Charmed Temporal deployment running.

The guide has been validated end-to-end on Juju `3.6.21`.

---

## Important

Read these notes before starting the upgrade.

- **The schema migration is forward-only.** There is no in-place downgrade. If the upgrade fails, the recovery path is restore-from-PostgreSQL-backup either back to `latest/stable` or directly on `1.23/stable` once the underlying issue is resolved.
- **The Temporal charms change their base from `ubuntu@22.04` to `ubuntu@24.04`** between `latest/stable` and `1.23/stable`.
- **`temporal-ui-k8s` requires the new `temporal-host-info` relation** and will block until it is integrated. `temporal-admin-k8s` accepts the deprecated `server-name` config as a fallback.
- **The `tctl` action on `temporal-admin-k8s` was renamed to `cli` in 1.23**, and the underlying binary changed from the legacy `tctl` to the modern [`temporal` CLI](https://docs.temporal.io/cli) with different argument grammar. Operator scripts that call `juju run temporal-admin/0 tctl args="..."` must be updated.

> ### Deprecation notice: `server-name`
>
> The `server-name` config option on `temporal-admin-k8s` is **deprecated in 1.23** and will be removed in a future release. Its only purpose in 1.23 is to act as a fallback when the `temporal-host-info` relation is absent. The supported configuration is to integrate the `temporal-host-info` relation and leave `server-name` unset. Do not introduce new dependencies on `server-name`.

---

## Step 1: Back up PostgreSQL

The single source of truth for workflow history and namespace metadata is the PostgreSQL backend. **Back it up before the refresh.**

> **Recommendation: stop active work before the backup.**
>
> Temporal can recover from a database backup without needing a clean shutdown first, so this step is optional. That said, backing up while the system is quiet lowers the risk of capturing incomplete workflow state. If you can, do the following before running the backup:
>
> - **Stop new workflow starts** - pause or disable anything that triggers new executions (cron jobs, API clients, schedules).
> - **Wait for running workflows to finish** - or at least reach a point where they are waiting on a timer, activity, or signal.
> - **Shut down workers gracefully** - send a shutdown signal so the SDK can finish cleanly. In the Python SDK, `worker.run()` handles `SIGINT`/`SIGTERM` this way by default.

Follow the official postgresql-k8s backup procedure: [Create a backup](https://charmhub.io/postgresql-k8s/docs/h-create-backup). The how-to covers configuring an S3 backup target, taking a backup, and verifying it.

If the upgrade fails at any point, restoring this dump and redeploying on `latest/stable` returns the cluster to its pre-upgrade state. See [Recovery](#recovery) for the full procedure.

---

## Step 2: Refresh `temporal-admin-k8s`

The admin charm owns schema management and must be refreshed first.

```bash
juju refresh temporal-admin --channel 1.23/stable --base ubuntu@24.04
```

After settling, `temporal-admin` reports `active` status.

Note: The `temporal-host-info` relation cannot be integrated yet because `temporal-k8s` has not been refreshed and does not yet provide the endpoint. The relation will be integrated in [Step 5](#step-5-integrate-the-temporal-host-info-relation) after `temporal-k8s` is refreshed.

---

## Step 3: Refresh `temporal-ui-k8s`

The UI charm in 1.23 strictly requires the new `temporal-host-info` relation. After refresh, it will go to `blocked` status with the message `temporal-host-info relation not established`. This is the expected state until [Step 5](#step-5-integrate-the-temporal-host-info-relation).

> **Service availability.** The Temporal UI is unavailable from the moment the UI pod starts replacing until the `temporal-host-info` relation is integrated in Step 5.

```bash
juju refresh temporal-ui --channel 1.23/stable --base ubuntu@24.04
```

---

## Step 4: Refresh `temporal-k8s`

```bash
juju refresh temporal-k8s --channel 1.23/stable --base ubuntu@24.04
```

---

## Step 5: Integrate the `temporal-host-info` relation

Both `temporal-ui` and `temporal-admin` need this relation in 1.23. Add both, and clear the deprecated `server-name` fallback so the relation becomes the single source of truth.

Reset the deprecated `server-name` config on `temporal-admin`:

```bash
juju config temporal-admin --reset server-name
```

Integrate the `temporal-host-info` relation:

```bash
juju integrate temporal-k8s:temporal-host-info temporal-ui:temporal-host-info
juju integrate temporal-k8s:temporal-host-info temporal-admin:temporal-host-info
```

After this step every application should be `active/idle`. Confirm the admin `cli` action is on the relation path (no longer the deprecated fallback):

```bash
juju run temporal-admin/0 cli args="operator namespace describe --namespace <your-namespace>"
```

---

## Step 6: (Optional) Insert `pgbouncer-k8s` between Temporal and PostgreSQL

The 1.23 solution recommends placing `pgbouncer-k8s` between Temporal services and PostgreSQL for connection pooling. This is a topology change, separate from the channel refresh.

```bash
juju deploy pgbouncer-k8s pgbouncer --channel 1/stable --trust
juju integrate pgbouncer:backend-database postgres:database

# Remove the direct postgres relations, then add the pgbouncer-fronted ones
juju remove-relation temporal-k8s:db          postgres:database
juju remove-relation temporal-k8s:visibility  postgres:database
juju integrate       temporal-k8s:db          pgbouncer:database
juju integrate       temporal-k8s:visibility  pgbouncer:database
```

---

## Recovery

If an upgrade or schema migration fails, stop further refreshes. Capture the deployment status and Juju debug logs for investigation:

```bash
juju status
juju debug-log --include temporal-admin/0
juju debug-log --include temporal-k8s/0
```

For a failed `upgrade-charm` hook, inspect the traceback and resolve the underlying issue before retrying.

Juju can be configured to automatically retry failed hooks:

```bash
juju model-config automatically-retry-hooks=true
```

Enable this only after correcting the underlying failure; it does not repair incompatible charm packages or failed database operations.

Do not downgrade charms against a database that has already undergone a forward schema migration. Follow the [PostgreSQL restore procedure](https://charmhub.io/postgresql-k8s/docs/h-restore-backup) using a validated backup taken before the failed upgrade.
