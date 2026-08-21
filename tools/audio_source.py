# -*- coding: utf-8 -*-
"""Shared audio sources and caches for speech and music analysis."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.request

HEADERS = {
    "User-Agent": "Mozilla/5.0 Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.douyin.com/",
}
_MUSIC_LOCKS = {}
_MUSIC_LOCKS_GUARD = threading.Lock()
_PUBLISHED_LOCKS = {}
_PUBLISHED_LOCKS_GUARD = threading.Lock()


def _read_manifest(root, account):
    path = os.path.join(root, "video-analysis", account, "manifest.json")
    if not os.path.exists(path):
        raise RuntimeError(f"缺少抓取 manifest: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception as e:
        raise RuntimeError(f"无法读取 manifest: {e}") from e
    if not isinstance(rows, list):
        raise RuntimeError("manifest 必须是数组")
    return rows


def _is_video(row):
    try:
        return int(row.get("aweme_type") or 0) != 68
    except (TypeError, ValueError):
        return True


def speech_items(root, account):
    """Return speech URL plus published mixed-track URL for video works."""
    items = []
    for row in _read_manifest(root, account):
        aid = str(row.get("aweme_id") or "")
        if aid and _is_video(row):
            published_url = str(row.get("published_audio_url") or row.get("music_url") or "")
            if not published_url and str(row.get("audio_source") or "") in ("music_url", "music_download_url"):
                published_url = str(row.get("audio_url") or "")
            published_key = str(row.get("published_audio_key") or row.get("music_key") or music_key(published_url)) if published_url else ""
            items.append((aid, str(row.get("speech_url") or row.get("video_url") or ""),
                          str(row.get("speech_source") or "local_video_then_remote_video"),
                          published_url, published_key))
    if not items:
        raise RuntimeError("manifest 中没有可处理视频")
    return items


def music_items(root, account):
    """Return (aweme_id, music URL, URL key); no video fallback is allowed."""
    items = []
    for row in _read_manifest(root, account):
        aid = str(row.get("aweme_id") or "")
        if aid and _is_video(row):
            url = str(row.get("music_url") or "")
            key = str(row.get("music_key") or music_key(url)) if url else ""
            items.append((aid, url, key))
    if not items:
        raise RuntimeError("manifest 中没有可处理视频")
    return items


def manifest_items(root, account):
    """Compatibility alias: transcript callers now receive speech items."""
    return speech_items(root, account)


def music_key(url):
    if not url:
        return ""
    return hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:24]


published_key = music_key


def file_sha256(path, block_size=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _download(url, path):
    """Download atomically and remove all temporary files on failure."""
    if not url:
        raise RuntimeError("missing URL")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
            while True:
                block = resp.read(1 << 20)
                if not block:
                    break
                f.write(block)
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            raise RuntimeError("empty audio response")
        os.replace(tmp, path)
        return path
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def _audio_is_decodable(path):
    """Require a readable audio stream and at least one decoded frame."""
    try:
        import av
        container = av.open(path)
        try:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                return False
            next(container.decode(stream), None)
            return True
        finally:
            container.close()
    except Exception:
        return False


def _published_lock(path):
    with _PUBLISHED_LOCKS_GUARD:
        return _PUBLISHED_LOCKS.setdefault(os.path.abspath(path), threading.Lock())


def _copy_atomic(source, target):
    """Copy a validated legacy cache without deleting its source."""
    directory = os.path.dirname(target)
    fd, tmp = tempfile.mkstemp(prefix="published-migrate-", suffix=".part", dir=directory)
    try:
        with os.fdopen(fd, "wb") as out, open(source, "rb") as src:
            while True:
                block = src.read(1 << 20)
                if not block:
                    break
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def cached_published(root, account, url, key=None, aweme_id=None, return_meta=False):
    """Cache the published mixed soundtrack under media-audio/.../published."""
    if not url:
        raise RuntimeError("missing published_audio_url")
    computed_key = published_key(url)
    key = computed_key if not key or key != computed_key else key
    directory = os.path.join(root, "media-audio", account, "published")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, key + ".mp3")
    with _published_lock(path):
        if os.path.isfile(path) and os.path.getsize(path) > 0 and _audio_is_decodable(path):
            result = (path, "")
            return result if return_meta else path
        legacy = []
        if aweme_id:
            legacy.append(os.path.join(root, "bgm", account, "audio", str(aweme_id) + ".mp3"))
        legacy.append(os.path.join(root, "media-audio", account, "music", key + ".mp3"))
        for old_path in legacy:
            if os.path.isfile(old_path) and os.path.getsize(old_path) > 0 and _audio_is_decodable(old_path):
                _copy_atomic(old_path, path)
                if _audio_is_decodable(path):
                    result = (path, old_path)
                    return result if return_meta else path
        path = _download(url, path)
        if not _audio_is_decodable(path):
            try:
                os.remove(path)
            except OSError:
                pass
            raise RuntimeError("published audio decode validation failed")
        result = (path, "")
        return result if return_meta else path


def _ffmpeg_extract(video_path, output_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg，无法从视频提取口播音轨")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="speech-", suffix=".m4a.tmp",
                               dir=os.path.dirname(output_path))
    os.close(fd)
    try:
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-i", video_path, "-map", "0:a:0", "-vn", "-c:a", "aac",
               "-b:a", "128k", "-movflags", "+faststart", "-f", "ipod", tmp]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=300, check=False)
        if proc.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            detail = proc.stderr.decode("utf-8", errors="replace")[-180:]
            raise RuntimeError(f"ffmpeg 提取失败: {detail}")
        os.replace(tmp, output_path)
        return output_path
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def cached_speech(root, account, aweme_id, video_url="", published_url="", published_key_value="", return_meta=False):
    """Resolve speech from published mixed audio, then local/remote video fallback.

    Legacy callers still receive ``(path, source_kind)``. With ``return_meta``
    the result also includes ``migrated_from`` as the fifth value.
    """
    fallback_reason = ""
    migrated_from = ""
    computed_published_hash = published_key(published_url) if published_url else ""
    published_hash = computed_published_hash
    if published_url:
        try:
            path, migrated_from = cached_published(root, account, published_url, published_hash,
                                                   aweme_id=aweme_id, return_meta=True)
            result = (path, "mixed_track", published_hash, "", migrated_from)
            return result if return_meta else result[:2]
        except Exception as e:
            fallback_reason = f"published_audio_failed:{str(e)[:120]}"
    speech_dir = os.path.join(root, "media-audio", account, "speech")
    os.makedirs(speech_dir, exist_ok=True)
    path = os.path.join(speech_dir, str(aweme_id) + ".m4a")
    local_video = os.path.join(root, "videos", account, str(aweme_id) + ".mp4")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        if not (os.path.exists(local_video) and os.path.getsize(local_video) > 0):
            result = (path, "cached_speech", published_hash, fallback_reason or "local_video_missing", migrated_from)
            return result if return_meta else result[:2]
        try:
            if os.path.getmtime(path) >= os.path.getmtime(local_video):
                result = (path, "local_video", published_hash, fallback_reason or "", migrated_from)
                return result if return_meta else result[:2]
        except OSError:
            # If timestamps cannot be read, re-extract from the authoritative local video.
            pass

    if os.path.exists(local_video) and os.path.getsize(local_video) > 0:
        try:
            result = (_ffmpeg_extract(local_video, path), "local_video", published_hash, fallback_reason or "", migrated_from)
            return result if return_meta else result[:2]
        except Exception as local_error:
            if not video_url:
                raise local_error
            fallback_reason = (fallback_reason + ";" if fallback_reason else "") + f"local_video_failed:{str(local_error)[:120]}"

    if not video_url:
        raise RuntimeError("missing local video and speech_url")
    fd, remote_tmp = tempfile.mkstemp(prefix="speech-video-", suffix=".mp4.tmp",
                                      dir=speech_dir)
    os.close(fd)
    try:
        _download(video_url, remote_tmp)
        result = (_ffmpeg_extract(remote_tmp, path), "remote_video", published_hash,
                  fallback_reason or "local_video_missing", migrated_from)
        return result if return_meta else result[:2]
    finally:
        if os.path.exists(remote_tmp):
            try:
                os.remove(remote_tmp)
            except OSError:
                pass


def cached_music(root, account, url, key=None):
    """Download a unique music URL into media-audio/.../music/<key>.mp3."""
    if not url:
        raise RuntimeError("missing music_url")
    key = key or music_key(url)
    music_dir = os.path.join(root, "media-audio", account, "music")
    os.makedirs(music_dir, exist_ok=True)
    path = os.path.join(music_dir, key + ".mp3")
    with _MUSIC_LOCKS_GUARD:
        lock = _MUSIC_LOCKS.setdefault(os.path.abspath(path), threading.Lock())
    with lock:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        return _download(url, path)


def cached_audio(root, account, aweme_id, url, source="music_download_url"):
    """Legacy adapter; new code should call cached_speech/cached_music."""
    if source in ("music_download_url", "music_url", "music"):
        return cached_music(root, account, url)
    path, _ = cached_speech(root, account, aweme_id, url)
    return path
