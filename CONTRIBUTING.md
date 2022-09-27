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

### Deploy

This charm is used to deploy Temporal server in a k8s cluster.
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

    # Enable DEBUG logging:
    juju model-config logging-config="<root>=INFO;unit=DEBUG"

    # Install charmcraft from snap:
    sudo snap install charmcraft --classic

    # Pack the charm:
    charmcraft pack [--destructive-mode]

    # Deploy the charm:
    juju deploy ./temporal-k8s_ubuntu-20.04-amd64.charm --resource temporal-server-image=temporalio/server:1.17.4

    # Relate it to postgres:
    juju deploy postgresql-k8s --channel edge --trust
    juju relate temporal-k8s postgresql-k8s:db

    # TODO(frankban): relate to temporal-admin-k8s.

    # Check progress:
    juju status --relations
    juju debug-log

    # Clean-up before retrying:
    juju remove-application temporal-k8s --force
    juju remove-application postgresql-k8s --force

## Relations

### db:pgsql

The charm supports Temporal server backed by a PostgreSQL database. The
application therefore needs to be related to *postgresql-k8s*. The usual events
are handled by the charm (*database_relation_joined*, *master_changed*).

One caveat is that the server cannot be started until the schema is initialized
by the *temporal-admin-k8s* application, which provides the Temporal admin tools
(see below).

### admin:temporal

In order to be able to initialize the related PostgreSQL database schema, admin
tools are required. These are provided through a relation to the
*temporal-admin-k8s* application. The relation works like this:
- the two applications are related;
- once *temporal-k8s* receives db connection info from *postgresql-k8s*, this
  info is sent to *temporal-admin-k8s*;
- the admin app uses the provided db connection info to initialize the database;
- when done, the admin app sends a message to *temporal-k8s* reporting that the
  schema is ready, and that therefore the server can be started.

On the **API**, the flow described above can be handled in a very simple way while
initializing the charm:
```Python
def __init__(self, *args):
    super().__init__(*args)
    self._state.set_default(schema_ready=False)
    self.admin = relations.Admin(self, lambda: self._state.db_conn)
    self.framework.observe(self.admin.on.schema_changed, self._on_schema_changed)
```
The `self._on_schema_changed` method can then check whether `event.schema_ready`
is *True*.
