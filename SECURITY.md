# Security Policy — Charmed Temporal Server

## Reporting a Vulnerability

The easiest way to report a security issue is through a [GitHub Private Security Report](https://github.com/canonical/temporal-k8s-operator/security/advisories/new) with a description of the issue, the steps you took to create the issue, affected versions, and, if known, mitigations for the issue.

Alternatively, to report a security issue via email, please email [security@ubuntu.com](mailto:security@ubuntu.com) with a description of the issue, the steps you took to create the issue, affected versions, and, if known, mitigations for the issue.

The [Ubuntu Security disclosure and embargo policy](https://ubuntu.com/security/disclosure-policy) contains more information about what you can expect when you contact us and what we expect from you.

## Supported Versions

Charmed Temporal Server follows Canonical's standard charm support lifecycle, aligned with the Ubuntu LTS base.

| Track | Temporal Server | Ubuntu Base | Status | End of Standard Support |
|-------|----------------|-------------|--------|------------------------|
| 1.23/stable | 1.23.x | Ubuntu 24.04 LTS (Noble) | **Active** | April 2029 |

Older tracks receive no further security updates. Users are encouraged to upgrade to a supported track.

## Product Lifetime and Support Phases

| Phase | Description |
|-------|-------------|
| **Standard Support** | Active bug fixes, security patches, and new features. |
| **Security Maintenance** | Security patches only; no new features or non-critical bug fixes. |
| **End of Life (EOL)** | No further updates. Users must upgrade to a supported track. |

The current `1.23/stable` track is in **Standard Support** and will transition to Security Maintenance prior to its End of Standard Support date.

## Vulnerability Response

Security vulnerabilities are triaged and addressed according to the following severity thresholds, based on NVD CVSS scoring:

| Severity | CVSS Score | Initial Response | Target Remediation |
|----------|-----------|------------------|--------------------|
| **Critical** | 9.0 – 10.0 | Within 24 hours | Within 7 days |
| **High** | 7.0 – 8.9 | Within 72 hours | Within 30 days |
| **Medium** | 4.0 – 6.9 | Within 2 weeks | Within 90 days |
| **Low** | 0.1 – 3.9 | Best effort | Best effort |

All **Critical** and **High** severity vulnerabilities will be remediated or have an active remediation plan in place. Any vulnerability listed in the [CISA Known Exploited Vulnerabilities (KEV) catalog](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) is treated as highest priority regardless of CVSS score.

Vulnerabilities are tracked via [GitHub Security Advisories](https://github.com/canonical/temporal-k8s-operator/security/advisories) and coordinated internally with Canonical's Product Security Incident Response Team (PSIRT).

Note that this charm packages the upstream [Temporal Server](https://github.com/temporalio/temporal). Vulnerabilities in the upstream server itself should be reported to the Temporal project directly; Canonical will track and apply upstream fixes to supported tracks.
