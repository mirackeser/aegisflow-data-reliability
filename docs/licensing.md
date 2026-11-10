# Licensing

Project-owned code, documentation and synthetic fixtures in this repository are licensed under Apache-2.0. See LICENSE for the full, unmodified terms and NOTICE for attribution. The package metadata uses the same SPDX expression and includes both files in distributions.

Apache-2.0 was selected as a single permissive license with an explicit contributor patent grant. The project does not offer an alternative MIT grant. License scope is limited to rights the contributors can grant: third-party quotations, references, trademarks and dependencies retain their original terms. External websites linked in the architecture archive are not relicensed. The previous supply/SLA repository is separate and its history and licensing are unchanged.

Contributions intentionally submitted for inclusion are under Apache-2.0 unless explicitly stated otherwise, consistent with section 5. Contributors must have the right to submit their work. Changes to copied third-party material must retain applicable notices and change notices.

Repository visibility is public, as configured by the repository owner. This does not change the Apache-2.0 license or publish a versioned release.

References: https://www.apache.org/licenses/LICENSE-2.0 and https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license-and-license-files

The runtime depends on separately installed jsonschema 4.26.0 ([upstream metadata](https://pypi.org/project/jsonschema/4.26.0/), MIT). It and its transitive dependencies retain their upstream licenses; their source is not vendored into this Apache-2.0 repository. Build/test/security tooling is likewise installed separately.

The optional test extra uses cryptography 50.0.2 to generate short-lived certificates and keys in temporary directories. It is separately installed under its upstream Apache-2.0 OR BSD-3-Clause terms; no private key or certificate is vendored. Production TLS uses Python ssl/OpenSSL and introduces no new runtime dependency.
