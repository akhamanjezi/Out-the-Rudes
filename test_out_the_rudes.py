"""Tests for out_the_rudes.

Run with:  python3 -m unittest
Self-contained — builds its own fixtures in temp dirs, no external data needed.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

import out_the_rudes as otr

REPO_DIR = os.path.dirname(os.path.abspath(__file__))


def entry(*, value=None, timestamp=None, href=None, title=""):
    """Build one Instagram relationship entry."""
    sld = {}
    if href is not None:
        sld["href"] = href
    if value is not None:
        sld["value"] = value
    if timestamp is not None:
        sld["timestamp"] = timestamp
    return {"title": title, "media_list_data": [], "string_list_data": [sld] if sld else []}


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


class TimestampTests(unittest.TestCase):
    def test_zero_and_missing_are_none(self):
        self.assertIsNone(otr._timestamp(0))
        self.assertIsNone(otr._timestamp(None))
        self.assertIsNone(otr._timestamp(""))
        self.assertIsNone(otr._timestamp("nope"))

    def test_positive_is_kept(self):
        self.assertEqual(otr._timestamp(1700000000), 1700000000.0)


class ParseFollowersTests(unittest.TestCase):
    def test_value_based_extraction(self):
        payload = [entry(value="alice", timestamp=1700000000),
                   entry(value="bob", timestamp=0)]
        self.assertEqual(otr.parse_followers(payload),
                         [("alice", 1700000000.0), ("bob", None)])

    def test_skips_entries_without_a_username(self):
        payload = [entry(), entry(value="   "), entry(value="real")]
        self.assertEqual(otr.parse_followers(payload), [("real", None)])

    def test_rejects_non_list(self):
        with self.assertRaises(ValueError):
            otr.parse_followers({"relationships_following": []})


class ParseFollowingTests(unittest.TestCase):
    def test_new_format_uses_title(self):
        # 2025/2026 exports: username in `title`, no `value` in string_list_data
        payload = {"relationships_following": [
            entry(title="charlie", href="https://www.instagram.com/charlie", timestamp=1700000200),
        ]}
        self.assertEqual(otr.parse_following(payload), [("charlie", 1700000200.0)])

    def test_old_format_uses_value(self):
        # 2024 exports: username in string_list_data[].value, title empty
        payload = {"relationships_following": [
            entry(value="dora", title="", timestamp=1709943050),
        ]}
        self.assertEqual(otr.parse_following(payload), [("dora", 1709943050.0)])

    def test_href_slug_fallback(self):
        payload = {"relationships_following": [
            entry(title="", href="https://www.instagram.com/eve/"),
        ]}
        self.assertEqual(otr.parse_following(payload), [("eve", None)])

    def test_rejects_non_dict(self):
        with self.assertRaises(ValueError):
            otr.parse_following([])


class BuildAccountsTests(unittest.TestCase):
    def _roles(self, accounts):
        return {a.username: a.role for a in accounts}

    def test_role_classification(self):
        followers = [("mutual", None), ("fan", None)]
        following = [("mutual", None), ("rude", None)]
        roles = self._roles(otr.build_accounts(followers, following))
        self.assertEqual(roles["mutual"], "mutual")
        self.assertEqual(roles["fan"], "not_following_back")    # follows you, you don't follow back
        self.assertEqual(roles["rude"], "doesnt_follow_back")   # you follow them, they don't follow back

    def test_matching_is_case_insensitive(self):
        accounts = otr.build_accounts([("MutualFriend", None)], [("mutualfriend", None)])
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].role, "mutual")
        # display username keeps the first-seen casing (the follower's)
        self.assertEqual(accounts[0].username, "MutualFriend")

    def test_results_are_sorted_case_insensitively(self):
        accounts = otr.build_accounts([("Zoe", None), ("amy", None)], [])
        self.assertEqual([a.username for a in accounts], ["amy", "Zoe"])

    def test_timestamps_are_attached_to_each_side(self):
        accounts = otr.build_accounts([("x", 1.0)], [("x", 2.0)])
        self.assertEqual(accounts[0].followed_you_at, 1.0)
        self.assertEqual(accounts[0].you_followed_them_at, 2.0)


class LoadFromFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_multiple_follower_files_are_merged(self):
        f1 = os.path.join(self.tmp, "followers_1.json")
        f2 = os.path.join(self.tmp, "followers_2.json")
        fg = os.path.join(self.tmp, "following.json")
        write_json(f1, [entry(value="alice")])
        write_json(f2, [entry(value="bob")])
        write_json(fg, {"relationships_following": [entry(title="alice")]})
        followers, following = otr.load_from_files([f2, f1], fg)
        self.assertEqual(sorted(u for u, _ in followers), ["alice", "bob"])
        self.assertEqual(following, [("alice", None)])


class LoadFromDirAndZipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(self._cleanup)
        self.followers_dir = os.path.join(self.tmp, "connections", "followers_and_following")
        write_json(os.path.join(self.followers_dir, "followers_1.json"), [entry(value="alice")])
        write_json(os.path.join(self.followers_dir, "followers_2.json"), [entry(value="bob")])
        write_json(os.path.join(self.followers_dir, "following.json"),
                   {"relationships_following": [entry(title="alice"), entry(title="carol")]})

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_from_dir_discovers_files(self):
        followers, following = otr.load_from_dir(self.tmp)
        self.assertEqual(sorted(u for u, _ in followers), ["alice", "bob"])
        self.assertEqual(sorted(u for u, _ in following), ["alice", "carol"])

    def test_load_from_dir_requires_followers(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(empty, ignore_errors=True))
        with self.assertRaises(SystemExit):
            otr.load_from_dir(empty)

    def test_load_from_zip(self):
        zip_path = os.path.join(self.tmp, "export.zip")
        with zipfile.ZipFile(zip_path, "w") as archive:
            for name in ("followers_1.json", "followers_2.json", "following.json"):
                archive.write(os.path.join(self.followers_dir, name),
                              arcname=f"connections/followers_and_following/{name}")
        followers, following = otr.load_from_zip(zip_path)
        self.assertEqual(sorted(u for u, _ in followers), ["alice", "bob"])
        self.assertEqual(sorted(u for u, _ in following), ["alice", "carol"])


class EndToEndTests(unittest.TestCase):
    """End-to-end over a representative dataset."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        base = os.path.join(self.tmp, "connections", "followers_and_following")
        write_json(os.path.join(base, "followers_1.json"), [
            entry(value="mutual_friend", timestamp=1700000000),
            entry(value="follower_only", timestamp=1700000100),
        ])
        write_json(os.path.join(base, "followers_2.json"), [
            entry(value="missing_timestamp", timestamp=0),
        ])
        write_json(os.path.join(base, "following.json"), {"relationships_following": [
            entry(title="mutual_friend", href="https://www.instagram.com/mutual_friend", timestamp=1700000200),
            entry(title="following_only", href="https://www.instagram.com/following_only", timestamp=1700000300),
            entry(title="missing_timestamp", href="https://www.instagram.com/missing_timestamp"),
        ]})

    def test_classification(self):
        followers, following = otr.load_from_dir(self.tmp)
        accounts = otr.build_accounts(followers, following)
        by_role = {}
        for account in accounts:
            by_role.setdefault(account.role, []).append(account.username)
        self.assertEqual(by_role["doesnt_follow_back"], ["following_only"])
        self.assertEqual(by_role["not_following_back"], ["follower_only"])
        self.assertEqual(sorted(by_role["mutual"]), ["missing_timestamp", "mutual_friend"])

    def test_cli_json_output(self):
        result = subprocess.run(
            [sys.executable, "out_the_rudes.py", self.tmp, "--json"],
            cwd=REPO_DIR, capture_output=True, text=True, check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["followers"], 3)
        self.assertEqual(payload["following"], 3)
        self.assertEqual(payload["mutuals"], 2)
        self.assertEqual([a["username"] for a in payload["doesnt_follow_back"]], ["following_only"])
        self.assertEqual([a["username"] for a in payload["not_following_back"]], ["follower_only"])
        self.assertEqual(payload["doesnt_follow_back"][0]["profile_url"],
                         "https://www.instagram.com/following_only")


if __name__ == "__main__":
    unittest.main()
