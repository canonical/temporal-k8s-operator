# temporal-k8s

## Developing

You can use the environments created by `tox` for development:

```shell
tox --notest -e unit
source .tox/unit/bin/activate
```

### Testing

```shell
tox -e fmt           # update your code according to linting rules
tox -e lint          # code style
tox -e unit          # unit tests
tox -e integration   # integration tests
tox                  # runs 'lint' and 'unit' environments
```

### Committing

This repo uses CI/CD workflows as outlined by
[operator-workflows](https://github.com/canonical/operator-workflows). The four
workflows are as follows:

- `test.yaml`: This is a series of tests including linting, unit tests and
  library checks which run on every pull request.
- `integration_test.yaml`: This runs the suite of integration tests included
  with the charm and runs on every pull request.
- `test_and_publish_charm.yaml`: This runs either by manual dispatch or on every
  push to the main branch or a special track/\*\* branch. Once a PR is merged
  with one of these branches, this workflow runs to ensure the tests have passed
  before building the charm and publishing the new version to the edge channel
  on Charmhub.
- `promote_charm.yaml`: This is a manually triggered workflow which publishes
  the charm currently on the edge channel to the stable channel on Charmhub.

These tests validate extensive linting and formatting rules. Before creating a
PR, please run `tox` to ensure proper formatting and linting is performed.

### Deploy

This charm is used to deploy Temporal server in a k8s cluster. For a local
deployment, follow the following steps:

    # Install Microk8s from snap:
    sudo snap install microk8s --classic --channel=1.25

    # Install charmcraft from snap:
    sudo snap install charmcraft --classic

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

    # Enable DEBUG logging:
    juju model-config logging-config="<root>=INFO;unit=DEBUG"

    # Pack the charm:
    charmcraft pack [--destructive-mode]

    # Deploy the charm:
    juju deploy ./temporal-k8s_ubuntu-22.04-amd64.charm --resource temporal-server-image=ghcr.io/canonical/temporal-server:latest

    # Deploy admin charm (Only if modifying admin charm, otherwise deploy as shown below):
    juju deploy ./temporal-admin-k8s_ubuntu-22.04-amd64.charm --resource temporal-admin-image=temporalio/admin-tools:1.23.1

    # Deploy ui charm (Only if modifying UI charm, otherwise deploy as shown below):
    juju deploy ./temporal-ui-k8s_ubuntu-22.04-amd64.charm --resource temporal-ui-image=temporalio/ui:2.27.1

    # Refresh charm
    juju refresh --path="./temporal-k8s_ubuntu-22.04-amd64.charm" temporal-k8s --force-units --resource temporal-server-image=ghcr.io/canonical/temporal-server:latest

    # Refresh the admin charm
    juju refresh --path="./temporal-admin-k8s_ubuntu-22.04-amd64.charm" temporal-admin-k8s --force-units --resource temporal-admin-image=temporalio/admin-tools:1.23.1

    # Refresh the ui charm
    juju refresh --path="./temporal-ui-k8s_ubuntu-22.04-amd64.charm" temporal-ui-k8s --force-units --resource temporal-ui-image=temporalio/ui:2.27.1

    # Relate operator to postgres:
    juju deploy postgresql-k8s --channel 14/stable --trust
    juju relate temporal-k8s:db postgresql-k8s:database
    juju relate temporal-k8s:visibility postgresql-k8s:database

    # Relate operator to temporal-admin-k8s:
    juju deploy temporal-admin-k8s --channel edge
    juju relate temporal-k8s:admin temporal-admin-k8s:admin

    # Create default namespace:
    juju run temporal-admin-k8s/0 tctl args="--ns default namespace register -rd 3"

    # Generate private key
    openssl genrsa -out server.key 2048

    # Generate a certificate signing request
    openssl req -new -key server.key -out server.csr -subj "/CN=temporal-k8s"

    # Create self-signed certificate
    openssl x509 -req -days 365 -in server.csr -signkey server.key -out server.crt -extfile <(printf "subjectAltName=DNS:temporal-k8s")

    # Create a k8s secret
    kubectl create secret tls temporal-tls --cert=server.crt --key=server.key

    # Deploy ingress controller:
    microk8s enable ingress:default-ssl-certificate=temporal/temporal-tls

    # Relate operator to nginx-ingress-integrator:
    juju deploy nginx-ingress-integrator
    juju relate temporal-k8s nginx-ingress-integrator

    # Relate operator to temporal-ui-k8s:
    juju deploy temporal-ui-k8s --channel edge
    juju relate temporal-k8s:ui temporal-ui-k8s:ui

    # Check progress:
    juju status --relations
    juju debug-log

    # Clean-up before retrying:
    juju remove-application temporal-k8s --force
    juju remove-application postgresql-k8s --force

## Relations

### db:pgsql and visibility:pgsql

The charm supports Temporal server backed by PostgreSQL databases. The
application needs to be related to _postgresql-k8s_ twice: once using the _db_
relation and once using the _visibility_ one). The usual events are handled by
the charm (_database_created_, _endpoints_changed_).

One caveat is that the server cannot be started until the schemas for both
databases are initialized by the _temporal-admin-k8s_ application, which
provides the Temporal admin tools (see below).

### admin:temporal

In order to be able to initialize the related PostgreSQL database schema, admin
tools are required. These are provided through a relation to the
_temporal-admin-k8s_ application. The relation works like this:

- the two applications are related;
- once _temporal-k8s_ receives db connection info from _postgresql-k8s_, this
  info is sent to _temporal-admin-k8s_;
- the admin app uses the provided db connection info (for both _db_ and
  _visibility_ connections) to initialize the databases;
- when done, the admin app sends a message to _temporal-k8s_ reporting that the
  schema is ready, and that therefore the server can be started.

On the **API**, the flow described above can be handled in a very simple way
while initializing the charm:

```Python
def __init__(self, *args):
    super().__init__(*args)
    self._state.set_default(schema_ready=False)
    self.admin = relations.Admin(self)
    self.framework.observe(self.admin.on.schema_changed, self._on_schema_changed)
```

The `self._on_schema_changed` method can then check whether `event.schema_ready`
is _True_.

### ingress

The charm exposes itself using the Nginx Ingress Integrator charm. Once
deployed, find the IP of the ingress controller by running
`microk8s kubectl get pods -n ingress -o wide` and add the IP-to-hostname
mapping in your /etc/hosts file. By default, the hostname will be set to
`temporal-k8s`. You can then connect a Temporal client through this hostname
i.e. `Client.connect("temporal-k8s")`.

### ui:temporal

In order to access the Temporal Web UI, the Temporal UI charm must be deployed.
Once done, the hostname will be set to the application name `temporal-ui-k8s` by
default and can be changed through the `external-hostname` config. If the
ingress relation has already been created through the previous step, then the
web UI can be accessed by visiting `https://temporal-ui-k8s`.

### openfga

To enable authorization, the OpenFGA charm must be deployed. Instructions on how
to enable authorization can be found
[here](./documentation/how-to/authorization.md).
