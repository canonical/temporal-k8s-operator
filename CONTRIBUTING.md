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

This repo uses CI/CD workflows as outlined by [operator-workflows](https://github.com/canonical/operator-workflows). The four workflows are as follows:
- `test.yaml`: This is a series of tests including linting, unit tests and library checks which run on every pull request.
- `integration_test.yaml`: This runs the suite of integration tests included with the charm and runs on every pull request.
- `test_and_publish_charm.yaml`: This runs either by manual dispatch or on every push to the main branch or a special track/** branch. Once a PR is merged with one of these branches, this workflow runs to ensure the tests have passed before building the charm and publishing the new version to the edge channel on Charmhub.
- `promote_charm.yaml`: This is a manually triggered workflow which publishes the charm currently on the edge channel to the stable channel on Charmhub.

These tests require extensive linting and formatting. Before creating a PR, please run `tox` to ensure proper formatting and linting is performed.

### Deploy

This charm is used to deploy Temporal server in a k8s cluster.
For a local deployment, follow the following steps:

    # Install Microk8s from snap:
    sudo snap install microk8s --classic --channel=1.24

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
    juju deploy ./temporal-k8s_ubuntu-22.04-amd64.charm --resource temporal-server-image=temporalio/server:1.17.4

    # Relate operator to postgres:
    juju deploy postgresql-k8s --channel edge --trust
    juju relate temporal-k8s:db postgresql-k8s:db
    juju relate temporal-k8s:visibility postgresql-k8s:db

    # Relate operator to temporal-admin-k8s (Navigate to temporal-admin-k8s directory):
    juju deploy temporal-admin-k8s --channel edge
    juju relate temporal-k8s:admin temporal-admin-k8s:admin

    # Create default namespace:
    juju run temporal-admin-k8s/0 tctl args="--ns default namespace register -rd 3"

    # Deploy ingress controller:
    microk8s enable ingress

    # Relate operator to nginx-ingress-integrator:
    juju deploy nginx-ingress-integrator
    juju relate temporal-k8s:ingress nginx-ingress-integrator:ingress

    # Check progress:
    juju status --relations
    juju debug-log

    # Clean-up before retrying:
    juju remove-application temporal-k8s --force
    juju remove-application postgresql-k8s --force

## Relations

### db:pgsql and visibility:pgsql

The charm supports Temporal server backed by PostgreSQL databases. The
application needs to be related to *postgresql-k8s* twice: once using the *db*
relation and once using the *visibility* one). The usual events are handled by
the charm (*database_relation_joined*, *master_changed*).

One caveat is that the server cannot be started until the schemas for both
databases are initialized by the *temporal-admin-k8s* application, which
provides the Temporal admin tools (see below).

### admin:temporal

In order to be able to initialize the related PostgreSQL database schema, admin
tools are required. These are provided through a relation to the
*temporal-admin-k8s* application. The relation works like this:
- the two applications are related;
- once *temporal-k8s* receives db connection info from *postgresql-k8s*, this
  info is sent to *temporal-admin-k8s*;
- the admin app uses the provided db connection info (for both *db* and
  *visibility* connections) to initialize the databases;
- when done, the admin app sends a message to *temporal-k8s* reporting that the
  schema is ready, and that therefore the server can be started.

On the **API**, the flow described above can be handled in a very simple way while
initializing the charm:
```Python
def __init__(self, *args):
    super().__init__(*args)
    self._state.set_default(schema_ready=False)
    self.admin = relations.Admin(self)
    self.framework.observe(self.admin.on.schema_changed, self._on_schema_changed)
```
The `self._on_schema_changed` method can then check whether `event.schema_ready`
is *True*.

### ingress

The charm exposes itself using the Nginx Ingress Integrator charm. Once deployed, find the IP of the ingress controller by running ``` microk8s kubectl get pods -n ingress -o wide ``` and add the IP-to-hostname mapping in your /etc/hosts file. By default, the hostname will be set to ```temporal-k8s```. You can then connect a Temporal client through this hostname on port 80 i.e. ```Client.connect("temporal-k8s:80")```.

You will need to modify the ingress resource to accept gRPC traffic. This can be done as follows:

```bash
# Edit the ingress resource
kubectl edit ingress -n <MODEL_NAME>

## Add the following line under annotations
nginx.ingress.kubernetes.io/backend-protocol: GRPC

```

One thing to note is that Temporal Server uses gRPC protocol and requires the server to use HTTP/2. If you try connecting a client without TLS to the operator through the ingress IP address and receive a connection error, you need to modify the nginx ingress controller to listen on port 80 and use HTTP/2. This can be done as follows:

```bash
# SSH into the nginx ingress controller
kubectl exec -it -n ingress <INGRESS_CONTROLLER_NAME> -- bash

# Modify nginx config file
nano nginx.conf

# Navigate to "## start server" and ensure that the lines relating to port 80 have http2 at the end
listen 80 default_server reuseport backlog=4096 http2;
listen [::]:80 default_server reuseport backlog=4096 http2;

# Reload the controller and exit
nginx -s reload
exit
```

### ui:temporal

In order to access the Temporal Web UI, the Temporal UI charm must be deployed. Once done, the hostname will be set to the application name `temporal-ui-k8s` by default and can be changed through the `external-hostname` config. If the ingress relation has already been created through the previous step, then the web UI can be accessed by visiting `temporal-ui-k8s:443`. As this setup is currently deployed in a development environment and TLS is not yet configured, the Temporal server and UI must be accessed through two different ports due to the [limitation](https://github.com/kubernetes/ingress-nginx/issues/4095) of port 80 not being able to multiplex between HTTP and gRPC traffic. This will be resolved in the near future when TLS certificates are implemented in this charm.
