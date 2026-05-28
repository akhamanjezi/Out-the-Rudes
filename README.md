# Out the Rudes

```Rude: an account you follow that doesn't follow you back.```

Reads your Instagram data export and shows who doesn't follow you back — and
who you don't follow back.

### Usage

1. [Download](https://help.instagram.com/181231772500920) your Instagram
   information in **JSON** format.
2. With Python 3 installed, point the script at the `.zip` Instagram gave you
   (no need to unzip):

```zsh
$ python out_the_rudes.py instagram-yourname-2026-05-16.zip

Followers: 1065
Following: 1100
Mutuals:   751

Doesn't follow back — you follow them, they don't follow you (349):
  some_account
  ...

Not following back — they follow you, you don't follow them (314):
  another_account
  ...
```

You can also point it at the extracted folder, or pass the JSON files directly:

```zsh
# extracted export folder (finds followers_*.json + following.json anywhere inside)
$ python out_the_rudes.py ~/Downloads/connections

# explicit files — followers can be split across multiple files
$ python out_the_rudes.py --followers followers_1.json followers_2.json --following following.json

# machine-readable output
$ python out_the_rudes.py export.zip --json
```

### Notes

- Matching is case-insensitive.
- Handles both Instagram export layouts: older exports store the username in
  `string_list_data[].value`; newer `following.json` stores it in `title`.
- Followers may be split across `followers_1.json`, `followers_2.json`, … —
  all parts are merged.
- No third-party dependencies; standard library only.
