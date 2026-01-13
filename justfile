# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
[private]
default:
	just --list

[private]
clean-mock-charm-libs:
	rm -rf tests/integration/host_info_requirer/lib/charms/temporal_k8s

setup-integration: (clean-mock-charm-libs)
	mkdir -p tests/integration/host_info_requirer/lib/charms/temporal_k8s
	cp -r lib/charms/temporal_k8s tests/integration/host_info_requirer/lib/charms/temporal_k8s
