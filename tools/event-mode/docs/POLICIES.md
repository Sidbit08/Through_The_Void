# Browser policy verification

Reviewed 2026-10-22. Baseline policy names are checked against Mozilla's official policy templates and Chromium's official policy-definition YAML. Firefox's shipped ESR 153.5 schema and a disposable browser policy-engine test provide additional evidence. Version support is distinct from successful deployment on the lab's package/profile.

## Firefox / Firefox ESR

Official references:

- [Mozilla policy reference source](https://github.com/mozilla/policy-templates/blob/master/docs/index.md). That file warns that documentation is moving to the [administrator reference](https://firefox-admin-docs.mozilla.org/reference/policies/). The implementation was also checked against the policies-schema.json shipped in Firefox ESR 153.5.
- [Example policy schema](https://github.com/mozilla/policy-templates/blob/master/linux/policies.json).

Generated settings:

| Policy | Setting and purpose |
| --- | --- |
| `Proxy` | Manual HTTP/HTTPS proxy, locked, empty configured bypass list |
| `DNSOverHTTPS` | `Enabled: false`, `Locked: true` |
| `ExtensionSettings` | Default installation mode `blocked`; explicit approved IDs may be `allowed` |
| `DisableDeveloperTools` | `false`; DevTools and View Source remain usable |
| `GenerativeAI` | Firefox 144+ or ESR 140.4+: `Chatbot: false`, `Locked: true` |
| `Preferences` | Older supported versions: lock `browser.ml.chat.enabled` false |

Not all browser AI features are covered. Broad `AIControls` blocking can remove downloaded on-device models. The toolkit deliberately does not apply it or the broad GenerativeAI default to existing profiles, because user files must not be deleted. Use clean reviewed event profiles and separately review offline assistants/models. Existing conflicting policy or AIControls settings require administrator integration, rather than being overwritten.

The disposable Firefox ESR check observed the generated active policies, locked manual proxy, locked/disabled DoH, locked/disabled chatbot and allowed DevTools. It copied the browser and used a fresh profile; no machine-wide Firefox policy was changed. The lab must still inspect `about:policies`, policy errors, extensions and actual network behavior on its installed version.

## Chromium / Google Chrome

Official source definitions:

- [ProxySettings](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/Miscellaneous/ProxySettings.yaml): fixed servers and `ProxyBypassList`.
- [DnsOverHttpsMode](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/Miscellaneous/DnsOverHttpsMode.yaml): `off` disables DoH, supported since desktop version 78.
- [QuicAllowed](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/Miscellaneous/QuicAllowed.yaml): false.
- [ExtensionSettings](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/Extensions/ExtensionSettings.yaml): blocked default and explicit approved IDs.
- [DeveloperToolsAvailability](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/Miscellaneous/DeveloperToolsAvailability.yaml): value 1 permits developer tools. Current source retrieved and verified; recheck the installed browser's policy page during the pilot.
- [AIModeSettings](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/GenerativeAI/AIModeSettings.yaml): value 1 disables address-bar/new-tab AI Mode integrations, supported since desktop 138. This does not remove AI features on Google web pages.

`ProxyBypassList: "<-loopback>"` removes Chromium's implicit loopback bypass. The network policy independently prevents direct connections. Older supported Chromium versions omit AI Mode settings they do not recognize.

Verified traps, deliberately excluded:

- [GenAiDefaultSettings](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/GenerativeAI/GenAiDefaultSettings.yaml) is marked **cloud_only**; local JSON is not claimed to enforce it.
- [GenAILocalFoundationalModelSettings](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/GenerativeAI/GenAILocalFoundationalModelSettings.yaml) explicitly deletes an already downloaded model when disabled, so it is not generated.
- [GeminiSettings](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/GenerativeAI/GeminiSettings.yaml) currently lists Linux as future support; it is not applied as a claimed Linux control.

Actual Chrome/Chromium policy UI acceptance and cloud-management precedence remain a target-PC check. Conflicting local JSON settings refuse activation. Review enterprise enrollment and cloud policies with IT; the toolkit does not override them silently.

## Packaging and operational checks

Native Firefox policy paths and Chromium/Chrome managed directories are detected. Existing unrelated JSON keys are retained. Conflicting proxy, extension or developer-tool policy fails before activation. Unknown versions/Snap packaging refuse automatic enable.

Policy support does not govern arbitrary browsers or command-line applications. The participant UID firewall and proxy destination ACLs remain the independent network boundary. Restart installed browsers, inspect their policy pages/errors, and test actual participant access before confirming the rollback timer.
