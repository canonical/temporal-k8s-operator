# Security

Temporalio proivdes an array of features that enable an operator to secure their
deployment. This guide describes the implementation of security features such as
client-side encryption, authentication and authorization.

## Ingress TLS

Charmed Temporal can terminate the Transport Layer Security (TLS) at the ingress
by leveraging the
[Nginx Ingress Integrator Charm](https://charmhub.io/nginx-ingress-integrator)
as outlined in
[this page](https://charmhub.io/temporal-k8s/docs/t-deploy-ingress) of the
tutorial.

## Authentication

Charmed Temporal supports Google IAM-based authentication through the web UI and
through the [temporal-lib-py](https://github.com/canonical/temporal-lib-py) and
[temporal-lib-go](https://github.com/canonical/temporal-lib-go) client
libraries. More details can be found in the
[Authentication](https://charmhub.io/temporal-k8s/docs/h-authentication) page.

## Authorization

Charmed Temporal supports authorization using Google IAM and OpenFGA. Through a
set of juju actions exposed by the charmed operator, the necessary authorization
rules can be created in OpenFGA. More details can be found in the
[Authorization](https://charmhub.io/temporal-k8s/docs/h-authorization) page.

## Client-side Encryption

Through the use of the
[temporal-lib-py](https://github.com/canonical/temporal-lib-py) and
[temporal-lib-go](https://github.com/canonical/temporal-lib-go) client
libraries, users of Charmed Temporal are able to encrypt their workflow inputs
and outputs, ensuring that any sensitive information remains obfuscated both in
transit and at rest. It is worth noting that when encrypting workflow payloads,
the same key must also be set on the Charmed Temporal Worker application using
the `encryption_key` configuration option.
