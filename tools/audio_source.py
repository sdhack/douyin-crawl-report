# -*- coding: utf-8 -*-
"""Shared captured-audio source for transcript and BGM analysis."""
import json
import os
import urllib.request

HEADERS = {
    "User-Agent": "Mozilla/5.0 Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.douyin.com/",
}


def manifest_items(root, account):
    path = os.path.join(root, "video-analysis", account, "manifest.json")
    if not os.path.exists(path):
        raise RuntimeError(f"缺少抓取 manifest: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception as e:
        raise RuntimeError(f"无法读取 manifest: {e}") from e
    items = [(str(r.get("aweme_id", "")), str(r.get("music_url") or r.get("music_download_url") or ""))
             for r in rows if r.get("aweme_id")]
    if not items:
        raise RuntimeError("manifest 中没有可处理视频")
    return items


def cached_audio(root, account, aweme_id, url):
    if not url:
        raise RuntimeError("missing audio URL (manifest.music_url / music_download_url)")
    audio_dir = os.path.join(root, "bgm", account, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    path = os.path.join(audio_dir, aweme_id + ".mp3")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    tmp = path + ".part"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
            while True:
                block = resp.read(1024 * 1024)
                if not block:
                    break
                f.write(block)
        if os.path.getsize(tmp) == 0:
            raise RuntimeError("empty audio response")
        os.replace(tmp, path)
        return path
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
