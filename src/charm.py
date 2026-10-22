#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm definition and helpers."""

# TODO: remove once the charm is split into smaller modules (refactor pending).
# pylint: disable=too-many-lines

import functools
import hashlib
import json
import logging
import os
import re
import socket
from typing import Optional

from botocore.exceptions import ClientError
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.data_platform_libs.v0.s3 import (
    CredentialsChangedEvent,
    CredentialsGoneEvent,
    S3Requirer,
)
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder, LogProxyConsumer
from charms.nginx_ingress_integrator.v0.nginx_route import require_nginx_route
from charms.openfga_k8s.v1.openfga import OpenFGARequires, OpenFGAStoreCreateEvent
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.temporal_k8s.v0.temporal_host_info import TemporalHostInfoProvider
from charms.tls_certificates_interface.v4.tls_certificates import (
    Certificate,
    CertificateRequestAttributes,
    Mode,
    PrivateKey,
    ProviderCertificate,
    TLSCertificatesRequiresV4,
)
from charms.traefik_k8s.v2.ingress import (
    IngressPerAppReadyEvent,
    IngressPerAppRequirer,
    IngressPerAppRevokedEvent,
)
from jinja2 import Environment, FileSystemLoader
from ops import main, pebble
from ops.charm import (
    CharmBase,
    ConfigChangedEvent,
    InstallEvent,
    RelationBrokenEvent,
    RelationEvent,
    RelationJoinedEvent,
    UpdateStatusEvent,
    UpgradeCharmEvent,
)
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    ModelError,
    WaitingStatus,
)
from ops.pebble import CheckStatus

from literals import (
    DB_NAME,
    LOG_FORMAT,
    LOG_OUTPUT_FILE,
    PROMETHEUS_PORT,
    REQUIRED_OPENFGA_KEYS,
    REQUIRED_S3_PARAMETERS,
    SERVICE_PORTS,
    VALID_LOG_LEVELS,
    VISIBILITY_DB_NAME,
    WORKLOAD_VERSION,
    ValidServiceTypes,
)
from log import log_event_handler

# import relations
from relations.openfga import OpenFGA
from relations.s3_archival import (
    construct_endpoint,
    create_bucket_if_not_exists,
    retrieve_s3_parameters,
)

CERTIFICATE_NAME = "temporal-frontend.pem"
CERTS_DIR_PATH = "/etc/temporal"
FRONTEND_CERTIFICATES_RELATION_NAME = "frontend-certificates"
PRIVATE_KEY_NAME = "temporal-frontend.key"
# Hash of the stored certificate and key in the Pebble environment, so a new
# certificate restarts the server.
FRONTEND_CERTIFICATE_HASH_ENV = "TEMPORAL_TLS_FRONTEND_CERT_HASH"
FRONTEND_TLS_CONFIGURATION = {
    "TEMPORAL_TLS_REQUIRE_CLIENT_AUTH": "false",
    "TEMPORAL_TLS_FRONTEND_CERT": f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}",
    "TEMPORAL_TLS_FRONTEND_KEY": f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}",
}
logger = logging.getLogger(__name__)


class SchemaPendingError(ValueError):
    """Raised while admin has not yet migrated the schema for this workload version."""


class ExitWithStatusError(Exception):
    """Exception raised to exit the reconciliation with a specific unit status."""

    def __init__(self, msg: str, status_type):
        """Construct.

        Args:
            msg: The status message.
            status_type: The ops status class to report.
        """
        super().__init__(str(msg))
        self.msg = str(msg)
        self.status_type = status_type

    @property
    def status(self):
        """Return the Juju unit status represented by this exception."""
        return self.status_type(self.msg)


class ExitWithoutStatusChange(Exception):
    """Exception raised to exit the reconciliation leaving the unit status as it is.

    The status that was announced for the event, if any, is kept; otherwise the previous status stays.
    """


def render(template_name, context):
    """Render the template with the given name using the given context dict.

    Args:
        template_name: File name to read the template from.
        context: Dict used for rendering.

    Returns:
        A dict containing the rendered template.
    """
    charm_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    loader = FileSystemLoader(os.path.join(charm_dir, "templates"))
    return Environment(loader=loader, autoescape=True).get_template(template_name).render(**context)


def is_valid_time_duration(duration_str):
    """Validate time duration.

    Args:
        duration_str: time duration string.

    Returns:
        True if the time duration is valid, False otherwise.
    """
    allowed_pattern = r"^[1-9]\d*[smh]$"
    return bool(re.match(allowed_pattern, duration_str))


class TemporalK8SCharm(CharmBase):
    """Temporal server charm.

    Attrs:
        external_hostname: DNS listing used for external connections.
    """

    def _active_status(self):
        """Return the active unit status depending on relations."""
        message = "auth enabled" if self.config["auth-enabled"] else ""
        return ActiveStatus(message)

    def set_active_unit_status(self):
        """Set active unit status depending on relations."""
        self.unit.status = self._active_status()

    @property
    def external_hostname(self):
        """Return the DNS listing used for external connections."""
        return self.config["external-hostname"] or self.app.name

    def __init__(self, *args):
        """Construct.

        Args:
            args: Ignore.
        """
        super().__init__(*args)
        self.name = "temporal"
        self.container = self.unit.get_container("temporal")
        self._extra_context = {}
        self._dns_entries = [
            dns.strip() for dns in self.config.get("frontend-cert-sans-dns", "").split(",") if dns.strip()
        ]

        # Actions keep dedicated handlers: they have a request/response contract.
        self.framework.observe(self.on.restart_action, self._on_restart_action)

        # Handle postgresql relation.
        self.db = DatabaseRequires(self, relation_name="db", database_name=DB_NAME, extra_user_roles="admin")
        self.visibility = DatabaseRequires(
            self,
            relation_name="visibility",
            database_name=VISIBILITY_DB_NAME,
            extra_user_roles="admin",
        )

        # Handle openfga relation
        self.openfga = OpenFGARequires(self, self.name)
        self.openfga_relation = OpenFGA(self)

        # Handle S3 integrator relation
        self.s3_client = S3Requirer(self, "s3-parameters")

        # Handle Ingress (Nginx)
        self._require_nginx_route()

        # Prometheus
        self._prometheus_scraping = MetricsEndpointProvider(
            self,
            relation_name="metrics-endpoint",
            jobs=[{"static_configs": [{"targets": [f"*:{PROMETHEUS_PORT}"]}]}],
            refresh_event=self.on.config_changed,
        )

        # Loki
        self._log_forwarder = LogForwarder(self, relation_name="logging")
        self._log_proxy = LogProxyConsumer(
            self,
            logs_scheme={"temporal": {"log-files": [LOG_OUTPUT_FILE]}},
            relation_name="log-proxy",
        )

        # Grafana
        self._grafana_dashboards = GrafanaDashboardProvider(self, relation_name="grafana-dashboard")

        # Frontend TLS certificates
        # Only frontend TLS will be configured
        self.certificates = TLSCertificatesRequiresV4(
            charm=self,
            relationship_name=FRONTEND_CERTIFICATES_RELATION_NAME,
            certificate_requests=[self._get_certificate_request_attributes()],
            mode=Mode.UNIT,
            refresh_events=[self.on.upgrade_charm, self.on.config_changed],
        )

        # Host Info
        #
        # Requirers are told the frontend's in-cluster address and whether it
        # serves gRPC over TLS, so they can dial it correctly either way. The
        # frontend port is published, not internal-frontend: the internal
        # frontend bypasses the authorizer, which must not apply to the UI.
        # `tls` is a callable because it depends on the certificates relation,
        # which is not resolved at charm initialisation.
        self._host_info = TemporalHostInfoProvider(
            self,
            port=SERVICE_PORTS["frontend"]["grpc"],
            host=self._in_cluster_fqdn,
            tls=self._frontend_tls_enabled,
        )

        # Handle Ingress (via the `ingress` interface). Temporal's frontend
        # service speaks gRPC and is the only service exposed via ingress. The
        # requirer is always instantiated so that its event handlers are
        # registered even when the relation is added after the charm has
        # started (e.g. relating to the ingress provider post-deployment). The
        # `frontend` constraint is enforced in `_validate`.
        #
        # The advertised scheme follows whether the frontend terminates TLS:
        # `https` with `frontend-certificates`, `h2c` without. Which of those a
        # provider accepts differs: Traefik handles h2c, while
        # ingress-configurator fronted by HAProxy requires HTTP/2 over TLS to
        # the backend and so needs `frontend-certificates`. The charm cannot
        # tell the providers apart, so it advertises the truth and leaves the
        # pairing to documentation rather than blocking.
        # See documentation/how-to/configure-ingress.md.
        self.ingress = IngressPerAppRequirer(
            self,
            port=SERVICE_PORTS["frontend"]["grpc"],
            relation_name="ingress",
            scheme=self._ingress_scheme,
        )

        # Every event the charm reacts to converges on the single reconciler.
        for event in [
            self.on.install,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on.update_status,
            self.on.temporal_pebble_ready,
            self.on.peer_relation_changed,
            self.on.admin_relation_joined,
            self.on.admin_relation_changed,
            self.on.ui_relation_joined,
            self.on.ui_relation_changed,
            self.on.db_relation_broken,
            self.on.visibility_relation_broken,
            self.on.openfga_relation_broken,
            self.db.on.database_created,
            self.db.on.endpoints_changed,
            self.visibility.on.database_created,
            self.visibility.on.endpoints_changed,
            self.openfga.on.openfga_store_created,
            self.s3_client.on.credentials_changed,
            self.s3_client.on.credentials_gone,
            self.certificates.on.certificate_available,
            self.on[FRONTEND_CERTIFICATES_RELATION_NAME].relation_joined,
            self.on[FRONTEND_CERTIFICATES_RELATION_NAME].relation_broken,
            self.ingress.on.ready,
            self.ingress.on.revoked,
        ]:
            self.framework.observe(event, self._reconcile)

    def _frontend_tls_enabled(self) -> bool:
        """Return whether the frontend is serving gRPC over TLS.

        This tracks what the workload actually serves, not merely what is
        related: the TLS listener is only configured once the provider has
        issued a certificate, so telling clients `tls=True` or advertising
        `https` any earlier would point them at a still-plaintext frontend.
        """
        if not self._relation_created(FRONTEND_CERTIFICATES_RELATION_NAME):
            return False
        return self._certificate_is_available()

    def _ingress_scheme(self) -> str:
        """Return the scheme to advertise to the ingress provider."""
        return "https" if self._frontend_tls_enabled() else "h2c"

    # Frontend TLS handler
    def _handle_frontend_tls(self):
        # The unit is not configured as a frontend service but has the relation. The workload is still configured,
        # without TLS, so this is only reported in the logs.
        if "frontend" not in self.config["services"] and self.model.get_relation(FRONTEND_CERTIFICATES_RELATION_NAME):
            logger.warning(f"Not a frontend service, please remove {FRONTEND_CERTIFICATES_RELATION_NAME} integration.")
            return

        # Pre-flight checks
        if not self._relation_created(FRONTEND_CERTIFICATES_RELATION_NAME):
            return

        # Fetch the assigned certificate and key
        provider_certificate, private_key = self.certificates.get_assigned_certificate(
            certificate_request=self._get_certificate_request_attributes()
        )

        if not provider_certificate or not private_key:
            # The library only returns a certificate matching the current
            # request, so after the request changes (new SANs, e.g. on refresh
            # or a `frontend-cert-sans-dns` change) there is a window before the
            # provider issues the new one. Keep serving the previously stored
            # certificate meanwhile rather than dropping the frontend to
            # plaintext; it is only removed when the relation is broken.
            if self._stored_certificate_is_usable():
                logger.info("Certificate renewal pending; serving the previously stored certificate.")
                self._extra_context.update(FRONTEND_TLS_CONFIGURATION)
                self._extra_context[FRONTEND_CERTIFICATE_HASH_ENV] = self._stored_certificate_hash()
                return
            # No certificate has been issued yet: the workload is configured without TLS meanwhile.
            logger.info("The certificate is not available yet. Waiting for certificates to be available")
            return

        self._extra_context.update(FRONTEND_TLS_CONFIGURATION)

        # If either the certificate or key is outdated or missing, update both
        if self._update_certificates_required(provider_certificate, private_key):
            self._store_certificate(certificate=provider_certificate.certificate)
            self._store_private_key(private_key=private_key)

        # The server reads the certificate files only at startup and their
        # paths never change, so a new certificate on disk (a renewal, or a
        # re-issue after the SANs change) wouldn't be picked up on its own.
        # Putting their hash in the Pebble environment makes a new certificate
        # change the layer, so the replan restarts the server.
        self._extra_context[FRONTEND_CERTIFICATE_HASH_ENV] = self._stored_certificate_hash()

    def _remove_certificates(self) -> None:
        """Remove the frontend certificates from the workload container once the relation is gone."""
        if self._relation_created(FRONTEND_CERTIFICATES_RELATION_NAME):
            return
        self._delete_certificate()
        self._delete_private_key()

    def _log_ingress_event(self, event) -> None:
        """Log the ingress events, which have no further effect on the workload.

        Args:
            event: The event being reconciled.
        """
        if isinstance(event, IngressPerAppReadyEvent):
            logger.info("This app's ingress URL: %s", event.url)
            # Without frontend TLS the charm advertises h2c. Traefik serves that
            # fine; ingress-configurator/HAProxy cannot, and will not reach the
            # backend. The provider is not identifiable from this side, so this is
            # a warning rather than a blocking condition -- blocking would make the
            # working Traefik topology impossible. Logged here, when ingress is
            # granted, rather than on every hook.
            if not self._relation_created(FRONTEND_CERTIFICATES_RELATION_NAME):
                logger.warning(
                    "ingress is related without %s: advertising the h2c scheme. Providers that require "
                    "HTTP/2 over TLS to the backend (ingress-configurator with HAProxy) will not be able "
                    "to reach the frontend; integrate %s if you are using one of those.",
                    FRONTEND_CERTIFICATES_RELATION_NAME,
                    FRONTEND_CERTIFICATES_RELATION_NAME,
                )
        elif isinstance(event, IngressPerAppRevokedEvent):
            logger.info("This app no longer has ingress")

    def _require_nginx_route(self):
        """Require nginx-route relation based on current configuration.

        The single-ingress-solution constraint (`ingress` vs `nginx-route`) is
        enforced in `_validate` so that the resulting blocked status persists
        through `_reconcile` instead of being reset when the charm reconciles.
        """
        require_nginx_route(
            charm=self,
            service_hostname=self.external_hostname,
            service_name=self.app.name,
            service_port=SERVICE_PORTS["frontend"]["grpc"],
            tls_secret_name=self.config["tls-secret-name"],
            backend_protocol="GRPC",
        )

    def database_connections(self):
        """Return connection info for the related databases.

        The connection info is returned as a dict like the following:

            {
                "db": {
                    "dbname": "...",
                    "host": "...",
                    "port": "...",
                    "user": "...",
                    "password": "...",
                },  # or None.

                "visibility": {
                    "dbname": "...",
                    "host": "...",
                    "port": "...",
                    "user": "...",
                    "password": "...",
                },  # or None.
            }

        Raises:
            ValueError: one of the databases is not connected yet

        Returns:
            DB connection info dict.
        """
        database_connections = {
            "db": self._database_connection("db"),
            "visibility": self._database_connection("visibility"),
        }

        if all(db_conn is None for db_conn in database_connections.values()):
            raise ValueError("database relation not ready")

        for rel_name, db_conn in database_connections.items():
            if db_conn is None:
                raise ValueError(f"{rel_name}:pgsql relation: no database connection available")
        return database_connections

    def _database_connection(self, rel_name):
        """Return the connection info read from the given database relation.

        Args:
            rel_name: Name of the database relation, `db` or `visibility`.

        Returns:
            The connection info dict, or None if the relation does not provide a usable connection yet.
        """
        if self.model.get_relation(rel_name) is None:
            return None

        requirer = self.db if rel_name == "db" else self.visibility
        relation_id = requirer.relations[0].id
        relation_data = requirer.fetch_relation_data()[relation_id]

        endpoints = relation_data.get("endpoints", "").split(",")
        primary_endpoint = endpoints[0].split(":")
        if len(primary_endpoint) < 2:
            return None

        db_conn = {
            "dbname": DB_NAME if rel_name == "db" else VISIBILITY_DB_NAME,
            "host": primary_endpoint[0],
            "port": primary_endpoint[1],
            "password": relation_data.get("password"),
            "user": relation_data.get("username"),
            "tls": relation_data.get("tls") == "True",
        }

        if None in (db_conn["user"], db_conn["password"]):
            return None
        return db_conn

    def _provide_admin_db_info(self):
        """Provide the database connection info to the admin charm; leader only."""
        if not self.unit.is_leader() or not self._peer_relation_ready():
            return

        try:
            database_connections = self.database_connections()
        except ValueError as err:
            logger.debug(f"admin:temporal: not providing database connections: {err}")
            return

        admin_relations = self.model.relations["admin"]
        if not admin_relations:
            logger.debug("admin:temporal: not providing database connections: admin not ready")
            return
        for relation in admin_relations:
            logger.debug(f"admin:temporal: providing database connections on relation {relation.id}")
            relation.data[self.app].update({"database_connections": json.dumps(database_connections)})

    def _provide_server_status(self):
        """Provide the current server status to the UI charm; leader only.

        The status is published when the UI relation changes and, once healthy, on update-status.
        """
        if not self.unit.is_leader():
            return

        is_active = self.unit.status == ActiveStatus() or self.unit.status == ActiveStatus("auth enabled")

        ui_relations = self.model.relations["ui"]
        if not ui_relations:
            logger.debug("ui:temporal: not providing server status: ui not ready")
            return
        for relation in ui_relations:
            logger.debug(f"ui:temporal: providing server status on relation {relation.id}")
            relation.data[self.app].update({"server_status": "ready" if is_active else "blocked"})

    def _peer_relation_ready(self) -> bool:
        """Report whether the peer relation is available."""
        return bool(self.model.get_relation("peer"))

    def _peer_get(self, key):
        """Read a JSON encoded value from the peer relation application databag.

        Args:
            key: Name of the value.

        Returns:
            The value, or None if it is not set or the peer relation is not available.
        """
        relation = self.model.get_relation("peer")
        if relation is None:
            return None
        return json.loads(relation.data[self.app].get(key, "null"))

    def _peer_set(self, key, value):
        """Write a JSON encoded value to the peer relation application databag.

        Args:
            key: Name of the value.
            value: Value to store.
        """
        self.model.get_relation("peer").data[self.app][key] = json.dumps(value)

    def _peer_delete(self, key):
        """Delete a value from the peer relation application databag, if it is set.

        Args:
            key: Name of the value.
        """
        relation = self.model.get_relation("peer")
        if relation is not None:
            relation.data[self.app].pop(key, None)

    def _stored_openfga_state(self):
        """Return the OpenFGA state persisted in the peer relation, in the format of the previous revisions.

        Returns:
            The persisted state dict, or None if there is none.
        """
        stored = self._peer_get("openfga")
        return stored if isinstance(stored, dict) and stored else None

    def _relation_openfga_state(self, stored):
        """Return the OpenFGA connection info read from the relation.

        The authorization model ID is the only value that cannot be read from the relation: it is created by an
        action and persisted in the peer relation, together with the ID of the store it belongs to.

        Args:
            stored: The OpenFGA state persisted in the peer relation, if any.

        Returns:
            The OpenFGA state dict, or None if the relation does not provide a usable store.
        """
        try:
            info = self.openfga.get_store_info()
        except ModelError as err:
            logger.error("failed to read the OpenFGA store info: %s", err)
            return None
        if not info or not info.store_id or not info.http_api_url:
            return None

        auth_model_id = None
        if stored and stored.get("store_id") == info.store_id:
            auth_model_id = stored.get("auth_model_id")

        try:
            return self.openfga_relation._openfga_state_from_store_info(info, auth_model_id)
        except ValueError as exc:
            logger.error("invalid OpenFGA store info: %s", exc)
            return None

    def _openfga_state(self):
        """Return the OpenFGA state the workload and the actions use.

        The relation is the source of truth. As the previous revisions did, the state persisted in the peer
        relation is used as it is while the relation does not provide a usable store (revoked, or an invalid
        HTTP API URL), so what is reported then is what the persisted state lacks, if anything.

        Returns:
            The OpenFGA state dict, or None if there is neither a usable store nor a persisted state.
        """
        stored = self._stored_openfga_state()
        return self._relation_openfga_state(stored) or stored

    def _store_openfga_auth_model_id(self, store_id, auth_model_id):
        """Persist the authorization model ID created for the given OpenFGA store.

        The fields persisted by other revisions are left as they are: units still running them read them.

        Args:
            store_id: ID of the OpenFGA store the model belongs to.
            auth_model_id: ID of the authorization model.
        """
        stored = self._stored_openfga_state() or {}
        self._peer_set("openfga", {**stored, "store_id": store_id, "auth_model_id": auth_model_id})

    @functools.cached_property
    def _s3_connection(self):
        """Return the S3 parameters read from the relation and the state derived from them.

        Returns:
            A tuple of the S3 parameters and the S3 state, both None if the relation does not provide usable
            credentials.
        """
        if not self.model.get_relation("s3-parameters"):
            return None, None

        s3_parameters, missing_parameters = retrieve_s3_parameters(self.s3_client)
        if missing_parameters:
            return None, None

        state = {
            "bucket": s3_parameters.get("bucket"),
            "endpoint": construct_endpoint(s3_parameters),
            "region": s3_parameters.get("region"),
            "aws_access_key_id": s3_parameters.get("access-key"),
            "aws_secret_access_key": s3_parameters.get("secret-key"),
            "uri_style": s3_parameters.get("s3-uri-style"),
        }
        return s3_parameters, state

    @staticmethod
    def _s3_fingerprint(s3_state) -> str:
        """Return a fingerprint of the S3 state, to tell whether a bucket was already created for it."""
        return hashlib.sha256(json.dumps(s3_state, sort_keys=True).encode()).hexdigest()

    def _s3_state(self):
        """Return the S3 state read from the relation and the outcome of the bucket creation.

        The outcome is the one recorded by the leader for the current credentials, or else the one the previous
        revisions persisted in the `s3` value, if it was for the same credentials: a unit upgraded before the
        leader is then configured like the units still running a previous revision.

        Returns:
            The S3 state dict, or None if the relation is not usable or its bucket was not processed yet.
        """
        _, s3_state = self._s3_connection
        if s3_state is None:
            return None

        record = self._peer_get("s3_bucket")
        if isinstance(record, dict) and record.get("fingerprint") == self._s3_fingerprint(s3_state):
            return {**s3_state, "bucket_created": bool(record.get("bucket_created"))}

        legacy = self._peer_get("s3")
        if isinstance(legacy, dict) and "bucket_created" in legacy:
            credentials = {key: value for key, value in legacy.items() if key != "bucket_created"}
            if credentials == s3_state:
                return {**s3_state, "bucket_created": bool(legacy["bucket_created"])}
        return None

    def _reconcile_peer_state(self, event):
        """Maintain the data the leader persists in the peer relation; leader only.

        This unit reads the data it is configured from from the relations. What cannot be read from its source is
        persisted: the outcome of the S3 bucket creation, the OpenFGA authorization model, and a digest that tells
        the other units when what they are configured from changed.

        The `database_connections`, `s3` and `openfga` values are the ones the previous revisions read. During a
        rolling upgrade the units still running one of them read these values from the peer relation, and the
        leader may already be upgraded and the only one updating them, so they are never removed or reshaped
        and are kept up to date, in the format of the previous revisions, for as long as the relations provide
        data. They are not cleaned up, as there is no telling when the last unit left the previous revision.

        Args:
            event: The event being reconciled.
        """
        if not self.unit.is_leader() or not self._peer_relation_ready():
            return

        self._reconcile_openfga_peer_state(event)
        self._reconcile_s3_bucket(event)
        self._reconcile_legacy_database_connections(event)
        self._reconcile_legacy_s3(event)
        self._publish_relation_digest()

    def _reconcile_openfga_peer_state(self, event):
        """Keep the OpenFGA state persisted in the peer relation up to date with the relation; leader only.

        The state is only replaced while the relation provides a usable store: when the store is revoked, or its
        HTTP API URL is invalid, the persisted state stays as it is, until the relation is broken.

        Args:
            event: The event being reconciled.
        """
        if isinstance(event, RelationBrokenEvent) and event.relation.name == "openfga":
            self._peer_delete("openfga")
            return

        stored = self._stored_openfga_state()
        if isinstance(event, OpenFGAStoreCreateEvent):
            # An authorization model has to be created again after the store is delivered, as it always was.
            stored = None

        state = self._relation_openfga_state(stored)
        if state is not None and state != self._peer_get("openfga"):
            self._peer_set("openfga", state)

    def _reconcile_legacy_database_connections(self, event):
        """Keep the `database_connections` value of the previous revisions up to date; leader only.

        A database that does not provide usable connection info keeps the value it had, until its relation is gone.

        Args:
            event: The event being reconciled.
        """
        stored = self._peer_get("database_connections")
        current = stored if isinstance(stored, dict) else {}
        connections = {}
        for rel_name in ("db", "visibility"):
            connection = self._database_connection(rel_name)
            relation_gone = self.model.get_relation(rel_name) is None or (
                isinstance(event, RelationBrokenEvent) and event.relation.name == rel_name
            )
            if relation_gone:
                connection = None
            elif connection is None:
                connection = current.get(rel_name)
            connections[rel_name] = connection

        if connections != stored and (stored is not None or any(connections.values())):
            self._peer_set("database_connections", connections)

    def _reconcile_legacy_s3(self, event):
        """Keep the `s3` value of the previous revisions up to date; leader only.

        Args:
            event: The event being reconciled.
        """
        stored = self._peer_get("s3")
        s3_state = self._s3_state()
        if s3_state is not None:
            if s3_state != stored:
                self._peer_set("s3", s3_state)
        elif stored is not None and (
            isinstance(event, CredentialsGoneEvent) or not self.model.get_relation("s3-parameters")
        ):
            self._peer_set("s3", None)

    def _relation_digest(self) -> str:
        """Return a digest of the data the workload is configured from, as read by this unit from the relations.

        The OpenFGA state persisted in the peer relation is only used for the authorization model: what the
        unit cannot read from the relation is not what it has to agree with the leader on.
        """
        return hashlib.sha256(
            json.dumps(
                {
                    "database_connections": {
                        rel_name: self._database_connection(rel_name) for rel_name in ("db", "visibility")
                    },
                    "openfga": self._relation_openfga_state(self._stored_openfga_state()),
                    "s3": self._s3_state(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def _publish_relation_digest(self):
        """Publish the digest of the data the workload is configured from; leader only.

        The other units follow the leader: they react to the peer relation changing, and to the relation events
        only once what they read agrees with the published digest. The digest is a notification, the data itself
        is always read from the relations.
        """
        digest = self._relation_digest()
        if self._peer_get("relation_digest") != digest:
            self._peer_set("relation_digest", digest)

    def _in_sync_with_leader(self) -> bool:
        """Report whether this unit reads the same relation data as the leader does."""
        published = self._peer_get("relation_digest")
        if published is None:
            return True
        return self._relations_visible() and self._relation_digest() == published

    def _reconcile_s3_bucket(self, event):
        """Create the S3 bucket when the relation provides new credentials, and record the outcome.

        The bucket is only checked when there is no record of the outcome for the current credentials, and when the
        credentials are provided again. Whatever goes wrong while checking it is a failed attempt, which is
        recorded like any other, so the endpoint is not contacted again on every event and no hook fails.

        Args:
            event: The event being reconciled.
        """
        s3_parameters, s3_state = self._s3_connection
        if s3_state is None:
            self._peer_delete("s3_bucket")
            return

        fingerprint = self._s3_fingerprint(s3_state)
        record = self._peer_get("s3_bucket")
        if (
            isinstance(record, dict)
            and record.get("fingerprint") == fingerprint
            and not isinstance(event, CredentialsChangedEvent)
        ):
            return

        bucket_created = True
        try:
            create_bucket_if_not_exists(s3_parameters, s3_state["endpoint"])
        except (ClientError, ValueError):
            bucket_created = False
        except Exception:  # pylint: disable=broad-exception-caught
            # E.g. the endpoint cannot be reached: the previous revisions let this fail the credentials-changed hook.
            logger.exception("failed to create the S3 bucket %s", s3_parameters.get("bucket"))
            bucket_created = False
        if not bucket_created:
            logger.warning("S3 bucket %s could not be created or checked", s3_parameters.get("bucket"))
        self._peer_set("s3_bucket", {"fingerprint": fingerprint, "bucket_created": bucket_created})

    @staticmethod
    def _relation_name(event):
        """Return the name of the relation the event is about, or None if it is not a relation event."""
        return event.relation.name if isinstance(event, RelationEvent) else None

    def _is_source_event(self, event) -> bool:
        """Report whether the event is about the data the workload is configured from, other than the config.

        The leader acts on these events and the other units follow it, see `_in_sync_with_leader`.
        """
        return self._relation_name(event) in ("db", "visibility", "openfga", "s3-parameters") or isinstance(
            event, (OpenFGAStoreCreateEvent, CredentialsChangedEvent, CredentialsGoneEvent)
        )

    def _handle_passive_event(self, event) -> bool:
        """Handle the events that only report, publish or log: they never reconfigure the workload.

        Args:
            event: The event being reconciled.

        Returns:
            True if the event was handled, False if it has to be reconciled.
        """
        if isinstance(event, InstallEvent):
            if self.unit.is_leader():
                self.unit.status = MaintenanceStatus("installing temporal")
            return True
        if isinstance(event, (IngressPerAppReadyEvent, IngressPerAppRevokedEvent)):
            self._log_ingress_event(event)
            return True
        if self._relation_name(event) == "ui":
            self._provide_server_status()
            return True
        if self._relation_name(event) == "admin" and isinstance(event, RelationJoinedEvent):
            self._provide_admin_db_info()
            return True
        return False

    def _ignore_event(self, event) -> bool:
        """Report whether there is nothing to reconcile for the event on this unit.

        Args:
            event: The event being reconciled.

        Returns:
            True if the event is ignored.
        """
        relation_name = self._relation_name(event)
        leader = self.unit.is_leader()
        if isinstance(event, UpgradeCharmEvent):
            # The workload container is restarted by the upgrade, and reconciled on pebble-ready.
            return not leader
        if relation_name == "peer" and leader:
            # The leader is the one writing to the peer relation.
            return True
        if relation_name in ("admin", "db", "visibility", "openfga") and not self._peer_relation_ready():
            return True
        if isinstance(event, OpenFGAStoreCreateEvent):
            info = self.openfga.get_store_info() if event.store_id else None
            if not info or not info.http_api_url:
                return True
        if isinstance(event, CredentialsChangedEvent) and self._s3_connection[1] is None:
            return True
        # A non-leader unit waits for the leader to have acted on the data, and for itself to read the same: a unit
        # that is being removed, for instance, loses its relations before the leader knows anything about it.
        return (
            not leader and (relation_name == "peer" or self._is_source_event(event)) and not self._in_sync_with_leader()
        )

    def _pending_status(self, event):
        """Return the status the event announces while it is reconciled.

        It stays as the unit status if the reconciliation ends without a status of its own, e.g. because the
        workload container cannot be reached yet.

        Args:
            event: The event being reconciled.

        Returns:
            The status, or None if the event does not announce one.
        """
        relation_name = self._relation_name(event)
        if isinstance(event, ConfigChangedEvent) or relation_name == "peer":
            return WaitingStatus("configuring temporal")
        if relation_name == "admin":
            return WaitingStatus("handling schema ready change")
        if not self.unit.is_leader() and self._is_source_event(event):
            return WaitingStatus("configuring temporal")
        if relation_name in ("db", "visibility") and not isinstance(event, RelationBrokenEvent):
            return WaitingStatus(f"handling {relation_name} change")
        return None

    @log_event_handler(logger)
    def _reconcile(self, event):
        """Reconcile the charm towards the desired state; idempotent for every event.

        Whatever the event, a reconciliation that reaches the workload ends with the "replanning application"
        status; only update-status, which is the periodic health check, reports the unit as active.

        Args:
            event: The event that triggered the reconciliation.
        """
        if self._handle_passive_event(event) or self._ignore_event(event):
            return

        pending_status = self._pending_status(event)
        try:
            if isinstance(event, ConfigChangedEvent):
                self._check_frontend_dns()

            self._reconcile_peer_state(event)
            if self._relation_name(event) in ("db", "visibility") and not isinstance(event, RelationBrokenEvent):
                self._provide_admin_db_info()

            if self.app.planned_units() == 0:
                logger.info("application is being removed, skipping temporal configuration")
                raise ExitWithoutStatusChange()

            self._check_ready(event)
            if isinstance(event, UpdateStatusEvent):
                self._provide_admin_db_info()

            if self.unit.is_leader():
                self._open_service_ports()
            container = self._check_container_can_connect()

            context = self._build_context()
            self._remove_certificates()
            self._handle_frontend_tls()
            context.update(self._extra_context)

            self._configure_log_rotation(container)
            self._configure_workload(container, context)
            replanned = self._apply_layer(container, context)

            if replanned or not isinstance(event, UpdateStatusEvent):
                # The certificates relation is not observed by the host-info or ingress
                # libraries, so republish both here: this runs on certificate_available
                # and on the frontend-certificates relation joining and breaking, which
                # are exactly the transitions that flip the published `tls` value and the
                # advertised ingress scheme. Only advertise what the workload is running.
                self._host_info.publish()
                self.ingress.provide_ingress_requirements(port=SERVICE_PORTS["frontend"]["grpc"])
                raise ExitWithStatusError("replanning application", MaintenanceStatus)
            self._check_server_healthy(container)
        except ExitWithoutStatusChange:
            if pending_status is not None:
                self.unit.status = pending_status
            return
        except ExitWithStatusError as e:
            self.unit.status = e.status
            return

        self.set_active_unit_status()
        self._provide_server_status()

    def _check_ready(self, event):
        """Verify that the configuration and the relations are valid and ready.

        update-status never reports a failure of these checks: the unit keeps the status the event that caused
        the failure gave it.

        Args:
            event: The event being reconciled.

        Raises:
            ExitWithoutStatusChange: If the checks fail on update-status.
            ExitWithStatusError: If the checks fail on any other event.
        """
        try:
            self._check_relations_visible()
            self._check_configuration()
        except ExitWithStatusError as err:
            if isinstance(event, UpdateStatusEvent):
                raise ExitWithoutStatusChange() from err
            raise

    def _check_frontend_dns(self):
        """Validate the frontend-cert-sans-dns configuration; only checked when the configuration changes.

        Raises:
            ExitWithStatusError: If one of the configured names is not a valid DNS name.
        """
        invalid_dns = [dns for dns in self._dns_entries if not self._valid_dns(dns)]
        if invalid_dns:
            logger.info(f"Invalid frontend-cert-sans-dns: {invalid_dns}")
            raise ExitWithStatusError("Invalid frontend-cert-sans-dns, please correct the value(s).", BlockedStatus)

    def _relations_visible(self) -> bool:
        """Report whether the relations the workload is configured from expose their remote units to this unit.

        A non-leader unit added after the relations were established cannot read their data before the remote
        units have joined it, and must not mistake that for relations that are not ready.
        """
        if self.unit.is_leader():
            return True

        relation_names = ["db", "visibility", "s3-parameters"]
        if self.config["auth-enabled"]:
            relation_names.append("openfga")
        for relation_name in relation_names:
            relation = self.model.get_relation(relation_name)
            if relation is not None and not relation.units:
                return False
        return True

    def _check_relations_visible(self):
        """Wait on a non-leader unit until the relations it has not joined yet expose their remote units.

        Raises:
            ExitWithStatusError: If a relation the workload is configured from is not visible to the unit yet.
        """
        if not self._relations_visible():
            raise ExitWithStatusError("configuring temporal", WaitingStatus)

    def _check_configuration(self):
        """Validate that configuration and relations are valid and ready.

        Raises:
            ExitWithStatusError: If the configuration or the relations are not valid or ready.
        """
        try:
            self._validate()
        except ValueError as err:
            status_type = WaitingStatus if isinstance(err, SchemaPendingError) else BlockedStatus
            raise ExitWithStatusError(str(err), status_type) from err

    def _check_container_can_connect(self):
        """Verify that the workload container is reachable.

        Raises:
            ExitWithoutStatusChange: If the container cannot be connected to; the unit status is left as it is
                and the next event reconciles again.

        Returns:
            The workload container.
        """
        container = self.unit.get_container(self.name)
        if not container.can_connect():
            raise ExitWithoutStatusChange()
        return container

    def _check_server_healthy(self, container):
        """Verify that the Temporal server is up, and perform the periodic maintenance (update-status only).

        Args:
            container: application container.

        Raises:
            ExitWithStatusError: If the server status check is failing.
        """
        check = container.get_check("temporal-server-running")
        if check.status != CheckStatus.UP:
            raise ExitWithStatusError("Status check: DOWN", MaintenanceStatus)

        self._run_log_rotation(container)
        self.unit.set_workload_version(WORKLOAD_VERSION)

    @log_event_handler(logger)
    def _on_restart_action(self, event):
        """Restart the temporal server, even if there are no changes.

        Args:
            event: The event triggered when the relation changed.
        """
        container = self.unit.get_container(self.name)

        logger.info("restarting temporal")
        self.unit.status = MaintenanceStatus("restarting temporal")
        container.restart("temporal-server")
        self.set_active_unit_status()

    def _server_running(self, container) -> bool:
        """Check whether the Temporal server Pebble service is running.

        Args:
            container: application container

        Returns:
            True if the service is running, False otherwise.
        """
        try:
            return container.get_service("temporal-server").is_running()
        except (ModelError, pebble.ConnectionError):
            return False

    def _run_log_rotation(self, container):
        """Run log rotation for temporal server logs.

        logrotate only rotates when the configured
        conditions are met (file size or time threshold).

        Args:
            container: application container
        """
        try:
            container.exec(["logrotate", "/etc/logrotate.d/temporal-server"]).wait()
        except (pebble.ExecError, pebble.APIError) as e:
            logger.warning(f"Log rotation failed: {e}")

    def _check_missing_params(self, params, required_params):
        """Validate that all required properties were extracted.

        Args:
            params: dictionary of parameters extracted from relation.
            required_params: list of required parameters.

        Returns:
            list: List of OpenFGA parameters that are not set in state.
        """
        missing_params = []
        for key in required_params:
            if params.get(key) is None:
                missing_params.append(key)
        return missing_params

    # flake8: noqa: C901
    def _validate(self):
        """Validate that configuration and relations are valid and ready.

        Raises:
            ValueError: in case of invalid configuration.
        """
        log_level = self.model.config["log-level"].lower()
        if log_level not in VALID_LOG_LEVELS:
            raise ValueError(f"config: invalid log level {log_level!r}")
        if not self._peer_relation_ready():
            raise ValueError("peer relation not ready")

        # Validate config.
        for service in self.config["services"].split(","):
            if not any(service == item.value for item in ValidServiceTypes):
                raise ValueError(f"error in services config: invalid service {service!r}")

        num_history_shards = self._peer_get("num_history_shards")
        if num_history_shards is None:
            if self.config.get("num-history-shards", "") == "" or self.config.get("num-history-shards") <= 0:
                raise ValueError(
                    "value of 'num-history-shards' config must be set to a positive power of 2 (e.g. 1, 2, 4)"
                )

            if self.unit.is_leader():
                self._peer_set("num_history_shards", self.config.get("num-history-shards"))

        elif num_history_shards != self.config["num-history-shards"]:
            message = f"value of 'num-history-shards' config cannot be changed after deployment. Value should be {num_history_shards}"
            logger.error(message)
            raise ValueError(message)

        if self.config["global-rps-limit"] < 0:
            raise ValueError("`global-rps-limit` must be grater than 0")

        db_types = ["persistence", "visibility"]
        for db_type in db_types:
            if self.config[f"{db_type}-max-conns"] < 1:
                raise ValueError(f"value of '{db_type}-max-conns' must be >= 1")
            if self.config[f"{db_type}-max-idle-conns"] < 1:
                raise ValueError(f"value of '{db_type}-max-idle-conns' must be >= 1")
            if not is_valid_time_duration(self.config[f"{db_type}-max-conn-time"]):
                raise ValueError(f"value of '{db_type}-max-conn-time' must be a valid time duration e.g. 1h")

        self._validate_ingress()

        # Validate admin relation.
        self.database_connections()
        self._validate_admin_schema()

        # Validate OpenFGA relation.
        if self.config["auth-enabled"]:
            openfga = self._openfga_state()
            if not openfga:
                raise ValueError("openfga:temporal relation not ready")
            missing_params = self._check_missing_params(openfga, REQUIRED_OPENFGA_KEYS)
            if len(missing_params) > 0:
                raise ValueError(f"openfga:missing parameters {missing_params!r}")
            if not openfga["auth_model_id"]:
                raise ValueError("missing openfga authorization model")

        # Validate S3 relation.
        s3 = self._s3_state()
        if s3:
            missing_params = self._check_missing_params(s3, REQUIRED_S3_PARAMETERS)
            if len(missing_params) > 0:
                raise ValueError(f"s3:missing parameters {missing_params!r}")

            if not s3.get("bucket_created"):
                raise ValueError("s3:archival failed to create s3 bucket.")

    def _validate_admin_schema(self):
        """Validate that admin has migrated the schema for this workload version.

        Raises:
            SchemaPendingError: while the schema is not ready for this workload version.
        """
        admin = self.model.get_relation("admin")
        admin_data = admin.data[admin.app] if admin and admin.app else {}
        if (admin_data.get("schema_status"), admin_data.get("migrated_workload_version")) != (
            "ready",
            WORKLOAD_VERSION,
        ):
            raise SchemaPendingError("admin:temporal relation: schema is pending migration")

    def _validate_ingress(self):
        """Validate the ingress relation.

        Raises:
            ValueError: in case of invalid ingress configuration.
        """
        if not self.model.get_relation("ingress"):
            return
        # Only one ingress solution can be used at a time.
        if self.model.get_relation("nginx-route"):
            raise ValueError("Only one ingress solution is allowed - remove the ingress or the nginx-route relation.")
        # Only the frontend service can be exposed through ingress.
        if "frontend" not in self.config["services"]:
            raise ValueError("Not a frontend service, please remove ingress integration.")
        # Ingress without frontend-certificates is valid (h2c, e.g. Traefik);
        # `_log_ingress_event` warns about it once ingress is granted.

    def _open_service_ports(self):
        """Open the respective ports based on Temporal service."""
        services = self.config["services"]

        open_port = functools.partial(self.model.unit.open_port, protocol="tcp")
        close_port = functools.partial(self.model.unit.close_port, protocol="tcp")

        for service, ports in SERVICE_PORTS.items():
            if service in services:
                open_port(port=ports["grpc"])
                open_port(port=ports["http"])
            else:
                close_port(port=ports["grpc"])
                close_port(port=ports["http"])

        if "frontend" in services:
            open_port(port=SERVICE_PORTS["internal-frontend"]["grpc"])
            open_port(port=SERVICE_PORTS["internal-frontend"]["http"])
        else:
            close_port(port=SERVICE_PORTS["internal-frontend"]["grpc"])
            close_port(port=SERVICE_PORTS["internal-frontend"]["http"])

    def _build_context(self):
        """Build the workload configuration context from the configuration and the relations.

        Returns:
            The context dict used to render the workload configuration and to set the service environment.
        """
        logger.info("configuring temporal")
        options = {
            "log-level": "LOG_LEVEL",
        }
        context = {config_key: self.config[key] for key, config_key in options.items()}
        context.update(
            {
                "LOG_OUTPUT_FILE": LOG_OUTPUT_FILE,
                "LOG_FORMAT": LOG_FORMAT,
            }
        )
        database_connections = self.database_connections()
        db_conn = database_connections["db"]
        visibility_conn = database_connections["visibility"]
        context.update(
            {
                "DB_NAME": db_conn["dbname"],
                "DB_HOST": db_conn["host"],
                "DB_PORT": db_conn["port"],
                "DB_USER": db_conn["user"],
                "DB_PSWD": db_conn["password"],
                "VISIBILITY_NAME": visibility_conn["dbname"],
                "VISIBILITY_HOST": visibility_conn["host"],
                "VISIBILITY_PORT": visibility_conn["port"],
                "VISIBILITY_USER": visibility_conn["user"],
                "VISIBILITY_PSWD": visibility_conn["password"],
                "TEMPORAL_BROADCAST_ADDRESS": str(self.model.get_binding("peer").network.bind_address),
                "NUM_HISTORY_SHARDS": self._peer_get("num_history_shards"),
                "SQL_MAX_CONNS": self.config["persistence-max-conns"],
                "SQL_MAX_IDLE_CONNS": self.config["persistence-max-idle-conns"],
                "SQL_MAX_CONN_TIME": self.config["persistence-max-conn-time"],
                "SQL_VIS_MAX_CONNS": self.config["visibility-max-conns"],
                "SQL_VIS_MAX_IDLE_CONNS": self.config["visibility-max-idle-conns"],
                "SQL_VIS_MAX_CONN_TIME": self.config["visibility-max-conn-time"],
                "SQL_TLS_ENABLED": db_conn.get("tls", False),
            }
        )

        if self.config["auth-enabled"]:
            openfga = self._openfga_state()
            context.update(
                {
                    "AUTH_ENABLED": True,
                    "OFGA_STORE_ID": openfga.get("store_id"),
                    "OFGA_AUTH_MODEL_ID": openfga.get("auth_model_id"),
                    "OFGA_API_HOST": openfga.get("address"),
                    "OFGA_API_SCHEME": openfga.get("scheme"),
                    "OFGA_SECRETS_BEARER_TOKEN": openfga.get("token"),
                    "OFGA_API_PORT": openfga.get("port"),
                    "AUTH_ADMIN_GROUPS": self.config["auth-admin-groups"],
                    "AUTH_OPEN_ACCESS_NAMESPACES": self.config["auth-open-access-namespaces"],
                    "AUTH_GOOGLE_CLIENT_ID": self.config["auth-google-client-id"],
                }
            )

        http_proxy = os.environ.get("JUJU_CHARM_HTTP_PROXY")
        https_proxy = os.environ.get("JUJU_CHARM_HTTPS_PROXY")
        no_proxy = os.environ.get("JUJU_CHARM_NO_PROXY")

        if http_proxy or https_proxy:
            context.update(
                {
                    "HTTP_PROXY": http_proxy,
                    "HTTPS_PROXY": https_proxy,
                    "NO_PROXY": no_proxy,
                }
            )

        s3 = self._s3_state()
        if s3:
            context.update(
                {
                    "ARCHIVAL_ENABLED": True,
                    "ARCHIVAL_BUCKET_REGION": s3.get("region"),
                    "ARCHIVAL_ENDPOINT": s3.get("endpoint"),
                    "ARCHIVAL_URI_STYLE": s3.get("uri_style"),
                    "AWS_ACCESS_KEY_ID": s3.get("aws_access_key_id"),
                    "AWS_SECRET_ACCESS_KEY": s3.get("aws_secret_access_key"),
                }
            )

        return context

    def _configure_workload(self, container, context):
        """Write the workload configuration files, unless they are already up to date.

        Args:
            container: The Temporal workload container.
            context: The workload configuration context.
        """
        config = render("config.jinja", context)
        self._push_if_changed(container, "/etc/temporal/config/charm.yaml", config)

        dynamic_context = {
            "GLOBAL_RPS_LIMIT": self.config["global-rps-limit"],
            "NAMESPACE_RPS_LIMIT": self.config["namespace-rps-limit"],
            "LONG_POLL_INTERVAL": self.config["long-poll-interval"],
        }
        dynamic_config = render("dynamic_config.jinja", dynamic_context)
        self._push_if_changed(container, "/etc/temporal/config/dynamicconfig/docker.yaml", dynamic_config)

    def _push_if_changed(self, container, path, content):
        """Write a file to the container unless it already has the given content.

        Args:
            container: The Temporal workload container.
            path: Path of the file in the container.
            content: Content of the file.
        """
        if container.exists(path) and container.pull(path).read() == content:
            return
        container.push(path, content, make_dirs=True)

    def _apply_layer(self, container, context) -> bool:
        """Add the Pebble layer and replan when the plan changed or the server is not running.

        Args:
            container: The Temporal workload container.
            context: The workload configuration context, used as the service environment.

        Raises:
            ExitWithStatusError: If the server cannot be started.

        Returns:
            True if the workload was replanned, False if it was already up to date.
        """
        logger.info("planning temporal execution")
        services = self.config["services"].split(",")
        services_args = " ".join(f"--service={service}" for service in services)
        if ValidServiceTypes.FRONTEND.value in services:
            services_args += " --service=internal-frontend"

        pebble_layer = {
            "summary": "temporal server layer",
            "services": {
                "temporal-server": {
                    "summary": "temporal server",
                    "command": "temporal-server --env charm start " + services_args,
                    "startup": "enabled",
                    "override": "replace",
                    # Including config values here so that a change in the
                    # config forces replanning to restart the service.
                    "environment": context,
                    "on-check-failure": {"temporal-server-running": "ignore"},
                    "user": "ubuntu",
                    "working-dir": "/etc/temporal",
                }
            },
            "checks": {
                "temporal-server-running": {
                    "override": "replace",
                    "level": "alive",
                    "period": "300s",
                    # curl cluster health of internal-frontend service
                    "exec": {"command": "temporal operator cluster health --address=temporal-k8s:7236"},
                }
            },
        }
        plan_before = container.get_plan().to_dict()
        container.add_layer(self.name, pebble_layer, combine=True)
        plan_changed = container.get_plan().to_dict() != plan_before

        # A previous replan may have failed to start the server: retry it.
        if not plan_changed and self._server_running(container):
            return False
        self._replan(container)
        return True

    def _configure_log_rotation(self, container):
        """Create the log directory and push the logrotate configuration.

        Args:
            container: The Temporal workload container.
        """
        # Ensure log directory exists
        log_dir = os.path.dirname(LOG_OUTPUT_FILE)
        container.make_dir(log_dir, make_parents=True, user="ubuntu", group="ubuntu")

        # Configure log rotation
        logrotate_config = f"""{LOG_OUTPUT_FILE} {{
    daily
    rotate 7
    size 100M
    missingok
    notifempty
    nomail
    compress
    delaycompress
    copytruncate
    create 0640 ubuntu ubuntu
}}
"""
        self._push_if_changed(container, "/etc/logrotate.d/temporal-server", logrotate_config)

    def _replan(self, container):
        """Replan the workload, blocking the unit instead of failing the hook if it cannot start.

        Args:
            container: The Temporal workload container.

        Raises:
            ExitWithStatusError: If the server cannot be started.
        """
        try:
            container.replan()
        except pebble.ChangeError as err:
            logger.error("failed to start temporal server: %s", err)
            raise ExitWithStatusError("failed to start temporal server; check logs", BlockedStatus) from err

    # Helpers for frontend TLS
    def _relation_created(self, relation_name: str) -> bool:
        return bool(self.model.relations.get(relation_name))

    def _certificate_is_available(self) -> bool:
        """Return whether the frontend has a certificate to serve TLS with.

        Mirrors `_handle_frontend_tls`: either a certificate is assigned for the
        current request, or a previously stored one keeps serving while a
        renewal for a changed request is pending.
        """
        cert, key = self.certificates.get_assigned_certificate(
            certificate_request=self._get_certificate_request_attributes()
        )
        return bool(cert and key) or self._stored_certificate_is_usable()

    def _stored_certificate_hash(self) -> str:
        """Return a hash of the stored frontend certificate and private key."""
        certificate = self.container.pull(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}").read()
        private_key = self.container.pull(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}").read()
        return hashlib.sha256(f"{certificate}{private_key}".encode()).hexdigest()

    def _stored_certificate_is_usable(self) -> bool:
        """Return whether a previously stored certificate and key can keep serving TLS.

        Used while a renewal for a changed certificate request is pending. The
        files are removed when the frontend-certificates relation is broken.

        This is also reached from the host-info and ingress libraries' own
        handlers (via the `tls` and `scheme` callables), which can run before
        Pebble is up; the files can't be checked then, so report not usable.
        `_reconcile` republishes both once the container is ready.
        """
        return (
            self._relation_created(FRONTEND_CERTIFICATES_RELATION_NAME)
            and self.container.can_connect()
            and self._certificate_is_stored()
            and self._private_key_is_stored()
        )

    def _valid_dns(self, dns: str) -> bool:
        """Return True if the DNS is RFC compliant, False otherwise.

        Args:
          dns: a SANS DNS to validate.
        """
        # Immediately return False if the SANS DNS does not exist or is larger than 253 chars
        if not dns or len(dns) > 253:
            return False

        # Check the labels (each part of the domain between the dots)
        for label in dns.rstrip(".").split("."):
            if len(label) == 0 or len(label) > 63:
                return False
            if not re.fullmatch(r"[A-Za-z0-9-]{1,63}", label):
                return False
            if label.startswith("-") or label.endswith("-"):
                return False

        # If everything is alright, return True
        return True

    def _get_certificate_request_attributes(self) -> CertificateRequestAttributes:
        """Return the attributes of the certificate this charm will request."""
        # Generate CN - try using the unit's FQDN -> HOSTNAME -> IP in that order
        unit_fqdn = socket.getfqdn()
        unit_hostname = socket.gethostname()
        unit_ip = socket.gethostbyname(unit_fqdn)
        for name in (unit_fqdn, unit_hostname, unit_ip):
            if len(name) <= 64:
                generated_common_name = name
                break
        common_name = self.config["frontend-cert-common-name"] or generated_common_name

        # Generate SANS_DNS. By default, request the unit FQDN and the
        # in-cluster service FQDN: in-model clients (e.g. the UI) dial the
        # service FQDN published over temporal-host-info, and a certificate that
        # does not name it fails their hostname verification.
        #
        # Configured names replace the defaults rather than adding to them.
        # Some providers (public CAs, restrictive Vault roles) refuse internal
        # names such as `*.svc.cluster.local` and reject the whole request, so
        # operators using them must be able to request public names only.
        if self._dns_entries:
            sans_dns = set(self._dns_entries)
            if self._in_cluster_fqdn not in sans_dns and self._relation_created(FRONTEND_CERTIFICATES_RELATION_NAME):
                logger.warning(
                    "frontend-cert-sans-dns does not include %s: in-model clients that verify the "
                    "frontend certificate over TLS will fail hostname verification. Add it if your "
                    "certificate provider allows internal names.",
                    self._in_cluster_fqdn,
                )
        else:
            sans_dns = {unit_fqdn, self._in_cluster_fqdn}

        return CertificateRequestAttributes(
            common_name=common_name,
            sans_dns=frozenset(sans_dns),
        )

    @property
    def _in_cluster_fqdn(self) -> str:
        """Return the Kubernetes service FQDN in-model clients use to reach this app."""
        return f"{self.app.name}.{self.model.name}.svc.cluster.local"

    def _check_and_update_certificate(self) -> bool:
        """Check if the certificate or private key needs an update and perform the update.

        This method retrieves the currently assigned certificate and private key associated with
        the charm's TLS relation. It checks whether the certificate or private key has changed
        or needs to be updated. If an update is necessary, the new certificate or private key is
        stored.

        Returns:
            bool: True if either the certificate or the private key was updated, False otherwise.
        """
        provider_certificate, private_key = self.certificates.get_assigned_certificate(
            certificate_request=self._get_certificate_request_attributes()
        )
        if not provider_certificate or not private_key:
            logger.debug("Certificate or private key is not available")
            return False
        if certificate_update_required := self._is_certificate_update_required(provider_certificate.certificate):
            self._store_certificate(certificate=provider_certificate.certificate)
        if private_key_update_required := self._is_private_key_update_required(private_key):
            self._store_private_key(private_key=private_key)
        return certificate_update_required or private_key_update_required

    def _update_certificates_required(self, provider_certificate: ProviderCertificate, private_key: PrivateKey) -> bool:
        """Check if the certificate or private key needs an update.

        This method retrieves the currently assigned certificate and private key associated with
        the charm's TLS relation. It checks whether the certificate or private key has changed
        or needs to be updated.

        Args:
            provider_certificate: the provider certificate given by the TLS provider.
            private_key: the private key given by the TLS provider.

        Returns:
            bool: True if either the certificate or the private key need to be updated,
                  False otherwise.
        """
        if not provider_certificate or not private_key:
            logger.debug("Certificate or private key is not available")
            return False

        certificate_update_required = self._is_certificate_update_required(provider_certificate.certificate)
        private_key_update_required = self._is_private_key_update_required(private_key)

        return certificate_update_required or private_key_update_required

    def _is_certificate_update_required(self, certificate: Certificate) -> bool:
        return self._get_existing_certificate() != certificate

    def _is_private_key_update_required(self, private_key: PrivateKey) -> bool:
        return self._get_existing_private_key() != private_key

    def _get_existing_certificate(self) -> Optional[Certificate]:
        return self._get_stored_certificate() if self._certificate_is_stored() else None

    def _get_existing_private_key(self) -> Optional[PrivateKey]:
        return self._get_stored_private_key() if self._private_key_is_stored() else None

    def _certificate_is_stored(self) -> bool:
        return self.container.exists(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")

    def _private_key_is_stored(self) -> bool:
        return self.container.exists(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")

    def _get_stored_certificate(self) -> Certificate:
        cert_string = str(self.container.pull(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}").read())
        return Certificate.from_string(cert_string)

    def _get_stored_private_key(self) -> PrivateKey:
        key_string = str(self.container.pull(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}").read())
        return PrivateKey.from_string(key_string)

    def _store_certificate(self, certificate: Certificate) -> None:
        """Store certificate in workload."""
        self.container.push(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}", source=str(certificate))
        logger.info("Pushed certificate pushed to workload")

    def _store_private_key(self, private_key: PrivateKey) -> None:
        """Store private key in workload."""
        self.container.push(
            path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}",
            source=str(private_key),
        )
        logger.info("Pushed private key to workload")

    def _delete_certificate(self):
        """Delete certificate from workload container."""
        if self._certificate_is_stored():
            self.container.remove_path(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")
            logger.info("Removed certificate from workload")

    def _delete_private_key(self):
        """Delete private key from workload container."""
        if self._private_key_is_stored():
            self.container.remove_path(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")
            logger.info("Removed private key from workload")


if __name__ == "__main__":
    main.main(TemporalK8SCharm)
