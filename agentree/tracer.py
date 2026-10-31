"""轻量运行轨迹：终端回显（按深度缩进，直观看到代理树）+ 可选 JSONL 落盘。"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any


class Tracer:
    """记录 run_start / llm / tool_call / tool_result / run_end 五类事件。

    - echo:       是否回显到终端（按 depth 缩进）
    - jsonl_path: 追加写入 JSONL 文件，便于事后分析
    - capture:    把事件留存到 self.records（测试用）
    """

    def __init__(
        self,
        echo: bool = False,
        jsonl_path: str | None = None,
        capture: bool = False,
        stream: Any = None,
        sink: Any = None,
    ) -> None:
        self.echo = echo
        self.capture = capture
        self.sink = sink  # 外部回调 sink(record_dict)，Web 服务用它实时推送事件
        self.records: list[dict] = []
        self.stream = stream or sys.stderr
        self._fh = None
        if jsonl_path:
            parent = os.path.dirname(os.path.abspath(jsonl_path))
            os.makedirs(parent, exist_ok=True)
            self._fh = open(jsonl_path, "a", encoding="utf-8")

    def event(self, kind: str, run_id: str = "", depth: int = 0, **data: Any) -> None:
        rec = {"t": round(time.time(), 3), "kind": kind,
               "run_id": run_id, "depth": depth, **data}
        if self.sink:
            try:
                self.sink(rec)
            except Exception:
                pass
        if self.capture:
            self.records.append(rec)
        if self.echo:
            print("  " * depth + f"[{run_id} d{depth}] {self._fmt(kind, data)}",
                  file=self.stream)
        if self._fh:
            self._fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()

    @staticmethod
    def _fmt(kind: str, d: dict) -> str:
        if kind == "run_start":
            parent = f"  <- parent {d['parent']}" if d.get("parent") else ""
            return f"start task={_short(d.get('task', ''))}{parent}"
        if kind == "llm":
            calls = d.get("tool_calls") or []
            if calls:
                return f"llm -> {len(calls)} tool call(s): {', '.join(calls)}"
            return f"llm -> final ({d.get('content_chars', 0)} chars)"
        if kind == "tool_call":
            return f"tool {d.get('name')}({_short(d.get('args', ''))})"
        if kind == "tool_result":
            return f"result {d.get('name')} -> {d.get('chars')} chars, {d.get('secs')}s"
        if kind == "run_end":
            err = f"  ERROR: {d['error']}" if d.get("error") else ""
            return f"end steps={d.get('steps')} out={d.get('chars')} chars{err}"
        return json.dumps(d, ensure_ascii=False, default=str)[:200]

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


def _short(s: str, n: int = 100) -> str:
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"
