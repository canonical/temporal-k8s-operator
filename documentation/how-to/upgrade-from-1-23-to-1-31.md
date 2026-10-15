# Upgrade Charmed Temporal `1.23/stable` to `1.31/stable`

This guide describes how to upgrade an existing Charmed Temporal deployment from the `1.23/stable` channel to the `1.31/stable` channel on `ubuntu@26.04`. It is intended for operators who already have a Charmed Temporal deployment running on `1.23/stable`.

The guide has been validated end-to-end on Juju `3.6`.

---

## Important

Read these notes before starting the upgrade.

- **The schema migration is forward-only.** There is no in-place downgrade. If the upgrade fails, the recovery path is restore-from-PostgreSQL-backup back to `1.23/stable` or directly onto `1.31/stable` once the underlying issue is resolved.
- **The Temporal charms change their base from `ubuntu@24.04` to `ubuntu@26.04`** between `1.23/stable` and `1.31/stable`.
- **`temporal-host-info` is mandatory.** All charms (`temporal-admin-k8s`, `temporal-ui-k8s`, and `temporal-worker-k8s`) must be integrated via the `temporal-host-info` relation. The deprecated `server-name` config on `temporal-admin-k8s` and `host` config on `temporal-worker-k8s` should be reset/cleared.
- **Sequential upgrade:** Upgrades must be executed consecutively. Do not upgrade directly from `latest/stable` to `1.31/stable`; upgrade to `1.23/stable` first.

---

## Step 1: Back up PostgreSQL

The single source of truth for workflow history and namespace metadata is the PostgreSQL backend. **Back it up before the refresh.**

> **Recommendation: stop active work before the backup.**
>
> Temporal can recover from a database backup without needing a clean shutdown first, so this step is optional. That said, backing up while the system is quiet lowers the risk of capturing incomplete workflow state:
>
> - **Stop new workflow starts** — pause or disable anything that triggers new executions (cron jobs, API clients, schedules).
> - **Wait for running workflows to finish** — or at least reach a point where they are waiting on a timer, activity, or signal.
> - **Shut down workers gracefully** — send a shutdown signal so the SDK can finish cleanly. In the Python SDK, `worker.run()` handles `SIGINT`/`SIGTERM` this way by default.

Follow the official postgresql-k8s backup procedure: [Create a backup](https://charmhub.io/postgresql-k8s/docs/h-create-backup).

If the upgrade fails at any point, restoring this dump returns the cluster to its pre-upgrade state. See [Recovery](#recovery-if-the-upgrade-fails) for the full procedure.

---

## Step 2: Refresh `temporal-admin-k8s`

The admin charm owns schema management and must be refreshed first.

```bash
juju refresh temporal-admin --channel 1.31/stable --base ubuntu@26.04
```

After settling, run the schema setup action to apply database schema updates for Temporal 1.31:

```bash
juju run temporal-admin/leader setup-schema
```

Ensure `temporal-admin` reports `active` status.

---

## Step 3: Refresh `temporal-ui-k8s`

Refresh the Web UI charm to 1.31 on `ubuntu@26.04`:

```bash
juju refresh temporal-ui --channel 1.31/stable --base ubuntu@26.04
```

Wait until the application finishes updating and returns to `active` status.

---

## Step 4: Refresh `temporal-k8s`

Refresh the core Temporal server charm:

```bash
juju refresh temporal-k8s --channel 1.31/stable --base ubuntu@26.04
```

Wait until the application reaches `active` status.

---

## Step 5: Verify Relations and Status

Verify that all units have updated and the integrations remain active:

```bash
juju status
juju status --relations
```

Confirm the admin `cli` action reaches the upgraded server and can query the cluster:

```bash
juju run temporal-admin/0 cli args="operator namespace list" --wait 1m
```

---

## Recovery (if the upgrade fails)

There is **no in-place rollback**. Temporal's schema migration is forward-only. If the upgrade fails at any step, restore from the PostgreSQL backup taken in [Step 1](#step-1-back-up-postgresql), then choose one of two redeployment paths:

1. Stop applying further refreshes.
2. Capture diagnostics:
   ```bash
   juju status > failure-status.txt
   juju show-unit <stuck-unit> > failure-unit.yaml
   juju debug-log --replay --level WARNING > failure-log.txt
   ```
3. Destroy the model:
   ```bash
   juju destroy-model <model> --no-prompt --destroy-storage
   ```
4. Restore PostgreSQL from your backup (see the [postgresql-k8s restore how-to](https://charmhub.io/postgresql-k8s/docs/h-restore-backup)).
5. Choose one of:
   * **Option A: Re-attempt the upgrade on `1.31/stable` (recommended).** If the failure was caused by a transient network issue or configuration mismatch, redeploy directly on `1.31/stable` against the restored database.
   * **Option B: Roll back to `1.23/stable`.** Redeploy on `1.23/stable` and reconnect to the restored database.

Report any reproducible failure to the [`temporal-k8s-operator` issues](https://github.com/canonical/temporal-k8s-operator/issues) with the diagnostics from step 2.
