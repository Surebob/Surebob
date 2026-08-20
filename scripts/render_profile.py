#!/usr/bin/env python3
"""Render the GitHub profile card from public profile data.

The script uses only Python's standard library. In GitHub Actions it reads the
built-in GITHUB_TOKEN. Locally it can reuse the authenticated `gh` CLI without
printing or persisting the token.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
API_URL = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"


THEMES = {
    "dark": {
        "bg": "#0b090c",
        "panel": "#110e12",
        "panel_alt": "#171219",
        "border": "#3b2931",
        "grid": "#f43f5e",
        "text": "#f3e9ed",
        "muted": "#9f8b94",
        "faint": "#65545c",
        "accent": "#fb4165",
        "accent_soft": "#ff8ca3",
        "value": "#f4c2cc",
        "success": "#69d6ad",
        "shadow": "#000000",
    },
    "light": {
        "bg": "#f7f1f2",
        "panel": "#fffafb",
        "panel_alt": "#f4e9ec",
        "border": "#d8bdc5",
        "grid": "#a91336",
        "text": "#26191f",
        "muted": "#79616b",
        "faint": "#b69da7",
        "accent": "#b31338",
        "accent_soft": "#d85a75",
        "value": "#7a2940",
        "success": "#147b62",
        "shadow": "#8c6f78",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="render from assets/stats.json without calling GitHub",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def get_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    if not shutil.which("gh"):
        return None
    result = subprocess.run(
        ["gh", "auth", "token"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def request_json(url: str, token: str | None, payload: dict | None = None) -> dict | list:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Surebob-profile-renderer",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, headers=headers, data=data)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def contribution_count(username: str, token: str | None, now: dt.datetime) -> int | None:
    if not token:
        return None
    start = now - dt.timedelta(days=365)
    query = """
      query($login: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $login) {
          contributionsCollection(from: $from, to: $to) {
            contributionCalendar { totalContributions }
          }
        }
      }
    """
    payload = {
        "query": query,
        "variables": {
            "login": username,
            "from": start.isoformat().replace("+00:00", "Z"),
            "to": now.isoformat().replace("+00:00", "Z"),
        },
    }
    response = request_json(GRAPHQL_URL, token, payload)
    return int(
        response["data"]["user"]["contributionsCollection"]
        ["contributionCalendar"]["totalContributions"]
    )


def account_uptime(created_at: str, now: dt.datetime) -> str:
    created = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    months = max(0, (now.year - created.year) * 12 + now.month - created.month)
    if now.day < created.day:
        months -= 1
    years, remaining_months = divmod(months, 12)
    return f"{years}y {remaining_months}m"


def fetch_stats(username: str) -> dict:
    token = get_token()
    now = dt.datetime.now(dt.timezone.utc)
    encoded_username = urllib.parse.quote(username)
    user = request_json(f"{API_URL}/users/{encoded_username}", token)
    contributions = contribution_count(username, token, now)
    return {
        "public_repos": int(user["public_repos"]),
        "followers": int(user["followers"]),
        "contributions_365d": contributions,
        "account_uptime": account_uptime(user["created_at"], now),
        "updated_at": now.date().isoformat(),
    }


def load_stats(config: dict, offline: bool) -> dict:
    cache_path = ROOT / "assets" / "stats.json"
    if offline:
        return load_json(cache_path)
    try:
        stats = fetch_stats(config["username"])
    except (OSError, KeyError, TypeError, ValueError, urllib.error.URLError) as exc:
        if not cache_path.exists():
            raise RuntimeError("GitHub stats unavailable and no cache exists") from exc
        print(f"warning: using cached stats ({exc})")
        return load_json(cache_path)
    cache_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def compact_number(value: int | None) -> str:
    if value is None:
        return "—"
    if value < 1_000:
        return f"{value:,}"
    if value < 10_000:
        return f"{value / 1_000:.1f}k"
    return f"{value / 1_000:.0f}k"


def text_row(
    label: str,
    value: str,
    y: int,
    colors: dict,
    *,
    dots_x: int = 550,
    value_x: int = 590,
) -> str:
    return (
        f'<text x="420" y="{y}" class="body">'
        f'<tspan fill="{colors["muted"]}">{esc(label)}</tspan>'
        f'<tspan x="{dots_x}" fill="{colors["faint"]}">····</tspan>'
        f'<tspan x="{value_x}" fill="{colors["value"]}">{esc(value)}</tspan>'
        "</text>"
    )


def render_svg(config: dict, stats: dict, avatar: list[str], theme_name: str) -> str:
    c = THEMES[theme_name]
    profile_url = f"https://github.com/{config['username']}"
    ascii_spans = "\n".join(
        f'<tspan x="31" y="{82 + index * 15}">{esc(line)}</tspan>'
        for index, line in enumerate(avatar)
    )
    rows = "\n".join(
        [
            text_row("identity.location", config["location"], 180, c),
            text_row("identity.company", config["company"], 204, c),
            text_row("focus.primary", config["focus_primary"], 228, c),
            text_row("focus.system", config["focus_systems"], 252, c),
        ]
    )

    stack_x = 420
    chips: list[str] = []
    for item in config["stack"]:
        width = 24 + len(item) * 8
        chips.append(
            f'<rect x="{stack_x}" y="294" width="{width}" height="28" rx="6" '
            f'fill="{c["panel_alt"]}" stroke="{c["border"]}"/>'
            f'<text x="{stack_x + width / 2:.1f}" y="313" text-anchor="middle" '
            f'class="chip" fill="{c["value"]}">{esc(item)}</text>'
        )
        stack_x += width + 9

    link_rows = "\n".join(
        text_row(
            link["label"],
            link["value"],
            366 + index * 22,
            c,
            dots_x=473,
            value_x=505,
        )
        for index, link in enumerate(config["links"])
    )

    stat_items = [
        (str(stats["public_repos"]), "PUBLIC REPOS"),
        (compact_number(stats.get("contributions_365d")), "CONTRIBS · 365D"),
        (str(stats["followers"]), "FOLLOWERS"),
        (stats["account_uptime"], "GITHUB UPTIME"),
    ]
    stat_markup: list[str] = []
    for index, (value, label) in enumerate(stat_items):
        x = 420 + index * 143
        if index:
            stat_markup.append(
                f'<line x1="{x - 15}" y1="451" x2="{x - 15}" y2="493" '
                f'stroke="{c["border"]}"/>'
            )
        stat_markup.append(
            f'<text x="{x}" y="470" class="stat" fill="{c["text"]}">{esc(value)}</text>'
            f'<text x="{x}" y="490" class="stat-label" fill="{c["muted"]}">{esc(label)}</text>'
        )

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1020" height="520" viewBox="0 0 1020 520" role="img" aria-labelledby="title desc">
  <title id="title">{esc(config["display_name"])} — GitHub profile</title>
  <desc id="desc">Terminal-style profile with an ASCII portrait, current focus, technology stack, public links, and live GitHub statistics.</desc>
  <defs>
    <linearGradient id="surface" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{c["panel"]}"/>
      <stop offset="1" stop-color="{c["bg"]}"/>
    </linearGradient>
    <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">
      <path d="M 24 0 L 0 0 0 24" fill="none" stroke="{c["grid"]}" stroke-width="0.5" opacity="0.055"/>
    </pattern>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">
      <feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="{c["shadow"]}" flood-opacity="0.16"/>
    </filter>
    <style>
      text {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; text-rendering: geometricPrecision; }}
      .body {{ font-size: 14px; }}
      .prompt {{ font-size: 14px; font-weight: 600; }}
      .headline {{ font-size: 14px; letter-spacing: 0.15px; }}
      .name {{ font-size: 28px; font-weight: 750; letter-spacing: -0.8px; }}
      .ascii {{ font-size: 12px; font-weight: 600; white-space: pre; }}
      .chip {{ font-size: 12px; font-weight: 700; }}
      .stat {{ font-size: 18px; font-weight: 750; }}
      .stat-label {{ font-size: 9px; font-weight: 700; letter-spacing: 0.8px; }}
      .micro {{ font-size: 10px; letter-spacing: 0.5px; }}
    </style>
  </defs>

  <rect x="12" y="12" width="996" height="496" rx="18" fill="url(#surface)" stroke="{c["border"]}" filter="url(#shadow)"/>
  <rect x="12" y="12" width="996" height="496" rx="18" fill="url(#grid)"/>
  <path d="M 30 55 H 990" stroke="{c["border"]}"/>
  <circle cx="35" cy="34" r="5" fill="{c["accent"]}"/>
  <circle cx="54" cy="34" r="5" fill="{c["accent_soft"]}" opacity="0.72"/>
  <circle cx="73" cy="34" r="5" fill="{c["success"]}" opacity="0.88"/>
  <text x="94" y="38" class="micro" fill="{c["muted"]}">~/profiles/{esc(config["username"])}</text>
  <rect x="924" y="25" width="62" height="18" rx="9" fill="{c["panel_alt"]}" stroke="{c["border"]}"/>
  <circle cx="937" cy="34" r="3" fill="{c["success"]}"/>
  <text x="946" y="37.5" class="micro" fill="{c["muted"]}">LIVE</text>

  <rect x="28" y="70" width="344" height="420" rx="12" fill="{c["panel_alt"]}" opacity="0.54" stroke="{c["border"]}"/>
  <text class="ascii" fill="{c["text"]}" opacity="0.88">{ascii_spans}</text>
  <path d="M 390 70 V 490" stroke="{c["border"]}"/>
  <path d="M 390 70 V 201" stroke="{c["accent"]}" stroke-width="3"/>
  <text x="47" y="469" class="micro" fill="{c["muted"]}">ASCII // AVATAR SIGNAL</text>
  <circle cx="340" cy="465" r="4" fill="{c["success"]}"/>

  <text x="420" y="86" class="prompt" fill="{c["accent"]}">{esc(config["terminal_user"])}@{esc(config["username"].lower())}</text>
  <text x="552" y="86" class="prompt" fill="{c["muted"]}">:~$ whoami</text>
  <text x="420" y="122" class="name" fill="{c["text"]}">{esc(config["display_name"])}</text>
  <text x="420" y="148" class="headline" fill="{c["muted"]}">{esc(config["headline"])}</text>
  <line x1="420" y1="161" x2="985" y2="161" stroke="{c["border"]}"/>

  {rows}

  <text x="420" y="282" class="prompt" fill="{c["accent"]}">&gt; stack --active</text>
  {''.join(chips)}

  <text x="420" y="346" class="prompt" fill="{c["accent"]}">&gt; links --public</text>
  {link_rows}

  <line x1="420" y1="438" x2="985" y2="438" stroke="{c["border"]}"/>
  {''.join(stat_markup)}

  <a href="{esc(profile_url)}">
    <rect x="12" y="12" width="996" height="496" rx="18" fill="transparent"/>
  </a>
</svg>
'''


def main() -> None:
    args = parse_args()
    config = load_json(ROOT / "profile.json")
    avatar_path = ROOT / config["avatar_ascii"]
    avatar = avatar_path.read_text(encoding="utf-8").splitlines()
    stats = load_stats(config, args.offline)
    for theme_name in THEMES:
        output = ROOT / f"{theme_name}_mode.svg"
        output.write_text(
            render_svg(config, stats, avatar, theme_name),
            encoding="utf-8",
        )
        print(f"rendered {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
