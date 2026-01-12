[private]
default:
	just --list

[private]
clean-mock-charm-libs:
	rm -rf tests/integration/host_info_requirer/lib/charms/temporal_k8s

setup-integration: (clean-mock-charm-libs)
	cp -r lib/charms/temporal_k8s tests/integration/host_info_requirer/lib/charms/temporal_k8s
