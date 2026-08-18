# -*- coding: utf-8 -*-
"""多线程下载视频+封面。并发默认 3 线程（规避抖音 CDN 风控）。
用法: python tools/download.py --root <工作根> --account <slug> [--threads N]
输入: <root>/video-analysis/<account>/manifest.json
输出: <root>/videos/<account>/*.mp4, <root>/covers/<account>/*.jpg
"""
import argparse, json, os, sys, urllib.request, concurrent.futures, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe  # noqa: E402

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://www.douyin.com/",
}


def download(url, path):
    if not url:
        return False, "no-url"
    if os.path.exists(path) and os.path.getsize(path) > 8192:
        return True, "exists"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
        return (os.path.getsize(path) > 8192), f"{os.path.getsize(path)}B"
    except Exception as e:
        return False, str(e)[:60]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True, help="账号 slug，如 nutelande")
    ap.add_argument("--threads", type=int, default=None,
                    help="并发下载线程数（缺省按机器配置调度 2..6）")
    a = ap.parse_args()

    t = a.threads or probe.download_threads()
    print(f"[资源] {probe.snapshot(probe.has_gpu())} -> 下载线程数={t}")

    mp = os.path.join(a.root, "video-analysis", a.account, "manifest.json")
    manifest = json.load(open(mp, encoding="utf-8"))
    vd = os.path.join(a.root, "videos", a.account)
    cd = os.path.join(a.root, "covers", a.account)
    os.makedirs(vd, exist_ok=True)
    os.makedirs(cd, exist_ok=True)

    def worker(it):
        aid = it["aweme_id"]
        ok, sub = download(it.get("video_url", ""), os.path.join(vd, f"{aid}.mp4"))
        try:
            download(it.get("cover_url", ""), os.path.join(cd, f"{aid}.jpg"))
        except Exception:
            pass
        return {"aweme_id": aid, "video_ok": ok, "note": sub}

    print(f"[下载] 共 {len(manifest)} 条，并发 {t} 线程")
    results, t0 = [], time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=t) as ex:
        futs = [ex.submit(worker, it) for it in manifest]
        for i, fu in enumerate(concurrent.futures.as_completed(futs), 1):
            r = fu.result()
            results.append(r)
            print(f"  [{i}/{len(manifest)}] {r['aweme_id']}: video_ok={r['video_ok']} {r['note']}")
    ok = sum(1 for r in results if r["video_ok"])
    print(f"[完成] 成功 {ok}/{len(manifest)}，耗时 {time.time()-t0:.0f}s")
    if ok < len(manifest):
        sys.exit(1)


if __name__ == "__main__":
    main()