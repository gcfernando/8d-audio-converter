# Windows code signing

Audio8D currently has no configured trusted signing identity. The proposed no-cost route is [SignPath Foundation's free program for qualifying open-source projects](https://signpath.org/); enrollment has not been submitted and no provider approval exists. No approved SignPath project or active provider is claimed. Automated releases remain unsigned until an approved identity is configured and signing is explicitly enabled. Audio8D remains free to use without buying a certificate. Application version 1.0.0 is unchanged by signing.

Authenticode can establish a publisher identity and protect signed executable integrity. It does not guarantee SmartScreen reputation or a warning-free download. Never disable Windows protection to make a test pass. See [Microsoft's SmartScreen explanation](https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/) and [Artifact Signing setup](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart).

## Apply for free SignPath signing

1. Read the [Foundation conditions](https://signpath.org/terms), then [apply for a free subscription](https://signpath.org/apply) with this repository and its release/download information. The Foundation decides eligibility; do not enable signing before approval.
2. After approval, link `https://github.com/gcfernando/8d-audio-converter` through the GitHub trusted-build integration. Require reviewed `main` builds and human release approval. Have the provider approve a configuration restricted to `Audio8D.exe` and `audio8d-cli.exe`, including their product/version metadata and how the PyInstaller frontends are built. The bundled Python, FFmpeg and other upstream binaries are not submitted for signing with this project's identity.
3. Configure the following real approved identifiers. All are Actions repository variables except the submitter token, which is a repository secret.

| Setting | Value |
| --- | --- |
| `AUDIO8D_SIGNING_PROVIDER` | Exactly `signpath`; absent/empty defaults to the existing `azure` route for compatibility |
| `SIGNPATH_ORGANIZATION_ID` | Approved SignPath organization ID |
| `SIGNPATH_PROJECT_SLUG` | Approved project slug for this repository |
| `SIGNPATH_SIGNING_POLICY_SLUG` | Approved release-signing policy slug |
| `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG` | Approved artifact configuration slug restricting the two frontend files |
| `SIGNPATH_API_TOKEN` **secret** | Token with submitter permission for the approved project/policy |
| `AUDIO8D_SIGNING_PUBLISHER` | Exact approved certificate subject distinguished name; do not guess its value |
| `AUDIO8D_SIGNING_ENABLED` | Exactly `true`, set **last** after approval/configuration; empty or `false` keeps unsigned publication |

4. Approve each release request in SignPath. After both native build/test jobs succeed, the main-only signing job submits the two verified frontends through an uploaded GitHub Actions artifact. It waits up to 1,800 seconds for completion; denial, timeout or invalid output blocks publication without an unsigned fallback. The returned files still undergo Windows trust/content verification and the frozen-GUI check before publication. See [SignPath's GitHub integration](https://docs.signpath.io/trusted-build-systems/github).

## Code signing policy

**Status: enrollment not submitted; proposed policy only.** No release is represented as SignPath-signed until approval, configuration and a successful verified run exist. The proposed author, reviewer and release-signing approver is [gcfernando](https://github.com/gcfernando), the repository maintainer; confirm these assignments during enrollment. Before activation, the maintainer must confirm MFA for all participants' GitHub/SignPath access and the required review/approval process. This document does not attest to existing MFA settings or completed approvals. Provider credit will be added only after approval and activation.

### Privacy and network behavior

Ordinary conversion processes selected audio with local FFmpeg; the app has no configured telemetry or audio-upload service. Installing or repairing the optional singer add-on explicitly invokes pip and downloads dependencies from the package sources configured for that Python installation. Choosing centered vocals can also download Demucs model weights on first use; separation runs locally on a temporary WAV. Help/download links open a browser on request. Consequently, this application is not described as having no network activity. See the [PyPI privacy notice](https://policies.python.org/pypi.org/Privacy-Notice/) when using PyPI and [Meta Open Source privacy policy](https://opensource.fb.com/legal/privacy/) for its services; custom package sources have their own policies. CI signing sends release frontends and build-origin metadata to the provider, not an end user's music. Local data/add-on removal is described in the [user guide](user-guide.md#guide-configuration-and-reference).

## Configuration

The [release workflow](https://github.com/gcfernando/8d-audio-converter/actions/workflows/release.yml) retains **Azure** Artifact Signing as an optional alternative using GitHub OIDC, with no certificate private key stored in GitHub. It is not required to use Audio8D or apply to the free Foundation program. Microsoft's [current Public Trust eligibility](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart) permits individual enrollment only in the US and Canada; an individual in Sweden is not currently eligible. EU organization eligibility is separate.

For an already eligible Azure account, configure an existing public-trust certificate profile and a federated identity with issuer `https://token.actions.githubusercontent.com`, audience `api://AzureADTokenExchange` and exact subject `repo:gcfernando/8d-audio-converter:ref:refs/heads/main`. Grant only the Artifact Signing Certificate Profile Signer role scoped to that profile. Only this provider job uses OIDC; SignPath uses its scoped submitter secret. Pull requests and manual workflow runs cannot sign or publish releases.

Set these repository Actions variables only after the identity, federation and permissions are ready:

| Variable | Value |
| --- | --- |
| `AUDIO8D_SIGNING_ENABLED` | Exactly `true` to require signed Windows publication; absent, empty or `false` keeps unsigned publication; other values fail validation |
| `AUDIO8D_SIGNING_PROVIDER` | Exactly `azure`, or absent/empty for compatibility with existing Azure configuration; only `azure` and `signpath` are accepted |
| `AZURE_CLIENT_ID` | Signing application's client GUID |
| `AZURE_TENANT_ID` | Tenant GUID |
| `AZURE_SUBSCRIPTION_ID` | Existing subscription GUID |
| `AUDIO8D_SIGNING_ENDPOINT` | Regional HTTPS `*.codesigning.azure.net` endpoint |
| `AUDIO8D_SIGNING_ACCOUNT` | Existing signing account name |
| `AUDIO8D_SIGNING_PROFILE` | Existing public-trust certificate profile name |
| `AUDIO8D_SIGNING_PUBLISHER` | Exact certificate subject distinguished name, including its formatting |

When enabled, missing configuration, denied access, signing failure, unexpected publisher, missing timestamp, invalid Windows trust or changed application content prevents publication. The workflow never substitutes the unsigned Windows package after an enabled signing job fails. Both platform builds and tests must succeed first. Linux packaging and executables are unchanged and unsigned.

## Verification and artifacts

Only `Audio8D/Audio8D.exe` and `Audio8D/audio8d-cli.exe` are signed after a provider is approved and enabled. Bundled Python libraries and third-party programs, including FFmpeg, keep their original bytes and licenses. The Azure Windows job has OIDC permission; the SignPath Windows job uses its submitter token. The separate publication job alone can write GitHub releases.

The Python standard-library helper checks the unsigned archive checksum, all ZIP CRCs, safe Windows member paths and ordinary file types. It rejects traversal, duplicate or case-colliding names, alternate streams, links and encrypted entries. A snapshot outside the extracted package records every original file's size and SHA-256 hash. It must be retained until finalization.

After signing, only the two frontends may differ. For both, Windows PowerShell `Get-AuthenticodeSignature` must report a valid embedded Authenticode signature, a timestamp certificate, the exact configured publisher and a non-self-issued certificate with the code-signing enhanced key usage. The content check retains all PyInstaller overlay bytes and omits only the PE checksum, security-directory entry and aligned EOF certificate table. At most seven newly appended zero alignment bytes are allowed. No packaged executable is run by the signing helper.

The repackaged ZIP preserves original file attributes. `Audio8D/signing-manifest.json` records the unsigned archive hash, original and signed frontend hashes, normalized content hashes, publisher, signer thumbprints, timestamp subjects and final hashes of every other packaged file. The manifest does not hash itself. The final ZIP receives a fresh SHA-256 sidecar; publication also produces `SHA256SUMS.txt` for both platform ZIPs.

The Linux publisher's `--signed-windows` guard verifies the signing manifest, full package file coverage, CRCs and hashes. It consumes the successful Windows job's evidence and does **not** perform Windows cryptographic trust verification on Linux. Release notes distinguish signed Windows frontends, unchanged third-party binaries and unsigned Linux downloads.

For local verification on Windows with Python 3.12 and PowerShell 7:

```powershell
python packaging/sign_release.py stage Audio8D-1.0.0-windows-x86_64.zip artifacts/signing-payload --checksum Audio8D-1.0.0-windows-x86_64.sha256
# An authorized trusted signing service must now sign and timestamp exactly the two frontends.
python packaging/sign_release.py finalize artifacts/signing-payload artifacts/signed/Audio8D-1.0.0-windows-x86_64.zip --publisher 'EXACT CERTIFICATE SUBJECT'
```

The focused tests use synthetic PE structures and mocked signature evidence. These fixtures are not usable certificates and do not demonstrate a live Azure signing operation. Validate an actual signed download on a clean Windows system after configuring a trusted identity; signing alone does not establish application quality or release readiness.
