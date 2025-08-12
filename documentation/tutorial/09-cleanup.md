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

## Next Steps

If you’re looking for what to do next you can:

- Explore Temporal
  [scalability](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-scaling/10840)
  and
  [observability](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-observability/11787).
- Explore
  Temporal client authentication and encryption:
    - [Python](https://github.com/canonical/temporal-lib-py)
    - [Go](https://github.com/canonical/temporal-lib-go)
- Explore [workflow samples](https://github.com/temporalio/samples-python)
- Report any problems you encountered for any of the following charms:
  - [Temporal Server](https://github.com/canonical/temporal-k8s-operator/issues)
  - [Temporal Admin](https://github.com/canonical/temporal-admin-k8s-operator/issues)
  - [Temporal Web UI](https://github.com/canonical/temporal-ui-k8s-operator/issues)
  - [Temporal Worker](https://github.com/canonical/temporal-worker-k8s-operator/issues)
- [Give us your feedback.](https://discourse.charmhub.io/t/temporal-server-documentation-overview/8948)
- [Contribute to the code base.](https://github.com/canonical/temporal-k8s-operator/issues)
