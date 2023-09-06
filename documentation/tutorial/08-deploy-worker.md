# Deploy Temporal Worker

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

The [Temporal Worker](https://docs.temporal.io/workers) is the entity which
listens and polls on specific task queue, and executes code in response to the
task.

## Deploy

In a production environment, a Temporal worker is deployed in a separate
environment from the Temporal server. As our server is currently locally
deployed, we will opt for a direct connection from the worker rather than using
the ingress.

To deploy Charmed Temporal Worker to a different model, you need to run the
following commands, which will fetch the charm from
[Charmhub](https://charmhub.io/temporal-worker-k8s) and deploy it to your model:

```bash
juju add-model temporal-worker
juju deploy temporal-worker-k8s
```

Wait until the application is ready - when it is ready, `juju status` will show:

```
Model            Controller           Cloud/Region        Version  SLA          Timestamp
temporal-worker  temporal-controller  microk8s/localhost  3.1.5    unsupported  13:21:49+03:00

App                  Version  Status   Scale  Charm                Channel  Rev  Address         Exposed  Message
temporal-worker-k8s           waiting      1  temporal-worker-k8s  stable     5  10.152.183.187  no       installing agent

Unit                    Workload  Agent  Address      Ports  Message
temporal-worker-k8s/0*  blocked   idle   10.1.232.75         Invalid config: wheel-file-name missing
```

## Configure Worker

In order to test our Temporal worker, we will use a
[sample resource](https://github.com/canonical/temporal-worker-k8s-operator/tree/main/resource_sample)
which contains one workflow and one activity. You can run the following commands
to clone the repository, build the necessary wheel file and attach it to the
worker charm:

```bash
git clone https://github.com/canonical/temporal-worker-k8s-operator.git
cd temporal-worker-k8s-operator/resource_sample

poetry build -f wheel # Take note of the generated file's name
```

We will then configure our worker to the Temporal server deployed in the
previous steps. Create a file `config.yaml` with the following content:

```yaml
temporal-worker-k8s:
  host: "10.1.232.64:7233" # Temporal Server unit IP address
  queue: "test-queue"
  namespace: "default"
  workflows-file-name: "python_samples-1.1.0-py3-none-any.whl"
  # To support all defined workflows and activities, use the 'all' keyword
  supported-workflows: "all"
  supported-activities: "all"
```

Note: To get the Temporal Server unit IP address, you need to switch to the
previously created model using `juju switch temporal-model` before switching
back to this model using `juju switch temporal-worker`.

Run the following command to configure your charm:

```bash
juju config temporal-worker-k8s --file=path/to/config.yaml

# Verify that the charm has been configured with the correct value
juju config temporal-worker-k8s host
```

And then run the following command to attach the workflows file to the worker:

```bash
juju attach-resource temporal-worker-k8s workflows-file=./dist/python_samples-1.1.0-py3-none-any.whl
```

Wait until the application is ready - when it is ready, `juju status` will show:

```
Model            Controller           Cloud/Region        Version  SLA          Timestamp
temporal-worker  temporal-controller  microk8s/localhost  3.1.5    unsupported  13:45:16+03:00

App                  Version  Status  Scale  Charm                Channel  Rev  Address         Exposed  Message
temporal-worker-k8s           active      1  temporal-worker-k8s  stable     5  10.152.183.187  no       worker listening to namespace 'default' on queue 'test-queue'

Unit                    Workload  Agent  Address      Ports  Message
temporal-worker-k8s/0*  active    idle   10.1.232.78         worker listening to namespace 'default' on queue 'test-queue'
```

To further verify that the worker is functioning correctly, observe the output
of the following command to ensure the absence of errors:

```bash
kubectl -n temporal-model logs temporal-worker-k8s-0 -c temporal-worker -f
```

At this point, we have a Temporal worker connected to our Temporal server on the
`default` namespace listening for tasks on the `test-queue` task queue.

> **See next:
> [Run Your First Workflow](/t/charmed-temporal-k8s-tutorial-run-your-first-workflow/11785)**
