"""Background run manager for the web UI."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .storage import RunStorage, utc_now_iso

LOG_LINE_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} [0-9:,]+) - "
    r"(?P<module>[\w\.]+) - "
    r"(?P<level>[A-Z]+) - "
    r"(?P<message>.*)$"
)

OUTPUT_PATH_PATTERN = re.compile(r"(?:报告已保存到|Weekly 已保存到|文件已保存到):\s*(.+)$")

CATEGORY_FINAL_PATTERN = re.compile(r"分类\s+(.+?)\s+最终:\s*(\d+)\s*条")


@dataclass
class RunRequest:
    """User request for creating a run."""

    mode: str = "weekly"
    dry_run: bool = False
    config_path: str = "config/config.yaml"
    weekly_config_path: str = "config/weekly_config.yaml"
    max_articles: Optional[int] = None
    hours: Optional[int] = None
    extra_args: List[str] = field(default_factory=list)


@dataclass
class ProgressUpdate:
    """Progress update parsed from one log line."""

    step: Optional[str] = None
    progress: Optional[int] = None
    output_path: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)


def parse_log_line(line: str) -> Dict[str, str]:
    """Parse a structured Python logging line if available."""
    clean = (line or "").rstrip("\n")
    matched = LOG_LINE_PATTERN.match(clean)
    if matched:
        payload = matched.groupdict()
        return {
            "timestamp": payload["timestamp"],
            "level": payload["level"],
            "module": payload["module"],
            "message": payload["message"],
            "raw_line": clean,
        }

    lowered = clean.lower()
    level = "INFO"
    if any(keyword in lowered for keyword in ("error", "失败", "异常", "traceback")):
        level = "ERROR"
    elif any(keyword in lowered for keyword in ("warning", "warn", "警告")):
        level = "WARNING"

    return {
        "timestamp": utc_now_iso(),
        "level": level,
        "module": "stdout",
        "message": clean,
        "raw_line": clean,
    }


def interpret_progress_line(mode: str, line: str, current_progress: int) -> ProgressUpdate:
    """Interpret one log line and derive optional run progress updates."""
    text = (line or "").strip()
    if not text:
        return ProgressUpdate()

    update = ProgressUpdate()

    output_match = OUTPUT_PATH_PATTERN.search(text)
    if output_match:
        update.output_path = output_match.group(1).strip()

    if mode == "standard":
        step_map = [
            ("Step 1", "抓取源", 20),
            ("Step 2", "内容过滤", 40),
            ("Step 3", "AI 分析", 60),
            ("Step 4", "写入缓存", 80),
            ("Step 5", "生成报告", 92),
        ]
    else:
        step_map = [
            ("开始生成 Weekly", "初始化", 8),
            ("共收集", "抓取完成", 25),
            ("处理文章", "AI 提取", 45),
            ("分类", "分类整理", 70),
            ("Weekly 已保存到", "写入结果", 92),
            ("文件已保存到", "写入结果", 92),
        ]

    for marker, step_name, progress in step_map:
        if marker in text and progress > current_progress:
            update.step = step_name
            update.progress = progress

    if any(keyword in text for keyword in ("执行完成", "生成完成", "✅ 完成", "Dry-run 模式")):
        update.step = "完成"
        update.progress = 100

    stats: Dict[str, Any] = {}

    match = re.search(r"共收集\s*(\d+)\s*篇唯一文章", text)
    if match:
        stats["unique_articles"] = int(match.group(1))

    match = re.search(r"过滤后剩余\s*(\d+)\s*篇文章待处理", text)
    if match:
        stats["filtered_articles"] = int(match.group(1))

    match = re.search(r"分析完成:\s*成功\s*(\d+)\s*/\s*(\d+)", text)
    if match:
        stats["ai_success"] = int(match.group(1))
        stats["ai_total"] = int(match.group(2))

    match = re.search(r"已写入 Weekly 去重缓存:\s*(\d+)\s*条", text)
    if match:
        stats["dedup_written"] = int(match.group(1))

    match = CATEGORY_FINAL_PATTERN.search(text)
    if match:
        stats["categories"] = {match.group(1): int(match.group(2))}

    if stats:
        update.stats = stats

    return update


class RunManager:
    """Create and track background runs started from the web UI."""

    def __init__(self, *, project_root: Path, python_exec: str, storage: RunStorage):
        self.project_root = Path(project_root)
        self.python_exec = python_exec
        self.storage = storage
        self._threads: Dict[int, threading.Thread] = {}
        self._lock = threading.Lock()

    def start_run(self, request: RunRequest) -> int:
        """Start a run in a background thread and return run id."""
        if request.mode not in {"weekly", "standard"}:
            raise ValueError("mode must be 'weekly' or 'standard'")

        if self.storage.has_active_run():
            raise RuntimeError("已有任务在运行，请等待当前任务结束")

        cmd = [self.python_exec, "main.py"]

        if request.mode == "weekly":
            cmd.extend(["--weekly", "--weekly-config", request.weekly_config_path])
        else:
            cmd.extend(["--config", request.config_path])
            if request.max_articles is not None:
                cmd.extend(["--max-articles", str(request.max_articles)])
            if request.hours is not None:
                cmd.extend(["--hours", str(request.hours)])

        if request.dry_run:
            cmd.append("--dry-run")

        if request.extra_args:
            cmd.extend(request.extra_args)

        command_text = " ".join(shlex.quote(part) for part in cmd)

        run_id = self.storage.create_run(
            mode=request.mode,
            dry_run=request.dry_run,
            config_path=request.config_path,
            weekly_config_path=request.weekly_config_path,
            extra_args=request.extra_args,
            command=command_text,
        )

        thread = threading.Thread(
            target=self._execute_run,
            args=(run_id, cmd, request.mode),
            daemon=True,
        )

        with self._lock:
            self._threads[run_id] = thread

        thread.start()
        return run_id

    def rerun(self, source_run_id: int) -> int:
        """Create a new run from an existing run's parameters."""
        source = self.storage.get_run(source_run_id)
        if not source:
            raise ValueError("原始运行记录不存在")

        source_stats = source.get("stats") or {}
        request = RunRequest(
            mode=source.get("mode", "weekly"),
            dry_run=bool(source.get("dry_run")),
            config_path=source.get("config_path") or "config/config.yaml",
            weekly_config_path=source.get("weekly_config_path") or "config/weekly_config.yaml",
            max_articles=source_stats.get("requested_max_articles"),
            hours=source_stats.get("requested_hours"),
            extra_args=list(source.get("extra_args") or []),
        )
        return self.start_run(request)

    def _execute_run(self, run_id: int, cmd: List[str], mode: str) -> None:
        self.storage.update_run(
            run_id,
            status="running",
            current_step="启动中",
            progress=2,
        )
        self.storage.append_log(
            run_id,
            level="INFO",
            module="webui.runner",
            message=f"启动任务: {' '.join(cmd)}",
            raw_line=f"启动任务: {' '.join(cmd)}",
        )

        start = datetime.now(timezone.utc)
        current_progress = 2
        current_step = "启动中"
        output_path: Optional[str] = None
        error_message = ""

        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=os.environ.copy(),
            )

            if process.stdout is None:
                raise RuntimeError("未能捕获子进程输出")

            for raw_line in process.stdout:
                parsed = parse_log_line(raw_line)
                self.storage.append_log(
                    run_id,
                    level=parsed["level"],
                    module=parsed["module"],
                    message=parsed["message"],
                    raw_line=parsed["raw_line"],
                    timestamp=parsed["timestamp"],
                )

                interpreted = interpret_progress_line(mode, parsed["message"], current_progress)
                if interpreted.stats:
                    self.storage.merge_stats(run_id, interpreted.stats)

                run_update: Dict[str, Any] = {}

                if interpreted.step and interpreted.step != current_step:
                    current_step = interpreted.step
                    run_update["current_step"] = current_step

                if interpreted.progress is not None and interpreted.progress > current_progress:
                    current_progress = interpreted.progress
                    run_update["progress"] = current_progress

                if interpreted.output_path:
                    output_path = interpreted.output_path
                    run_update["output_path"] = output_path

                if run_update:
                    self.storage.update_run(run_id, **run_update)

                if parsed["level"] == "ERROR" and not error_message:
                    error_message = parsed["message"][:400]

            return_code = process.wait()

            end = datetime.now(timezone.utc)
            duration = (end - start).total_seconds()

            if return_code == 0:
                self.storage.update_run(
                    run_id,
                    status="success",
                    current_step="完成",
                    progress=100,
                    ended_at=utc_now_iso(),
                    duration_seconds=duration,
                    exit_code=0,
                    output_path=output_path,
                )
                self.storage.append_log(
                    run_id,
                    level="INFO",
                    module="webui.runner",
                    message="任务执行成功",
                    raw_line="任务执行成功",
                )
            else:
                if not error_message:
                    latest = self.storage.latest_log(run_id)
                    if latest:
                        error_message = latest.get("message", "任务执行失败")
                    else:
                        error_message = f"任务执行失败，退出码 {return_code}"

                self.storage.update_run(
                    run_id,
                    status="failed",
                    current_step=current_step,
                    progress=max(current_progress, 3),
                    ended_at=utc_now_iso(),
                    duration_seconds=duration,
                    exit_code=return_code,
                    output_path=output_path,
                    error_message=error_message,
                )
                self.storage.append_log(
                    run_id,
                    level="ERROR",
                    module="webui.runner",
                    message=error_message,
                    raw_line=error_message,
                )

        except Exception as exc:  # pragma: no cover - safety net
            end = datetime.now(timezone.utc)
            duration = (end - start).total_seconds()
            message = f"任务异常终止: {exc}"
            self.storage.append_log(
                run_id,
                level="ERROR",
                module="webui.runner",
                message=message,
                raw_line=message,
            )
            self.storage.update_run(
                run_id,
                status="failed",
                current_step=current_step,
                progress=max(current_progress, 3),
                ended_at=utc_now_iso(),
                duration_seconds=duration,
                error_message=message,
            )
        finally:
            with self._lock:
                self._threads.pop(run_id, None)
