# -*- coding: utf-8 -*-
"""给 MediaCrawler 的 douyin client.py 打补丁：get_all_user_aweme_posts 增加断点续传 + 失败重试。
用法: python tools/patch_mediacrawler.py [<client.py 完整路径>]
未传路径时，自动探测常见安装位置；找不到则报错提示手填。
"""
import sys, io, os, glob


def find_client():
    candidates = [
        os.environ.get("MC_CLIENT_PATH", ""),
        os.path.join(os.path.expanduser("~"), ".cache", "codex-mediacrawler", "MediaCrawler", "media_platform", "douyin", "client.py"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    hits = glob.glob(os.path.join(os.path.expanduser("~"), ".cache", "**", "MediaCrawler", "media_platform", "douyin", "client.py"), recursive=True)
    return hits[0] if hits else ""


OLD_METHOD = '''    async def get_all_user_aweme_posts(self, sec_user_id: str, callback: Optional[Callable] = None):
        posts_has_more = 1
        max_cursor = ""
        result = []
        while posts_has_more == 1:
            aweme_post_res = await self.get_user_aweme_posts(sec_user_id, max_cursor)
            posts_has_more = aweme_post_res.get("has_more", 0)
            max_cursor = aweme_post_res.get("max_cursor")
            aweme_list = aweme_post_res.get("aweme_list") if aweme_post_res.get("aweme_list") else []
            utils.logger.info(f"[DouYinClient.get_all_user_aweme_posts] get sec_user_id:{sec_user_id} video len : {len(aweme_list)}")
            if callback:
                await callback(aweme_list)
            result.extend(aweme_list)
        return result'''

NEW_METHOD = '''    async def get_all_user_aweme_posts(self, sec_user_id: str, callback: Optional[Callable] = None):
        posts_has_more = 1
        max_cursor = self._load_cursor(sec_user_id)
        result = []
        retries = 0
        while posts_has_more == 1:
            try:
                aweme_post_res = await self.get_user_aweme_posts(sec_user_id, max_cursor)
                retries = 0
            except Exception as e:
                retries += 1
                if retries > 5:
                    raise
                wait = 15 * retries
                utils.logger.warning(f"[DouYinClient] page error: {e}; retry {retries} after {wait}s")
                await asyncio.sleep(wait)
                continue
            posts_has_more = aweme_post_res.get("has_more", 0)
            next_cursor = aweme_post_res.get("max_cursor")
            aweme_list = aweme_post_res.get("aweme_list") if aweme_post_res.get("aweme_list") else []
            utils.logger.info(f"[DouYinClient.get_all_user_aweme_posts] get sec_user_id:{sec_user_id} video len : {len(aweme_list)} cursor:{max_cursor} has_more:{posts_has_more}")
            if callback:
                await callback(aweme_list)
            result.extend(aweme_list)
            if posts_has_more == 1 and next_cursor is not None and next_cursor != max_cursor:
                self._save_cursor(sec_user_id, next_cursor)
            if next_cursor is not None and next_cursor == max_cursor:
                posts_has_more = 0
            max_cursor = next_cursor
        self._save_cursor(sec_user_id, "")
        return result

    def _cursor_path(self, sec_user_id: str):
        d = os.environ.get("MC_CURSOR_DIR", "")
        return os.path.join(d, "cursor_" + sec_user_id + ".json") if d else None

    def _load_cursor(self, sec_user_id: str):
        p = self._cursor_path(sec_user_id)
        try:
            if p and os.path.exists(p):
                data = json.load(open(p, encoding="utf-8"))
                return data.get("max_cursor", "")
        except Exception:
            pass
        return ""

    def _save_cursor(self, sec_user_id: str, cursor: str):
        p = self._cursor_path(sec_user_id)
        try:
            if p:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump({"max_cursor": cursor}, f)
        except Exception:
            pass'''


def main():
    client = sys.argv[1] if len(sys.argv) > 1 else find_client()
    if not client or not os.path.exists(client):
        sys.exit(f"[ERR] 未找到 MediaCrawler douyin/client.py。请传入路径：python tools/patch_mediacrawler.py <client.py>")

    src = io.open(client, encoding="utf-8").read()
    # 注入方法体用到 os / json，缺一都会在运行时 NameError（假依赖），故一并确保
    if "\nimport os\n" not in src and "\nimport json\n" not in src:
        src = src.replace("import asyncio\n", "import asyncio\nimport os\nimport json\n", 1)
    else:
        if "\nimport os\n" not in src:
            src = src.replace("import asyncio\n", "import asyncio\nimport os\n", 1)
        if "\nimport json\n" not in src:
            src = src.replace("import asyncio\n", "import asyncio\nimport json\n", 1)

    count = src.count(OLD_METHOD)
    if count != 1:
        sys.exit(f"[ERR] 期望匹配 1 处旧方法，实际 {count} 处——可能已打过补丁或版本不同")
    src = src.replace(OLD_METHOD, NEW_METHOD, 1)
    io.open(client, "w", encoding="utf-8").write(src)
    print(f"patched ok -> {client}")


if __name__ == "__main__":
    main()