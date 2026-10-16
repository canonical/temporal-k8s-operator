# Configure the Temporal worker

This guide describes the configuration surface of the [`temporal-worker-k8s`](https://charmhub.io/temporal-worker-k8s) charm. Each section below covers one concern (server connection, authentication, observability, …); apply only the sections that match your environment. The full list of options is also available on the auto-generated [Configurations](https://charmhub.io/temporal-worker-k8s/configurations) page.

This guide assumes you have already deployed the worker - see the [Deploy Temporal Worker tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-worker/11784) if you have not.

---

## Connect to a Temporal server

The worker connects to a Temporal frontend through the **`temporal-host-info` relation**, provided by the `temporal-k8s` charm. This is the supported and recommended path:

```bash
juju integrate temporal-k8s:temporal-host-info temporal-worker-k8s:temporal-host-info
```

For cross-model deployments, use a [cross-model relation](https://juju.is/docs/juju/manage-cross-model-integrations) (`juju offer` + `juju consume` + `juju integrate`). See the [tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-worker/11784) for the full sequence.

> **Deprecation notice: `host` config.** The `host` config is deprecated and will be removed in a future release. It is only consulted as a fallback when the `temporal-host-info` relation is absent. Do not introduce new dependencies on `host`.

## Set the namespace and task queue

The worker polls a single `(namespace, task-queue)` pair. Configure both:

```bash
juju config temporal-worker-k8s namespace=your-namespace queue=your-queue
```

These options have no defaults - the worker will block until both are set.

## Inject environment variables into the worker

The `environment` config injects values into the worker container at runtime. Values can come from **three sources** - plain environment variables, Juju secrets, or HashiCorp Vault and you can mix them in a single `environment.yaml` file. The worker resolves values in the order: Vault -> Juju secrets -> plain env vars.

Apply the file with:

```bash
juju config temporal-worker-k8s environment=@/path/to/environment.yaml
```

Workflow code reads the values via `os.getenv("KEY")`.

### Plain environment variables

For non-sensitive values such as the deployment environment label:

```yaml
# environment.yaml
env:
  - name: APP_ENV
    value: production
  - name: REGION
    value: eu-west-1
```

> **Do not put plain secrets in the `env:` section.** Anything here is visible in `juju config` output. Use the `juju:` or `vault:` sections for sensitive values.

### Juju user secrets (Juju 3.3+)

Add a secret to the Juju model and grant the worker access:

```bash
juju add-secret my-secret key1=value1 key2=value2
juju grant-secret my-secret temporal-worker-k8s
```

Then reference the secret in `environment.yaml`:

```yaml
juju:
  - secret-id: <secret-id-from-add-secret>
    name: ENV_VAR1
    key: key1
  - secret-id: <secret-id-from-add-secret>
    name: ENV_VAR2
    key: key2
  - secret-id: <other-secret-id> # reads all keys; injects them as SCREAMING_SNAKE_CASE env vars
```

If a `juju:` entry omits `name` and `key`, the charm reads **all** keys from that secret and injects each one as a SCREAMING_SNAKE_CASE environment variable (e.g. `access-token` → `ACCESS_TOKEN`).

### HashiCorp Vault

Once the Vault relation is established (see [Use HashiCorp Vault for runtime secrets](#use-hashicorp-vault-for-runtime-secrets) below), reference Vault paths in `environment.yaml`:

```yaml
vault:
  - path: my-secrets
    name: ENV_VAR1
    key: key1
  - path: my-secrets
    name: ENV_VAR2
    key: key2
```

## Use Juju secrets for authentication

The supported way to give the worker its auth and encryption material is to put it in a Juju secret and point the charm at the secret via `auth-secret-id`.

### What keys the secret accepts

The secret can contain any of the following keys; only include the ones relevant to your auth provider.

| Group | Keys | Used when |
| :--- | :--- | :--- |
| Encryption | `encryption-key` | Always supported; base64-encoded data encryption key |
| Auth provider | `auth-provider` | Set to either `candid` or `google` |
| Candid | `candid-url`, `candid-username`, `candid-public-key`, `candid-private-key` | `auth-provider=candid` |
| OIDC (Google) | `oidc-auth-type`, `oidc-project-id`, `oidc-private-key-id`, `oidc-private-key`, `oidc-client-email`, `oidc-client-id`, `oidc-auth-uri`, `oidc-token-uri`, `oidc-auth-cert-url`, `oidc-client-cert-url` | `auth-provider=google` |

### Create the secret and wire it up

```bash
juju add-secret temporal-worker-auth \
  encryption-key=<base64-key> \
  auth-provider=google \
  oidc-auth-type=service_account \
  oidc-project-id=<gcp-project-id> \
  oidc-private-key-id=<...> \
  oidc-private-key=<...> \
  oidc-client-email=<...> \
  oidc-client-id=<...> \
  oidc-auth-uri=<...> \
  oidc-token-uri=<...> \
  oidc-auth-cert-url=<...> \
  oidc-client-cert-url=<...>

juju grant-secret temporal-worker-auth temporal-worker-k8s
juju config temporal-worker-k8s auth-secret-id=<secret-id-from-add-secret>
```

Replace the `oidc-*` block with the four `candid-*` keys if `auth-provider=candid`.

`auth-secret-id` **takes precedence** over the individual auth-related charm config options (`encryption-key`, `auth-provider`, `candid-*`, `oidc-*`). Those individual config options are deprecated and will be removed in a future release - set everything via the secret instead.

For a focused walkthrough of OAuth / Google Cloud service-account authentication including obtaining the OIDC values, see the [How to configure authentication](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-authentication/12586) guide.

## Use HashiCorp Vault for runtime secrets

The worker can pull secrets from a Vault instance at runtime, in addition to or instead of Juju secrets. This is the recommended option for production environments where workflow code needs database credentials, API keys, or other rotating secrets.

1. Deploy and unseal `vault-k8s`. Vault requires a manual initialisation and unseal step before it can serve secrets - follow the [`vault-k8s` operator instructions](https://charmhub.io/vault-k8s).

```bash
juju deploy vault-k8s --channel 1.16/edge

# ... follow the vault-k8s docs to initialise and unseal ...
```

2. Integrate the worker with `vault-k8s`:

```bash
juju integrate temporal-worker-k8s:vault vault-k8s
```

3. Add a secret to Vault via the worker's action:

```bash
juju run temporal-worker-k8s/leader add-vault-secret \
  path=<secret-path> key=<secret-key> value=<secret-value>
```

4. Read it back to verify:

```bash
juju run temporal-worker-k8s/leader get-vault-secret \
  path=<secret-path> key=<secret-key>
```

5. Reference the Vault-backed values in your `environment.yaml` under the `vault:` section (see [Inject environment variables into the worker](#inject-environment-variables-into-the-worker)).

> **Vault must be unsealed** every time it restarts. If the Temporal worker enters `blocked` after a Vault unit restart, check the Vault unit status; workflow runs will fail until Vault is unsealed.

## Configure TLS for the Temporal server connection

If the Temporal frontend uses TLS with a non-system-trusted CA, set the root CA(s) via `tls-root-cas`:

```bash
juju config temporal-worker-k8s tls-root-cas="$(cat ca-bundle.pem)"
```

The value is a PEM-encoded bundle. The worker presents these CAs when validating the frontend's certificate.

## Configure Sentry for error reporting

The worker can report unhandled errors to a Sentry project:

```bash
juju config temporal-worker-k8s \
  sentry-dsn=https://<key>@<org>.ingest.sentry.io/<project> \
  sentry-environment=production \
  sentry-release=2026.05.01 \
  sentry-sample-rate=1.0 \
  sentry-redact-params=true
```

| Option | Purpose | Default |
| :--- | :--- | :--- |
| `sentry-dsn` | Sentry DSN to send events to | empty (Sentry disabled) |
| `sentry-environment` | Free-form environment label | empty |
| `sentry-release` | Release identifier (e.g. version, commit) | empty |
| `sentry-sample-rate` | Fraction of errors to capture (0.0–1.0) | `1.0` |
| `sentry-redact-params` | Redact event parameters before sending | `false` |

Leave `sentry-dsn` empty to disable Sentry entirely.

## Connect to a PostgreSQL database

If the worker's workflows need a relational database, integrate the worker with `postgresql-k8s` and configure a database name:

```bash
juju deploy postgresql-k8s --channel 14/stable --trust
juju integrate temporal-worker-k8s:database postgresql-k8s:database
juju config temporal-worker-k8s db-name=your-db-name
```

Once the relation is `active`, the charm injects the following environment variables into the worker container, workflow code can reference them directly:

| Env var | Contains |
| :--- | :--- |
| `TEMPORAL_DB_NAME` | Database name (matches `db-name` config) |
| `TEMPORAL_DB_HOST` | PostgreSQL host |
| `TEMPORAL_DB_PORT` | PostgreSQL port |
| `TEMPORAL_DB_USER` | DB username provisioned for the relation |
| `TEMPORAL_DB_PASSWORD` | DB password provisioned for the relation |
| `TEMPORAL_DB_TLS` | Whether the relation uses TLS |

The relation is optional, only integrate it if the workflows actually consume a database connection.

## Set the log level

```bash
juju config temporal-worker-k8s log-level=debug
```

Acceptable values: `info` (default), `debug`, `warning`, `error`, `critical`.

## Use an HTTP proxy

If the workload container needs to reach the Temporal server (or any other endpoint) through an HTTP proxy, set the proxy on the **Juju model**. The charm reads these values and injects `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` into the workload container.

```bash
juju model-config juju-http-proxy=<http-proxy-url>
juju model-config juju-https-proxy=<https-proxy-url>
juju model-config juju-no-proxy=<no-proxy-list>
```

If the worker is already deployed when you change these, trigger a reconciliation (e.g. `juju config temporal-worker-k8s log-level=info` or run the `restart` action below) so the new env vars take effect.

---

## Restart the worker

Some config changes require a worker restart to take effect. The charm exposes a `restart` action:

```bash
juju run temporal-worker-k8s/0 restart
```

## Reset a config option

To revert any option to its default, use `--reset`:

```bash
juju config temporal-worker-k8s --reset host
juju config temporal-worker-k8s --reset sentry-dsn
```

`--reset` is the migration command for moving off deprecated options once their replacement is wired up.

---

## See also

- [Deploy Temporal Worker tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-worker/11784) - the prerequisite tutorial.
- [How to configure authentication](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-authentication/12586) - focused walkthrough of OAuth / Google Cloud service accounts.
- [How to scale Temporal](https://discourse.charmhub.io/t/10840) - including the worker.
- [`temporal-worker-k8s` Configurations page](https://charmhub.io/temporal-worker-k8s/configurations) - auto-generated reference of all options.
- [`latest/stable` to `1.23/stable` upgrade guide](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-upgrade-from-latest-stable-to-1-23-stable/20313) - for migrating an existing worker to the relation-based connection.
