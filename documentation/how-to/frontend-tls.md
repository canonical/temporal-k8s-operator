# Configure frontend TLS

This guide provides instructions for configuring frontend TLS in Charmed Temporal.

In the context of Temporal, frontend TLS refers to the use of TLS to secure network communication between Temporal clients (SDKs, CLI, or Web UI) and the Temporal Frontend Service. The Temporal Frontend Service acts as the API gateway for client requests to the Temporal Server.

See [TLS configuration reference](https://docs.temporal.io/references/configuration#tls) for more details.

[note]

Frontend TLS is different from TLS termination at ingress. In the former case, TLS termination is handled by the Temporal frontend. If your setup requires TLS termination at ingress, see [Configure Ingress with Nginx Ingress Integrator](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-nginx-ingress-integrator/11783) guide.

While it is technically possible to have end-to-end encryption with Temporal handling TLS termination and the ingress bypassing encrypted requests, this setup is not currently supported.
[/note]

## Requirements

* A Charmed Temporal deployment.
* The `temporal-k8s` charm to be configured with TLS must include `frontend` in its `service` configuration. You can check it as follows:

```
juju config temporal-k8s services

frontend
```

## Enable frontend TLS

1. Integrate with a TLS certificate provider:

```
juju integrate temporal-k8s <tls-certificate-provider-charm>
```

2. If the certificate needs a specific Common Name (CN) and SANS (Subject Alternative NAmes) DNS, you can configure them as follows:

```
juju config temporal-k8s frontend-cert-common-name=<common_name>
juju config temporal-k8s frontend-cert-sans-dns=<sans_dns_comma_separated_list>
```

3. All requests from Temporal clients to the frontend must now trust the Certificate Authority (CA) that signed the Temporal frontend certificate. You can retrieve the CA certificate from the TLS certificate provider charms by running:

```
juju run <tls-cert-provider-charm> get-ca-certificate
```
