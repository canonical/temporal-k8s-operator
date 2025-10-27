# Horizontal Scaling

The Temporal Server services can run independently on one or more machines (virtual or physical), which is the recommended setup for production environments. See [Temporal Server](https://docs.temporal.io/temporal-service/temporal-server#temporal-server) for more details.

The Charmed Temporal K8s operator is designed such that each service can be
deployed as a separate scalable application which can then be connected together by
integrating with the same backend database.

[note]

Only the `frontend` service is required to be integrated to the `nginx-ingress-integrator`and `openfga-k8s` if required.
The `frontend` service will automatically handle the internal gateway that the `worker` service uses to bypass authorisation rules imposed for external connections

[/note]

## Deploying as scalable services

To deploy the services separately in a scalable way, follow the next steps:

1. Deploy each service as a separate application:

```bash
juju deploy temporal-k8s --config services="frontend"
juju deploy temporal-k8s --config services="matching" temporal-k8s-matching
juju deploy temporal-k8s --config services="history" temporal-k8s-history
juju deploy temporal-k8s --config services="worker" temporal-k8s-worker

2. Deploy the Temporal admin charm and relate to the `frontend` service

juju deploy temporal-admin-k8s
juju relate temporal-k8s:admin temporal-admin-k8s:admin
```

3. Integrate with the backend database. See section below for details.
4. Scale up the applications as you need:

```
juju scale-application temporal-* <num_of_replicas_required_replicas>
```

## Integrate with backend database

The integration with the backend database has to be managed depending on the amount of units Charmed Temporal is scaled to. There are two options for this:

* Integrate directly with `postgresql-k8s` through the `database` interface:

```
juju relate temporal-k8s:db postgresql-k8s:database
juju relate temporal-k8s:visibility postgresql-k8s:database


juju relate temporal-k8s-history:db postgresql-k8s:database
juju relate temporal-k8s-history:visibility postgresql-k8s:database

juju relate temporal-k8s-matching:db postgresql-k8s:database
juju relate temporal-k8s-matching:visibility postgresql-k8s:database

juju relate temporal-k8s-worker:db postgresql-k8s:database
juju relate temporal-k8s-worker:visibility postgresql-k8s:database
```

* Integrate with a connection pooler, such as `pgbouncer-k8s`

```
juju relate temporal-k8s:db pgbouncer-k8s:database
juju relate temporal-k8s:visibility pgbouncer-k8s:database


juju relate temporal-k8s-history:db pgbouncer-k8s:database
juju relate temporal-k8s-history:visibility pgbouncer-k8s:database

juju relate temporal-k8s-matching:db pgbouncer-k8s:database
juju relate temporal-k8s-matching:visibility pgbouncer-k8s:database

juju relate temporal-k8s-worker:db pgbouncer-k8s:database
juju relate temporal-k8s-worker:visibility pgbouncer-k8s:database
```

### Configure database connections

Charmed Temporal offers a set of configuration options for setting up the maximum database connections. These numbers are to be set depending on the use case, the number of units each Temporal service has, the number of applications integrated with the backend database, the number of connections those create, and the allowed number of connections that the backend database allows. At the moment, there is no easy mechanism or formula to define these numbers, but these should be determined through load testing and monitoring.

Please make sure you set up the following configuration options based on your testing:

* [persistence-max-conn-time](https://charmhub.io/temporal-k8s/configurations#persistence-max-conn-time)
* [persistence-max-conns](https://charmhub.io/temporal-k8s/configurations#persistence-max-conns)
* [persistence-max-idle-conns](https://charmhub.io/temporal-k8s/configurations#persistence-max-idle-conns)
* [visibility-max-conn-time](https://charmhub.io/temporal-k8s/configurations#visibility-max-conn-time)
* [visibility-max-conns](https://charmhub.io/temporal-k8s/configurations#visibility-max-conns)
* [visibility-max-idle-conns](https://charmhub.io/temporal-k8s/configurations#visibility-max-idle-conns)

[note]

The maximum amount of connections that `postgresql-k8s` allows is `100` (cannot be changed at the moment), and because of canonical/pgbouncer-k8s-operator#634 and canonical/postgresql-k8s-operator#1143, the connection settings may be affected.

[/note]

## Removing Replicas

To scale down the number of replicas, you can again use the juju
scale-application functionality:

```
juju scale-application temporal-* <num_of_replicas_required_replicas>
```
