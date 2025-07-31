# Deploy Temporal worker

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

The [Temporal worker](https://docs.temporal.io/workers) is the entity that
listens and polls a specific task queue, and executes code in response to the
task.

## Explanation

The Temporal worker charm allows users to upload and automatically run custom worker scripts (regardless of the SDK of choice).
This is achieved by creating a rock with all runtime dependencies, worker scripts, and workflows, that is used at deployment time.

Because of this, deploying the worker goes in two parts:

1. Creating a custom worker rock
2. Deploying the worker charm using the worker rock

[note]

In a production environment, a Temporal worker can be deployed in a separate
environment from the Temporal server, for simplicity, this guide will assume
the server and worker belong to the same network, and can be connected directly.

It this is not the case, an ingress can be considered. See [Configure Ingress with Nginx Ingress Integrator](https://charmhub.io/temporal-k8s/docs/h-deploy-ingress) for more details.

[/note]

## Custom worker rock

### Requirements

* [`rockcraft`](https://snapcraft.io/rockcraft) installed
* A local OCI images registry to push images to or access to a public one


1. Create a `rockcraft` project, you can use the [`rockcraft.yaml`](https://github.com/canonical/temporal-worker-k8s-operator/tree/main/resource_sample_py) as template.

2. Make sure the `command` of the rock runs the worker script directly. For example, if `command: "./app/scripts/start-worker.sh"`:

```
$ cat start-worker.sh
 
python3 app/resource_sample/worker.py
```

3. Make sure your activities and workflows are also included in the rock as the worker script needs access to them.

4. Build the rock with `rockcraft pack`.

5. Make your rock available in a local or public registry. See [Publish a rock to a registry](https://documentation.ubuntu.com/rockcraft/latest/how-to/rocks/publish-a-rock/) for details.

## Deploy and configure Temporal worker

1. (optional) Add a model where worker charms will be deployed:

```
juju add-model temporal-workers-model
```

2. Deploy the worker charm using the recently created image:

```
juju deploy temporal-worker-k8s --resource temporal-worker-image=<your-registry>/<your-rock-name>:<tag>
```

3. Create a configuration file with information about the server hostname, the task queue to poll, and namespace to connect to:

```
cat config.yaml

temporal-worker-k8s:
  host: "temporal-server-hostname:7233"
  queue: "your-queue"
  namespace: "your-namespace"
```

4. Configure the worker charm with the configuration file from the previous step:

```
juju config temporal-worker-k8s --file=path/to/config.yaml
```

> **See next: [Run Your First Workflow](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-run-your-first-workflow/11785)**
