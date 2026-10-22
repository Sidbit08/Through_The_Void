# CTF Event Mode

Reversible controls for administrator-managed Linux participant PCs. This is independent of the Windows CTF server and needs no router, DHCP or LAN changes. **Participants must have no sudo/root access or equivalent privileges.** A user-level script cannot reliably enforce these restrictions.

Copy only this standalone toolkit to participant PCs. Keep the CTF application's source, assets, answer keys and organizer documents on the organizer's machine.

Balanced mode permits ordinary HTTP/HTTPS browsing while blocking a starter list of known AI hostnames. **It cannot guarantee zero AI access.** Strict mode permits approved hostnames and exact CTF endpoints only. Approved sites can themselves contain AI or relay traffic; neither mode proves that all AI is inaccessible.

## Baseline and boundaries

- Ubuntu/Debian, systemd, nftables, Squid 5/6/7 and Unbound. Ubuntu was requested; its exact release is still needed before deployment. Real service/packet tests ran on Debian 13 tooling in isolated namespaces, not a physical Ubuntu lab PC.
- Native Firefox/Firefox ESR or Chromium/Chrome 128+. **Snap browser integration is unsupported and activation refuses it.** On stock Ubuntu, have the lab administrator provision a supported native browser using [Mozilla's installation documentation](https://support.mozilla.org/en-US/kb/install-firefox-linux), or arrange a reviewed Snap integration before deployment. Do not remove an enterprise browser blindly.
- No active/enabled UFW, firewalld or nftables persistence manager, and no foreign nftables tables. Existing management is detected and activation refuses it. Choose an approved clean pilot or obtain an IT-reviewed integration; never flush/disable a lab firewall just to make preflight pass.
- No TLS interception, custom CA, page-content capture, query logging or proxy access logging. Developer tools and View Source remain available. User files/models are not deleted.
- Proxy: `127.0.0.1:3129`. Filtering DNS: **`127.0.0.2:53`**. Squid uses that resolver. The system resolver and `/etc/resolv.conf` remain unchanged. The DNS unit alone gets `CAP_NET_BIND_SERVICE` to bind port 53.
- An `inet ctf_event_mode` table scopes output rules to participant UIDs (including assigned subordinate UIDs), `ctfproxy`, and `ctfdns`. Other system/admin traffic, DHCP and neighbour discovery are outside these UID rules. Direct participant TCP/UDP, IPv4/IPv6, DNS/DoT and QUIC paths are denied. Web and network tools must use the proxy.

Read [security and residual limits](docs/SECURITY.md), [policy verification](docs/POLICIES.md), and [test evidence](docs/VERIFICATION.md) before a pilot.

## Read-only preflight and offline plan

From this directory:

```sh
python3 -I ctf_event.py preflight
python3 -I ctf_event.py plan --config examples/event.json \
  --inventory examples/inventory.json --output /tmp/ctf-event-plan
```

The example inventory is synthetic and is never accepted by `enable`. The plan writes files only in the requested output directory. Review `plan.json`, nftables/Squid/Unbound files and generated browser JSON. A preflight JSON result with `safe_to_enable: false` is not a readiness pass. Root preflight is needed to inspect firewall and sudo rights completely.

## One-PC pilot

Use a supervised spare PC/VM first. Keep an administrator session open and a separate root/sudo console available. Do not pilot during an active event.

1. Inspect the actual PC read-only. Have IT resolve every privilege, firewall, packaging and policy blocker. A separate ordinary event account is preferable. Creating one is an explicit administrator action, for example `sudo adduser ctfplayer`; the toolkit never changes existing participant accounts or their groups.
2. During an approved maintenance window install prerequisites. Package installation may start vendor services; review them and repeat preflight. Do not alter existing system DNS/firewall services blindly.

```sh
sudo apt-get update
sudo apt-get install python3 squid unbound nftables iproute2 acl sudo
cp examples/event.json examples/pilot.json
nano examples/pilot.json
sudo python3 -I ctf_event.py preflight --config examples/pilot.json
```

Set `participants` to the real standard account, `ctf_servers` to the Windows host's exact IP/ports, and `dns_upstreams` to actual reachable upstream DNS IPs (not a local system stub). DNS upstreams can be exact approved LAN DNS addresses. Review both domain lists and required site dependencies. Do not configure the CTF endpoint as a web proxy/relay; addresses must be dedicated and stable.

3. Install the toolkit. This creates dedicated service identities and files, **without starting restrictions**:

```sh
sudo sh install.sh --config examples/pilot.json
sudo ctf-event preflight --config /etc/ctf-event-mode/event.json
sudo ctf-event validate --config /etc/ctf-event-mode/event.json \
  --output /root/ctf-event-plan --kernel
sudo ctf-event enable --mode strict --rollback-seconds 300
```

Enable validates both daemon configs, kernel syntax, existing browser policy compatibility and supported AppArmor local overrides before activation. It backs up bytes, ownership, modes, timestamps and extended attributes in root-only `/var/lib/ctf-event-mode/`. A **five-minute rollback is armed before firewall activation**. The printed confirmation token is unique to this activation. Do not close the recovery console.

4. Restart participant browsers. As the participant, inspect `about:policies` or `chrome://policy` for active settings and errors. Test the CTF entry/assets, permitted sites, denied sites, extensions, DevTools, View Source, audio/image saving and required tools. Example participant diagnostic:

```sh
python3 participant-check.py --mode strict \
  --ctf-url http://192.168.1.50:8080/entry \
  --approved-url https://docs.python.org/ \
  --unlisted-url https://example.net/
```

For terminal tools supporting a web proxy:

```sh
export http_proxy=http://127.0.0.1:3129
export https_proxy=http://127.0.0.1:3129
export no_proxy= NO_PROXY=
curl --proxy http://127.0.0.1:3129 --noproxy '' http://192.168.1.50:8080/entry
```

No proxy environment is installed globally. Offline puzzle tools remain available. Tools without proxy support cannot use the network unless an exact CTF exception is explicitly configured with `direct_ctf: true` and reviewed for relay risk.

5. Inspect status, then **explicitly confirm** only after successful participant checks:

```sh
sudo ctf-event status
sudo ctf-event diagnose
sudo ctf-event confirm TOKEN_PRINTED_BY_ENABLE
```

Without confirmation, prior configuration restores automatically. An unconfirmed reboot also restores the prior state. After confirmation, reboot the pilot and repeat participant checks. A participant-only PAM session gate checks the owned firewall signature before interactive and standard noninteractive sessions; administrator accounts remain outside it. Test this on the actual PAM/login stack.

6. Test failure behavior under supervision:

```sh
sudo systemctl stop ctf-event-proxy.service
# Participant: denied/direct connections must remain unavailable.
sudo systemctl restart ctf-event-proxy.service
sudo systemctl stop ctf-event-dns.service
# BindsTo stops the proxy; participant egress must not become unrestricted.
sudo systemctl restart ctf-event-dns.service ctf-event-proxy.service
```

## Change modes or add approved/denied sites

Configuration and lists are root-managed. Stage a complete set privately; validate before applying:

```sh
sudo install -d -m 700 /root/ctf-stage
sudo cp /etc/ctf-event-mode/event.json /root/ctf-stage/event.json
sudo cp /etc/ctf-event-mode/*list.txt /root/ctf-stage/
sudoedit /root/ctf-stage/event.json
sudoedit /root/ctf-stage/strict-allowlist.txt
```

In the staged JSON set `allowlist` and `denylist` to the corresponding `/root/ctf-stage/` filenames. Add plain ASCII/IDNA hostnames, one per line; `example.org` matches that hostname and its subdomains, not `notexample.org`. No URL paths, wildcard syntax, literal IPs or shared CDN-wide blocks. Use the denylist for AI sites; record provenance for additions in your administrator change record. Overlapping allow/deny domains are refused.

```sh
sudo ctf-event validate --config /root/ctf-stage/event.json \
  --output /root/ctf-stage/plan --kernel
sudo ctf-event enable --config /root/ctf-stage/event.json --mode balanced --rollback-seconds 300
# Repeat participant checks, then confirm the NEW printed token.
```

Validated settings/lists are committed to the installed configuration with the activation. Immutable generations and an atomic current-generation link support rollback. Each activation gets its own timer. Repeating an already confirmed, unchanged enable is a no-op.

## Disable, rollback and complete uninstall

```sh
sudo ctf-event rollback                 # Undo the pending activation.
sudo ctf-event disable                  # Restore original browser/PAM/polkit/D-Bus/AppArmor configuration.
sudo ctf-event uninstall --archive /root/ctf-event-archive-$(date +%Y%m%d-%H%M%S)
```

Disable removes only the owned nftables table and stops/disables the three toolkit services. Uninstall archives records privately and removes toolkit files, units and identities it created. Dependencies installed separately by the administrator remain installed; existing vendor services are not uninstalled or reset.

If an administrator/management agent edited a managed file during the event, restore refuses to overwrite that edit. Keep the recovery console, inspect `status`, and export originals for a reviewed merge:

```sh
sudo ctf-event export-backups --destination /root/ctf-originals-review
sudo diff -u /root/ctf-originals-review/etc/pam.d/common-session /etc/pam.d/common-session
```

Do not replace PAM files blindly. An emergency `sudo nft delete table inet ctf_event_mode` removes only this toolkit's egress restriction; browser policies and the participant login gate still need proper restoration. Administrator network access remains outside the participant UID rules throughout.

## Multi-PC rollout and event day

- Pilot on the actual Ubuntu release/browser packaging, including service-stop, reboot and disable/restore. Have IT sign off the account and policy inventory before rolling out.
- Deploy the same reviewed source/list revision; inspect each PC's actual UIDs, subordinate UIDs, privileges, DNS, firewall and policies. Do not copy another PC's generated UID rules or private state directory.
- Confirm the Windows CTF host's reserved IP/port and reachability; use unique participant CTF credentials. Never allow the entire LAN as an exception.
- Use clean event accounts/profiles. Review installed assistants, extensions, model files and privileged local brokers; do not delete user files. Control boot media/firmware and supervise personal phones.
- Before participants arrive, verify `status`, confirmed state, browser policies, a representative allowed/denied site, CTF media and terminal tools. Keep recovery access and private backups available.
- After the event disable/uninstall on each PC, verify original browsing/login behavior and archive restoration records. Firewall and account inventories must match the approved pre-event baseline.

The organizer-operated search desk is the strict alternative for research that cannot be confined to approved reference/tool hosts. Browser search parameters, cosmetic extensions and page URL filters are supplementary only; they do not make Google universally AI-free.
