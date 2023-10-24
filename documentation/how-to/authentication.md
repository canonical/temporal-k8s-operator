# Authentication

Clients of the Charmed Temporal k8s Operator can be authenticated in two
different ways as described below. Authentication entails acquiring a Google
OAuth access token, which will be attached to each request made to the Temporal
Server on the `Authorization` header. The [Authorization](./authorization.md)
page will discuss further how this access token is further utilized on the
Temporal Server.

## 1. Temporal Web UI Authentication

Enabling authentication through the web UI requires that you have an active
[Charmed Temporal UI K8s Operator](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777)
deployed along with Nginx ingress integration as described in the tutorial.

Google OAuth can be enabled on the Charmed Temporal UI K8s Operator through the
use of simple config parameters. First, you must set up a
[Google Cloud project](https://developers.google.com/workspace/guides/create-project).
Through this project, you will need to setup OAuth 2.0 as described
[here](https://support.google.com/cloud/answer/6158849?hl=en#zippy=%2Cuser-consent).
This includes creating an OAuth client ID and configuring the OAuth consent
screen. At a minimum, the scope that needs to be enabled is
`./auth/userinfo.email`.

When creating the OAuth client ID, the application type selected must be
`Web application`. For `Authorized JavaScript Origins`, you must include your
web UI's external hostname (by default, this value is
`https://temporal-ui-k8s`). For `Authorized redirect URIs`, you must include the
URI `https://<external_hostname>/auth/sso/callback`, where `<external_hostname>`
is the same value used for `Authorized JavaScript Origins`.

Once that is done, extract the client ID and secret of the OAuth 2.0 client you
created. With the Charmed Temporal UI K8s Operator deployed and active, you can
set the following configuration parameters:

```bash
juju config temporal-ui-k8s auth-enabled=true auth-client-id="<google_client_id>" auth-secret-id="<google_secret_id>"
```

And you're done! When visiting the Temporal Web UI through the external hostname
set previously, you should be presented with a 'Sign In' button which will
redirect you to a Google OAuth login page before allowing you to access the web
UI.

## 2. Google Cloud Service Account Authentication

Enabling authentication through service accounts requires that you have an
active
[Charmed Temporal Worker K8s Operator](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777)
deployed as described in the tutorial.

Service accounts can be used to programmatically trigger and execute workflows
on the Temporal Server. They can be used by both Temporal clients or
[worker operator instances](https://charmhub.io/temporal-worker-k8s). To enable
the use of Google Cloud service accounts, you will also need an active Google
Cloud project. The steps for creating a service account are described
[here](https://support.google.com/cloud/answer/6158849?hl=en#zippy=%2Cservice-accounts).
Once done, you can download a JSON file which contains your service account's
credentials. With the Charmed Temporal Worker K8s Operator deployed and active,
you can create a `config.yaml` file with the following, replacing `<>` with the
corresponding values from your service account's JSON file:

```yaml
temporal-worker-k8s:
  auth-provider: "google"
  oidc-auth-type: "service_account"
  oidc-auth-uri: "<auth_uri>"
  oidc-client-cert-url: "<client_x509_cert_url>"
  oidc-client-email: "<client_email>"
  oidc-client-id: "<client_id>"
  oidc-private-key: "<private_key>"
  oidc-private-key-id: "<private_key_id>"
  oidc-project-id: "<project_id>"
  oidc-token-uri: "<token_uri>"
```

You can then set the application's configuration as follows:

```bash
juju config temporal-worker-k8s --file=config.yaml
```

And you're done! Requests made by the Temporal worker will now contain an
`Authorization` header with a valid Google OAuth access token, which will be
further processed on the Temporal Server for authorization. For Temporal
clients, you can also use the
[temporal-lib-go](https://github.com/canonical/temporal-lib-go) and
[temporal-lib-py](https://github.com/canonical/temporal-lib-py) client libraries
and injecting your service account credentials.

The [Authorization](./authorization.md) page discusses further how to authorize
users and restrict their access to namespaces once they are authenticated.
