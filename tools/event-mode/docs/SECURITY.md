# Enforcement and residual limits

## Scope

The trusted boundary is the Linux host administrator. Participant UIDs, including their configured subordinate UID ranges, are restricted in the host network namespace. Participants must not have sudo, a root password, root-equivalent socket/group access, privileged VMs, firmware control or an uncontrolled alternate boot. The toolkit reports risky groups, sudo rights, subordinate mappings and known local brokers. These checks are conservative, not a vulnerability assessment.

Root privileges or access to an uncontrolled operating system make reliable host-local enforcement unavailable. Do not represent a shell/profile setting as a substitute. The toolkit does not silently change existing participant accounts; an administrator must resolve reported issues, preferably by provisioning separate standard accounts.

## Network design

- The sole participant web listener is localhost Squid. `ctfproxy` may reach its filtering resolver, exact CTF IP/port pairs and ordinary public TCP 80/443 destinations. It may not generally reach loopback, private LAN, metadata, multicast or other special ranges. Configured CTF addresses are explicitly denied on their other ports even when public.
- Squid separately validates the requested hostname, denied/approved domain lists, literal-IP exceptions and CONNECT port restrictions. Exact CTF host/IP/port ACLs precede its general private-address and literal-IP denial. Shared cloud IPs are unsuitable as dedicated CTF exceptions.
- `ctfdns` may send DNS only to explicit upstream IPs on UDP/TCP 53 and return loopback DNS responses. Its only capability is binding port 53, granted in its systemd unit. It cannot generally browse the internet.
- Participants may connect to the loopback proxy and filtering resolver. Direct CTF access is off by default. Enabling it permits only explicit address/port pairs and makes the organizer responsible for ensuring those endpoints cannot relay arbitrary traffic.
- No participant `established,related` shortcut is used: existing direct connections do not become a permanent bypass after activation. IPv4 and IPv6 use the same `inet` policy. UDP web/QUIC, direct DNS/DoT and other direct connections are denied.
- Unrelated administrator/system UIDs are accepted by this table. DHCP and IPv6 neighbour discovery remain system/kernel functions. This is not a machine-wide internet ban.
- Existing UFW/firewalld/nftables management or foreign rules cause a refusal. The toolkit never flushes the global ruleset, changes router/DHCP settings, or tries to win a race against another firewall manager.

The system resolver remains intact for other accounts/services. Ordinary system-stub DNS paths are denied for participant sockets; selected D-Bus resolver/administration brokers are also denied per participant. NSS/Varlink or other system brokers can still resolve names in some stacks. Learning an IP is not a web-access bypass: direct participant connections and proxy literal-IP requests remain restricted, and the proxy checks destinations independently. Do not claim that every possible name-resolution path is intercepted.

Unix-domain local brokers are outside IP filtering. Known root-equivalent groups/socket ACLs are checked, and participant polkit actions are denied. Custom enterprise brokers, writable privileged scripts, VM management, setuid tools and local vulnerabilities require lab review. Rootless-container subordinate UID ranges are included in the nftables set; overlapping/aliased privileged identities are refused.

## What neither mode proves

Balanced browsing plus a finite hostname denylist cannot guarantee zero AI. Unknown/new services, alternate API endpoints, user-hosted models, web proxies, VPN-over-HTTPS and arbitrary HTTPS tunnels can use otherwise permitted destinations. Blocking DNS/DoT ports and familiar DoH hosts does not block all HTTPS tunnelling. There is no comprehensive “top 100” claim.

Strict mode rejects unapproved proxy hostnames and direct egress, but an approved origin can contain an AI feature, become compromised, offer a relay, accept domain-fronted requests, or load an on-device model. Hostname allowlisting is not a proof about all encrypted content. Allowing an entire parent domain allows its subdomains; choose narrow hosts and review changes/dependencies.

DNS cannot distinguish Google search from AI features on the same hostname. Browser-only URL policies or result preferences affect cooperating browsers only and are not universal enforcement. No Google URL parameter or cosmetic extension is claimed to guarantee AI-free search. Strict default lists omit search engines; use reviewed references/tools and an organizer-operated search desk.

Likewise, publishing the CTF's answer keys in an accessible source repository defeats puzzle secrecy independently of this toolkit. Keep the application repository/ZIP private; copy only the standalone participant toolkit to lab PCs. Blocking all of a shared hosting service is not a substitute.

Browser policies do not govern downloaded/modified browsers, command-line clients or arbitrary executables. Strict network rules apply independently, but offline programs require no network. Model files may be renamed, embedded or already cached. No scan proves their absence. Personal phones and alternate boot media are outside this toolkit.

## Offline-model and machine review

Use clean event accounts/profiles and a reviewed software image. Preflight reports metadata for known assistant executables/services; inspect packages, desktop launchers, user services and running programs as the administrator. An optional filename-only review of a selected account can help identify candidates:

```sh
sudo find /home/ctfplayer -type f \( -iname '*.gguf' -o -iname '*.ggml' -o -iname '*.onnx' -o -iname '*.safetensors' \) -print
sudo systemctl status ollama local-ai llama-server
```

These commands do not delete anything or prove absence. Record original service settings before separately approved assistant disable/removal work. Keep necessary terminal, image/audio, ASCII and Morse tools available. Use physical supervision and lab controls for firmware, boot media and personal devices; the browser cannot enforce those policies.

## Rollback, persistence and privacy

Activation snapshots original file bytes/metadata, validates generated configs, then arms a root systemd timer before applying the owned nft table. Explicit administrator confirmation cancels it only within the recorded deadline. Confirmation checks active services and table ownership; participant/browser tests are still the administrator's responsibility. An unconfirmed reboot restores the preceding configuration.

Confirmed boot reloads the owned firewall before networking/display-manager ordering targets. Participant-only PAM session gates in the standard interactive/noninteractive stacks refuse participant sessions when the expected table/signature is missing; other account names pass. This is baseline-specific and requires a real PAM/boot pilot. Confirmed service failures leave the nft table in place; DNS/proxy units are bound dependencies. An unconfirmed timeout rollback deliberately restores the previous state and must be supervised.

Standard AppArmor service profiles with recognized local includes receive only bounded runtime/config permissions, validated offline and reloaded without disabling AppArmor. Other layouts are unsupported. Existing policies and metadata restore on normal disable/rollback; external concurrent edits cause a stop rather than an overwrite. Original files can be exported privately for recovery review.

There is no TLS bumping or custom CA, and no proxy access/query/page-content logging. Daemon startup/failure diagnostics, root-only configuration snapshots and test status records remain. Participants cannot modify protected configuration; an administrator can always change or remove these controls.
