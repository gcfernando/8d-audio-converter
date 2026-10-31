# Windows code signing

Audio8D currently has no configured trusted signing identity. Automated releases remain unsigned until an administrator provisions a public-trust signing account and explicitly enables the optional job. No certificate or Azure account is created by this repository. Application version 1.0.0 is unchanged by signing.

Authenticode can establish a publisher identity and protect signed executable integrity. It does not guarantee SmartScreen reputation or a warning-free download. Never disable Windows protection to make a test pass. See [Microsoft's SmartScreen explanation](https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/) and [Artifact Signing setup](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart).

## Configuration

The [release workflow](https://github.com/gcfernando/8d-audio-converter/actions/workflows/release.yml) uses Azure Artifact Signing through GitHub OIDC, with no certificate private key stored in GitHub. Check the provider's current eligibility requirements before enrolling; individual and organization eligibility differ. An administrator must configure an existing public-trust certificate profile and a federated identity with issuer `https://token.actions.githubusercontent.com`, audience `api://AzureADTokenExchange` and exact subject `repo:gcfernando/8d-audio-converter:ref:refs/heads/main`. Grant only the Artifact Signing Certificate Profile Signer role scoped to that profile. Pull requests and manual workflow runs cannot use this signing job.

Set these repository Actions variables only after the identity, federation and permissions are ready:

| Variable | Value |
| --- | --- |
| `AUDIO8D_SIGNING_ENABLED` | Exactly `true` to require signed Windows publication; absent, empty or `false` keeps unsigned publication; other values fail validation |
| `AZURE_CLIENT_ID` | Signing application's client GUID |
| `AZURE_TENANT_ID` | Tenant GUID |
| `AZURE_SUBSCRIPTION_ID` | Existing subscription GUID |
| `AUDIO8D_SIGNING_ENDPOINT` | Regional HTTPS `*.codesigning.azure.net` endpoint |
| `AUDIO8D_SIGNING_ACCOUNT` | Existing signing account name |
| `AUDIO8D_SIGNING_PROFILE` | Existing public-trust certificate profile name |
| `AUDIO8D_SIGNING_PUBLISHER` | Exact certificate subject distinguished name, including its formatting |

When enabled, missing configuration, denied access, signing failure, unexpected publisher, missing timestamp, invalid Windows trust or changed application content prevents publication. The workflow never substitutes the unsigned Windows package after an enabled signing job fails. Both platform builds and tests must succeed first. Linux packaging and executables are unchanged and unsigned.

## Verification and artifacts

Only `Audio8D/Audio8D.exe` and `Audio8D/audio8d-cli.exe` are signed. Bundled Python libraries and third-party programs, including FFmpeg, keep their original bytes and licenses. The isolated Windows job has OIDC permission; the separate publication job alone can write GitHub releases.

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
