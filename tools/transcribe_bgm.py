# -*- coding: utf-8 -*-
"""Analyze BGM candidates in non-speech windows of the published mixed track.

The input is the same published/final mixed audio used by speech transcription.
Transcript segments are used only as an exclusion mask; this tool never treats
an independent music URL as the video's BGM and never runs a second Whisper pass.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe  # noqa: E402
from audio_source import cached_speech, speech_items  # noqa: E402

try:
    import numpy as np
except Exception:
    sys.exit("[ERR] 需 numpy：安装分析运行库后重试")


BGM_CACHE_VERSION = "published-mixed-track-bgm-v3"
SR = 16000
FLEN = int(0.025 * SR)
FSTEP = int(0.010 * SR)
LOWF = 200.0
SPEECH_MARGIN = 0.15
MIN_NON_SPEECH_SECONDS = 3.0
MIN_NON_SPEECH_COVERAGE = 0.10


def _decoded_audio(path):
    try:
        import av
    except Exception:
        raise RuntimeError("需 av：分析运行库未装")
    container = av.open(path)
    try:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            return None
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SR)
        out = []
        for frame in container.decode(stream):
            for rf in resampler.resample(frame):
                out.append(rf.to_ndarray().reshape(-1))
        if not out:
            return None
        return np.concatenate(out).astype(np.float32) / 32768.0
    finally:
        container.close()


def _rms_frames(x):
    if x is None or len(x) == 0:
        return np.zeros(1), 0.0, 0.0, 1.0
    n_frames = max(1, (len(x) - FLEN) // FSTEP + 1)
    if len(x) < FLEN:
        rms = np.asarray([np.sqrt(np.mean(np.square(x, dtype=np.float64)))], dtype=float)
    else:
        starts = np.arange(n_frames, dtype=np.int64) * FSTEP
        power = np.square(x, dtype=np.float64)
        cumulative = np.concatenate((np.zeros(1, dtype=np.float64), np.cumsum(power)))
        sums = cumulative[starts + FLEN] - cumulative[starts]
        rms = np.sqrt(sums / FLEN)
    return rms, float(rms.mean()), float(rms.std()), float((rms < 0.01).mean())


def _lowfreq_ratio(x):
    if x is None or len(x) < 1024:
        return 0.0
    nfft = 2048
    x = x[: min(len(x), int(SR * 30), 60 * nfft)]
    low, total = 0.0, 1e-9
    for start in range(0, len(x), nfft):
        blk = x[start:start + nfft]
        if len(blk) < 2:
            continue
        spectrum = np.abs(np.fft.rfft(blk * np.hanning(len(blk))))
        freqs = np.fft.rfftfreq(len(blk), 1.0 / SR)
        low += float(spectrum[freqs < LOWF].sum())
        total += float(spectrum.sum())
    return low / total if total else 0.0


def classify(x):
    """Classify only the concatenated non-speech windows; no ASR/text signal."""
    if x is None or len(x) < FLEN:
        return {"bgm_level": "unknown", "vocal": "unknown", "mood": "unknown",
                "energy": None, "energy_var": None, "silence": None, "lfe_ratio": None}
    _, emean, evar, sil = _rms_frames(x)
    lfe = _lowfreq_ratio(x)
    if lfe >= 0.55:
        bgm = "full" if emean >= 0.18 else "light"
    elif lfe >= 0.35:
        bgm = "light" if emean < 0.25 else "full"
    elif emean >= 0.12 and evar < 0.15:
        bgm = "light"
    else:
        bgm = "none"
    if emean >= 0.32:
        mood = "强节奏/重鼓点" if evar < 0.12 else "明快节奏"
    elif emean <= 0.10:
        mood = "平静铺垫"
    elif evar >= 0.10:
        mood = "叙事起伏"
    else:
        mood = "明快节奏"
    return {"bgm_level": bgm, "vocal": "unknown", "mood": mood,
            "energy": round(emean, 4), "energy_var": round(evar, 4),
            "silence": round(sil, 3), "lfe_ratio": round(lfe, 3)}


def _speech_windows(duration, transcript, margin=SPEECH_MARGIN):
    """Return complement windows and a status explaining missing/invalid masks."""
    if not isinstance(transcript, dict):
        return [], "missing_transcript"
    raw = []
    for segment in transcript.get("segments") or []:
        try:
            start = max(0.0, float(segment.get("start")))
            end = min(duration, float(segment.get("end")))
        except (TypeError, ValueError):
            continue
        if end > start:
            raw.append((max(0.0, start - margin), min(duration, end + margin)))
    if not raw:
        return [], "missing_segments"
    raw.sort()
    merged = []
    for start, end in raw:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    windows, cursor = [], 0.0
    for start, end in merged:
        if start > cursor:
            windows.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        windows.append((cursor, duration))
    windows = [(round(s, 3), round(e, 3)) for s, e in windows if e - s > 0.02]
    return windows, "segment_mask"


def _window_audio(audio, windows):
    chunks = []
    actual = []
    for start, end in windows:
        lo = max(0, int(round(start * SR)))
        hi = min(len(audio), int(round(end * SR)))
        if hi > lo:
            chunks.append(audio[lo:hi])
            actual.append((lo / SR, hi / SR))
    return (np.concatenate(chunks) if chunks else None), actual


def _atomic_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _transcript_fingerprint(path):
    if not path or not os.path.isfile(path):
        return None
    s = os.stat(path)
    return {"mtime": s.st_mtime, "size": s.st_size}


def _cached_audio_result(result):
    if not isinstance(result, (tuple, list)) or not result:
        raise RuntimeError("cached_speech return_meta 必须返回音频元组")
    values = list(result) + [""] * 5
    return (str(values[0]), str(values[1] or "unknown"), str(values[2] or ""),
            str(values[3] or ""), str(values[4] or ""))


def _record_base(aid, cfg_hash, transcript_fp, requested_music_asr):
    record = {"cache_version": BGM_CACHE_VERSION, "config_hash": cfg_hash,
              "aweme_id": aid, "source_kind": "mixed_track", "analysis_scope": "non_speech_windows",
              "speech_margin_seconds": SPEECH_MARGIN, "transcript_fingerprint": transcript_fp,
              "music_asr_requested": bool(requested_music_asr),
              "music_asr_status": "deprecated_ignored", "text_source": "deprecated_ignored",
              "bgm_text": "", "vocal": "unknown", "bgm_level": "unknown", "mood": "unknown",
              "analysis_status": "insufficient_evidence", "source_status": "insufficient_evidence",
              "non_speech_seconds": 0.0,
              "non_speech_coverage": 0.0, "non_speech_windows": [],
              "limitations": []}
    if requested_music_asr:
        record["limitations"].append("--music-asr 已弃用并忽略；不会对 published mixed track 重复 Whisper")
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--model", default="large-v3", help="兼容保留；BGM 不再加载 Whisper")
    ap.add_argument("--device", default="auto", help="兼容保留；BGM 不再加载 Whisper")
    ap.add_argument("--compute", default="auto", help="兼容保留；BGM 不再加载 Whisper")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--music-asr", action="store_true",
                    help="已弃用兼容参数：忽略，不重复 Whisper，并在 JSON 记录 deprecated_ignored")
    a = ap.parse_args()

    od = os.path.join(a.root, "bgm", a.account)
    os.makedirs(od, exist_ok=True)
    try:
        items = speech_items(a.root, a.account)
    except Exception as e:
        sys.exit(f"[ERR] {e}")
    try:
        import ctranslate2
        has_cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        has_cuda = False
    workers = a.workers or probe.transcribe_workers(has_cuda)
    cfg_payload = {"version": BGM_CACHE_VERSION, "source_kind": "mixed_track",
                   "analysis_scope": "non_speech_windows", "speech_margin": SPEECH_MARGIN,
                   "min_non_speech_seconds": MIN_NON_SPEECH_SECONDS,
                   "min_non_speech_coverage": MIN_NON_SPEECH_COVERAGE,
                   "music_asr_requested": bool(a.music_asr)}
    cfg_hash = hashlib.sha256(json.dumps(cfg_payload, sort_keys=True).encode()).hexdigest()[:24]

    def transcript_path(aid):
        return os.path.join(a.root, "transcript", a.account, aid + ".json")

    def done(aid):
        jp = os.path.join(od, aid + ".json")
        try:
            data = json.load(open(jp, encoding="utf-8"))
            if data.get("cache_version") != BGM_CACHE_VERSION or data.get("config_hash") != cfg_hash:
                return False
            if data.get("source_kind") != "mixed_track":
                return False
            if data.get("transcript_fingerprint") != _transcript_fingerprint(transcript_path(aid)):
                return False
            status = data.get("analysis_status") or data.get("source_status")
            if status == "missing":
                return True
            if status not in ("ok", "insufficient_evidence"):
                return False
            path = os.path.join(a.root, str(data.get("audio_path") or ""))
            expected = str(data.get("audio_sha256") or "")
            return (bool(expected) and os.path.isfile(path) and os.path.getsize(path) > 0
                    and _sha256(path) == expected)
        except Exception:
            return False

    if a.music_asr:
        print("[deprecated] --music-asr 已忽略：published mixed track 不重复 Whisper", flush=True)
    print(f"[source] published mixed track -> {od} | workers={workers}", flush=True)

    def one(item):
        aid, video_url, policy, published_url, published_key = item
        jp = os.path.join(od, aid + ".json")
        if done(aid):
            return aid, "skip"
        transcript_fp = _transcript_fingerprint(transcript_path(aid))
        record = _record_base(aid, cfg_hash, transcript_fp, a.music_asr)
        t0 = time.time()
        try:
            if not video_url and not published_url:
                record["analysis_status"] = "missing"
                record["source_status"] = "missing"
                record["limitations"].append("缺少视频与 published 音频来源，无法取得混合音轨")
                _atomic_json(jp, record)
                return aid, "missing published audio URL"
            result = cached_speech(a.root, a.account, aid, video_url, published_url,
                                   published_key, return_meta=True)
            audio_path, audio_origin, source_url_hash, fallback_reason, migrated_from = _cached_audio_result(result)
            audio = _decoded_audio(audio_path)
            if audio is None or len(audio) == 0:
                raise RuntimeError("published mixed track 无可解码音频")
            duration = len(audio) / SR
            record.update({"source": "published_audio", "audio_origin": audio_origin,
                           "source_url_hash": source_url_hash, "fallback_reason": fallback_reason,
                           "migrated_from": migrated_from, "analysis_status": "ok",
                           "source_status": "ok", "audio_sha256": _sha256(audio_path),
                           "audio_path": os.path.relpath(audio_path, a.root).replace(os.sep, "/"),
                           "duration_seconds": round(duration, 3), "speech_source": policy})
            try:
                transcript = json.load(open(transcript_path(aid), encoding="utf-8"))
            except Exception:
                transcript = None
            windows, window_status = _speech_windows(duration, transcript)
            analysis_audio, actual_windows = _window_audio(audio, windows)
            non_speech_seconds = sum(end - start for start, end in actual_windows)
            coverage = non_speech_seconds / duration if duration else 0.0
            record.update({"analysis_scope": "non_speech_windows",
                           "transcript_status": window_status,
                           "non_speech_windows": [{"start": round(s, 3), "end": round(e, 3),
                                                    "duration": round(e - s, 3)} for s, e in actual_windows],
                           "non_speech_seconds": round(non_speech_seconds, 3),
                           "non_speech_coverage": round(coverage, 4)})
            if window_status != "segment_mask":
                record["analysis_status"] = "insufficient_evidence"
                record["source_status"] = "insufficient_evidence"
                record["limitations"].append("缺少有效 transcript segments，无法排除口播窗口")
            elif non_speech_seconds < MIN_NON_SPEECH_SECONDS or coverage < MIN_NON_SPEECH_COVERAGE:
                record["analysis_status"] = "insufficient_evidence"
                record["source_status"] = "insufficient_evidence"
                record["limitations"].append("非口播窗口不足 3 秒或不足音频时长 10%，不强判 BGM")
            else:
                record.update(classify(analysis_audio))
                record["analysis_status"] = "ok"
                record["source_status"] = "ok"
                record["limitations"].append("BGM 为混合音轨非口播窗口候选，非独立纯 BGM 识别")
            _atomic_json(jp, record)
            return aid, f"ok {record['source_status']}/{record['bgm_level']} {time.time()-t0:.1f}s"
        except Exception as e:
            record["analysis_status"] = "error"
            record["source_status"] = "error"
            record["error"] = str(e)[:180]
            record["limitations"].append("published mixed track 下载或解码失败")
            _atomic_json(jp, record)
            return aid, f"ERR {str(e)[:100]}"

    pending = [item for item in items if not done(item[0])]
    print(f"[start] {len(pending)} published mixed-track records -> {od}", flush=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(one, item) for item in pending]
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            aid, note = future.result()
            results.append(note)
            print(f"  [{i}/{len(pending)}] {aid}: {note}", flush=True)

    records = []
    for aid, _, _, _, _ in items:
        try:
            records.append(json.load(open(os.path.join(od, aid + ".json"), encoding="utf-8")))
        except Exception:
            pass
    evidence = [r for r in records if (r.get("analysis_status") or r.get("source_status")) == "ok"
                and r.get("bgm_level") in ("none", "light", "full")]
    status_counts = {}
    for record in records:
        status = record.get("analysis_status") or record.get("source_status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    agg = {"cache_version": BGM_CACHE_VERSION, "source_kind": "mixed_track",
           "analysis_scope": "non_speech_windows", "analysis_status_counts": status_counts,
           "n": len(evidence),
           "total_records": len(records), "excluded_records": len(records) - len(evidence),
           "by_bgm": {}, "by_mood": {}, "by_vocal": {},
           "limitations": ["仅统计有足够非口播窗口证据的记录；相关统计非因果"]}
    for record in evidence:
        for group, field in (("by_bgm", "bgm_level"), ("by_mood", "mood"), ("by_vocal", "vocal")):
            value = record.get(field, "unknown")
            agg[group][value] = agg[group].get(value, 0) + 1
    _atomic_json(os.path.join(od, "_manifest.json"), agg)
    errs = [r for r in results if r.startswith("ERR")]
    print(f"[聚合] {json.dumps(agg, ensure_ascii=False)}", flush=True)
    print(f"[done] total={len(results)} ok={len(results)-len(errs)} err={len(errs)}", flush=True)
    if errs:
        sys.exit(1)


if __name__ == "__main__":
    main()
