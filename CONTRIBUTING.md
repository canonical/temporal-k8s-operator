# temporal-k8s

## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

Run `tox` for *linting* and *testing* the code, and `tox -e fmt` for formatting it.

## Intended use case

This charm is used to deploy Temporal Server in a k8s cluster.
For a local deployment, follow the following steps:

    # Install Microk8s from snap:
    sudo snap install microk8s --classic --channel=1.24

    # Add the 'ubuntu' user to the Microk8s group:
    sudo usermod -a -G microk8s ubuntu

    # Give the 'ubuntu' user permissions to read the ~/.kube directory:
    sudo chown -f -R ubuntu ~/.kube

    # Create the 'microk8s' group:
    newgrp microk8s

    # Enable the necessary Microk8s addons:
    microk8s enable hostpath-storage dns

    # Install the Juju CLI client, juju:
    sudo snap install juju --classic

    # Install a "juju" controller into your "microk8s" cloud:
    juju bootstrap microk8s temporal-controller

    # Create a 'model' on this controller:
    juju add-model temporal

    # Install charmcraft from snap:
    sudo snap install charmcraft --classic

    # Pack the charm:
    charmcraft pack

    # Deploy the charm:
    juju deploy ./temporal-k8s-22.04-amd64.charm
