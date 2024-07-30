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

In order to test our Temporal worker, we will use a
[sample resource](https://github.com/canonical/temporal-worker-k8s-operator/tree/main/resource_sample_py)
which contains two workflows and two activities. This will require the
availability of a local registry. In our case, we can enable the
[microk8s registry](https://microk8s.io/docs/registry-built-in). You can run the
following commands to clone the repository, build the necessary rock image and
deploy the worker charm with it:

```bash
juju add-model worker-model

git clone https://github.com/canonical/temporal-worker-k8s-operator.git
make -C resource_sample_py build_rock

juju deploy temporal-worker-k8s --resource temporal-worker-image=localhost:32000/temporal-worker-rock
```

Wait until the application is ready - when it is ready, `juju status` will show:

```
Model            Controller           Cloud/Region        Version  SLA          Timestamp
worker-model     temporal-controller  microk8s/localhost  3.1.5    unsupported  13:21:49+03:00

App                  Version  Status   Scale  Charm                Channel  Rev  Address         Exposed  Message
temporal-worker-k8s           waiting      1  temporal-worker-k8s  stable     5  10.152.183.187  no       installing agent

Unit                    Workload  Agent  Address      Ports  Message
temporal-worker-k8s/0*  blocked   idle   10.1.232.75         Invalid config: host missing
```

## Configure Worker

We will then configure our worker to the Temporal server deployed in the
previous steps. We will also configure our charm to add a couple of environment
variables to be read by the workflows. Create a file `config.yaml` with the
following content:

```yaml
temporal-worker-k8s:
  host: "10.1.232.64:7233" # Temporal Server unit IP address
  queue: "test-queue"
  namespace: "default"
  environment: |
    env:
      - name: message
        value: hello
      - name: juju-key1
        value: world
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

Wait until the application is ready - when it is ready, `juju status` will show:

```
Model            Controller           Cloud/Region        Version  SLA          Timestamp
worker-model     temporal-controller  microk8s/localhost  3.1.5    unsupported  13:45:16+03:00

App                  Version  Status  Scale  Charm                Channel  Rev  Address         Exposed  Message
temporal-worker-k8s           active      1  temporal-worker-k8s  stable     5  10.152.183.187  no       worker listening to namespace 'default' on queue 'test-queue'

Unit                    Workload  Agent  Address      Ports  Message
temporal-worker-k8s/0*  active    idle   10.1.232.78         worker listening to namespace 'default' on queue 'test-queue'
```

To further verify that the worker is functioning correctly, observe the output
of the following command to ensure the absence of errors:

```bash
kubectl -n worker-model logs temporal-worker-k8s-0 -c temporal-worker -f
```

At this point, we have a Temporal worker connected to our Temporal server on the
`default` namespace listening for tasks on the `test-queue` task queue.

> **See next:
> [Run Your First Workflow](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-run-your-first-workflow/11785)**
