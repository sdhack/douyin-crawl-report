# -*- coding: utf-8 -*-
"""douyin-crawl-report 技能第一阶段：调用 MediaCrawler 抓取抖音数据。

MediaCrawler 本体不随技能复制，保留在 `~/.cache/codex-mediacrawler/MediaCrawler`，
本脚本是技能内建的**轻量调度封装**：解析其解释器/源码根、拼接经校验的参数、
断点续传、进度日志、并把产物落到项目目录（不占 C 盘）。

用法:
  # 账号主页全量
  runtime.py run --tool crawl.py --root <根> --account <slug> \
      --mode creator --target "<sec_uid>" --max 90
  # 单条视频
  ... --mode detail --target "<aweme_id>"
  # 关键词搜索
  ... --mode search --target "关键词"
  # 想用 cookie 登录（复用已登录态）
  ... --lt cookie --cookies "<cookie串>"
  # 只打印将执行的命令，不真正爬（校验用）
  ... --dry-run

产物: <run-root>/crawl_<account>/  （原始 jsonl + 过滤去重 jsonl + crawl.log）
下一阶段: runtime.py run --tool process.py --root <root> --account <account> --json <过滤后jsonl>
"""
import argparse
import json
import os
import re
import random
import sys
import glob
import subprocess
import time
import datetime

try:
    import runtime  # noqa: F401  复用同目录 runtime.py 的解析逻辑
except Exception:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import runtime
from run_progress import RunProgress

PLATFORM = "dy"  # 抖音 固定
_MODES = ("creator", "detail", "search")
_LTS = ("qrcode", "cookie", "phone")
# --speed 预设并发（MediaCrawler 抖音多 context 并行，2-3 已是安全偏激进上限）
_SPEED_CONC = {"safe": 1, "normal": 2, "fast": 3}
_SAFE_ACCOUNT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def validate_account_slug(slug):
    """Keep every account inside its own predictable project directory."""
    if not _SAFE_ACCOUNT.fullmatch(slug) or slug in (".", ".."):
        sys.exit("[ERR] --account 仅允许 1-80 位字母、数字、点、下划线或连字符，且必须以字母或数字开头。")


def bind_account_identity(root, slug, mode, target, dry_run=False):
    """Bind a local slug to one creator sec_uid and reject cross-account mixing."""
    accounts_dir = os.path.join(root, "accounts")
    meta_path = os.path.join(accounts_dir, slug + ".json")
    current = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                current = json.load(f)
        except Exception as e:
            sys.exit(f"[ERR] 账号身份文件损坏，拒绝继续以免混入数据：{meta_path} ({e})")
    bound = current.get("creator_sec_uid")
    if mode == "creator" and bound and bound != target:
        sys.exit(
            f"[ERR] 账号 slug '{slug}' 已绑定其他 sec_uid，拒绝混写。\n"
            f"  已绑定: {bound}\n  本次: {target}\n"
            "  请为新账号使用不同的 --account slug。"
        )
    if dry_run:
        return meta_path
    os.makedirs(accounts_dir, exist_ok=True)
    if mode == "creator":
        current["creator_sec_uid"] = target
    current.update({
        "account": slug,
        "last_mode": mode,
        "last_target": target,
        "updated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "paths": {
            "crawl": f"crawl_{slug}",
            "manifest": f"video-analysis/{slug}",
            "videos": f"videos/{slug}",
            "covers": f"covers/{slug}",
            "transcript": f"transcript/{slug}",
            "bgm": f"bgm/{slug}",
            "decompose": f"decompose/{slug}",
            "reports": f"reports/{slug}",
        },
    })
    tmp = meta_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    os.replace(tmp, meta_path)
    return meta_path


def _run_marker(path):
    return os.path.join(path, ".douyin-crawl-run.json")


def _existing_run(path, slug):
    """Return True when path is an existing run root for this account."""
    marker = _run_marker(path)
    identity = os.path.join(path, "accounts", slug + ".json")
    account_files = glob.glob(os.path.join(path, "accounts", "*.json"))
    if not (os.path.isfile(marker) or account_files):
        return False
    if os.path.isfile(marker):
        try:
            data = json.load(open(marker, encoding="utf-8"))
        except Exception as e:
            sys.exit(f"[ERR] 运行目录标记损坏：{marker} ({e})")
        if data.get("account") != slug:
            sys.exit(f"[ERR] 运行目录属于账号 {data.get('account')}，不能用于 {slug}。")
    elif not os.path.isfile(identity):
        owners = ", ".join(os.path.splitext(os.path.basename(p))[0] for p in account_files)
        sys.exit(f"[ERR] 旧运行目录属于账号 {owners}，不能用于 {slug}。")
    return True


def _write_run_marker(path, slug):
    marker = _run_marker(path)
    if os.path.exists(marker):
        return
    with open(marker, "w", encoding="utf-8") as f:
        json.dump({"type": "douyin-crawl-report-run", "account": slug,
                   "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")},
                  f, ensure_ascii=False, indent=2)


def _pointer_path(parent, slug):
    return os.path.join(parent, f".douyin-crawl-current-{slug}.json")


def _set_pointer(parent, slug, run_root):
    path = _pointer_path(parent, slug)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"account": slug, "run_root": os.path.abspath(run_root),
                   "updated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")},
                  f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _current_run(parent, slug):
    pointer = _pointer_path(parent, slug)
    if os.path.isfile(pointer):
        try:
            path = os.path.abspath(json.load(open(pointer, encoding="utf-8")).get("run_root", ""))
            if os.path.isdir(path) and os.path.dirname(path) == parent and _existing_run(path, slug):
                return path
        except Exception:
            pass
    candidates = []
    for path in glob.glob(os.path.join(parent, slug + "-????????-??????*")):
        if os.path.isdir(path) and os.path.dirname(os.path.abspath(path)) == parent and _existing_run(path, slug):
            candidates.append(os.path.abspath(path))
    return max(candidates, key=os.path.getmtime) if candidates else None


def _acquire_run_lock(parent, slug, timeout=30):
    lock = os.path.join(parent, f".douyin-crawl-{slug}.lock")
    deadline = time.time() + timeout
    while True:
        try:
            os.mkdir(lock)
            return lock
        except FileExistsError:
            if time.time() >= deadline:
                sys.exit(f"[ERR] 等待其他 Agent 创建运行目录超时：{lock}")
            time.sleep(0.2)


def _release_run_lock(lock):
    try:
        os.rmdir(lock)
    except OSError:
        pass


def make_run_dir(parent, slug, explicit=None, new_run=False):
    """Resolve one cross-agent run root; only --new-run opens another collection session."""
    if explicit:
        path = os.path.abspath(explicit)
        os.makedirs(path, exist_ok=True)
        if os.listdir(path) and not _existing_run(path, slug):
            sys.exit(f"[ERR] --run-dir 已存在但不是账号 {slug} 的运行目录：{path}")
        parent = os.path.dirname(path)
    else:
        parent = os.path.abspath(parent)
        if os.path.isdir(parent) and _existing_run(parent, slug):
            _write_run_marker(parent, slug)
            return parent
        os.makedirs(parent, exist_ok=True)
        lock = _acquire_run_lock(parent, slug)
        try:
            if not new_run:
                current = _current_run(parent, slug)
                if current:
                    _write_run_marker(current, slug)
                    _set_pointer(parent, slug, current)
                    return current
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            path = os.path.join(parent, f"{slug}-{stamp}")
            suffix = 2
            while os.path.exists(path):
                path = os.path.join(parent, f"{slug}-{stamp}-{suffix}")
                suffix += 1
            os.makedirs(path, exist_ok=True)
            _write_run_marker(path, slug)
            _set_pointer(parent, slug, path)
            return path
        finally:
            _release_run_lock(lock)
    os.makedirs(path, exist_ok=True)
    _write_run_marker(path, slug)
    _set_pointer(parent, slug, path)
    return path


def validate_save_dir(run_root, account, save_dir):
    if not save_dir:
        return os.path.join(run_root, "crawl_" + account)
    path = os.path.abspath(save_dir)
    try:
        if os.path.commonpath([os.path.abspath(run_root), path]) != os.path.abspath(run_root):
            sys.exit("[ERR] --save-dir 必须位于本次运行目录内，禁止把数据写到运行目录外。")
    except ValueError:
        sys.exit("[ERR] --save-dir 与运行目录不在同一文件系统，禁止跨目录写入。")
    return path


def _patch_verify(p, marker, pat, new):
    """正则替换 MediaCrawler base_config 变量为 env 覆盖版，并回读验证生效（防静默假成功）。"""
    src = open(p, encoding="utf-8-sig").read()
    if marker in src:
        return "already"
    try:
        bak = p + ".bak"
        if not os.path.isfile(bak):
            open(bak, "w", encoding="utf-8").write(src)
        if not re.search(r"(?m)^import os", src):
            src = "import os\n" + src
        if not re.search(pat, src):
            return "no-var"
        src = re.sub(pat, new, src)
        open(p, "w", encoding="utf-8", newline="").write(src)
        # 回读校验：补丁必须真正落盘，否则报失败而非假装成功
        return "patched" if marker in open(p, encoding="utf-8").read() else "verify-failed"
    except Exception:
        return None


def ensure_mc_sleep_patch(mc_root):
    """给 MediaCrawler base_config 打一次性 env 补丁：CRAWLER_MAX_SLEEP_SEC 可由 MC_SLEEP_SEC 覆盖。

    不改逻辑默认值，仅注入 env。返回 ('patched'|'already'|'no-var'|'verify-failed'|None)。"""
    p = os.path.join(mc_root, "config", "base_config.py")
    if not os.path.isfile(p):
        return None
    pat = r"CRAWLER_MAX_SLEEP_SEC\s*=\s*(?:int|float)\([^)]*\)|\d+(?:\.\d+)?"
    return _patch_verify(p, "MC_SLEEP_SEC", pat,
                         'CRAWLER_MAX_SLEEP_SEC = float(os.getenv("MC_SLEEP_SEC", "10"))')


def ensure_mc_comments_patch(mc_root):
    """给 MediaCrawler base_config 打一次性 env 补丁：单视频评论上限
    CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES 可由 MC_COMMENTS_COUNT 覆盖。"""
    p = os.path.join(mc_root, "config", "base_config.py")
    if not os.path.isfile(p):
        return None
    pat = r"CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES\s*=\s*\d+"
    return _patch_verify(p, "MC_COMMENTS_COUNT", pat,
                         'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = int(float(os.getenv("MC_COMMENTS_COUNT", "10")))')


def ensure_mc_creator_limit_patch(mc_root):
    """Make creator pagination stop at MC_CREATOR_MAX_COUNT before its save callback."""
    p = os.path.join(mc_root, "media_platform", "douyin", "client.py")
    if not os.path.isfile(p):
        return "missing-client"
    src = open(p, encoding="utf-8").read()
    marker = "MC_CREATOR_MAX_COUNT"
    if marker in src:
        return "already"
    needle = "            if callback:\n                await callback(aweme_list)\n            result.extend(aweme_list)"
    if needle not in src:
        return "unsupported-version"
    block = '''            creator_limit = int(os.getenv("MC_CREATOR_MAX_COUNT", "0"))
            if creator_limit > 0:
                remaining = max(0, creator_limit - len(result))
                aweme_list = aweme_list[:remaining]
            if callback:
                await callback(aweme_list)
            result.extend(aweme_list)
            if creator_limit > 0 and len(result) >= creator_limit:
                posts_has_more = 0'''
    try:
        bak = p + ".limit.bak"
        if not os.path.exists(bak):
            with open(bak, "w", encoding="utf-8") as f:
                f.write(src)
        patched = src.replace(needle, block, 1)
        if "\nimport os\n" not in patched:
            patched = patched.replace("import asyncio\n", "import asyncio\nimport os\n", 1)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(patched)
        return "patched" if marker in open(p, encoding="utf-8").read() else "verify-failed"
    except Exception:
        return "write-failed"


def rollback_mc_sleep_patch(mc_root):
    """回滚上次 sleep 补丁（有 .bak 时恢复）。"""
    p = os.path.join(mc_root, "config", "base_config.py")
    bak = p + ".bak"
    if os.path.isfile(bak):
        open(p, "w", encoding="utf-8").write(open(bak, encoding="utf-8").read())
        return True
    return False


def resolve_mc():
    py = runtime.mc_py()
    root = runtime.mc_root()
    if not py or not root or not os.path.isfile(os.path.join(root, "main.py")):
        sys.exit("[ERR] 未找到 MediaCrawler：请先在本机安装并用 runtime.py register 登记。")
    return py, root


def build_cmd(a, mc_root):
    cmd = [a.mc_py, os.path.join(mc_root, "main.py"),
           "--platform", PLATFORM,
           "--type", a.mode,
           "--save_data_option", "jsonl",
           "--save_data_path", a.save_dir,
           "--get_comment", str(a.get_comment).lower()[:1],
           "--max_concurrency_num", str(a.concurrency),
           "--headless", str(a.headless).lower()[:1],
           "--crawler_max_notes_count", str(a.max)]
    if a.mode == "creator":
        cmd += ["--creator_id", a.target]
    elif a.mode == "detail":
        cmd += ["--specified_id", a.target]
    else:
        cmd += ["--keywords", a.target]
    if a.lt:
        cmd += ["--lt", a.lt]
    if a.lt == "cookie" and a.cookies:
        cmd += ["--cookies", a.cookies]
    return cmd


def tee_run(py, main_args, mc_root, log_path, env, timeout=None, progress=None):
    """流式执行：逐行回显到控制台 + 写入日志。返回退出码。

    timeout=None 时不限时（长任务不误杀）；给定秒数则超时后 terminate 并返回 -9。
    用泵线程读 stdout，避免子进程在未产输出时永久挂起主线程。"""
    try:
        proc = subprocess.Popen(
            [py, main_args[0]] + main_args[1:],
            cwd=mc_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except (FileNotFoundError, OSError) as e:
        print(f"[ERR] MediaCrawler 无法启动：{e}")
        print("[停止] 不执行浏览器 API、网页抓取或其他兜底方案。")
        return 127
    import threading
    errors = []

    def pump():
        with open(log_path, "a", encoding="utf-8") as lf:
            try:
                for line in proc.stdout:
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    lf.write(f"[{ts}] {line}")
                    if progress:
                        progress.observe(line.strip()[:240])
            except Exception as e:
                errors.append(str(e))

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    try:
        rc = proc.wait(timeout=timeout)
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        raise
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait()
        print(f"[超时] 抓取超过 {timeout} 秒，已终止（可用 --max-min 调大重试）")
        return -9
    t.join()
    return rc


def newest_raw(save_dir):
    files = glob.glob(os.path.join(save_dir, "**", "*.jsonl"), recursive=True)
    files = [f for f in files if "contents" in os.path.basename(f)]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def filter_dedup(raw, out, keyword, hard_limit=None):
    kw = keyword
    seen, rows, counts = set(), [], {"total": 0, "matched": 0, "unique_before_limit": 0, "unique": 0}
    with open(raw, encoding="utf-8") as fi:
        for line in fi:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            counts["total"] += 1
            blob = (j.get("desc") or "") + "|" + (j.get("nickname") or "") + "|" + (j.get("author_word") or "")
            if kw and kw not in blob:
                continue
            counts["matched"] += 1
            aid = j.get("aweme_id")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            rows.append(j)
    counts["unique_before_limit"] = len(rows)
    if hard_limit is not None:
        rows = rows[:hard_limit]
    counts["unique"] = len(rows)
    with open(out, "w", encoding="utf-8") as fo:
        for j in rows:
            fo.write(json.dumps(j, ensure_ascii=False) + "\n")
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="首次为父目录；若指向已有运行目录则自动复用，禁止嵌套新建")
    ap.add_argument("--account", required=True, help="账号唯一 slug，如 brand-001；不同账号不得复用")
    ap.add_argument("--mode", choices=_MODES, required=True, help="creator=账号全量 / detail=单条 / search=关键词")
    ap.add_argument("--target", required=True, help="creator: sec_uid；detail: aweme_id/URL；search: 关键词")
    ap.add_argument("--max", type=int, default=100, help="最大抓取数 (crawler_max_notes_count)")
    ap.add_argument("--lt", choices=_LTS, default="qrcode", help="登录方式")
    ap.add_argument("--cookies", default=None, help="cookie 登录时的 cookie 串")
    comment_group = ap.add_mutually_exclusive_group()
    comment_group.add_argument("--get-comment", dest="get_comment", action="store_true",
                               help="抓一级评论（默认开启）")
    comment_group.add_argument("--no-comment", dest="get_comment", action="store_false",
                               help="显式跳过评论抓取")
    ap.set_defaults(get_comment=True)
    ap.add_argument("--comments-count", type=int, default=100,
                    help="单视频最多抓取的一级评论数（默认100；MediaCrawler 出厂硬编码10，本参数会打 env 补丁覆盖）")
    ap.add_argument("--headless", action="store_true", help="无头模式")
    ap.add_argument("--speed", choices=_SPEED_CONC, default=None,
                    help="预设档：safe=并发1(默认) / normal=并发2 / fast=并发3（快档风控风险更高）")
    ap.add_argument("--concurrency", type=int, default=None, help="显式并发数（覆盖 --speed 预设）")
    ap.add_argument("--sleep-min", type=float, default=None, help="随机延时下限(秒)，启用即给 MediaCrawler 打 env 补丁改其固定 sleep")
    ap.add_argument("--sleep-max", type=float, default=None, help="随机延时上限(秒)，与 --sleep-min 成对")
    ap.add_argument("--retry-fail", type=int, default=0, help="抓取失败(非0退出/超时)自动重试次数，指数退避")
    ap.add_argument("--max-min", type=float, default=None,
                    help="单次抓取最大运行分钟数（防子进程永久挂起；缺省不限时，长任务不误杀）")
    ap.add_argument("--no-mc-patch", action="store_true", help="不修改 MediaCrawler 源码（仅改用并发提速，随机延时参数失效）")
    ap.add_argument("--run-dir", default=None, help="指定本次运行目录；已存在时校验账号身份并断点续跑")
    ap.add_argument("--new-run", action="store_true", help="显式开始全新一轮采集；缺省复用父目录记录的当前运行根")
    ap.add_argument("--save-dir", dest="save_dir", default=None, help="高级覆盖：仅改变 MediaCrawler 原始数据目录")
    ap.add_argument("--account-filter", dest="kw", default=None, help="可选内容过滤关键词；缺省不过滤，禁止用目录 slug 猜测内容")
    ap.add_argument("--dry-run", action="store_true", help="只打印命令，不实际爬取")
    a = ap.parse_args()

    if a.max <= 0:
        sys.exit("[ERR] --max 必须大于 0")

    validate_account_slug(a.account)
    a.mc_py, mc_root = resolve_mc()
    parent_root = a.root
    if a.run_dir and a.new_run:
        sys.exit("[ERR] --run-dir 与 --new-run 不能同时使用")
    a.root = make_run_dir(parent_root, a.account, a.run_dir, a.new_run)
    identity_path = bind_account_identity(a.root, a.account, a.mode, a.target, dry_run=a.dry_run)
    a.save_dir = validate_save_dir(a.root, a.account, a.save_dir)
    os.makedirs(os.path.join(a.save_dir, "cursor"), exist_ok=True)
    a.speed = a.speed or "safe"
    a.concurrency = a.concurrency or _SPEED_CONC[a.speed]
    if a.sleep_min is not None or a.sleep_max is not None:
        if a.sleep_min is None or a.sleep_max is None:
            sys.exit("[ERR] --sleep-min 与 --sleep-max 需成对提供")
        if a.sleep_max < a.sleep_min:
            sys.exit("[ERR] --sleep-max 不得小于 --sleep-min")

    cmd = build_cmd(a, mc_root)
    pretty = " \\\n  ".join(cmd)
    print("=" * 70)
    print(f"[MediaCrawler] 平台=dy 模式={a.mode} 目标={a.target} 上限={a.max}")
    print(f"[账号隔离] {a.account} -> {identity_path}")
    print(f"[本次运行目录] {a.root}")
    print(f"[命令] {pretty}")

    env = dict(os.environ)
    env["MC_CURSOR_DIR"] = os.path.join(a.save_dir, "cursor")  # 断点续传落项目目录
    env.setdefault("PYTHONUNBUFFERED", "1")
    if a.mode == "creator":
        if a.no_mc_patch:
            sys.exit("[ERR] creator 模式的 --max 硬上限需要 MediaCrawler 补丁，不能与 --no-mc-patch 同时使用。")
        limit_patch = ensure_mc_creator_limit_patch(mc_root)
        if limit_patch not in ("patched", "already"):
            sys.exit(f"[ERR] MediaCrawler creator 硬上限补丁失败({limit_patch})；无法保证 --max={a.max}，停止抓取。")
        env["MC_CREATOR_MAX_COUNT"] = str(a.max)
        print(f"[主页硬上限] {limit_patch}：最多保存 {a.max} 条，达到后立即停止翻页")

    # —— 随机延时落地：给 MediaCrawler base_config 打 env 补丁，抓取间隔由 MC_SLEEP_SEC 覆盖 ——
    if a.sleep_min is not None:
        if a.no_mc_patch:
            print("[提示] --no-mc-patch 已启用，--sleep-min/--sleep-max 不生效（仍用 MediaCrawler 固定延时）")
        else:
            r = ensure_mc_sleep_patch(mc_root)
            if r not in ("patched", "already"):
                print(f"[延时补丁] 失败({r})：MediaCrawler base_config 未能由 MC_SLEEP_SEC 覆盖，本参数不生效")
                print("  建议：检查 MediaCrawler 是否含 CRAWLER_MAX_SLEEP_SEC 变量，或用 --no-mc-patch 仅并发提速")
            else:
                print(f"[延时补丁] {r}（base_config 已可由 MC_SLEEP_SEC 覆盖）")
                env["MC_SLEEP_SEC"] = str(round(random.uniform(a.sleep_min, a.sleep_max), 2))
                print(f"[随机延时] 本次抓取 MC_SLEEP_SEC={env['MC_SLEEP_SEC']}s（MediaCrawler 内部取 uniform(0, 此值)）")

    # —— 评论数上限落地：MediaCrawler 出厂单视频 10 条，打 env 补丁让 MC_COMMENTS_COUNT 覆盖 ——
    if a.get_comment and a.comments_count != 10:
        r = ensure_mc_comments_patch(mc_root)
        if r not in ("patched", "already"):
            sys.exit(f"[ERR] 评论上限补丁失败({r})，无法保证每视频 100 条；停止抓取，不降级到 10 条。")
        env["MC_COMMENTS_COUNT"] = str(a.comments_count)
        print(f"[评论数补丁] {r}（CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES 可由 MC_COMMENTS_COUNT 覆盖）")
        print(f"[评论数] 本次单视频上限 MC_COMMENTS_COUNT={env['MC_COMMENTS_COUNT']} 条")

    if a.dry_run:
        print("-" * 70)
        print("[dry-run] 未执行。环境: MC_CURSOR_DIR=", env["MC_CURSOR_DIR"],
              " MC_SLEEP_SEC=", env.get("MC_SLEEP_SEC"),
              " MC_COMMENTS_COUNT=", env.get("MC_COMMENTS_COUNT"), " 并发=", a.concurrency)
        return

    log_path = os.path.join(a.save_dir, "crawl.log")
    progress = RunProgress(a.root, "crawl").heartbeat()
    progress.log(f"运行目录={a.root} account={a.account} mode={a.mode} target={a.target}")
    print(f"[日志] {log_path}")

    # —— 失败自动重试（指数退避：5s→10s→20s→...→封顶60s）———
    attempts = a.retry_fail + 1
    rc = None
    for i in range(1, attempts + 1):
        if i > 1 and a.sleep_min is not None and not a.no_mc_patch:
            env["MC_SLEEP_SEC"] = str(round(random.uniform(a.sleep_min, a.sleep_max), 2))
            print(f"[随机延时] 第 {i} 次尝试重随机 MC_SLEEP_SEC={env['MC_SLEEP_SEC']}s")
        print(f"[尝试 {i}/{attempts}]")
        timeout = a.max_min * 60 if a.max_min else None
        progress.detail(f"MediaCrawler 尝试 {i}/{attempts}")
        rc = tee_run(a.mc_py, cmd[1:], mc_root, log_path, env, timeout=timeout, progress=progress)
        print(f"[退出码] {rc}")
        if rc == 0:
            break
        if i < attempts:
            wait = min(60, 5 * (2 ** (i - 1)))
            print(f"[重试] 退出码 {rc}，{wait}s 后重试...")
            time.sleep(wait)

    # Never process stale or partial output after a crawler failure.
    if rc != 0:
        progress.finish(False, f"MediaCrawler 失败，退出码={rc}")
        print(f"[停止] MediaCrawler 退出码 {rc}；不执行任何兜底方案。请修复 MediaCrawler 后重试。")
        sys.exit(rc or 1)

    # —— 产物判定：detail+get_comment 看 detail_comments_*.jsonl（勿用账号关键词过滤，会误删评论） ——
    comment_mode = (a.mode == "detail") and a.get_comment
    if comment_mode:
        cps = glob.glob(os.path.join(a.save_dir, "**", "detail_comments*.jsonl"), recursive=True)
        if not cps:
            print("[提示] 未发现 detail_comments_*.jsonl；请检查登录态/风控，重试或看 crawl.log。")
            sys.exit(rc or 1)
        print("=" * 70)
        print(f"[评论产物] {len(cps)} 个 detail_comments_*.jsonl：")
        for f in sorted(cps):
            print("  " + f)
        progress.finish(True, f"评论抓取完成：文件={len(cps)}")
        print(f"[下一阶段] runtime.py run --tool comments.py --root \"{a.root}\" --account \"{a.account}\" --max {a.comments_count}")
        sys.exit(0)

    raw = newest_raw(a.save_dir)
    if not raw:
        progress.finish(False, "抓取结束但未发现 contents JSONL")
        print("[提示] save_dir 下未发现 *_contents*.jsonl；请检查登录态/风控，重试或看 crawl.log。")
        sys.exit(rc or 1)

    # Account slug is a storage key, never a content filter. Filter only when explicitly requested.
    kw = a.kw
    filtered = os.path.join(a.save_dir, f"{a.account}_dedup.jsonl")
    counts = filter_dedup(raw, filtered, kw, hard_limit=a.max if a.mode == "creator" else None)
    progress.finish(bool(counts["unique"]), f"抓取完成：原始={counts['total']} 唯一={counts['unique']}")
    print("=" * 70)
    print(f"[原始文件] {raw}")
    print(f"[去重文件] {filtered}")
    print(f"[统计] 引擎原始 {counts['total']} 行 | 匹配 {counts['matched']} | 去重 {counts['unique_before_limit']} | 最终保留 {counts['unique']} / 上限 {a.max if a.mode == 'creator' else '不适用'}")
    print("-" * 70)
    print(f"[下一阶段] runtime.py run --tool process.py --root \"{a.root}\" --account \"{a.account}\" --json \"{filtered}\"")
    sys.exit(0 if counts["unique"] else 1)


if __name__ == "__main__":
    main()
