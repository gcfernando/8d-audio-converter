"""Publish complete per-push releases; importing this module performs no I/O."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


class ReleaseError(RuntimeError):
    """A publication precondition or GitHub request failed."""


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return stream_hash(source)


def stream_hash(source) -> str:
    digest = hashlib.sha256()
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


class GitHub:
    def __init__(self, repository: str, token: str):
        self.root = f"https://api.github.com/repos/{repository}"
        self.token = token

    def request(self, method: str, route: str, payload=None, *, missing=False):
        url = route if route.startswith("https://") else self.root + route
        if urllib.parse.urlparse(url).hostname not in (
            "api.github.com",
            "uploads.github.com",
        ):
            raise ReleaseError("Refusing an unexpected GitHub API host")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "per-push-application-release",
        }
        if isinstance(payload, Path):
            body = payload.read_bytes()
            headers["Content-Type"] = "application/octet-stream"
        elif payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        else:
            body = None
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                content = response.read()
                return json.loads(content) if content else None
        except urllib.error.HTTPError as exc:
            if missing and exc.code == 404:
                return None
            raise ReleaseError(
                f"GitHub {method} request failed (HTTP {exc.code})"
            ) from exc
        except (OSError, ValueError) as exc:
            raise ReleaseError(
                f"GitHub {method} request failed ({type(exc).__name__})"
            ) from exc

    def download_hash(self, asset: dict) -> str:
        # These repositories are public. Never send a token to a download redirect.
        url = asset["browser_download_url"]
        if urllib.parse.urlparse(url).hostname != "github.com":
            raise ReleaseError("Refusing an unexpected public asset host")
        try:
            with urllib.request.urlopen(url, timeout=300) as response:
                return stream_hash(response)
        except OSError as exc:
            raise ReleaseError("Could not verify an existing release asset") from exc


def identity(environment: dict[str, str], version: str):
    if (
        environment.get("GITHUB_ACTIONS") != "true"
        or environment.get("GITHUB_EVENT_NAME") != "push"
        or environment.get("GITHUB_REF") != "refs/heads/main"
    ):
        raise ReleaseError("Publication is restricted to GitHub Actions pushes to main")
    repository = environment.get("GITHUB_REPOSITORY", "")
    commit = environment.get("GITHUB_SHA", "")
    run = environment.get("GITHUB_RUN_ID", "")
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
        or not re.fullmatch(r"[a-f0-9]{40}", commit)
        or not re.fullmatch(r"[0-9]+", run)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
    ):
        raise ReleaseError("Invalid repository, commit, run, or base version")
    tag = f"v{version}-main.{run}.{commit}"
    marker = f"<!-- automated-main-release run={run} commit={commit} -->"
    return repository, commit, run, tag, marker


def verify_published(api, release: dict, expected_names: set[str]):
    assets = release.get("assets", [])
    by_name = {asset["name"]: asset for asset in assets}
    if len(by_name) != len(assets) or set(by_name) != expected_names:
        raise ReleaseError(
            "The existing published release has unexpected or missing assets"
        )
    for asset in assets:
        if asset.get("state") != "uploaded" or asset.get("size", 0) <= 0:
            raise ReleaseError("The existing published release has an incomplete asset")
        digest = asset.get("digest", "")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
            raise ReleaseError("The existing release lacks a verifiable asset digest")
        if api.download_hash(asset) != digest.split(":", 1)[1]:
            raise ReleaseError("Existing release asset failed its SHA-256 verification")


def find_release(api, tag: str, encoded_tag: str):
    found = api.request("GET", f"/releases/tags/{encoded_tag}", missing=True)
    if found:
        return found
    # The by-tag endpoint describes published releases. Authenticated list calls
    # also include drafts, which are required to recover an interrupted upload.
    page = 1
    while True:
        batch = api.request("GET", f"/releases?per_page=100&page={page}")
        if not isinstance(batch, list):
            raise ReleaseError("GitHub returned an invalid release listing")
        matches = [item for item in batch if item.get("tag_name") == tag]
        if len(matches) > 1:
            raise ReleaseError("Multiple releases use this push's tag")
        if matches:
            return matches[0]
        if len(batch) < 100:
            return None
        page += 1


def publish(
    api,
    environment: dict[str, str],
    project: str,
    version: str,
    packages: list[Path],
    *,
    signed_windows: bool = False,
):
    repository, commit, run, tag, marker = identity(environment, version)
    expected = {"Aster": 1, "Audio8D": 2}
    if project not in expected or len(packages) != expected[project]:
        raise ReleaseError("Unexpected project or package count")
    names = [package.name for package in packages]
    if len(set(names)) != len(names) or any(
        not re.fullmatch(r"[A-Za-z0-9_.-]+\.zip", name) for name in names
    ):
        raise ReleaseError("Unsafe or duplicate package names")
    if project == "Aster" and names != ["Aster-win-x64.zip"]:
        raise ReleaseError("Expected the verified Windows x64 Aster package")
    if project == "Audio8D" and set(names) != {
        f"Audio8D-{version}-windows-x86_64.zip",
        f"Audio8D-{version}-linux-x86_64.zip",
    }:
        raise ReleaseError("Expected both verified Audio8D platform packages")
    for package in packages:
        if not package.is_file() or package.stat().st_size <= 0:
            raise ReleaseError("A required package is missing or empty")
    if signed_windows:
        if project != "Audio8D":
            raise ReleaseError("Windows signing evidence is supported only for Audio8D")
        helper_path = (
            Path(__file__).resolve().parents[2] / "packaging" / "sign_release.py"
        )
        specification = importlib.util.spec_from_file_location(
            "audio8d_sign_release", helper_path
        )
        helper = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(helper)
        try:
            helper.verify_signed_archive(
                next(p for p in packages if "-windows-" in p.name)
            )
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
            zipfile.BadZipFile,
        ) as exc:
            raise ReleaseError(
                "Signed Windows package evidence failed validation"
            ) from exc
    checksum = packages[0].parent / "SHA256SUMS.txt"
    checksum.write_text(
        "".join(f"{sha256(package)}  {package.name}\n" for package in sorted(packages)),
        encoding="utf-8",
    )
    assets = [*packages, checksum]
    expected_names = {asset.name for asset in assets}
    encoded_tag = urllib.parse.quote(tag, safe="")
    release = find_release(api, tag, encoded_tag)
    reference = api.request("GET", f"/git/ref/tags/{encoded_tag}", missing=True)
    if reference and reference.get("object", {}).get("sha") != commit:
        raise ReleaseError("The release tag already targets a different commit")
    if release:
        if (
            release.get("tag_name") != tag
            or marker not in release.get("body", "")
            or release.get("target_commitish") != commit
            or release.get("prerelease") is not True
            or (
                "Signing status: Windows frontends Authenticode signed."
                in release.get("body", "")
            )
            != signed_windows
        ):
            raise ReleaseError("Refusing to modify a release not owned by this push")
        if not release.get("draft"):
            if reference is None:
                raise ReleaseError("Published release tag is missing")
            verify_published(api, release, expected_names)
            return release[
                "html_url"
            ], "Already published; original verified assets retained"
        if release.get("immutable"):
            raise ReleaseError("Cannot recover an immutable draft")
    elif reference:
        raise ReleaseError("The tag exists without an owned release")
    instructions = (
        "Extract the entire ZIP and run Aster.exe. Windows x64 and the .NET 10 "
        "Desktop Runtime are required. The runtime is not bundled."
        if project == "Aster"
        else "Extract the entire platform ZIP, then run Audio8D.exe on Windows or "
        "./Audio8D on Linux. Keep its companion files together. Python and FFmpeg "
        "are bundled. FFmpeg and the bundled libraries retain their own licenses; "
        "see THIRD-PARTY-NOTICES.md and licenses/ in the package. macOS is not built."
    )
    signing_notes = (
        "Signing status: Windows frontends Authenticode signed. "
        "The two Audio8D Windows frontends (Audio8D.exe and audio8d-cli.exe) have "
        "trusted, timestamped Authenticode signatures verified on Windows. "
        "Bundled third-party programs, including FFmpeg, "
        "are not signed by this project. "
        "The Linux package is unsigned. signing-manifest.json records Windows signing "
        "and final file-integrity evidence; the Linux publication job checks those "
        "hashes and metadata, not Windows cryptographic trust. Signing does not "
        "guarantee SmartScreen reputation or eliminate security warnings."
        if signed_windows
        else "These are **unsigned automated preview builds**. "
        "They are not signed or notarized. "
        "Windows may show Unknown publisher / SmartScreen until a trusted signing "
        "identity and reputation are established. "
        "Signing support alone does not remove this warning."
    )
    notes = (
        f"{marker}\n\nBuilt from main commit [{commit}]"
        f"(https://github.com/{repository}/commit/{commit}).\n\n"
        f"[Required checks and package verification](https://github.com/{repository}/actions/runs/{run}).\n\n"
        f"{instructions}\n\n{signing_notes} SHA256SUMS.txt records each application "
        "ZIP's SHA-256 checksum. Source-code archives are not runnable downloads.\n\n"
        f"Release identity: `{tag}`. Application base version: `{version}`. "
        "Each successful main push keeps its own release; reruns retain an already "
        "published complete release. Manual desktop acceptance remains separate "
        "from automated tests.\n"
    )
    if not release:
        release = api.request(
            "POST",
            "/releases",
            {
                "tag_name": tag,
                "target_commitish": commit,
                "name": f"{project} {version} · main build {run}",
                "body": notes,
                "draft": True,
                "prerelease": True,
                "make_latest": "false",
            },
        )
    release_id = release["id"]
    # Only an owned, unpublished draft can have assets replaced during recovery.
    for asset in release.get("assets", []):
        api.request("DELETE", f"/releases/assets/{asset['id']}")
    upload = release["upload_url"].split("{", 1)[0]
    uploaded = []
    for asset in assets:
        result = api.request(
            "POST", upload + "?name=" + urllib.parse.quote(asset.name), asset
        )
        if (
            result.get("name") != asset.name
            or result.get("state") != "uploaded"
            or result.get("size") != asset.stat().st_size
            or result.get("digest") != "sha256:" + sha256(asset)
        ):
            raise ReleaseError(
                "Uploaded release asset failed size or SHA-256 verification"
            )
        uploaded.append(result["name"])
    if set(uploaded) != expected_names:
        raise ReleaseError("Not every required asset was uploaded")
    # This is the only operation that makes the release publicly available.
    published = api.request(
        "PATCH",
        f"/releases/{release_id}",
        {
            "draft": False,
            "prerelease": True,
            "make_latest": "false",
            "body": notes,
        },
    )
    if published.get("draft") is not False:
        raise ReleaseError("GitHub did not publish the completed draft")
    return published["html_url"], "Published complete release"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, choices=("Aster", "Audio8D"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--signed-windows", action="store_true")
    parser.add_argument("packages", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        repository, *_ = identity(dict(os.environ), args.version)
        token = os.environ.get("GH_TOKEN", "")
        if not token:
            raise ReleaseError("GH_TOKEN is required")
        url, status = publish(
            GitHub(repository, token),
            dict(os.environ),
            args.project,
            args.version,
            args.packages,
            signed_windows=args.signed_windows,
        )
        print(f"{status}: {url}")
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(summary).open("a", encoding="utf-8") as target:
                target.write(f"{status}: [download and release notes]({url}).\n")
        return 0
    except ReleaseError as exc:
        print(f"Release failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
