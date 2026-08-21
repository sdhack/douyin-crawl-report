# -*- coding: utf-8 -*-
"""Append-only run logging and atomic resumable state."""
import datetime
import json
import os
import tempfile
import threading


class RunProgress:
    def __init__(self, root, stage, interval=60):
        self.root = os.path.abspath(root)
        self.stage = stage
        self.interval = interval
        self.log_path = os.path.join(self.root, "run.log")
        self.state_path = os.path.join(self.root, "run-state.json")
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._finished = False
        self._detail = "starting"
        self._started_at = self._new_started_at()
        os.makedirs(self.root, exist_ok=True)
        self.update("running", self._detail)

    def _new_started_at(self):
        """续跑 running 阶段时沿用起始时间；已结束阶段重新计时。"""
        try:
            with open(self.state_path, encoding="utf-8") as f:
                old = json.load(f)
            stage = (old.get("stages") or {}).get(self.stage) or {}
            if stage.get("status") == "running" and stage.get("started_at"):
                return stage["started_at"]
        except Exception:
            pass
        return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _merge_dict(old, new):
        merged = dict(old or {})
        for key, value in (new or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = RunProgress._merge_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _duration(self, now):
        try:
            started = datetime.datetime.fromisoformat(self._started_at)
            return max(0.0, (now - started).total_seconds())
        except (TypeError, ValueError):
            return 0.0

    def log(self, message):
        stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        line = f"[{stamp}] [{self.stage}] {message}"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line, flush=True)

    def update(self, status="running", detail=None, **metrics):
        with self._lock:
            if detail is not None:
                self._detail = detail
            state = {}
            if os.path.exists(self.state_path):
                try:
                    with open(self.state_path, encoding="utf-8") as f:
                        state = json.load(f)
                except Exception:
                    state = {}
            stages = state.setdefault("stages", {})
            previous = stages.get(self.stage) or {}
            now = datetime.datetime.now().astimezone()
            merged_metrics = self._merge_dict(previous.get("metrics"), metrics)
            # duration_sec is maintained by the progress writer itself, so a heartbeat
            # never replaces historical stage metrics with an empty dict.
            merged_metrics["duration_sec"] = round(self._duration(now), 3)
            stages[self.stage] = {
                "status": status, "detail": self._detail, "metrics": merged_metrics,
                "started_at": self._started_at,
                "updated_at": now.isoformat(timespec="seconds"),
            }
            state["current_stage"] = self.stage
            state["updated_at"] = stages[self.stage]["updated_at"]
            out_dir = os.path.dirname(self.state_path) or "."
            fd, tmp = tempfile.mkstemp(prefix=os.path.basename(self.state_path) + ".",
                                       suffix=".tmp", dir=out_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.state_path)
            finally:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass

    def heartbeat(self):
        def loop():
            while not self._stop.wait(self.interval):
                with self._lock:
                    if self._finished:
                        return
                    detail = self._detail
                    self.update("running", detail)
                    self.log("进度心跳: " + detail)
        threading.Thread(target=loop, daemon=True).start()
        return self

    def detail(self, text, **metrics):
        self._detail = text
        self.update("running", text, **metrics)

    def observe(self, text):
        """Refresh heartbeat text without rewriting state for every subprocess line."""
        self._detail = text

    def finish(self, ok, detail, **metrics):
        with self._lock:
            self._finished = True
            self._stop.set()
            self.update("completed" if ok else "failed", detail, **metrics)
            self.log(detail)
