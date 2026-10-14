# Deploy Temporal worker

## Requirements

* [`rockcraft`](https://snapcraft.io/rockcraft) installed.
* A local OCI images registry to push images to or access to a public one.

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

The [Temporal worker](https://docs.temporal.io/workers) is the entity that
listens and polls a specific task queue, and executes code in response to the
task.

The Temporal worker charm allows users to upload and automatically run custom worker scripts, independent of the chosen SDK.
This is achieved by creating a rock with all runtime dependencies, worker scripts, and workflows, that is used at deployment time.

Because of this, deploying the worker involves three steps:

1. Creating a custom container image for the worker using [rocks](https://documentation.ubuntu.com/server/explanation/virtualisation/about-rock-images/).
2. Deploying the worker charm using a custom container image.
3. Integrating the worker with the Temporal server via the `temporal-host-info` relation.

[note]
This guide covers two deployment topologies:

* **Same-model deployment** (recommended for first-time users): worker runs in the same Juju model as the Temporal server.
* **Cross-model deployment** (production-style): worker runs in a dedicated Juju model for isolation, integrated to the server via a cross-model relation.

Each topology has its own walkthrough below. Pick the one that matches your environment and follow it through the **Deploy** and **Connect** sections.

If your worker runs against a Temporal server outside the Juju controller, an ingress can be considered. See [Configure Ingress with Nginx Ingress Integrator](https://charmhub.io/temporal-k8s/docs/h-deploy-ingress) for more details.
[/note]

## Custom container image for the worker

To create a custom container image for the worker, you need to build and publish it using Rockcraft. The steps below guide you through creating a rock-based image that includes your worker script and associated workflows.

1. Create a `rockcraft` project. You can use the [`rockcraft.yaml`](https://github.com/canonical/temporal-worker-k8s-operator/tree/main/resource_sample_py) as template.

2. Ensure the `command` of the rock runs the worker script directly. For example, if `command: "/app/scripts/start-worker.sh"`:

```bash
$ cat start-worker.sh

python3 /app/resource_sample/worker.py
```

3. Ensure your activities and workflows are also included in the rock as the worker script needs access to them.

4. Build the rock with `rockcraft pack`.

5. Make your rock available in a local or public registry. See [Publish a rock to a registry](https://documentation.ubuntu.com/rockcraft/latest/how-to/rocks/publish-a-rock/) for details.

## Deploy the Temporal worker

Once the rock is ready and available, deploy the worker charm. The exact commands depend on the topology you chose in the introduction.

### Same-model deployment

Deploy the worker into the same Juju model as the Temporal server.

1. Deploy the worker charm using the recently created image:

```bash
juju deploy temporal-worker-k8s --channel 1.0/stable --base ubuntu@24.04 \
  --resource temporal-worker-image=<your-registry>/<your-rock-name>:<tag>
```

2. Configure the worker with the task queue to poll and namespace to connect to:

```bash
juju config temporal-worker-k8s queue=your-queue namespace=your-namespace
```

[note]
The `temporal-worker-k8s` charm follows its own version track (`1.0`), independent of the Temporal server (`1.31`). User workflows are SDK-pinned rather than server-pinned, so the worker charm does not bump its track when the server bumps. `1.0/stable` is the supported track for use with `temporal-k8s` `1.31/stable`.
[/note]

### Cross-model deployment

Deploy the worker into a dedicated Juju model.

[note]
A dedicated model gives logical isolation between the Temporal server components and the workers. This is useful for production environments where the worker fleet has its own access controls, scaling policy, or operator team.
[/note]

1. Add a model for the workers and deploy the charm there:

```bash
juju add-model temporal-workers-model

juju deploy temporal-worker-k8s -m temporal-workers-model \
  --channel 1.0/stable --base ubuntu@24.04 \
  --resource temporal-worker-image=<your-registry>/<your-rock-name>:<tag>
```

2. Configure the worker with the task queue to poll and namespace to connect to:

```bash
juju config -m temporal-workers-model temporal-worker-k8s queue=your-queue namespace=your-namespace
```

---

At this point the worker is configured but does not yet know how to reach the Temporal frontend. The next section adds the `temporal-host-info` relation, which is the supported way to provide that information.

## Connect the worker to the Temporal server using `temporal-host-info`

The worker discovers the Temporal frontend's host and port through the **`temporal-host-info` relation**, provided by the `temporal-k8s` charm. This is the **supported and recommended way** to connect a worker to a Temporal server in `1.23/stable`, `1.31/stable`, and later.

Once the relation is in place, the worker re-reads the frontend address whenever the server publishes a change, with no manual reconfiguration required. If the relation is absent, the worker falls back to the deprecated `host` config. See the deprecation notice at the end of this section.

### Same-model integration

If the worker and the server are in the same Juju model, integrate them directly:

```bash
juju integrate temporal-k8s:temporal-host-info temporal-worker-k8s:temporal-host-info
```

Then wait for the worker to reach `active`:

```bash
juju wait-for application temporal-worker-k8s --query='status=="active"' --timeout=10m

juju status
```

### Cross-model integration

If the worker lives in a separate model from the server, use a [cross-model relation](https://juju.is/docs/juju/manage-cross-model-integrations). This involves three commands: `juju offer` on the server side, `juju consume` on the worker side, then `juju integrate`.

1. In the **server model** (the model where `temporal-k8s` is deployed), expose `temporal-host-info` as an offer:

```bash
juju switch <server-model>

juju offer temporal-k8s:temporal-host-info
```

This produces an offer URL of the form `<controller>:admin/<server-model>.temporal-k8s`.

2. In the **worker model**, consume the offer and integrate the worker against it:

```bash
juju switch temporal-workers-model

juju consume <controller>:admin/<server-model>.temporal-k8s temporal-host-info-offer

juju integrate temporal-worker-k8s:temporal-host-info temporal-host-info-offer
```

3. Wait for the worker to reach `active`:

```bash
juju wait-for application temporal-worker-k8s --query='status=="active"' --timeout=10m

juju status
```

---

The worker now polls the task queue and namespace you configured, against the frontend address advertised over the relation.

> ### Deprecation notice: `host` config
>
> Earlier versions of the `temporal-worker-k8s` charm accepted a `host` config option to point at the Temporal server. **`host` is deprecated in `1.23/stable`** and will be removed in a future release. It is only consulted as a fallback when the `temporal-host-info` relation is absent.
>
> Do not introduce new dependencies on `host`. If you are migrating an existing worker that uses `host`, integrate the relation as shown above and clear the config: `juju config temporal-worker-k8s --reset host`. See the [`latest/stable` → `1.23/stable` upgrade guide](https://charmhub.io/temporal-k8s/docs/h-upgrade-1.23/stable) for the full migration procedure.

## Expose worker metadata to other charms (optional)

The worker charm provides a `temporal-worker-info` relation that publishes its **namespace** and **task queue** to consuming charms. This lets downstream charms (for example, an admin or routing charm) discover where to start workflows without hard-coding the values.

If you are writing a charm that needs to consume worker metadata, use the [`temporal_worker_info` charm library](https://charmhub.io/temporal-worker-k8s/libraries/temporal_worker_info). The `TemporalWorkerInfoRequirer` class exposes an `is_ready()` method and a `temporal_worker_info_available` event.

Most tutorial users do **not** need this relation. It is only relevant if another Juju application needs to discover the worker's namespace and queue.

> **See next: [Run Your First Workflow](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-run-your-first-workflow/11785)**
