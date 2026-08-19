# -*- coding: utf-8 -*-
"""Append-only run logging and atomic resumable state."""
import datetime
import json
import os
import threading


class RunProgress:
    def __init__(self, root, stage, interval=60):
        self.root = os.path.abspath(root)
        self.stage = stage
        self.interval = interval
        self.log_path = os.path.join(self.root, "run.log")
        self.state_path = os.path.join(self.root, "run-state.json")
        self._stop = threading.Event()
        self._detail = "starting"
        os.makedirs(self.root, exist_ok=True)
        self.update("running", self._detail)

    def log(self, message):
        stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        line = f"[{stamp}] [{self.stage}] {message}"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line, flush=True)

    def update(self, status="running", detail=None, **metrics):
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
        stages[self.stage] = {"status": status, "detail": self._detail, "metrics": metrics,
                              "updated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
        state["current_stage"] = self.stage
        state["updated_at"] = stages[self.stage]["updated_at"]
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)

    def heartbeat(self):
        def loop():
            while not self._stop.wait(self.interval):
                self.log("进度心跳: " + self._detail)
                self.update("running", self._detail)
        threading.Thread(target=loop, daemon=True).start()
        return self

    def detail(self, text, **metrics):
        self._detail = text
        self.update("running", text, **metrics)

    def observe(self, text):
        """Refresh heartbeat text without rewriting state for every subprocess line."""
        self._detail = text

    def finish(self, ok, detail):
        self._stop.set()
        self.update("completed" if ok else "failed", detail)
        self.log(detail)
