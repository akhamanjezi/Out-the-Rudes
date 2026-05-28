"""Out the Rudes — find who doesn't follow you back from an Instagram JSON export.

Instagram's export has shifted layouts over time, so usernames can live in
different fields:

  * followers live in `followers_*.json` as a top-level JSON array; the username
    is `string_list_data[0].value`.
  * following lives in `following.json` under `relationships_following`; newer
    exports put the username in the entry's top-level `title`, older ones put it
    in `string_list_data[0].value`.
  * matching is case-insensitive (trim + lowercase).
  * timestamps of 0 / missing mean "no date".
"""

import argparse
import json
import os
import sys
import zipfile

FOLLOWERS_PREFIX = "followers_"
FOLLOWING_BASENAME = "following.json"


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def _normalize(username):
    return username.strip().lower()


def _timestamp(value):
    """Instagram uses 0 / missing to mean 'no timestamp'."""
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    return ts if ts > 0 else None


def _account_from_entry(entry):
    """(username, timestamp) from one relationship entry, or None.

    Handles both Instagram export eras:
      * older exports put the username in string_list_data[0].value
        (title is empty) — used by followers and older following.json.
      * newer exports put the username in the entry's top-level `title`
        and omit `value` — used by newer following.json.
    Falls back to the href slug if neither is present.
    """
    entry = entry or {}
    string_data = entry.get("string_list_data") or []
    first = (string_data[0] if string_data else {}) or {}

    username = (first.get("value") or "").strip()
    if not username:
        username = (entry.get("title") or "").strip()
    if not username:
        href = (first.get("href") or "").strip().rstrip("/")
        username = href.rsplit("/", 1)[-1] if href else ""
    if not username:
        return None
    return username, _timestamp(first.get("timestamp"))


def parse_followers(payload):
    """followers_*.json (top-level array) -> list of (username, followed_you_at)."""
    if not isinstance(payload, list):
        raise ValueError("followers file must contain a top-level JSON array")
    return [acc for acc in (_account_from_entry(e) for e in payload) if acc]


def parse_following(payload):
    """following.json (relationships_following) -> list of (username, you_followed_them_at)."""
    if not isinstance(payload, dict):
        raise ValueError("following file must contain a top-level JSON object")
    entries = payload.get("relationships_following", []) or []
    return [acc for acc in (_account_from_entry(e) for e in entries) if acc]


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #

class Account:
    __slots__ = ("username", "is_follower", "is_following",
                 "followed_you_at", "you_followed_them_at")

    def __init__(self, username):
        self.username = username
        self.is_follower = False
        self.is_following = False
        self.followed_you_at = None
        self.you_followed_them_at = None

    @property
    def role(self):
        if self.is_follower and not self.is_following:
            return "not_following_back"   # they follow you, you don't follow back
        if self.is_following and not self.is_follower:
            return "doesnt_follow_back"    # you follow them, they don't follow back (rude)
        return "mutual"


def build_accounts(followers, following):
    records = {}

    for username, followed_at in followers:
        key = _normalize(username)
        record = records.get(key) or Account(username)
        if not record.username:
            record.username = username
        record.is_follower = True
        record.followed_you_at = followed_at
        records[key] = record

    for username, followed_at in following:
        key = _normalize(username)
        record = records.get(key) or Account(username)
        if not record.username:
            record.username = username
        record.is_following = True
        record.you_followed_them_at = followed_at
        records[key] = record

    return sorted(records.values(), key=lambda a: a.username.lower())


# --------------------------------------------------------------------------- #
# Loading: explicit files, a folder, or a .zip
# --------------------------------------------------------------------------- #

def _is_followers_name(name):
    base = os.path.splitext(os.path.basename(name))[0]
    return base.startswith(FOLLOWERS_PREFIX) and base[len(FOLLOWERS_PREFIX):].isdigit()


def _load_json_bytes(raw, source):
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: {source} is not valid JSON ({exc})")


def load_from_files(follower_paths, following_path):
    followers = []
    for path in sorted(follower_paths):
        with open(path, "rb") as handle:
            followers += parse_followers(_load_json_bytes(handle.read(), path))
    with open(following_path, "rb") as handle:
        following = parse_following(_load_json_bytes(handle.read(), following_path))
    return followers, following


def load_from_dir(root):
    follower_paths, following_path = [], None
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            full = os.path.join(dirpath, name)
            if _is_followers_name(name):
                follower_paths.append(full)
            elif name == FOLLOWING_BASENAME and following_path is None:
                following_path = full
    if not follower_paths:
        raise SystemExit(f"error: no followers_*.json found under {root}")
    if following_path is None:
        raise SystemExit(f"error: no {FOLLOWING_BASENAME} found under {root}")
    return load_from_files(follower_paths, following_path)


def load_from_zip(zip_path):
    with zipfile.ZipFile(zip_path) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        follower_names = sorted(n for n in names if _is_followers_name(n))
        following_name = next(
            (n for n in names if os.path.basename(n) == FOLLOWING_BASENAME), None
        )
        if not follower_names:
            raise SystemExit(f"error: no followers_*.json inside {zip_path}")
        if following_name is None:
            raise SystemExit(f"error: no {FOLLOWING_BASENAME} inside {zip_path}")

        followers = []
        for name in follower_names:
            followers += parse_followers(_load_json_bytes(archive.read(name), name))
        following = parse_following(_load_json_bytes(archive.read(following_name), following_name))
    return followers, following


def load(args):
    if args.export:
        path = args.export
        if not os.path.exists(path):
            raise SystemExit(f"error: {path} does not exist")
        if zipfile.is_zipfile(path):
            return load_from_zip(path)
        if os.path.isdir(path):
            return load_from_dir(path)
        raise SystemExit(f"error: {path} is not a .zip or a folder")

    missing = [flag for flag, val in (("--followers", args.followers),
                                      ("--following", args.following)) if not val]
    if missing:
        raise SystemExit(
            "error: provide an export path, or both --followers and --following "
            f"(missing: {', '.join(missing)})"
        )
    for path in list(args.followers) + [args.following]:
        if not os.path.exists(path):
            raise SystemExit(f"error: {path} does not exist")
    return load_from_files(args.followers, args.following)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def _profile_url(username):
    return f"https://www.instagram.com/{username}"


def report(accounts, follower_count, following_count, as_json=False):
    rudes = [a for a in accounts if a.role == "doesnt_follow_back"]
    not_following_back = [a for a in accounts if a.role == "not_following_back"]
    mutuals = [a for a in accounts if a.role == "mutual"]

    if as_json:
        payload = {
            "followers": follower_count,
            "following": following_count,
            "mutuals": len(mutuals),
            "doesnt_follow_back": [
                {"username": a.username, "profile_url": _profile_url(a.username)}
                for a in rudes
            ],
            "not_following_back": [
                {"username": a.username, "profile_url": _profile_url(a.username)}
                for a in not_following_back
            ],
        }
        print(json.dumps(payload, indent=2))
        return

    print(
        f"\nFollowers: {follower_count}"
        f"\nFollowing: {following_count}"
        f"\nMutuals:   {len(mutuals)}"
    )

    print(f"\nDoesn't follow back — you follow them, they don't follow you ({len(rudes)}):")
    for account in rudes:
        print(f"  {account.username}")

    print(f"\nNot following back — they follow you, you don't follow them ({len(not_following_back)}):")
    for account in not_following_back:
        print(f"  {account.username}")
    print()


# --------------------------------------------------------------------------- #

def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Find who doesn't follow you back from an Instagram JSON export."
    )
    parser.add_argument(
        "export", nargs="?", metavar="PATH",
        help="Instagram export .zip or its extracted folder (auto-finds the JSON files)",
    )
    parser.add_argument(
        "--followers", nargs="+", metavar="FILE",
        help="one or more followers_*.json files",
    )
    parser.add_argument(
        "--following", metavar="FILE",
        help="following.json file",
    )
    parser.add_argument(
        "--json", dest="as_json", action="store_true",
        help="emit machine-readable JSON instead of text",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_arguments(argv)
    followers, following = load(args)
    accounts = build_accounts(followers, following)
    report(accounts, len(followers), len(following), as_json=args.as_json)


if __name__ == "__main__":
    main()
