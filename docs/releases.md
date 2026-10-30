# Audio8D packaging and automated releases

The native package builder creates portable Windows x86_64 and Linux x86_64 application ZIPs. Each contains the GUI, CLI, Python runtime, FFmpeg/FFprobe, user documentation and license notices. macOS build code exists but remains untested and is excluded from automated release targets.

## Build and verify a local package

From the repository root, run `python packaging/build_release.py` with Python 3.10 or newer. The builder creates its own virtual environment and installs the versions in [requirements-build.txt](../packaging/requirements-build.txt). Windows uses the repository's Git LFS FFmpeg binaries; Linux downloads its configured static FFmpeg build and checks the upstream checksum. `--ffmpeg-dir <folder>` selects a local folder containing both tools.

The builder writes `bin/Audio8D-<base-version>-<platform>.zip`. It preserves executable modes in the archive, extracts into a path containing spaces, removes Python from the test `PATH`, checks the extracted CLI version/system check and converts a generated six-second tone using bundled FFmpeg. Do not use `--skip-check` for release candidates. The GUI still needs desktop acceptance on the intended machines.

## A release for each main push

[release.yml](https://github.com/gcfernando/8d-audio-converter/actions/workflows/release.yml) runs on every push to `main`, on pull requests and on manual dispatch. It builds on native Windows and Linux runners, runs the converter and GUI test suites, and retains one checked ZIP from each platform. Only a successful **push to main**, with both required platform jobs successful, reaches publication. Pull requests and manual runs only create artifacts.

The workflow has no branch-level concurrency group, so a newer push does not cancel an older run or replace a pending push. Its unique tag is `v<base-version>-main.<run-id>.<full-commit-sha>`. The application version remains the base version from `pyproject.toml`; release notes identify the exact build commit and run. Every successful push keeps its own release rather than replacing a rolling download.

Publication creates an owned draft, uploads both packages and `SHA256SUMS.txt`, checks their uploaded sizes and SHA-256 digests, then publishes the completed preview. Failed builds or uploads cannot publish an incomplete new release. A failed upload can leave a private draft. Rerun the same workflow to recover that draft. An already published complete release is downloaded and verified, then retained; rebuilt bytes do not silently overwrite it. A tag collision, unrelated release, API failure or checksum failure stops publication visibly.

## Permissions and signing

Build jobs use `contents: read`; only the publication job receives `contents: write` through the scoped GitHub token. Checkout credentials are not persisted. Actions are pinned to immutable commits. No personal access token or signing certificate is required by this configuration. Repository policy must allow the token to create tags and releases.

The packages are **unsigned**. The workflow does not provide Windows Authenticode signing, Linux package signatures or macOS notarization. Adding signed distribution requires the relevant certificates/credentials and platform-specific signing and verification steps before release upload. Do not label the current ZIPs as signed.

## Checksums and third-party notices

Download an application ZIP and `SHA256SUMS.txt` from the same release. Compare the expected entry with `Get-FileHash <zip> -Algorithm SHA256` on Windows or `sha256sum <zip>` on Linux before extracting. Checksums detect changed bytes; they do not replace publisher trust or code signing.

Audio8D's code has an [MIT license](../LICENSE). Bundled FFmpeg uses GPLv3 and other components retain separate licenses. Preserve [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md), the [license texts](https://github.com/gcfernando/8d-audio-converter/tree/main/licenses) and corresponding-source information when redistributing. Each newly built package records its actual Python/platform identity in `BUILD-INFO.txt`; runtime patch versions can differ from the original repository ZIPs.

## Verification status

Use the [releases index](https://github.com/gcfernando/8d-audio-converter/releases) and [workflow runs](https://github.com/gcfernando/8d-audio-converter/actions/workflows/release.yml) to inspect actual published downloads and their source/build evidence. Local checks and static workflow validation alone do not establish a successful remote run.

The full test suite runs on both native platforms before publication. GUI control and player-state tests isolate playback devices so hosted runners without audio hardware can still verify those behaviors. Maximized-window tests require an actual supported window-manager state; ordinary popup geometry remains covered on every GUI runner. Physical playback, perceived audio quality and clean-machine desktop acceptance remain separate manual checks.
