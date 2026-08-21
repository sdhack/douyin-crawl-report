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
import socket
import subprocess
import time
import datetime
import tempfile

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


def _atomic_overwrite(path, text):
    """Overwrite a patch target atomically without creating a backup file."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def aweme_comment_count(aweme):
    """Return an integer comment count, or None when the value is unknown."""
    if not isinstance(aweme, dict):
        return None
    stats = aweme.get("statistics") if isinstance(aweme.get("statistics"), dict) else {}
    value = stats.get("comment_count")
    if value is None or value == "":
        value = aweme.get("comment_count")
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        text = str(value).strip()
        if not re.fullmatch(r"[+-]?\d+", text):
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def _url_list(value):
    if not isinstance(value, dict):
        return []
    urls = value.get("url_list")
    return [x for x in urls if x] if isinstance(urls, list) else []


def aweme_contract_complete(aweme):
    """Conservative creator-page completeness gate for save/media analysis.

    The gate accepts raw MediaCrawler aweme objects or already-normalized
    records. Missing fields return False so the detail endpoint remains the
    correctness fallback. Music is intentionally optional.
    """
    if not isinstance(aweme, dict) or not aweme.get("aweme_id"):
        return False
    if "desc" not in aweme and "title" not in aweme:
        return False
    if aweme.get("create_time") in (None, ""):
        return False
    try:
        aweme_kind = int(aweme.get("aweme_type") or 0)
    except (TypeError, ValueError):
        return False
    stats = aweme.get("statistics") if isinstance(aweme.get("statistics"), dict) else {}
    for field in ("digg_count", "collect_count", "comment_count", "share_count"):
        value = stats.get(field, aweme.get(field))
        if value is None or value == "":
            return False
    if aweme.get("video_download_url") and aweme.get("cover_url"):
        return True
    is_note = aweme_kind == 68
    if is_note:
        note = aweme.get("note_download_url") or aweme.get("note_urls")
        if isinstance(note, str):
            return bool([x for x in note.split(",") if x.strip()])
        if isinstance(note, list):
            return bool([x for x in note if x])
        images = aweme.get("images")
        return isinstance(images, list) and any(_url_list((x or {}).get("origin_url")) for x in images if isinstance(x, dict))
    video = aweme.get("video") if isinstance(aweme.get("video"), dict) else {}
    video_urls = (_url_list(video.get("play_addr_h264")) or
                  _url_list(video.get("play_addr_256")) or
                  _url_list(video.get("play_addr")))
    cover = video.get("raw_cover") or video.get("origin_cover")
    return len(video_urls) >= 2 and len(_url_list(cover)) >= 2


def collect_optimization_metrics(log_path, start_offset=0):
    """Count optimization markers emitted by the MediaCrawler patch."""
    metrics = {"saved_detail_requests": 0, "skipped_comment_requests": 0,
               "skipped_zero_comments": 0}
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            if start_offset:
                f.seek(start_offset)
            for line in f:
                if "[MC_OPT] saved_detail_requests" in line:
                    metrics["saved_detail_requests"] += 1
                if "[MC_OPT] skipped_zero_comments" in line:
                    metrics["skipped_comment_requests"] += 1
                    metrics["skipped_zero_comments"] += 1
    except OSError:
        pass
    return metrics


def collect_skipped_zero_comment_ids(log_path, start_offset=0):
    """Return zero-comment IDs emitted during this run only."""
    ids = set()
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            if start_offset:
                f.seek(start_offset)
            for line in f:
                match = re.search(r"\[MC_OPT\] skipped_zero_comments aweme_id:([^\s]+)", line)
                if match:
                    ids.add(match.group(1))
    except OSError:
        pass
    return ids


def target_aweme_rows(raws, keyword=None, hard_limit=None, mode=None, target=None):
    """Read target contents in first-seen order without writing a file."""
    order, latest = [], {}
    for raw in raws:
        try:
            with open(raw, encoding="utf-8") as f:
                lines = f
                for line in lines:
                    try:
                        item = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    aid = item.get("aweme_id")
                    if not aid:
                        continue
                    blob = (item.get("desc") or "") + "|" + (item.get("nickname") or "") + "|" + (item.get("author_word") or "")
                    if keyword and keyword not in blob:
                        continue
                    if aid not in latest:
                        order.append(aid)
                    latest[aid] = item
        except OSError:
            continue
    rows = [latest[aid] for aid in order]
    if mode == "detail" and target:
        expected_ids = extract_target_aweme_ids(target)
        if expected_ids:
            by_id = {str(row.get("aweme_id")): row for row in rows}
            rows = [by_id[aid] for aid in expected_ids if aid in by_id]
    return rows[:hard_limit] if hard_limit is not None else rows


def extract_target_aweme_ids(target):
    """Extract all detail IDs in input order, without duplicates."""
    result = []
    seen = set()
    for aid in re.findall(r"(?<!\d)(\d{8,})(?!\d)", str(target or "")):
        if aid not in seen:
            seen.add(aid)
            result.append(aid)
    return result


def all_targets_explicit_zero(rows, skipped_ids, expected_ids=None):
    """Allow a missing comments file only when every target is explicit zero."""
    row_ids = {str(row.get("aweme_id")) for row in rows if row.get("aweme_id")}
    target_ids = set(expected_ids or row_ids)
    if not target_ids or row_ids != target_ids:
        return False
    if len(skipped_ids.intersection(target_ids)) < len(target_ids):
        return False
    return all(aweme_comment_count(row) == 0 for row in rows)


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


def _acquire_run_lock(parent, slug, timeout=30, stale_after=600):
    lock = os.path.join(parent, f".douyin-crawl-{slug}.lock")
    deadline = time.time() + timeout
    while True:
        try:
            os.mkdir(lock)
            return lock
        except FileExistsError:
            # 崩溃残留的 stale 锁（持有者已死）会永久阻塞后续 Agent；
            # 超过 stale_after 秒无更新则视为陈旧并接管
            try:
                age = time.time() - os.path.getmtime(lock)
                if age > stale_after:
                    import shutil
                    shutil.rmtree(lock, ignore_errors=True)
                    continue
            except OSError:
                pass
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
        parent = os.path.dirname(path)
        lock = _acquire_run_lock(parent, slug)
        try:
            os.makedirs(path, exist_ok=True)
            if os.listdir(path) and not _existing_run(path, slug):
                sys.exit(f"[ERR] --run-dir 已存在但不是账号 {slug} 的运行目录：{path}")
        finally:
            _release_run_lock(lock)
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


def preview_run_dir(parent, slug, explicit=None, new_run=False):
    """Resolve the run root for --dry-run without creating files or pointers."""
    if explicit:
        path = os.path.abspath(explicit)
        if os.path.isdir(path) and os.listdir(path) and not _existing_run(path, slug):
            sys.exit(f"[ERR] --run-dir 已存在但不是账号 {slug} 的运行目录：{path}")
        return path

    parent = os.path.abspath(parent)
    if os.path.isdir(parent) and _existing_run(parent, slug):
        return parent
    if not new_run:
        current = _current_run(parent, slug)
        if current:
            return current

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(parent, f"{slug}-{stamp}")
    suffix = 2
    while os.path.exists(path):
        path = os.path.join(parent, f"{slug}-{stamp}-{suffix}")
        suffix += 1
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
    """正则替换 MediaCrawler base_config 变量为 env 覆盖版，并回读验证生效（防静默假成功）。

    pat 必须行首锚定到目标变量名（(?m)^VAR...），且空白匹配只能用 [ \\t] 不能用
    \\s——\\s 会吞掉行尾换行连吃后续空行/注释行（实测 150 行被吃成 148 行）。
    历史教训——无锚定的 \\d+ 分支曾把全文件所有数字字面量（coding 声明/端口号/
    注释行号）一并替换，导致 base_config.py 无法导入。此处再以"仅允许 1 行变更"
    做二次误伤防护。"""
    src = open(p, encoding="utf-8-sig").read()
    if marker in src:
        return "already"
    try:
        if not re.search(r"(?m)^import os", src):
            src = "import os\n" + src
        if not re.search(pat, src):
            return "no-var"
        patched = re.sub(pat, new, src, count=1)
        old_l, new_l = src.splitlines(), patched.splitlines()
        changed = sum(1 for x, y in zip(old_l, new_l) if x != y) + abs(len(old_l) - len(new_l))
        if changed > 1:
            return "verify-failed"
        _atomic_overwrite(p, patched)
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
    pat = r"(?m)^CRAWLER_MAX_SLEEP_SEC[ \t]*=[ \t]*\d+(?:\.\d+)?[ \t]*(?:#.*)?$"
    return _patch_verify(p, "MC_SLEEP_SEC", pat,
                         'CRAWLER_MAX_SLEEP_SEC = float(os.getenv("MC_SLEEP_SEC", "10"))')


def ensure_mc_comments_patch(mc_root):
    """给 MediaCrawler base_config 打一次性 env 补丁：单视频评论上限
    CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES 可由 MC_COMMENTS_COUNT 覆盖。"""
    p = os.path.join(mc_root, "config", "base_config.py")
    if not os.path.isfile(p):
        return None
    pat = r"(?m)^CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES[ \t]*=[ \t]*\d+(?:\.\d+)?[ \t]*(?:#.*)?$"
    return _patch_verify(p, "MC_COMMENTS_COUNT", pat,
                         'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = int(float(os.getenv("MC_COMMENTS_COUNT", "10")))')


def ensure_mc_fetch_resilience_patch(mc_root):
    """Retry per-video detail/comment fetches and randomize each request delay."""
    p = os.path.join(mc_root, "media_platform", "douyin", "core.py")
    if not os.path.isfile(p):
        return "missing-core"
    src = open(p, encoding="utf-8").read()
    marker = "MC_FETCH_RETRY_COUNT"
    if marker in src:
        return "already"
    detail_old = '''    async def get_aweme_detail(self, aweme_id: str, semaphore: asyncio.Semaphore) -> Any:
        """Get note detail"""
        async with semaphore:
            try:
                result = await self.dy_client.get_video_by_id(aweme_id)
                # Sleep after fetching aweme detail
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[DouYinCrawler.get_aweme_detail] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching aweme {aweme_id}")
                return result
            except DataFetchError as ex:
                utils.logger.error(f"[DouYinCrawler.get_aweme_detail] Get aweme detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[DouYinCrawler.get_aweme_detail] have not fund note detail aweme_id:{aweme_id}, err: {ex}")
                return None
'''
    detail_new = '''    async def get_aweme_detail(self, aweme_id: str, semaphore: asyncio.Semaphore) -> Any:
        """Get note detail with bounded retry; never hide the failing aweme id."""
        async with semaphore:
            retry_count = max(0, int(os.getenv("MC_FETCH_RETRY_COUNT", "2")))
            for attempt in range(retry_count + 1):
                try:
                    result = await self.dy_client.get_video_by_id(aweme_id)
                    sleep_min = float(os.getenv("MC_SLEEP_MIN", str(config.CRAWLER_MAX_SLEEP_SEC)))
                    sleep_max = float(os.getenv("MC_SLEEP_MAX", str(config.CRAWLER_MAX_SLEEP_SEC)))
                    delay = random.uniform(min(sleep_min, sleep_max), max(sleep_min, sleep_max))
                    await asyncio.sleep(delay)
                    utils.logger.info(f"[DouYinCrawler.get_aweme_detail] Sleeping for {delay:.2f} seconds after fetching aweme {aweme_id}")
                    return result
                except (DataFetchError, KeyError) as ex:
                    utils.logger.error(
                        f"[DouYinCrawler.get_aweme_detail] aweme_id:{aweme_id} attempt:{attempt + 1}/{retry_count + 1} error:{ex}"
                    )
                    if attempt < retry_count:
                        await asyncio.sleep(min(60, 5 * (2 ** attempt)))
            utils.logger.error(f"[DouYinCrawler.get_aweme_detail] MC_FINAL_FAILURE aweme_id:{aweme_id}")
            return None
'''
    comments_old = '''    async def get_comments(self, aweme_id: str, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                # Pass the list of keywords to the get_aweme_all_comments method
                # Use fixed crawling interval
                crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
                await self.dy_client.get_aweme_all_comments(
                    aweme_id=aweme_id,
                    crawl_interval=crawl_interval,
                    is_fetch_sub_comments=config.ENABLE_GET_SUB_COMMENTS,
                    callback=douyin_store.batch_update_dy_aweme_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )
                # Sleep after fetching comments
                await asyncio.sleep(crawl_interval)
                utils.logger.info(f"[DouYinCrawler.get_comments] Sleeping for {crawl_interval} seconds after fetching comments for aweme {aweme_id}")
                utils.logger.info(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} comments have all been obtained and filtered ...")
            except DataFetchError as e:
                utils.logger.error(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} get comments failed, error: {e}")
'''
    comments_new = '''    async def get_comments(self, aweme_id: str, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            retry_count = max(0, int(os.getenv("MC_FETCH_RETRY_COUNT", "2")))
            for attempt in range(retry_count + 1):
                try:
                    sleep_min = float(os.getenv("MC_SLEEP_MIN", str(config.CRAWLER_MAX_SLEEP_SEC)))
                    sleep_max = float(os.getenv("MC_SLEEP_MAX", str(config.CRAWLER_MAX_SLEEP_SEC)))
                    crawl_interval = random.uniform(min(sleep_min, sleep_max), max(sleep_min, sleep_max))
                    await self.dy_client.get_aweme_all_comments(
                        aweme_id=aweme_id,
                        crawl_interval=crawl_interval,
                        is_fetch_sub_comments=config.ENABLE_GET_SUB_COMMENTS,
                        callback=douyin_store.batch_update_dy_aweme_comments,
                        max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                    )
                    await asyncio.sleep(crawl_interval)
                    utils.logger.info(f"[DouYinCrawler.get_comments] aweme_id:{aweme_id} complete; delay={crawl_interval:.2f}s")
                    return
                except DataFetchError as ex:
                    utils.logger.error(
                        f"[DouYinCrawler.get_comments] aweme_id:{aweme_id} attempt:{attempt + 1}/{retry_count + 1} error:{ex}"
                    )
                    if attempt < retry_count:
                        await asyncio.sleep(min(60, 5 * (2 ** attempt)))
            utils.logger.error(f"[DouYinCrawler.get_comments] MC_FINAL_FAILURE aweme_id:{aweme_id}")
'''
    if detail_old not in src or comments_old not in src:
        return "unsupported-version"
    try:
        patched = src.replace(detail_old, detail_new, 1).replace(comments_old, comments_new, 1)
        _atomic_overwrite(p, patched)
        return "patched" if marker in open(p, encoding="utf-8").read() else "verify-failed"
    except Exception:
        return "write-failed"


def ensure_mc_fetch_optimization_patch(mc_root):
    """Skip safe creator detail/comment requests inside MediaCrawler.

    The patch is opt-out through MC_CRAWL_OPTIMIZATIONS=0 and is deliberately
    conservative: missing metadata never qualifies for a skip. It is source
    version-gated and idempotent; no backup is created here.
    """
    p = os.path.join(mc_root, "media_platform", "douyin", "core.py")
    if not os.path.isfile(p):
        return "missing-core"
    src = open(p, encoding="utf-8").read()
    marker = "MC_OPTIMIZATION_PATCH_V1"
    if marker in src:
        return "already"
    batch_old = '''    async def batch_get_note_comments(self, aweme_list: List[str]) -> None:
        """
        Batch get note comments
        """
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[DouYinCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        task_list: List[Task] = []
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        for aweme_id in aweme_list:
            task = asyncio.create_task(self.get_comments(aweme_id, semaphore), name=aweme_id)
            task_list.append(task)
        if len(task_list) > 0:
            await asyncio.wait(task_list)
'''
    comments_old = '''    async def get_comments(self, aweme_id: str, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            retry_count = max(0, int(os.getenv("MC_FETCH_RETRY_COUNT", "2")))
            for attempt in range(retry_count + 1):
                try:
                    sleep_min = float(os.getenv("MC_SLEEP_MIN", str(config.CRAWLER_MAX_SLEEP_SEC)))
                    sleep_max = float(os.getenv("MC_SLEEP_MAX", str(config.CRAWLER_MAX_SLEEP_SEC)))
                    crawl_interval = random.uniform(min(sleep_min, sleep_max), max(sleep_min, sleep_max))
                    await self.dy_client.get_aweme_all_comments(
                        aweme_id=aweme_id,
                        crawl_interval=crawl_interval,
                        is_fetch_sub_comments=config.ENABLE_GET_SUB_COMMENTS,
                        callback=douyin_store.batch_update_dy_aweme_comments,
                        max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                    )
                    await asyncio.sleep(crawl_interval)
                    utils.logger.info(f"[DouYinCrawler.get_comments] aweme_id:{aweme_id} complete; delay={crawl_interval:.2f}s")
                    return
                except DataFetchError as ex:
                    utils.logger.error(
                        f"[DouYinCrawler.get_comments] aweme_id:{aweme_id} attempt:{attempt + 1}/{retry_count + 1} error:{ex}"
                    )
                    if attempt < retry_count:
                        await asyncio.sleep(min(60, 5 * (2 ** attempt)))
            utils.logger.error(f"[DouYinCrawler.get_comments] MC_FINAL_FAILURE aweme_id:{aweme_id}")
'''
    fetch_old = '''    async def fetch_creator_video_detail(self, video_list: List[Dict]):
        """
        Concurrently obtain the specified post list and save the data
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_aweme_detail(post_item.get("aweme_id"), semaphore) for post_item in video_list]

        note_details = await asyncio.gather(*task_list)
        for aweme_item in note_details:
            if aweme_item is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_item)
                await self.get_aweme_media(aweme_item=aweme_item)
'''
    specified_old = '''        aweme_details = await asyncio.gather(*task_list)
        for aweme_detail in aweme_details:
            if aweme_detail is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_detail)
                await self.get_aweme_media(aweme_item=aweme_detail)
        await self.batch_get_note_comments(aweme_id_list)
'''
    batch_new = '''    async def batch_get_note_comments(self, aweme_list: List[Dict]) -> None:
        """Batch comments while skipping only explicitly zero-count works."""
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[DouYinCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return
        task_list: List[Task] = []
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        for candidate in aweme_list:
            aweme_id = candidate.get("aweme_id") if isinstance(candidate, dict) else candidate
            if not aweme_id:
                continue
            if isinstance(candidate, dict):
                self._mc_opt_record_aweme(candidate)
            task_list.append(asyncio.create_task(self.get_comments(str(aweme_id), semaphore), name=str(aweme_id)))
        if task_list:
            await asyncio.wait(task_list)
'''
    comments_new = '''    async def get_comments(self, aweme_id: str, semaphore: asyncio.Semaphore) -> None:
        if (os.getenv("MC_CRAWL_OPTIMIZATIONS", "1") != "0" and
                os.getenv("MC_SKIP_ZERO_COMMENTS", "1") != "0"):
            counts = getattr(self, "_mc_opt_comment_counts", {})
            if counts.get(str(aweme_id)) == 0:
                self._mc_opt_metric("skipped_comment_requests")
                utils.logger.info(f"[MC_OPT] skipped_zero_comments aweme_id:{aweme_id}")
                return
        async with semaphore:
            retry_count = max(0, int(os.getenv("MC_FETCH_RETRY_COUNT", "2")))
            for attempt in range(retry_count + 1):
                try:
                    sleep_min = float(os.getenv("MC_SLEEP_MIN", str(config.CRAWLER_MAX_SLEEP_SEC)))
                    sleep_max = float(os.getenv("MC_SLEEP_MAX", str(config.CRAWLER_MAX_SLEEP_SEC)))
                    crawl_interval = random.uniform(min(sleep_min, sleep_max), max(sleep_min, sleep_max))
                    await self.dy_client.get_aweme_all_comments(
                        aweme_id=aweme_id,
                        crawl_interval=crawl_interval,
                        is_fetch_sub_comments=config.ENABLE_GET_SUB_COMMENTS,
                        callback=douyin_store.batch_update_dy_aweme_comments,
                        max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                    )
                    await asyncio.sleep(crawl_interval)
                    utils.logger.info(f"[DouYinCrawler.get_comments] aweme_id:{aweme_id} complete; delay={crawl_interval:.2f}s")
                    return
                except DataFetchError as ex:
                    utils.logger.error(
                        f"[DouYinCrawler.get_comments] aweme_id:{aweme_id} attempt:{attempt + 1}/{retry_count + 1} error:{ex}"
                    )
                    if attempt < retry_count:
                        await asyncio.sleep(min(60, 5 * (2 ** attempt)))
            utils.logger.error(f"[DouYinCrawler.get_comments] MC_FINAL_FAILURE aweme_id:{aweme_id}")
'''
    fetch_new = '''    async def fetch_creator_video_detail(self, video_list: List[Dict]):
        """Resolve creator items in page order; complete items avoid detail API."""
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        async def resolve(post_item):
            self._mc_opt_record_aweme(post_item)
            if (os.getenv("MC_CRAWL_OPTIMIZATIONS", "1") != "0" and
                    os.getenv("MC_SKIP_COMPLETE_DETAIL", "1") != "0" and
                    self._mc_opt_complete(post_item)):
                self._mc_opt_metric("saved_detail_requests")
                utils.logger.info(f"[MC_OPT] saved_detail_requests aweme_id:{post_item.get('aweme_id')}")
                return post_item
            return await self.get_aweme_detail(post_item.get("aweme_id"), semaphore)
        note_details = await asyncio.gather(*(resolve(item) for item in video_list))
        for aweme_item in note_details:
            if aweme_item is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_item)
                await self.get_aweme_media(aweme_item=aweme_item)
'''
    specified_new = '''        aweme_details = await asyncio.gather(*task_list)
        detail_comment_items = []
        for aweme_id, aweme_detail in zip(aweme_id_list, aweme_details):
            item = aweme_detail if isinstance(aweme_detail, dict) else {"aweme_id": aweme_id}
            detail_comment_items.append(item)
            if aweme_detail is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_detail)
                await self.get_aweme_media(aweme_item=aweme_detail)
        await self.batch_get_note_comments(detail_comment_items)
'''
    helper = '''    # MC_OPTIMIZATION_PATCH_V1
    def _mc_opt_init(self):
        if not hasattr(self, "_mc_opt_comment_counts"):
            self._mc_opt_comment_counts = {}
        if not hasattr(self, "_mc_opt_metrics"):
            self._mc_opt_metrics = {"saved_detail_requests": 0, "skipped_comment_requests": 0}

    def _mc_opt_metric(self, name):
        self._mc_opt_init()
        self._mc_opt_metrics[name] = self._mc_opt_metrics.get(name, 0) + 1

    def _mc_opt_record_aweme(self, aweme):
        self._mc_opt_init()
        if not isinstance(aweme, dict) or not aweme.get("aweme_id"):
            return
        stats = aweme.get("statistics") if isinstance(aweme.get("statistics"), dict) else {}
        value = stats.get("comment_count", aweme.get("comment_count"))
        try:
            if value is not None and str(value).strip() != "" and str(value).strip().lstrip("+-").isdigit():
                self._mc_opt_comment_counts[str(aweme.get("aweme_id"))] = int(value)
        except (TypeError, ValueError):
            return

    @staticmethod
    def _mc_opt_complete(aweme):
        if not isinstance(aweme, dict) or not aweme.get("aweme_id"):
            return False
        if "desc" not in aweme and "title" not in aweme:
            return False
        if aweme.get("create_time") in (None, ""):
            return False
        try:
            aweme_kind = int(aweme.get("aweme_type") or 0)
        except (TypeError, ValueError):
            return False
        stats = aweme.get("statistics") if isinstance(aweme.get("statistics"), dict) else {}
        if any(stats.get(key) in (None, "") for key in ("digg_count", "collect_count", "comment_count", "share_count")):
            return False
        if aweme.get("video_download_url") and aweme.get("cover_url"):
            return True
        is_note = aweme_kind == 68
        if is_note:
            images = aweme.get("images")
            return isinstance(images, list) and any(isinstance(x, dict) and
                isinstance(x.get("origin_url"), dict) and x.get("origin_url", {}).get("url_list")
                for x in images)
        video = aweme.get("video") if isinstance(aweme.get("video"), dict) else {}
        def urls(value):
            return value.get("url_list", []) if isinstance(value, dict) and isinstance(value.get("url_list"), list) else []
        video_urls = urls(video.get("play_addr_h264")) or urls(video.get("play_addr_256")) or urls(video.get("play_addr"))
        cover = video.get("raw_cover") or video.get("origin_cover")
        return len(video_urls) >= 2 and len(urls(cover)) >= 2

'''
    if batch_old not in src or comments_old not in src or fetch_old not in src or specified_old not in src:
        return "unsupported-version"
    patched = (src.replace(batch_old, helper + batch_new, 1)
               .replace(comments_old, comments_new, 1)
               .replace(fetch_old, fetch_new, 1)
               .replace(specified_old, specified_new, 1))
    search_needle = '                    aweme_list.append(aweme_info.get("aweme_id", ""))'
    if search_needle not in patched:
        return "unsupported-version"
    patched = patched.replace(search_needle, '                    self._mc_opt_record_aweme(aweme_info)\n' + search_needle, 1)
    creator_needle = '            video_ids = [video_item.get("aweme_id") for video_item in all_video_list]\n            await self.batch_get_note_comments(video_ids)'
    if creator_needle not in patched:
        return "unsupported-version"
    patched = patched.replace(creator_needle, '            await self.batch_get_note_comments(all_video_list)', 1)
    try:
        _atomic_overwrite(p, patched)
        return "patched" if marker in open(p, encoding="utf-8").read() else "verify-failed"
    except Exception:
        return "write-failed"


def ensure_mc_quiet_comment_log_patch(mc_root):
    """Keep raw comments in JSONL without duplicating every body in the INFO log."""
    p = os.path.join(mc_root, "store", "douyin", "__init__.py")
    if not os.path.isfile(p):
        return "missing-store"
    src = open(p, encoding="utf-8").read()
    marker = "MC_QUIET_COMMENT_LOG"
    if marker in src:
        return "already"
    needle = '    utils.logger.info(f"[store.douyin.update_dy_aweme_comment] douyin aweme comment: {comment_id}, content: {save_comment_item.get(\'content\')}")'
    if needle not in src:
        return "unsupported-version"
    try:
        patched = src.replace(needle, "    # MC_QUIET_COMMENT_LOG: raw body is already persisted in JSONL; avoid duplicate INFO I/O.", 1)
        _atomic_overwrite(p, patched)
        return "patched" if marker in open(p, encoding="utf-8").read() else "verify-failed"
    except Exception:
        return "write-failed"


def ensure_mc_cdp_reuse_patch(mc_root):
    """Allow the wrapper to reuse an already-running MediaCrawler CDP browser."""
    p = os.path.join(mc_root, "config", "base_config.py")
    if not os.path.isfile(p):
        return "missing-config"
    src = open(p, encoding="utf-8-sig").read()
    marker = "MC_CDP_CONNECT_EXISTING"
    if marker in src:
        return "already"
    pat = r"(?m)^CDP_CONNECT_EXISTING[ \t]*=[ \t]*(?:True|False)[ \t]*(?:#.*)?$"
    if not re.search(pat, src):
        return "unsupported-version"
    replacement = ('CDP_CONNECT_EXISTING = os.getenv("MC_CDP_CONNECT_EXISTING", "0").lower() '
                   'in ("1", "true", "t", "yes")')
    try:
        patched = re.sub(pat, replacement, src, count=1)
        _atomic_overwrite(p, patched)
        return "patched" if marker in open(p, encoding="utf-8").read() else "verify-failed"
    except Exception:
        return "write-failed"


def ensure_mc_music_url_patch(mc_root):
    """Use Douyin play_url.url_list when music play_url.uri is absent."""
    p = os.path.join(mc_root, "store", "douyin", "__init__.py")
    if not os.path.isfile(p):
        return "missing-store"
    src = open(p, encoding="utf-8").read()
    marker = 'play_url.get("url_list"'
    if marker in src:
        return "already"
    needle = '''    music_item = aweme_detail.get("music", {})
    play_url = music_item.get("play_url", {})
    music_url = play_url.get("uri", "")
    return music_url'''
    replacement = '''    music_item = aweme_detail.get("music", {})
    play_url = music_item.get("play_url", {}) or {}
    url_list = play_url.get("url_list", []) or []
    return url_list[-1] if url_list else play_url.get("uri", "")'''
    if needle not in src:
        return "unsupported-version"
    try:
        patched = src.replace(needle, replacement, 1)
        _atomic_overwrite(p, patched)
        return "patched" if marker in open(p, encoding="utf-8").read() else "verify-failed"
    except Exception:
        return "write-failed"


def mc_cdp_port(mc_root):
    p = os.path.join(mc_root, "config", "base_config.py")
    try:
        src = open(p, encoding="utf-8-sig").read()
        match = re.search(r"(?m)^CDP_DEBUG_PORT[ \t]*=[ \t]*(\d+)", src)
        return int(match.group(1)) if match else 9222
    except Exception:
        return 9222


def port_is_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


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
        patched = src.replace(needle, block, 1)
        if "\nimport os\n" not in patched:
            patched = patched.replace("import asyncio\n", "import asyncio\nimport os\n", 1)
        _atomic_overwrite(p, patched)
        return "patched" if marker in open(p, encoding="utf-8").read() else "verify-failed"
    except Exception:
        return "write-failed"


def ensure_mc_creator_profile_patch(mc_root):
    """save_creator 落作品/粉丝计数（不含昵称等隐私字段）到 MC_CREATOR_PROFILE_DIR，
    供抓取后核对主页作品数，防「--max 裁剪 + 翻页中断」造成的静默漏抓。"""
    p = os.path.join(mc_root, "store", "douyin", "__init__.py")
    if not os.path.isfile(p):
        return "missing-store"
    src = open(p, encoding="utf-8").read()
    marker = "MC_CREATOR_PROFILE_DIR"
    if marker in src:
        return "already"
    needle = ('async def save_creator(user_id: str, creator: Dict):\n'
              '    # 教学版：创作者个人资料(昵称/性别/头像/签名/IP/粉丝数等)不再落库，防骚扰。\n'
              '    return')
    if needle not in src:
        return "unsupported-version"
    block = ('async def save_creator(user_id: str, creator: Dict):\n'
             '    # 教学版：创作者个人资料(昵称/性别/头像/签名/IP/粉丝数等)不再落库，防骚扰。\n'
             '    # v0.6.8: 仅落公开计数(作品/粉丝/获赞)供 crawl.py 核对主页作品数，防静默漏抓\n'
             '    try:\n'
             '        import json as _json, os as _os\n'
             '        d = _os.environ.get("MC_CREATOR_PROFILE_DIR", "")\n'
             '        if d:\n'
             '            u = creator.get("user") if isinstance(creator.get("user"), dict) else creator\n'
             '            counts = {\n'
             '                "aweme_count": u.get("aweme_count"),\n'
             '                "follower_count": u.get("follower_count"),\n'
             '                "total_favorited": u.get("total_favorited"),\n'
             '                "sec_uid": u.get("sec_uid"),\n'
             '            }\n'
             '            _os.makedirs(d, exist_ok=True)\n'
             '            with open(_os.path.join(d, "creator_profile.json"), "w", encoding="utf-8") as f:\n'
             '                _json.dump(counts, f, ensure_ascii=False, indent=2)\n'
             '    except Exception:\n'
             '        pass\n'
             '    return')
    try:
        patched = src.replace(needle, block, 1)
        _atomic_overwrite(p, patched)
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
        t.join(5)
        return -9
    t.join()
    return rc


def raw_contents_files(save_dir):
    """所有 contents JSONL（跨天续跑会产生多个日期文件），按 mtime 旧→新返回，合并去重不丢旧数据。"""
    files = glob.glob(os.path.join(save_dir, "**", "*contents*.jsonl"), recursive=True)
    return sorted(files, key=os.path.getmtime)


def filter_dedup(raws, out, keyword, hard_limit=None):
    """按 aweme_id 合并；保留首次主页顺序，但用后到详情刷新缺失字段。"""
    kw = keyword
    order, latest = [], {}
    counts = {"total": 0, "matched": 0, "unique_before_limit": 0, "unique": 0}
    for raw in raws:
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
                if not aid:
                    continue
                if aid not in latest:
                    order.append(aid)
                latest[aid] = j
    rows = [latest[aid] for aid in order]
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
    ap.add_argument("--fetch-retry", type=int, default=2,
                    help="单视频详情/评论 API 失败重试次数（默认2，日志保留失败 aweme_id）")
    ap.add_argument("--no-crawl-optimization", action="store_true",
                    help="关闭保守的 creator detail/comment 请求优化（默认启用，未知字段不跳过）")
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
    if a.fetch_retry < 0:
        sys.exit("[ERR] --fetch-retry 不得小于 0")

    validate_account_slug(a.account)
    a.mc_py, mc_root = resolve_mc()
    parent_root = a.root
    if a.run_dir and a.new_run:
        sys.exit("[ERR] --run-dir 与 --new-run 不能同时使用")
    if a.dry_run:
        a.root = preview_run_dir(parent_root, a.account, a.run_dir, a.new_run)
    else:
        a.root = make_run_dir(parent_root, a.account, a.run_dir, a.new_run)
    identity_path = bind_account_identity(a.root, a.account, a.mode, a.target, dry_run=a.dry_run)
    a.save_dir = validate_save_dir(a.root, a.account, a.save_dir)
    if not a.dry_run:
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
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["MC_FETCH_RETRY_COUNT"] = str(a.fetch_retry)
    env["MC_CRAWL_OPTIMIZATIONS"] = "0" if a.no_crawl_optimization else "1"
    env["MC_SKIP_ZERO_COMMENTS"] = "0" if a.no_crawl_optimization else "1"
    env["MC_SKIP_COMPLETE_DETAIL"] = "0" if a.no_crawl_optimization else "1"
    cdp_port = mc_cdp_port(mc_root)
    if a.dry_run:
        if a.mode == "creator" and a.no_mc_patch:
            sys.exit("[ERR] creator 模式的 --max 硬上限需要 MediaCrawler 补丁，不能与 --no-mc-patch 同时使用。")
        if a.sleep_min is not None and not a.no_mc_patch:
            env["MC_SLEEP_MIN"] = str(a.sleep_min)
            env["MC_SLEEP_MAX"] = str(a.sleep_max)
        if a.get_comment and a.comments_count != 10:
            env["MC_COMMENTS_COUNT"] = str(a.comments_count)
        print("-" * 70)
        print("[dry-run] 未执行且未写入目录、指针或补丁。实际运行时将验证所需补丁。环境:",
              "MC_CURSOR_DIR=", env["MC_CURSOR_DIR"],
              "MC_SLEEP_RANGE=", (env.get("MC_SLEEP_MIN"), env.get("MC_SLEEP_MAX")),
              "MC_COMMENTS_COUNT=", env.get("MC_COMMENTS_COUNT"),
              "CRAWL_OPTIMIZATIONS=", env.get("MC_CRAWL_OPTIMIZATIONS"),
              "CDP_REUSE=", port_is_open(cdp_port), "并发=", a.concurrency)
        return

    cdp_patch = ensure_mc_cdp_reuse_patch(mc_root)
    if cdp_patch not in ("patched", "already"):
        sys.exit(f"[ERR] CDP 复用补丁失败({cdp_patch})；无法避免已有浏览器端口竞态。")
    reuse_cdp = port_is_open(cdp_port)
    env["MC_CDP_CONNECT_EXISTING"] = "1" if reuse_cdp else "0"
    print(f"[CDP 复用] {cdp_patch}：端口 {cdp_port} {'已监听，连接现有浏览器' if reuse_cdp else '未监听，启动新浏览器'}")

    resilience_patch = ensure_mc_fetch_resilience_patch(mc_root)
    if resilience_patch not in ("patched", "already"):
        sys.exit(f"[ERR] 详情/评论重试补丁失败({resilience_patch})；拒绝静默漏条。")
    quiet_patch = ensure_mc_quiet_comment_log_patch(mc_root)
    if quiet_patch not in ("patched", "already"):
        sys.exit(f"[ERR] 评论日志降噪补丁失败({quiet_patch})。")
    print(f"[单条容错] {resilience_patch}：详情/评论失败最多重试 {a.fetch_retry} 次并记录 aweme_id")
    optimization_patch = ensure_mc_fetch_optimization_patch(mc_root)
    if optimization_patch not in ("patched", "already"):
        sys.exit(f"[ERR] 抓取提速补丁失败({optimization_patch})；无法保证未知字段不被错误跳过。")
    print(f"[请求提速] {optimization_patch}：完整 creator 项跳过 detail，明确零评论项跳过评论请求")
    print(f"[评论日志] {quiet_patch}：正文仅存 JSONL，运行日志按视频汇总")
    music_patch = ensure_mc_music_url_patch(mc_root)
    if music_patch not in ("patched", "already"):
        sys.exit(f"[ERR] 音频 URL 提取补丁失败({music_patch})。")
    print(f"[音频地址] {music_patch}：play_url.url_list 优先，uri 回退")

    if a.mode == "creator":
        if a.no_mc_patch:
            sys.exit("[ERR] creator 模式的 --max 硬上限需要 MediaCrawler 补丁，不能与 --no-mc-patch 同时使用。")
        limit_patch = ensure_mc_creator_limit_patch(mc_root)
        if limit_patch not in ("patched", "already"):
            sys.exit(f"[ERR] MediaCrawler creator 硬上限补丁失败({limit_patch})；无法保证 --max={a.max}，停止抓取。")
        env["MC_CREATOR_MAX_COUNT"] = str(a.max)
        print(f"[主页硬上限] {limit_patch}：最多保存 {a.max} 条，达到后立即停止翻页")
        profile_patch = ensure_mc_creator_profile_patch(mc_root)
        if profile_patch in ("patched", "already"):
            env["MC_CREATOR_PROFILE_DIR"] = a.save_dir
            print(f"[作品数核对] {profile_patch}：抓取后将比对主页 aweme_count 防漏抓")
        else:
            print(f"[作品数核对] 补丁未生效({profile_patch})，本次无法自动核对主页作品数")

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
                env["MC_SLEEP_MIN"] = str(a.sleep_min)
                env["MC_SLEEP_MAX"] = str(a.sleep_max)
                print(f"[随机延时] 每次请求独立取 uniform({a.sleep_min}, {a.sleep_max}) 秒")

    # —— 评论数上限落地：MediaCrawler 出厂单视频 10 条，打 env 补丁让 MC_COMMENTS_COUNT 覆盖 ——
    if a.get_comment and a.comments_count != 10:
        r = ensure_mc_comments_patch(mc_root)
        if r not in ("patched", "already"):
            sys.exit(f"[ERR] 评论上限补丁失败({r})，无法保证每视频 100 条；停止抓取，不降级到 10 条。")
        env["MC_COMMENTS_COUNT"] = str(a.comments_count)
        print(f"[评论数补丁] {r}（CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES 可由 MC_COMMENTS_COUNT 覆盖）")
        print(f"[评论数] 本次单视频上限 MC_COMMENTS_COUNT={env['MC_COMMENTS_COUNT']} 条")

    log_path = os.path.join(a.save_dir, "crawl.log")
    log_start_offset = os.path.getsize(log_path) if os.path.isfile(log_path) else 0
    progress = RunProgress(a.root, "crawl").heartbeat()
    progress.log(f"运行目录={a.root} account={a.account} mode={a.mode} target={a.target}")
    print(f"[日志] {log_path}")

    # —— 失败自动重试（指数退避：5s→10s→20s→...→封顶60s）———
    attempts = a.retry_fail + 1
    rc = None
    for i in range(1, attempts + 1):
        if i > 1 and a.sleep_min is not None and not a.no_mc_patch:
            print(f"[随机延时] 第 {i} 次尝试继续逐请求取 uniform({a.sleep_min}, {a.sleep_max}) 秒")
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

    optimization_metrics = collect_optimization_metrics(log_path, log_start_offset)
    progress.detail(
        "请求提速统计: "
        f"saved_detail_requests={optimization_metrics['saved_detail_requests']} "
        f"skipped_comment_requests={optimization_metrics['skipped_comment_requests']}",
        **optimization_metrics,
    )
    print(f"[请求提速统计] saved detail requests={optimization_metrics['saved_detail_requests']} | "
          f"skipped comment requests={optimization_metrics['skipped_comment_requests']}")

    # Never process stale or partial output after a crawler failure.
    if rc != 0:
        progress.finish(False, f"MediaCrawler 失败，退出码={rc}", **optimization_metrics)
        print(f"[停止] MediaCrawler 退出码 {rc}；不执行任何兜底方案。请修复 MediaCrawler 后重试。")
        sys.exit(rc or 1)

    # 先读取本次 contents，评论文件校验需要用它判断是否所有目标明确为零评论。
    raws = raw_contents_files(a.save_dir)
    if not raws:
        progress.finish(False, "抓取结束但未发现 contents JSONL", **optimization_metrics)
        print("[提示] save_dir 下未发现 *contents*.jsonl；请检查登录态/风控，重试或看 crawl.log。")
        sys.exit(rc or 1)

    # —— 产物判定：开评论时先校验评论产物（MediaCrawler 文件名前缀 = {mode}_comments），
    # 缺失即失败；仅当本次所有目标明确为零评论且跳过标记覆盖全部目标时允许缺失 ——
    comment_files = []
    if a.get_comment:
        cps = glob.glob(os.path.join(a.save_dir, "**", f"{a.mode}_comments*.jsonl"), recursive=True)
        if not cps:
            skipped_ids = collect_skipped_zero_comment_ids(log_path, log_start_offset)
            target_rows = target_aweme_rows(
                raws, keyword=a.kw,
                hard_limit=a.max if a.mode == "creator" else None,
                mode=a.mode, target=a.target,
            )
            expected_ids = extract_target_aweme_ids(a.target) if a.mode == "detail" else None
            if all_targets_explicit_zero(target_rows, skipped_ids, expected_ids):
                optimization_metrics["zero_comment_targets_without_file"] = len(target_rows)
                print(f"[评论产物] 无 {a.mode}_comments_*.jsonl，但 {len(target_rows)} 个目标均明确 comment_count=0，"
                      "且本次 skipped_zero_comments 已覆盖全部目标，按空评论集放行。")
            else:
                progress.finish(False, f"评论抓取已开启但未发现 {a.mode}_comments_*.jsonl", **optimization_metrics)
                print(f"[ERR] 已开启评论抓取（--comments-count {a.comments_count}）但未发现 {a.mode}_comments_*.jsonl；"
                      "目标存在未知/非零评论或 skipped_zero_comments 未覆盖全部目标，拒绝静默降级。")
                sys.exit(rc or 1)
        comment_files = sorted(cps)
        print("=" * 70)
        print(f"[评论产物] {len(cps)} 个 {a.mode}_comments_*.jsonl：")
        for f in comment_files:
            print("  " + f)

    # Account slug is a storage key, never a content filter. Filter only when explicitly requested.
    kw = a.kw
    filtered = os.path.join(a.save_dir, f"{a.account}_dedup.jsonl")
    counts = filter_dedup(raws, filtered, kw, hard_limit=a.max if a.mode == "creator" else None)

    # —— 主页作品数核对（防静默漏抓：--max 裁剪、翻页中断、detail 签名失败都会漏）——
    if a.mode == "creator":
        aweme_total = None
        try:
            with open(os.path.join(a.save_dir, "creator_profile.json"), encoding="utf-8") as f:
                aweme_total = json.load(f).get("aweme_count")
        except Exception:
            aweme_total = None
        if isinstance(aweme_total, int) and aweme_total > 0:
            print(f"[核对] 主页作品总数={aweme_total} | 实际抓取唯一={counts['unique']}")
            if counts["unique"] < aweme_total:
                missing = aweme_total - counts["unique"]
                if counts["unique"] >= a.max:
                    print(f"[警告] 抓取 {counts['unique']} 条已达 --max={a.max} 上限，仍少于主页 {aweme_total} 条；"
                          f"调大 --max 重跑即可断点续传补 {missing} 条。")
                else:
                    progress.finish(False, f"漏抓：唯一={counts['unique']} < 主页={aweme_total}（未达上限）", **optimization_metrics)
                    print(f"[ERR] 漏抓 {missing} 条（唯一 {counts['unique']} < 主页 {aweme_total}，且未达 --max 上限）。"
                          "请检查 crawl.log 的翻页/签名错误后重试；本次结果不完整，禁止直接进入报告阶段。")
                    sys.exit(1)
        else:
            print("[核对] 未获取主页作品总数（creator_profile.json 缺失或 aweme_count 无效），跳过核对")

    progress.finish(bool(counts["unique"]), f"抓取完成：原始={counts['total']} 唯一={counts['unique']}", **optimization_metrics)
    print("=" * 70)
    for raw in raws:
        print(f"[原始文件] {raw}")
    print(f"[去重文件] {filtered}")
    print(f"[统计] 引擎原始 {counts['total']} 行 | 匹配 {counts['matched']} | 去重 {counts['unique_before_limit']} | 最终保留 {counts['unique']} / 上限 {a.max if a.mode == 'creator' else '不适用'}")
    print("-" * 70)
    print(f"[下一阶段] runtime.py run --tool process.py --root \"{a.root}\" --account \"{a.account}\" --json \"{filtered}\"")
    if comment_files:
        print(f"[下一阶段] runtime.py run --tool comments.py --root \"{a.root}\" --account \"{a.account}\" --max {a.comments_count}")
    sys.exit(0 if counts["unique"] else 1)


if __name__ == "__main__":
    main()
