#!/usr/bin/env python3
"""Generate a local live-activity SVG for the GitHub profile README.

Uses public GitHub GraphQL data and writes assets/activity.svg. The README then
shows a stable local asset while GitHub Actions keeps it fresh.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

USERNAME = os.environ.get("PROFILE_USERNAME", "Micoh18")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "activity.svg"

QUERY = """
query($login:String!){
  user(login:$login){
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalRepositoryContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount color } }
      }
      commitContributionsByRepository(maxRepositories:20){
        repository { name url isPrivate primaryLanguage { name color } }
        contributions { totalCount }
      }
    }
    repositoriesContributedTo(first:1, contributionTypes:[COMMIT, PULL_REQUEST, REPOSITORY, ISSUE], includeUserRepositories:true){ totalCount }
    repositories(first:8, privacy:PUBLIC, orderBy:{field:PUSHED_AT,direction:DESC}){
      nodes { name url pushedAt isFork primaryLanguage { name color } }
    }
  }
}
"""


def gh_graphql() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": f"{USERNAME}-profile-readme-activity",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps({"query": QUERY, "variables": {"login": USERNAME}}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as res:
        payload = json.loads(res.read().decode())
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]["user"]


def short_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b")
    except Exception:
        return value[:10]


def heat_color(count: int) -> str:
    if count <= 0:
        return "#17211B"
    if count <= 2:
        return "#1F6B45"
    if count <= 6:
        return "#2F9E63"
    if count <= 14:
        return "#7DD3A8"
    return "#F4B860"


def render_calendar(days: list[dict], x0: int = 96, y0: int = 248, scale: float = 3.55) -> str:
    # Isometric commit calendar adapted from lowlighter/metrics' isocalendar plugin.
    # Each day is a diamond top plus two shaded side faces; column height follows contribution count.
    recent = days[-182:]
    reference = max((int(day.get("contributionCount") or 0) for day in recent), default=1) or 1
    size = 6
    parts = [f'<g transform="translate({x0} {y0}) scale({scale})">']
    for week_idx in range(0, len(recent), 7):
        week = recent[week_idx:week_idx + 7]
        i = week_idx // 7
        parts.append(f'<g transform="translate({i * 1.7:.2f} {i:.2f})">')
        for j, day in enumerate(week):
            count = int(day.get("contributionCount") or 0)
            ratio = count / reference if reference else 0
            color = day.get("color") or heat_color(count)
            y = j + (1 - ratio) * size
            parts.append(f'''
        <g transform="translate({j * -1.7:.2f} {y:.2f})">
          <title>{escape(day.get("date", ""))}: {count}</title>
          <path fill="{color}" d="M1.7,2 0,1 1.7,0 3.4,1 z" />
          <path fill="{color}" filter="url(#isoBrightness1)" d="M0,1 1.7,2 1.7,{2 + ratio * size:.2f} 0,{1 + ratio * size:.2f} z" />
          <path fill="{color}" filter="url(#isoBrightness2)" d="M1.7,2 3.4,1 3.4,{1 + ratio * size:.2f} 1.7,{2 + ratio * size:.2f} z" />
        </g>''')
        parts.append("</g>")
    parts.append("</g>")
    return "\n    ".join(parts)


def streak_stats(days: list[dict]) -> tuple[int, int, int, str]:
    current = 0
    best = 0
    highest = 0
    total = 0
    for day in days:
        count = int(day.get("contributionCount") or 0)
        total += count
        highest = max(highest, count)
        if count:
            current += 1
            best = max(best, current)
        else:
            current = 0
    average = f"{(total / len(days)):.2f}".rstrip("0").rstrip(".") if days else "0"
    return current, best, highest, average


def progress_bars(top_repos: list[dict], x: int = 574, y: int = 108) -> str:
    if not top_repos:
        return '<text x="574" y="132" class="muted">Not enough public data yet.</text>'
    max_count = max(item["count"] for item in top_repos) or 1
    parts = []
    for i, item in enumerate(top_repos[:5]):
        yy = y + i * 42
        width = max(18, int(360 * item["count"] / max_count))
        color = item.get("color") or "#7DD3A8"
        name = escape(item["name"][:24])
        count = item["count"]
        parts.append(f'<text x="{x}" y="{yy}" class="repo">{name}</text>')
        parts.append(f'<rect x="{x}" y="{yy + 10}" width="360" height="10" rx="5" fill="#1F2937"/>')
        parts.append(f'<rect x="{x}" y="{yy + 10}" width="{width}" height="10" rx="5" fill="{color}"/>')
        parts.append(f'<text x="{x + 386}" y="{yy + 18}" class="count">{count}</text>')
    return "\n    ".join(parts)


def render_svg(user: dict) -> str:
    cc = user["contributionsCollection"]
    calendar_days = [day for week in cc["contributionCalendar"]["weeks"] for day in week["contributionDays"]]
    recent_30 = sum(int(d["contributionCount"] or 0) for d in calendar_days[-30:])
    recent_7 = sum(int(d["contributionCount"] or 0) for d in calendar_days[-7:])
    current_streak, best_streak, highest, average = streak_stats(calendar_days)
    contributed = int((user.get("repositoriesContributedTo") or {}).get("totalCount") or 0)

    top_repos = []
    for item in cc["commitContributionsByRepository"]:
        repo = item["repository"]
        if repo.get("isPrivate"):
            continue
        top_repos.append({
            "name": repo["name"],
            "url": repo["url"],
            "count": int(item["contributions"]["totalCount"] or 0),
            "color": (repo.get("primaryLanguage") or {}).get("color") or "#7DD3A8",
        })
    top_repos.sort(key=lambda r: r["count"], reverse=True)

    recent_repos = [r for r in user["repositories"]["nodes"] if not r.get("isFork")]
    if recent_repos:
        direction = recent_repos[0]["name"]
        direction_date = short_date(recent_repos[0]["pushedAt"])
    else:
        direction = top_repos[0]["name"] if top_repos else "open workshop"
        direction_date = date.today().strftime("%d %b")

    direction_short = direction[:18]

    isometric = render_calendar(calendar_days)
    bars = progress_bars(top_repos)

    return f'''<svg width="1200" height="430" viewBox="0 0 1200 430" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">Live activity for {escape(USERNAME)}</title>
  <desc id="desc">Public contribution metrics, commits, isometric calendar, and active repositories.</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1200" y2="430" gradientUnits="userSpaceOnUse">
      <stop stop-color="#0B1116"/>
      <stop offset="0.55" stop-color="#101C24"/>
      <stop offset="1" stop-color="#1A1333"/>
    </linearGradient>
    <linearGradient id="edge" x1="0" y1="0" x2="1200" y2="430" gradientUnits="userSpaceOnUse">
      <stop stop-color="#7DD3A8"/><stop offset="0.5" stop-color="#F4B860"/><stop offset="1" stop-color="#C084FC"/>
    </linearGradient>
    <filter id="isoBrightness1">
      <feComponentTransfer>
        <feFuncR type="linear" slope="0.6"/><feFuncG type="linear" slope="0.6"/><feFuncB type="linear" slope="0.6"/>
      </feComponentTransfer>
    </filter>
    <filter id="isoBrightness2">
      <feComponentTransfer>
        <feFuncR type="linear" slope="0.2"/><feFuncG type="linear" slope="0.2"/><feFuncB type="linear" slope="0.2"/>
      </feComponentTransfer>
    </filter>
    <style>
      .eyebrow{{font:700 14px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:2.4px;fill:#9CA3AF;text-transform:uppercase}}
      .title{{font:800 34px ui-serif,Georgia,'Times New Roman',serif;fill:#F8FAFC}}
      .value{{font:800 44px ui-serif,Georgia,'Times New Roman',serif;fill:#F8FAFC}}
      .label{{font:600 15px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#A7F3D0}}
      .muted{{font:500 16px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#9CA3AF}}
      .repo{{font:650 16px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#E5E7EB}}
      .count{{font:650 15px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#F4B860}}
      .copy{{font:400 19px ui-serif,Georgia,'Times New Roman',serif;fill:#D1D5DB}}
    </style>
  </defs>

  <rect width="1200" height="430" rx="30" fill="url(#bg)"/>
  <rect x="1" y="1" width="1198" height="428" rx="29" stroke="url(#edge)" stroke-opacity="0.42"/>

  <text x="50" y="58" class="eyebrow">live activity</text>
  <text x="50" y="98" class="title">stats</text>

  <rect x="50" y="126" width="140" height="96" rx="22" fill="#111827" fill-opacity="0.82" stroke="#7DD3A8" stroke-opacity="0.22"/>
  <text x="76" y="162" class="value">{cc['contributionCalendar']['totalContributions']}</text>
  <text x="76" y="196" class="label">contribs/year</text>

  <rect x="214" y="126" width="140" height="96" rx="22" fill="#111827" fill-opacity="0.82" stroke="#F4B860" stroke-opacity="0.22"/>
  <text x="240" y="162" class="value">{cc['totalCommitContributions']}</text>
  <text x="240" y="196" class="label">commits/year</text>

  <rect x="378" y="126" width="140" height="96" rx="22" fill="#111827" fill-opacity="0.82" stroke="#C084FC" stroke-opacity="0.22"/>
  <text x="404" y="162" class="value">{recent_30}</text>
  <text x="404" y="196" class="label">30 days</text>

  <text x="50" y="254" class="eyebrow">3d calendar</text>
  {isometric}
  <text x="50" y="404" class="muted">last 182 days · last 7 days: {recent_7}</text>

  <text x="574" y="58" class="eyebrow">most commits this year</text>
  {bars}

  <rect x="574" y="318" width="552" height="46" rx="23" fill="#0B1116" fill-opacity="0.7" stroke="#F7E6B1" stroke-opacity="0.16"/>
  <text x="604" y="348" class="copy">last push: {escape(direction_short)} · {escape(direction_date)}</text>
  <text x="574" y="394" class="muted">streak: {current_streak}d · best: {best_streak}d · daily max: {highest} · avg: ~{average}</text>
  <text x="574" y="418" class="muted">contributed to {contributed} public/visible repositories</text>
</svg>
'''


def main() -> int:
    user = gh_graphql()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render_svg(user), encoding="utf-8")
    print(f"Updated {OUT.relative_to(ROOT)} for {USERNAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
