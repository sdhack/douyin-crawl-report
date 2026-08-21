# -*- coding: utf-8 -*-
"""口播转写：从本地视频最终混合音轨提取 speech 音频后转写。

首轮使用 beam=1；只有低语言置信度、低平均 log probability 或空结果才
使用 beam=5 精转。产物带 cache_version/config_hash/audio_sha256 及实际
device/compute/runner，避免旧音源、旧参数或 GPU 回退缓存被误当成当前结果。
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
from audio_source import cached_speech, file_sha256, speech_items  # noqa: E402

CACHE_VERSION = "speech-transcript-v3"
CACHE_SCHEMA = "speech-cache-v3"


def find_cublas():
    import glob as g
    for base in list(sys.path):
        for p in g.glob(os.path.join(base, "nvidia", "cublas*", "bin")):
            if os.path.isdir(p) and p not in os.environ.get("PATH", ""):
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
                return


def load_terms(path):
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if k and v and k != v}
    except Exception as e:
        print(f"[warn] --map 解析失败，忽略: {e}", flush=True)
        return None


def correct(text, terms):
    if not terms or not text:
        return text
    for k, v in terms.items():
        text = text.replace(k, v)
    return text


def _config_hash(model, device, compute, terms):
    payload = {"model": model, "device": device, "compute": compute,
               "terms": terms or {}, "version": CACHE_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


def _atomic_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _avg_logprob(probs):
    vals = [float(x) for x in probs if x is not None]
    return sum(vals) / len(vals) if vals else None


def _valid_cached_transcript(data, root, cfg_hash, requested_device, requested_compute):
    """Validate without loading the model; device must match, compute may be a recorded runtime fallback."""
    if not isinstance(data, dict):
        return False
    if (data.get("cache_version") != CACHE_VERSION or
            data.get("cache_schema") != CACHE_SCHEMA or
            data.get("config_hash") != cfg_hash or
            data.get("requested_device") != requested_device or
            data.get("requested_compute") != requested_compute or
            data.get("actual_device") != requested_device or
            not data.get("actual_compute") or
            not data.get("runner") or
            "source_kind" not in data or
            "source_url_hash" not in data or
            "fallback_reason" not in data):
        return False
    audio_path = os.path.join(root, str(data.get("audio_path") or ""))
    try:
        if not os.path.isfile(audio_path) or os.path.getsize(audio_path) <= 0:
            return False
        expected_hash = str(data.get("audio_sha256") or "")
        return bool(expected_hash) and file_sha256(audio_path) == expected_hash
    except (OSError, ValueError):
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="auto", help="auto/cuda/cpu")
    ap.add_argument("--compute", default="auto", help="auto/float16/int8/float32")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--map", default=None, help="术语纠错映射 json：{误词: 正词}")
    a = ap.parse_args()

    find_cublas()
    try:
        import ctranslate2
        has_cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        ctranslate2 = None
        has_cuda = False

    od = os.path.join(a.root, "transcript", a.account)
    os.makedirs(od, exist_ok=True)
    try:
        inputs = speech_items(a.root, a.account)
    except Exception as e:
        sys.exit(f"[ERR] {e}")
    terms = load_terms(a.map)
    requested_device = "cuda" if (a.device == "auto" and has_cuda) else ("cpu" if a.device == "auto" else a.device)
    requested_compute = "float16" if (a.compute == "auto" and requested_device == "cuda") else ("int8" if a.compute == "auto" else a.compute)
    cfg_hash = _config_hash(a.model, requested_device, requested_compute, terms)

    def prod_valid(aid):
        jp = os.path.join(od, aid + ".json")
        tp = os.path.join(od, aid + ".txt")
        if not (os.path.exists(jp) and os.path.exists(tp)):
            return False
        try:
            data = json.load(open(jp, encoding="utf-8"))
            return _valid_cached_transcript(data, a.root, cfg_hash,
                                            requested_device, requested_compute)
        except Exception:
            return False

    def rewrite_existing(aid):
        if not terms:
            return False
        tp = os.path.join(od, aid + ".txt")
        jp = os.path.join(od, aid + ".json")
        try:
            with open(tp, encoding="utf-8") as f:
                txt = f.read()
            new_txt = correct(txt, terms)
            if new_txt != txt:
                with open(tp, "w", encoding="utf-8") as f:
                    f.write(new_txt)
            data = json.load(open(jp, encoding="utf-8"))
            for seg in data.get("segments", []):
                seg["text"] = correct(seg.get("text", ""), terms)
            _atomic_json(jp, data)
            return new_txt != txt
        except Exception:
            return False

    if all(prod_valid(item[0]) for item in inputs):
        fixed = sum(rewrite_existing(item[0]) for item in inputs)
        print(f"[skip-all] {len(inputs)} 个口播产物均为 {CACHE_VERSION}，订正 {fixed} 个 | {probe.snapshot(has_cuda)}", flush=True)
        return

    pending = [item for item in inputs if not prod_valid(item[0])]
    print(f"[env] cuda_count={has_cuda}", flush=True)
    workers = a.workers or probe.transcribe_workers(has_cuda)
    print(f"[资源] {probe.snapshot(has_cuda)} -> device={requested_device}/{requested_compute}，转写worker数={workers}", flush=True)

    from faster_whisper import WhisperModel

    def load_model(path, dev, comp):
        try:
            return WhisperModel(path, device=dev, compute_type=comp), dev, comp
        except (ValueError, RuntimeError, OSError) as e:
            if dev == "cuda" and comp == "float16":
                print(f"[warn] float16 不受支持({str(e)[:60]})，降级 int8_float32 重试", flush=True)
                try:
                    return WhisperModel(path, device="cuda", compute_type="int8_float32"), "cuda", "int8_float32"
                except (ValueError, RuntimeError, OSError):
                    pass
            if dev == "cuda":
                print("[warn] CUDA 后端不可用，回退 CPU int8", flush=True)
                return WhisperModel(path, device="cpu", compute_type="int8"), "cpu", "int8"
            raise

    model, device, compute = load_model(a.model, requested_device, requested_compute)
    print(f"[model] 实际生效 device={device}/{compute}", flush=True)
    if terms:
        print(f"[map] 术语纠错映射已启用：{len(terms)} 项", flush=True)

    # BatchedInferencePipeline is optional across faster-whisper versions.
    # Use it when available, but always fall back to the model API.
    runner = model.transcribe
    runner_name = "WhisperModel"
    try:
        from faster_whisper import BatchedInferencePipeline
        batched = BatchedInferencePipeline(model=model)
        runner = lambda path, **kwargs: batched.transcribe(path, batch_size=max(1, workers), **kwargs)
        runner_name = "BatchedInferencePipeline"
    except Exception as e:
        print(f"[warn] BatchedInferencePipeline 不可用，回退 WhisperModel: {str(e)[:80]}", flush=True)
    print(f"[runner] {runner_name}", flush=True)

    def transcribe_once(audio_path, beam):
        kwargs = dict(language="zh", beam_size=beam, vad_filter=True,
                      initial_prompt="以下是一段抖音口播视频的普通话转写，请准确识别产品专业名词、数字与品牌名。")
        try:
            segs, info = runner(audio_path, **kwargs)
            return list(segs), info
        except Exception:
            # Some batched versions reject an option; retry through the stable API.
            fallback_segs, fallback_info = model.transcribe(audio_path, **kwargs)
            return list(fallback_segs), fallback_info

    def one(item):
        aid, url, policy, published_url, published_key_value = (item + ("", ""))[:5]
        tp = os.path.join(od, aid + ".txt")
        jp = os.path.join(od, aid + ".json")
        t0 = time.time()
        try:
            audio_path, source_kind, source_url_hash, fallback_reason, migrated_from = cached_speech(
                a.root, a.account, aid, url, published_url, published_key_value, return_meta=True)
            audio_hash = file_sha256(audio_path)
            segs, info = transcribe_once(audio_path, 1)
            probs = [getattr(s, "avg_logprob", None) for s in segs]
            avg = _avg_logprob(probs)
            lang_prob = float(getattr(info, "language_probability", 0.0) or 0.0)
            needs_refine = not segs or lang_prob < 0.80 or (avg is not None and avg < -0.80)
            refined = False
            if needs_refine:
                segs, info = transcribe_once(audio_path, 5)
                probs = [getattr(s, "avg_logprob", None) for s in segs]
                avg = _avg_logprob(probs)
                lang_prob = float(getattr(info, "language_probability", 0.0) or 0.0)
                refined = True
            lines, serialized = [], []
            for s in segs:
                text = correct(s.text.strip(), terms)
                lines.append(f"[{s.start:06.2f} - {s.end:06.2f}] {text}")
                serialized.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
            with open(tp + ".tmp", "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            os.replace(tp + ".tmp", tp)
            data = {
                "cache_version": CACHE_VERSION, "cache_schema": CACHE_SCHEMA, "config_hash": cfg_hash,
                "audio_sha256": audio_hash, "aweme_id": aid,
                "requested_device": requested_device, "requested_compute": requested_compute,
                "actual_device": device, "actual_compute": compute, "runner": runner_name,
                "language": getattr(info, "language", "zh"),
                "language_probability": round(lang_prob, 3),
                "duration": round(float(getattr(info, "duration", 0.0) or 0.0), 2),
                "segments": serialized, "source": source_kind,
                "source_kind": source_kind, "source_url_hash": source_url_hash,
                "fallback_reason": fallback_reason, "migrated_from": migrated_from,
                "published_audio_url": published_url,
                "speech_source": source_kind,
                "speech_policy": policy,
                "audio_path": os.path.relpath(audio_path, a.root).replace(os.sep, "/"),
                "avg_logprob": round(avg, 3) if avg is not None else None,
                "decode_beam": 5 if refined else 1,
                "needs_visual_review": bool(lang_prob < 0.80 or not serialized or (avg is not None and avg < -0.8)),
            }
            _atomic_json(jp, data)
            return aid, f"ok {len(serialized)}segs source={source_kind} beam={data['decode_beam']} {time.time()-t0:.1f}s"
        except Exception as e:
            if os.path.exists(tp + ".tmp"):
                os.remove(tp + ".tmp")
            return aid, f"ERR {str(e)[:100]}"

    print(f"[start] {len(pending)} videos -> {od} ({device}, {workers} workers)", flush=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, item): item for item in pending}
        for i, fu in enumerate(concurrent.futures.as_completed(futs), 1):
            aid, note = fu.result()
            results.append(note)
            print(f"  [{i}/{len(pending)}] {aid}: {note}", flush=True)
    errs = [r for r in results if r.startswith("ERR")]
    print(f"[done] total={len(pending)} ok={len(pending)-len(errs)} err={len(errs)}", flush=True)
    if errs:
        sys.exit(1)


if __name__ == "__main__":
    main()
