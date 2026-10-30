"""Release publication policy tests use a fake API and never contact GitHub."""

import copy
import tempfile
import unittest
from pathlib import Path

import publish_main_release as release

ENV = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_EVENT_NAME": "push",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_REPOSITORY": "example/app",
    "GITHUB_SHA": "a" * 40,
    "GITHUB_RUN_ID": "123",
}


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.release = None
        self.reference = None
        self.fail_upload = False
        self.bad_digest = False
        self.remote_bad_digest = False

    def request(self, method, route, payload=None, **_kwargs):
        self.calls.append((method, route, payload))
        if method == "GET":
            if "/releases/tags/" in route:
                return (
                    self.release
                    if self.release and not self.release.get("draft")
                    else None
                )
            if "/releases?" in route:
                return [self.release] if self.release else []
            return self.reference
        if method == "POST" and route == "/releases":
            self.release = {
                **payload,
                "id": 1,
                "assets": [],
                "upload_url": "https://uploads.github.com/repos/example/app/releases/1/assets{?name}",
                "html_url": "https://github.com/example/app/releases/tag/test",
            }
            return copy.deepcopy(self.release)
        if method == "POST":
            if self.fail_upload:
                raise release.ReleaseError("Simulated upload failure")
            asset = {
                "id": len(self.release["assets"]) + 1,
                "name": payload.name,
                "state": "uploaded",
                "size": payload.stat().st_size,
                "digest": "sha256:"
                + ("0" * 64 if self.bad_digest else release.sha256(payload)),
                "browser_download_url": "https://github.com/example/download",
            }
            self.release["assets"].append(asset)
            return asset
        if method == "DELETE":
            return None
        if method == "PATCH":
            self.release.update(payload)
            self.reference = {"object": {"sha": ENV["GITHUB_SHA"]}}
            return self.release
        raise AssertionError((method, route))

    def download_hash(self, asset):
        return "0" * 64 if self.remote_bad_digest else asset["digest"].split(":")[1]


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name) / "Aster-win-x64.zip"
        self.package.write_bytes(b"verified application fixture")
        self.api = FakeAPI()

    def publish(self, environment=None):
        return release.publish(
            self.api, environment or ENV, "Aster", "1.0.0", [self.package]
        )

    def test_success_uploads_all_assets_before_publish(self):
        self.publish()
        methods = [call[0] for call in self.api.calls]
        self.assertEqual(
            methods, ["GET", "GET", "GET", "POST", "POST", "POST", "PATCH"]
        )
        self.assertTrue(self.api.calls[3][2]["draft"])
        self.assertFalse(self.api.release["draft"])
        self.assertEqual(
            {a["name"] for a in self.api.release["assets"]},
            {self.package.name, "SHA256SUMS.txt"},
        )
        self.assertIn(ENV["GITHUB_SHA"], self.api.release["tag_name"])

    def test_failure_never_publishes_draft(self):
        self.api.fail_upload = True
        with self.assertRaises(release.ReleaseError):
            self.publish()
        self.assertTrue(self.api.release["draft"])
        self.assertNotIn("PATCH", [call[0] for call in self.api.calls])

    def test_bad_uploaded_digest_never_publishes(self):
        self.api.bad_digest = True
        with self.assertRaises(release.ReleaseError):
            self.publish()
        self.assertTrue(self.api.release["draft"])

    def test_published_rerun_verifies_and_retains_original_assets(self):
        self.publish()
        original = copy.deepcopy(self.api.release)
        self.api.calls.clear()
        self.package.write_bytes(b"rebuilt package has different evidence timestamps")
        _, status = self.publish()
        self.assertIn("Already published", status)
        self.assertEqual(self.api.release, original)
        self.assertEqual([c[0] for c in self.api.calls], ["GET", "GET"])

    def test_published_rerun_rejects_corrupted_remote_asset(self):
        self.publish()
        self.api.remote_bad_digest = True
        with self.assertRaises(release.ReleaseError):
            self.publish()

    def test_interrupted_draft_is_recovered_after_all_uploads(self):
        self.api.fail_upload = True
        with self.assertRaises(release.ReleaseError):
            self.publish()
        self.api.release["assets"] = [{"id": 99, "name": "partial.zip"}]
        self.api.fail_upload = False
        self.api.calls.clear()
        self.publish()
        methods = [call[0] for call in self.api.calls]
        self.assertEqual(
            methods, ["GET", "GET", "GET", "DELETE", "POST", "POST", "PATCH"]
        )

    def test_listing_api_failure_stops_before_any_mutation(self):
        def fail(*_args, **_kwargs):
            raise release.ReleaseError("Simulated API failure")

        self.api.request = fail
        with self.assertRaises(release.ReleaseError):
            self.publish()
        self.assertIsNone(self.api.release)

    def test_draft_lookup_follows_paginated_release_listing(self):
        tag = release.identity(ENV, "1.0.0")[3]
        calls = []

        class Pages:
            def request(self, method, route, **kwargs):
                calls.append(route)
                if "/tags/" in route:
                    return None
                if route.endswith("&page=1"):
                    return [{"tag_name": f"other-{i}"} for i in range(100)]
                return [{"tag_name": tag, "draft": True}]

        self.assertTrue(release.find_release(Pages(), tag, tag)["draft"])
        self.assertEqual(len(calls), 3)

    def test_wrong_tag_commit_is_rejected_without_mutation(self):
        self.api.reference = {"object": {"sha": "b" * 40}}
        with self.assertRaises(release.ReleaseError):
            self.publish()
        self.assertTrue(all(c[0] == "GET" for c in self.api.calls))

    def test_unowned_release_is_rejected(self):
        self.api.release = {"tag_name": "manual", "body": "manual"}
        with self.assertRaises(release.ReleaseError):
            self.publish()
        self.assertTrue(all(c[0] == "GET" for c in self.api.calls))

    def test_ineligible_event_is_rejected_before_github(self):
        for change in (
            {"GITHUB_EVENT_NAME": "pull_request"},
            {"GITHUB_REF": "refs/heads/other"},
            {"GITHUB_ACTIONS": "false"},
            {"GITHUB_SHA": "bad"},
        ):
            with self.subTest(change=change), self.assertRaises(release.ReleaseError):
                self.publish({**ENV, **change})
        self.assertEqual(self.api.calls, [])

    def test_each_push_gets_a_distinct_tag_even_for_same_commit(self):
        first = release.identity(ENV, "1.0.0")[3]
        second = release.identity({**ENV, "GITHUB_RUN_ID": "124"}, "1.0.0")[3]
        self.assertNotEqual(first, second)

    def test_missing_platform_package_is_rejected(self):
        with self.assertRaises(release.ReleaseError):
            release.publish(self.api, ENV, "Audio8D", "1.0.0", [self.package])
        self.assertEqual(self.api.calls, [])


if __name__ == "__main__":
    unittest.main()
