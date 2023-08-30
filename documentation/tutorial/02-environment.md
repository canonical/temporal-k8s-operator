# Environment Setup

This is part of the [Charmed Temporal Tutorial](./00-introduction.md). Please
refer to this page for more information and the overview of the content.

## Minimum Requirements

Before we start, make sure your machine meets the following requirements:

- A laptop or desktop running Ubuntu 22.04 (Jammy) or later. Machines running
  other operating systems may opt for the use of
  [Multipass](https://multipass.run/docs).
- Access to the internet for downloading the required snaps and charms.

## Install MicroK8s

On your machine, install and configure MicroK8s:

```bash
# Install Microk8s from snap:
sudo snap install microk8s --channel 1.25-strict/stable

# Add your user to the MicroK8s group:
sudo usermod -a -G snap_microk8s $USER

# Give your user permissions to read the ~/.kube directory:
sudo chown -f -R $USER ~/.kube

# Create the 'microk8s' group:
newgrp snap_microk8s

# Enable the necessary MicroK8s addons:
sudo microk8s enable hostpath-storage dns

# Set up a short alias for the Kubernetes CLI:
sudo snap alias microk8s.kubectl kubectl
```

[MicroK8s](https://microk8s.io/docs) is a minimal production Kubernetes, so now
you have a small Kubernetes cloud (by default called microk8s) on your machine.

## Set up Juju

On your machine, install Juju, connect it to your MicroK8s cloud, and prepare a
workspace (‘model’):

```bash
# Install 'juju':
sudo snap install juju --channel 3.1/stable
# >>> juju (3.1/stable) 3.1.5 from Canonical✓ installed

# Since the juju package is strictly confined, you also need to manually create a path:
mkdir -p ~/.local/share

# Register your "microk8s" cloud with juju:
# Not necessary --juju recognises a MicroK8s cloud automatically, as you can see by running 'juju clouds'.
juju clouds
# >>> Cloud      Regions  Default    Type  Credentials  Source    Description
# >>> localhost  1        localhost  lxd   0            built-in  LXD Container Hypervisor
# >>> microk8s   1        localhost  k8s   1            built-in  A Kubernetes Cluster
# (If for any reason this doesn't happen, you can register it manually using 'juju add-k8s microk8s'.)

# Install a "juju" controller into your "microk8s" cloud.
# We'll name ours "temporal-controller".
juju bootstrap microk8s temporal-controller

# Create a workspace, or 'model', on this controller.
# We'll call ours "temporal-model".
# Juju will create a Kubernetes namespace "temporal-model"
juju add-model temporal-model

# Check status:
juju status
# >>> Model         Controller           Cloud/Region        Version  SLA          Timestamp
# >>> temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  16:05:03+01:00

# >>> Model "admin/temporal-model" is empty.
```

> **See next: [Deploying Temporal Server](./03-deploying-server)**
