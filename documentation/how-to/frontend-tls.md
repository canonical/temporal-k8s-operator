# Frontend TLS

This guide provides instructions for configuring Frontend TLS in Charmed Temporal.

In the context of Temporal, "frontend TLS" refers to the use of TLS to secure network communication between Temporal clients (SDKs, CLI, or Web UI) and the Temporal Frontend Service. The Temporal Frontend Service acts as the API gateway for client requests to the Temporal Server.

For more information, please go to the [TLS configuration reference](https://docs.temporal.io/references/configuration#tls).

[note]

Frontend TLS is different from TLS termination at Ingress - in the former case, TLS termination is handled by the Temporal Frontend. If your setup requires TLS termination at Ingress, please refer to the Configure Ingress with Nginx Ingress Integrator guide.

Also note that while it is possible to have end-to-end encryption with Temporal handling the TLS termination and the Ingress bypassing encrypted requests, this setup is not supported yet.
[/note]

## Pre requisites

* A Charmed Temporal deployment.
* The `temporal-k8s` charm to be configured with TLS must include `frontend` in its `service` configuration. This can be checked with:

```
juju config temporal-k8s services

frontend
```

## Enable Frontend TLS

1. Integrate with a TLS certificate provider.

```
juju integrate temporal-k8s <tls-certificate-provider-charm>
```

2. If the certificate needs a specific Common Name (CN) and SANS (Subject Alternative NAmes) DNS, they can be configured as follows:

```
juju config temporal-k8s frontend-cert-common-name=<common_name>
juju config temporal-k8s frontend-cert-sans-dns=<sans_dns_comma_separated_list>
```

3. All requests from Temporal clients to the frontend will now have to trust the Certificate Authority (CA) that signed the Temporal Frontend certificate. The CA certificate can be retrieved from the TLS certificate provider charms by running:

```
juju run <tls-cert-provider-charm> get-ca-certificate
```
