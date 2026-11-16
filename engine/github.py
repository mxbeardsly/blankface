"""Tiny GitHub REST client for the review queue (issues + release assets)."""
from __future__ import annotations

import os
from pathlib import Path

import requests

from .core import OFFLINE

API = "https://api.github.com"
RELEASE_TAG = "review-videos"


def _repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY", "local/offline")


def _h(extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
         "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    h.update(extra or {})
    return h


def _req(method: str, url: str, **kw):
    r = requests.request(method, url if url.startswith("http") else f"{API}{url}",
                         headers=kw.pop("headers", None) or _h(), timeout=kw.pop("timeout", 60), **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub {method} {url} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


def ensure_labels() -> None:
    if OFFLINE:
        return
    want = {"review": "fbca04", "approved": "0e8a16", "rejected": "b60205",
            "posted": "5319e7", "expired": "cccccc", "report": "1d76db", "bot-alert": "d93f0b"}
    have = {l["name"] for l in _req("GET", f"/repos/{_repo()}/labels?per_page=100")}
    for name, color in want.items():
        if name not in have:
            _req("POST", f"/repos/{_repo()}/labels", json={"name": name, "color": color})


def _release() -> dict:
    try:
        return _req("GET", f"/repos/{_repo()}/releases/tags/{RELEASE_TAG}")
    except RuntimeError:
        return _req("POST", f"/repos/{_repo()}/releases", json={
            "tag_name": RELEASE_TAG, "name": "Videos awaiting review",
            "body": "Bot managed. Files here are deleted after they post or expire.",
            "prerelease": True})


def upload_asset(path: Path) -> dict:
    if OFFLINE:
        return {"id": 0, "browser_download_url": f"file://{path}", "name": path.name}
    rel = _release()
    url = rel["upload_url"].split("{")[0] + f"?name={path.name}"
    with open(path, "rb") as f:
        return _req("POST", url, data=f, timeout=600,
                    headers=_h({"Content-Type": "video/mp4" if path.suffix == ".mp4" else "image/jpeg"}))


def download_asset(asset_id: int, dest: Path) -> Path:
    url = f"{API}/repos/{_repo()}/releases/assets/{asset_id}"
    with requests.get(url, headers=_h({"Accept": "application/octet-stream"}),
                      stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dest


def delete_asset(asset_id: int) -> None:
    if OFFLINE or not asset_id:
        return
    try:
        _req("DELETE", f"/repos/{_repo()}/releases/assets/{asset_id}")
    except RuntimeError:
        pass


def create_issue(title: str, body: str, labels: list[str]) -> int:
    if OFFLINE:
        print(f"\n--- ISSUE: {title}\n{body}\n")
        return 0
    return _req("POST", f"/repos/{_repo()}/issues",
                json={"title": title, "body": body, "labels": labels})["number"]


def issue(number: int) -> dict:
    return _req("GET", f"/repos/{_repo()}/issues/{number}")


def comments(number: int) -> list[dict]:
    return _req("GET", f"/repos/{_repo()}/issues/{number}/comments?per_page=100")


def comment(number: int, body: str) -> None:
    if OFFLINE:
        print(f"[comment #{number}] {body}")
        return
    _req("POST", f"/repos/{_repo()}/issues/{number}/comments", json={"body": body})


def close(number: int, label: str) -> None:
    if OFFLINE:
        return
    _req("POST", f"/repos/{_repo()}/issues/{number}/labels", json={"labels": [label]})
    try:
        _req("DELETE", f"/repos/{_repo()}/issues/{number}/labels/review")
    except RuntimeError:
        pass
    _req("PATCH", f"/repos/{_repo()}/issues/{number}", json={"state": "closed"})


def owner() -> str:
    return _repo().split("/")[0]
