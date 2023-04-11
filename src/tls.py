# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Temporal TLS configuration."""

import logging

from charms.tls_certificates_interface.v2.tls_certificates import (
    CertificateAvailableEvent,
    TLSCertificatesRequiresV2,
    generate_csr,
    generate_private_key,
)
from ops import framework
from ops.charm import RelationJoinedEvent
from ops.model import ActiveStatus, WaitingStatus

# from literals import TLS_RELATION, TRUSTED_CA_RELATION, TRUSTED_CERTIFICATE_RELATION
from utils import push_to_file

logger = logging.getLogger(__name__)

CHARM_CONFIG_PATH = "/etc/temporal/tls"


class TemporalTLS(framework.Object):
    def __init__(self, charm):
        """Handler for managing the client and unit TLS keys/certs."""
        super().__init__(charm, "tls")
        self.charm = charm
        self.cert_subject = "temporal-k8s"
        self.certificates = TLSCertificatesRequiresV2(self.charm, "certificates")
        self.framework.observe(getattr(self.certificates.on, "install"), self._on_install)
        self.framework.observe(charm.on.certificates_relation_joined, self._on_certificates_relation_joined)
        self.framework.observe(getattr(self.certificates.on, "certificate_available"), self._on_certificate_available)
        # self.framework.observe(charm.on.certificates_relation_broken, self._on_certificates_relation_broken)

    def _on_install(self, event) -> None:
        if not self.charm._state.is_ready():
            event.defer()
            return

        # private_key_password = b"banana"
        private_key = generate_private_key()
        # self.charm._state.private_key_password = private_key_password.decode("utf-8")
        self.charm._state.private_key = private_key.decode("utf-8")

    def _on_certificates_relation_joined(self, event: RelationJoinedEvent) -> None:
        if not self.charm._state.is_ready():
            self.charm.model.unit.status = WaitingStatus("Waiting for peer relation to be created")
            event.defer()
            return

        # private_key_password = b"banana"
        private_key = generate_private_key()
        # self.charm._state.private_key_password = private_key_password.decode("utf-8")
        self.charm._state.private_key = private_key.decode("utf-8")

        # private_key_password = self.charm._state.private_key_password
        private_key = self.charm._state.private_key
        csr = generate_csr(
            private_key=private_key.encode(),
            # private_key_password=private_key_password.encode(),
            subject=self.cert_subject,
            sans_dns=["temporal-k8s"],
        )

        self.charm._state.csr = csr.decode()

        self.certificates.request_certificate_creation(certificate_signing_request=csr)

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        if not self.charm._state.is_ready():
            self.charm.model.unit.status = WaitingStatus("Waiting for peer relation to be created")
            event.defer()
            return

        self.charm._state.certificate = event.certificate
        self.charm._state.ca = event.ca
        self.charm._state.chain = event.chain

        container = self.charm.model.unit.get_container(self.charm.name)
        if not container.can_connect():
            event.defer()
            return

        push_to_file(container=container, content=self.charm._state.private_key, path=f"{CHARM_CONFIG_PATH}/server.key")
        push_to_file(container=container, content=self.charm._state.ca, path=f"{CHARM_CONFIG_PATH}/ca.pem")
        push_to_file(container=container, content=self.charm._state.certificate, path=f"{CHARM_CONFIG_PATH}/server.crt")

        self.charm._update(event)
        self.charm.model.unit.status = ActiveStatus()

    # def _on_certificates_relation_broken(self, event: RelationJoinedEvent) -> None:
    #     if not self.charm._state.is_ready():
    #         self.charm.model.unit.status = WaitingStatus("Waiting for peer relation to be created")
    #         event.defer()
    #         return

    #     container = self.charm.model.unit.get_container(self.charm.name)
    #     if not container.can_connect():
    #         event.defer()
    #         return

    #     if container.exists('/etc/temporal/tls/server.key'):
    #         container.remove_path(path=f"{CHARM_CONFIG_PATH}/server.key")

    #     if container.exists('/etc/temporal/tls/ca.pem'):
    #         container.remove_path(path=f"{CHARM_CONFIG_PATH}/ca.pem")

    #     if container.exists('/etc/temporal/tls/server.crt'):
    #         container.remove_path(path=f"{CHARM_CONFIG_PATH}/server.crt")

    #     self.charm._state.certificate = ""
    #     self.charm._state.ca = ""
    #     self.charm._state.chain = ""
