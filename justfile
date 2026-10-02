# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

set export

[private]
default:
	just --list

# Format the code
format:
	uv tool run --with tox-uv tox -e fmt

# Run linters
lint:
	uv tool run --with tox-uv tox -e lint

# Run unit tests
unit:
	uv tool run --with tox-uv tox -e unit

# Pack the charm under test and the host-info requirer test charm
pack:
	charmcraft pack
	mkdir -p tests/integration/host_info_requirer/lib/charms/temporal_k8s/v0
	cp lib/charms/temporal_k8s/v0/temporal_host_info.py tests/integration/host_info_requirer/lib/charms/temporal_k8s/v0/
	cd tests/integration/host_info_requirer && charmcraft pack
	rm -rf tests/integration/host_info_requirer/lib

# Run integration tests
integration *args: pack
	uv tool run --with tox-uv tox -e integration -- {{args}}

# Print system state to help debug a failed run
get-system-state:
	#!/usr/bin/bash
	df -h
	echo "---"
	juju status --relations --storage --color || true
	echo "---"
	sudo k8s status || true
