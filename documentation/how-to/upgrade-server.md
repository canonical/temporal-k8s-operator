# Upgrade Temporal Server

Excerpt from
[Temporal's documentation](https://docs.temporal.io/self-hosted-guide/upgrade-server):

> Temporal Server should be upgraded sequentially. That is, if you're on version
> (v1.n.x), your next upgrade should be to (v1.n+1.x) or the closest available
> subsequent version. This sequence should be repeated until your desired
> version is reached.
>
> 1. Upgrade Database Schema: Before initiating the Temporal Server upgrade, use
>    one of the recommended upgrade tools to update your database schema. This
>    ensures it is aligned with the version of Temporal Server you aim to
>    upgrade to.
> 2. Upgrade Temporal Server: Once the database schema is updated, proceed to
>    upgrade the Temporal Server deployment to the next sequential version.
>
> Also, be aware that each upgrade requires the History Service to load all
> Shards and update the Shard metadata, so allow approximately 10 minutes on
> each version for these processes to complete before upgrading to the next
> version.

The Charmed Temporal K8s charms facilitate server upgrades in the following way:

1. The Charmed Temporal Admin charm should be updated to the next revision that
   you currently have deployed as follows:

   ```bash
   juju refresh temporal-admin-k8s --revision=<your_revision + 1>
   ```

   This will ensure that your database schema is updated if any updates are
   available.

2. The Charmed Temporal K8s charm should be updated to the next revision that
   you currently have deployed as follows:

   ```bash
   juju refresh temporal-k8s --revision=<your_revision + 1>
   ```

_Warning: It is essential that upgrades are done one consecutive revision at a
time. Charmed Temporal K8s can only guarantee backward compatibility between two
consecutive revisions in line with the upgrade system adopted by the Temporal
Server._