import json
import argparse
import os


def is_valid_file(parser, arg):
    if not os.path.exists(arg):
        parser.error("The file %s does not exist!" % arg)
    else:
        return open(arg, 'r')  # return an open file handle


def build_followers(followers_dict):
    followers = []
    for relationship in followers_dict:
        for sld in relationship["string_list_data"]:
            followers.append(sld['value'])

    return followers


def build_following(following_dict):
    following = []
    for relationship in following_dict["relationships_following"]:
        for sld in relationship["string_list_data"]:
            following.append(sld['value'])
    return following


def parseArguments():
    parser = argparse.ArgumentParser(description="csv exports")

    parser.add_argument("--followers", dest="followers", required=True,
                        help="csv file of followers", metavar="FILE",
                        type=lambda x: is_valid_file(parser, x))

    parser.add_argument("--following", dest="following", required=True,
                        help="csv file of followers", metavar="FILE",
                        type=lambda x: is_valid_file(parser, x))

    return parser.parse_args()


if __name__ == "__main__":
    args = parseArguments()

    following_dict = json.load(args.following)
    followers_dict = json.load(args.followers)

    following = build_following(following_dict)
    followers = build_followers(followers_dict)

    rudes = [follow for follow in following if follow not in followers]

    print(f'''
Followers: {len(followers)}
Following: {len(following)}
Rudes: {len(rudes)}

Rude Accounts:
        ''')

    for rude in rudes:
        print(rude)
