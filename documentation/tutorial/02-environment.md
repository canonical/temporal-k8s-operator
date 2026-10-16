# Environment Setup

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

## Minimum Requirements

Before we start, make sure your machine meets the following requirements:

- A machine running Ubuntu 24.04 (Noble), Ubuntu 26.04 (Resolute), or later. Machines running other
  operating systems may opt for the use of
  [Multipass](https://multipass.run/docs). A simple set of instructions to set
  up Multipass can be found
  [here](https://juju.is/docs/sdk/set-up-your-development-environment#heading--set-up-an-ubuntu-vm-with-multipass).
- 8GB of RAM.
- 2 CPU threads.
- At least 20GB of available storage.
- Access to the internet for downloading the required snaps and charms.

## Install Canonical Kubernetes

On your machine, install and configure Canonical Kubernetes (K8s):

```bash
sudo snap install k8s --classic

sudo k8s bootstrap
```

Wait until the `k8s` cluster is in `Ready` state. You can check it as follows:

```
sudo k8s status --wait-ready
```
Install kubectl and write `kubeconfig` for the current user:

```
sudo snap install kubectl --classic
mkdir -p ~/.kube
sudo k8s config > ~/.kube/config
```

## Set up Juju

Install Juju as follows:

```
sudo snap install juju --channel=3.6/stable
```

Register your Canonical K8s cluster with Juju as a cloud named `ck8s`:

```
juju add-k8s ck8s
```

Confirm the new cloud entry is present:

```
juju clouds
# >>> Cloud      Regions  Default    Type  Credentials  Source    Description
# >>> ck8s       0                   k8s   1            local     A Kubernetes Cluster
# >>> k8s        0                   k8s   0            built-in  A local Kubernetes context
# >>> localhost  1        localhost  lxd   0            built-in  LXD Container Hypervisor
```

Install a Juju controller into your `ck8s` cloud. You can name it `temporal-controller`:

```
juju bootstrap ck8s temporal-controller
```

## Create the Temporal Model

Once you have Juju bootstrapped to your Kubernetes cluster, create a `model`, for Temporal. You can name it `temporal-model`:

```bash
juju add-model temporal-model
```

You can optionally configure the default base for the model:

```bash
juju model-config default-base=ubuntu@26.04
```

[note]
**Base selection:** Default bases can be set at the model level via `juju model-config default-base=<base>` (e.g. `default-base=ubuntu@24.04` for 1.23, or `default-base=ubuntu@26.04` for 1.31), or specified when deploying or downloading by using the `--base` flag (e.g. `juju deploy ... --base ubuntu@26.04` or `juju download --channel 1.23/stable --base ubuntu@24.04`).

If neither of these is set, Charmhub will default to the latest LTS version that is available for the charm on the channel being downloaded.
[/note]

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
