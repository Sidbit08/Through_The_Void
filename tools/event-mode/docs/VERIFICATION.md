# Verification record

No toolkit installation, participant account change, machine-wide policy, resolver change or host firewall activation was performed in the development environment. Configuration/file lifecycle tests use a temporary filesystem and simulated systemd/nft command adapter. Real network tests use a fresh user/network namespace with only loopback interfaces. Firefox tests use a copied browser and disposable profile.

## Executed

- **43 toolkit unit tests passed**, exercising domain boundaries and malicious input rejection, subordinate UID scope, paired CTF address/port exceptions, IPv4/IPv6 rule generation, mode-specific ACLs, supported policy values, inactive/idempotent installation, timer-before-firewall ordering, matching confirmation tokens and deadlines, failed-enable rollback, mode-update rollback, source-list commit/rollback, original bytes/modes/extended attributes, preserving external administrator edits, participant/admin session gating, simulated reboot behavior, AppArmor local-fragment staging/restore, private backup export and uninstall.
- The existing **46 application tests** remained passing. The combined run passed **89 tests**, with no skips or expected failures. Toolkit work does not alter puzzle routes, assets, credentials or event data.
- **18 real isolated integration checks passed** with Squid 6.13, Unbound 1.22 and nftables 1.1.3 on the Debian 13 cloud kernel. They verify approved websites, balanced ordinary browsing, strict unlisted-host refusal, denied hostnames/subdomains at both proxy and DNS, literal-IP/relay rejection, exact CTF address/hostname/port access, unchanged binary media, CONNECT restrictions including an IPv6 CTF exception, real kernel IPv4/IPv6 direct TCP rejection, alternate DNS/DoT and UDP/QUIC denial, continued direct-egress denial with filtering processes stopped, and rollback restoring connectivity while preserving a separate table.
- Packet fixtures are local to the namespace. Baseline TCP/UDP endpoints are reachable before filtering; rejected paths are tested after the actual nft transaction, and connectivity returns after deleting only the owned table. No external web availability is assumed.
- **Firefox ESR 153.5 policy-engine check passed** with a copied browser: all generated policies active; manual proxy locked; DoH locked/off; chatbot locked/off; DevTools allowed. GeckoDriver's explicit system-access flag is confined to that disposable automation session. No normal profile or `/etc` policy was edited.
- Read-only cloud preflight identified Debian 13, the available browsers/existing policies, inactive systemd, missing installed firewall/resolver/proxy commands and absent configured participant account. It correctly reported `safe_to_enable: false`.
- AppArmor 4.1's real userspace parser accepted the standard Unbound profile with the proposed bounded local fragment, using skip-kernel-load/skip-cache flags and extracted distribution includes. It did not load a kernel profile. Actual AppArmor enforcement and integration remain lab checks.
- An offline synthetic-inventory plan generated inspectable files without installation. Python/shell syntax and whitespace checks were performed.

Integration testing found and fixed Squid's nonstandard DNS-port handling, exact IPv6 literal matching, public CTF addresses accidentally falling through to ordinary balanced ports, and test-fixture use of Unbound's reserved `.test` zone. Portable `drop` verdicts avoid reliance on the optional kernel reject expression.

The isolated namespace maps **one UID only**. Real proxy/DNS ACL behavior and real participant packet filtering are exercised in separate phases; this is not a simultaneous multi-UID systemd/PAM deployment test. The fixture necessarily adjusts service names, runtime files and upstream DNS to its isolated environment. Production generation remains separately validated by unit/config checks.

## Evidence and reproduction

Ignored outputs:

- `tools/event-mode/test-results/namespace.json`
- `tools/event-mode/test-results/firefox-policy.json`
- Firefox driver startup diagnostics in the same directory.

Run the tests from repository root:

```sh
.venv/bin/python -m pytest -q tools/event-mode/tests
```

On an authorized disposable Linux test machine with actual Squid/Unbound/nft installed:

```sh
unshare --user --map-current-user --keep-caps --net \
  env CTF_TEST_NETNS=1 python3 tools/event-mode/tests/namespace_check.py
```

The script refuses normal interface layouts and requires the explicit namespace marker. Some distributions disable unprivileged user namespaces. Use an administrator-approved disposable VM instead; never remove the isolation guard or run firewall fixtures on the lab host. The cloud test used userland packages extracted under `/workspace`, with signatures checked against the system Debian archive keyring, package-index SHA-256 checked against signed release metadata, and each package payload checked against the index. No package was installed into the host OS.

The optional Firefox check needs Selenium and geckodriver, and copies the supplied native browser:

```sh
python3 tools/event-mode/tests/browser_policy_check.py \
  --firefox-directory /path/to/native/firefox-directory \
  --executable firefox --driver /path/to/geckodriver --version 153.5
```

## Not executed; mandatory real-PC pilot

- Actual Ubuntu release/package compatibility, including AppArmor, live enterprise policies and browser packaging. The requested distro is Ubuntu; its release is not yet supplied. Snap automatic integration is deliberately unsupported.
- Simultaneous real participant/proxy/DNS UIDs, protected-file write attempts from the actual participant account, and privileged local socket/ACL/polkit review.
- Actual systemd activation/timer cancellation/expiry, service dependency failure propagation, PAM login/cron/user-service integration, administrator recovery, reboot persistence and unconfirmed-boot rollback. These lifecycle paths have simulated tests only.
- Actual AppArmor kernel load/reload and Chrome/Chromium policy UI acceptance/cloud precedence. The supported local-fragment transaction is modeled and syntax-checked at deployment; the cloud machine is not a suitable AppArmor/systemd pilot.
- Real DHCP renewal, IPv6 neighbour discovery, interface changes, lab DNS availability, CTF Windows host/media and required research/tool dependencies. The UID scope is designed to preserve unrelated system networking, but that needs the actual lab network.
- Offline assistants/model review, clean profiles, boot-media controls, personal phones, supervision, multi-PC rollout and complete disable/uninstall verification against the lab baseline.

Failed connections, domain tests, and this test count are not proof that all AI is inaccessible. See the security document for shared-domain features, unknown services, proxies/tunnels, offline models and approved-origin relay limits.
