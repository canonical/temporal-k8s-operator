# Environment Setup

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

## Minimum Requirements

Before we start, make sure your machine meets the following requirements:

- A machine running Ubuntu 22.04 (Jammy) or later. Machines running other
  operating systems may opt for the use of
  [Multipass](https://multipass.run/docs). A simple set of instructions to set
  up Multipass can be found
  [here](https://juju.is/docs/sdk/set-up-your-development-environment#heading--set-up-an-ubuntu-vm-with-multipass).
- 8GB of RAM.
- 2 CPU threads.
- At least 20GB of available storage.
- Access to the internet for downloading the required snaps and charms.

## Install Kubernetes and bootstrap Juju

Charmed Temporal is deployed to Kubernetes using Juju. Before deployment, you need:

1.  **A running Kubernetes cluster**:  Canonical K8s is our preference. See [Canonical Kubernetes documentation](https://documentation.ubuntu.com/canonical-kubernetes/release-1.32/snap/howto/install/snap/) for installation instructions.

2. **Juju bootstrapped to your cluster**. See [Get started with Juju](https://documentation.ubuntu.com/juju/3.6/tutorial/) for more details.

[note]

Our recommendation is bootstrapping Juju on a Canonical K8s cluster. See [Canonical K8s cloud and Juju](https://documentation.ubuntu.com/juju/3.6/reference/cloud/list-of-supported-clouds/the-canonical-ks-cloud-and-juju/) and the [bootstrap command reference](https://documentation.ubuntu.com/juju/3.6/reference/juju-cli/list-of-juju-cli-commands/bootstrap/) for more details.

[/note]

## Create the Temporal Model

Once you have Juju bootstrapped to your Kubernetes cluster, create a `model`, for Temporal. You can name it `temporal-model`:

```bash
juju add-model temporal-model
```

You can check its status as follows:

```bash
juju status
# >>> Model           Controller           Cloud/Region  Version  SLA          Timestamp
# >>> temporal-model  temporal-controller  ck8s          3.6.8    unsupported  06:26:34-06:00
# >>>
# >>> Model "admin/temporal-model" is empty.
```

> **See next:
> [Deploying Temporal Server](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-server/11779)**
