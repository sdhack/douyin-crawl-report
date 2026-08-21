#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
运行库全局解析器（douyin-crawl-report 技能内建）。
设计目标：运行库统一安装在【项目目录 .runtime/py】，通过全局注册指针复用，
换项目/换目录调用不重装环境。

用法：
  python runtime.py py            # 打印分析运行库（faster-whisper 栈）解释器绝对路径
  python runtime.py mc / mc-py    # 打印 MediaCrawler 抓取运行库解释器
  python runtime.py mc-root       # 打印 MediaCrawler 源码根
  python runtime.py mc-doctor     # 校验抓取运行库（main.py + playwright）
  python runtime.py register      # 把当前项目 .runtime/py 与 MediaCrawler 写入全局注册指针
  python runtime.py doctor        # 校验分析运行库必要依赖是否齐备，并探测 CUDA
  python runtime.py run  <tool> [args...]  # 用解析出的解释器运行 skills/tools/<tool>.py

解析优先级（douyin）：
  1) 环境变量  DOUYIN_RUNTIME_PY
  2) 全局注册指针 runtime-registry.json -> keys.douyin.python
  3) 当前项目  <workspace>/.runtime/py/Scripts/python.exe
            （运行库统一装在项目目录，写入全局指针复用，换目录不重装、不装 C 盘）

解析优先级（MediaCrawler，crawl）：
  1) 环境变量  MEDIACRAWLER_PY（解释器）/ MC_ROOT（源码根）
  2) 全局注册指针 runtime-registry.json -> keys.mediacrawler
  3) ~/.cache/codex-mediacrawler/MediaCrawler
"""
import os
import sys
import json
import subprocess

try:
    import toml
except Exception:
    toml = None

REGISTRY = os.path.join(
    os.path.expanduser("~"), ".trae-cn", "runtime-registry.json"
)
KEY = "douyin"
KEY_MC = "mediacrawler"
CACHE_MC = os.path.join(
    os.path.expanduser("~"), ".cache", "codex-mediacrawler", "MediaCrawler"
)


def skill_dir():
    d = os.path.dirname(os.path.abspath(__file__))  # .../skills/douyin-crawl-report/tools
    return os.path.dirname(d)


def project_runtime_py(cwd=None):
    cwd = cwd or os.getcwd()
    p = os.path.join(cwd, ".runtime", "py", "Scripts", "python.exe")
    return p if os.path.isfile(p) else None


def registered_py():
    try:
        with open(REGISTRY, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    p = data.get("keys", {}).get(KEY, {}).get("python")
    return p if p and os.path.isfile(p) else None


def _reg_get(key):
    try:
        with open(REGISTRY, encoding="utf-8") as f:
            return json.load(f).get("keys", {}).get(key, {})
    except Exception:
        return {}


def mc_py():
    """MediaCrawler 解释器：env > 全局指针 > 默认 cache。"""
    env = os.environ.get("MEDIACRAWLER_PY")
    if env and os.path.isfile(env):
        return env
    reg_py = _reg_get(KEY_MC).get("python")
    if reg_py and os.path.isfile(reg_py):
        return reg_py
    cand = os.path.join(CACHE_MC, ".venv", "Scripts", "python.exe")
    return cand if os.path.isfile(cand) else None


def mc_root():
    """MediaCrawler 源码根：env > 全局指针 > 默认 cache。"""
    r = os.environ.get("MC_ROOT", "").strip()
    if r and os.path.isfile(os.path.join(r, "main.py")):
        return r
    reg_root = _reg_get(KEY_MC).get("root")
    if reg_root and os.path.isfile(os.path.join(reg_root, "main.py")):
        return reg_root
    return CACHE_MC if os.path.isfile(os.path.join(CACHE_MC, "main.py")) else None


def mc_doctor():
    py = mc_py()
    root = mc_root()
    print("mc.python:", py)
    print("mc.root  :", root)
    if not py or not root:
        print("RESULT: 缺失 MediaCrawler 运行库（未找到 .venv 或 main.py）")
        return False
    main_ok = os.path.isfile(os.path.join(root, "main.py"))
    try:
        r = subprocess.run(
            [py, "-c", "import playwright,execjs,requests;print('ok')"],
            capture_output=True, text=True, timeout=60, cwd=root,
        )
        pw_ok = ("ok" in (r.stdout or "")) and r.returncode == 0
    except Exception:
        pw_ok = False
    print("main.py  :", main_ok)
    print("playwright+execjs+requests:", "OK" if pw_ok else "MISSING")
    ok = main_ok and pw_ok
    print("RESULT:", "OK" if ok else "需补装 run: <mc-python> -m pip install playwright execjs requests")
    return ok


def resolve_py():
    env = os.environ.get("DOUYIN_RUNTIME_PY")
    if env and os.path.isfile(env):
        return env
    for cand in (registered_py(), project_runtime_py()):
        if cand:
            return cand
    return None


def cmd_py():
    p = resolve_py()
    if not p:
        print("ERROR: 未找到运行库解释器（已尝试注册指针/项目.runtime）。", file=sys.stderr)
        sys.exit(2)
    return p


def required_ok(python):
    code = (
        "import importlib.util,sys\n"
        "mods=('faster_whisper','ctranslate2','av','PIL','numpy','tokenizers','onnxruntime')\n"
        "miss=[m for m in mods if importlib.util.find_spec(m) is None]\n"
        "import ctypes\n"
        "try:\n"
        "  import ctranslate2; g=ctranslate2.get_cuda_device_count()\n"
        "except Exception as e:\n"
        "  g=None\n"
        "print('miss='+repr(miss))\n"
        "print('cuda='+repr(g))\n"
    )
    try:
        r = subprocess.run([python, "-c", code], capture_output=True, text=True,
                           timeout=60, cwd=skill_dir())
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out
    except Exception as e:
        return False, f"run err: {e}"


def utf8_env():
    """Keep tool output and redirected logs readable on Windows consoles."""
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def configure_utf8_stdio():
    """Make this wrapper's own output deterministic before it starts child tools."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace", write_through=True)
            except (OSError, ValueError):
                pass


def main(argv):
    if not argv:
        print("用法见文件头 docstring。")
        sys.exit(0)
    cmd = argv[0]
    if cmd == "py":
        print(cmd_py())
    elif cmd in ("mc", "mc-py"):
        py = mc_py()
        if not py:
            print("ERROR: 未找到 MediaCrawler 解释器（env/全局指针/cache 均无）。", file=sys.stderr)
            sys.exit(2)
        print(py)
    elif cmd == "mc-root":
        r = mc_root()
        if not r:
            print("ERROR: 未找到 MediaCrawler 源码根（未发现 main.py）。", file=sys.stderr)
            sys.exit(2)
        print(r)
    elif cmd == "mc-doctor":
        ok = mc_doctor()
        sys.exit(0 if ok else 3)
    elif cmd == "register":
        p = project_runtime_py()
        if not p:
            print("ERROR: 当前目录下无 .runtime/py，请先在本=项目安装。", file=sys.stderr)
            sys.exit(2)
        os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
        data = {}
        if os.path.exists(REGISTRY):
            try:
                data = json.load(open(REGISTRY, encoding="utf-8"))
            except Exception:
                data = {}
        data.setdefault("keys", {})[KEY] = {
            "label": "douyin-crawl-report 分析运行库 (faster-whisper/av/pillow)",
            "python": p,
            "location": os.path.dirname(p),
            "note": "运行库装在项目目录，全局注册复用；换目录不重装。",
        }
        if mc_root():
            data.setdefault("keys", {})[KEY_MC] = {
                "label": "MediaCrawler 抓取运行库 (playwright, 断点续传)",
                "python": mc_py(),
                "root": mc_root(),
                "note": "抓取引擎源码保留在 cache，由技能 crawl.py 统一调度。",
            }
        json.dump(data, open(REGISTRY, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"registered -> {REGISTRY}\n  python={p}")
    elif cmd == "doctor":
        p = cmd_py()
        print("interpreter:", p)
        ok, out = required_ok(p)
        print(out)
        print("deps:", "OK" if ok else "CHECK OUTPUT")
    elif cmd == "run":
        if len(argv) < 3 or argv[1] != "--tool":
            print("用法: runtime.py run --tool <name.py> [args...]", file=sys.stderr)
            sys.exit(2)
        tool = argv[2]
        tool_path = os.path.join(skill_dir(), "tools", tool)
        if not os.path.isfile(tool_path):
            print(f"ERROR: 未找到工具 {tool_path}", file=sys.stderr)
            sys.exit(2)
        args = argv[3:]
        p = cmd_py()
        r = subprocess.run([p, tool_path] + args, cwd=os.getcwd(), env=utf8_env())
        sys.exit(r.returncode)
    else:
        print(f"未知命令: {cmd}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    configure_utf8_stdio()
    main(sys.argv[1:])
