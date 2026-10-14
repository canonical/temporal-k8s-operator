# Cleanup and Extra Info

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

In this tutorial we’ve successfully deployed the Temporal Server, Temporal
Admin, Temporal Web UI, and Temporal Worker, relating them together and running
a basic workflow. You may now keep your Charmed Temporal K8s deployment running
and write more complex workflows, or clean up your environment as shown below.

## Remove and Cleanup Environment

If you’re done with testing and would like to free up resources on your machine,
just run the following command:

```bash
juju destroy-controller -y --destroy-all-models --destroy-storage temporal-controller
```

_Warning: when you remove the models as shown, you will lose all the data in
PostgreSQL and any other applications inside the model!_

[note]
If you followed the [cross-model deployment](https://charmhub.io/temporal-k8s/docs/t-deploy-worker) path and created a separate `temporal-workers-model`, the `--destroy-all-models` flag above tears down both models on the controller in one go. No additional cleanup is needed.
[/note]

## Next Steps

If you’re looking for what to do next you can:

- [Configure the Temporal worker](https://charmhub.io/temporal-k8s/docs/h-configure-temporal-worker) for production: `auth-secret-id`, environment variables, Vault, TLS, Sentry, and the PostgreSQL relation.
- [Upgrade an existing deployment from `latest/stable` to `1.23/stable`](https://charmhub.io/temporal-k8s/docs/h-upgrade-1.23/stable).
- Explore Temporal
  [scalability](https://charmhub.io/temporal-k8s/docs/h-scaling)
  and
  [observability](https://charmhub.io/temporal-k8s/docs/h-observability).
- Explore [Temporal client authentication and encryption](https://pypi.org/project/temporal-lib-py/).
- Explore [workflow samples](https://github.com/temporalio/samples-python).
- Report any problems you encountered for any of the following charms:
  - [Temporal Server](https://github.com/canonical/temporal-k8s-operator/issues)
  - [Temporal Admin](https://github.com/canonical/temporal-admin-k8s-operator/issues)
  - [Temporal Web UI](https://github.com/canonical/temporal-ui-k8s-operator/issues)
  - [Temporal Worker](https://github.com/canonical/temporal-worker-k8s-operator/issues)
- [Give us your feedback.](https://charmhub.io/temporal-k8s/docs)
- [Contribute to the code base.](https://github.com/canonical/temporal-k8s-operator/issues)
