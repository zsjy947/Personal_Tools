"""后台任务执行器：工作线程、日志队列与结果回传。

工具函数在后台线程运行，print 输出经线程安全队列交给主线程，
主线程通过定期调用 `poll()` 刷日志并接收完成/失败结果。
"""

import queue
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout

POLL_INTERVAL_MS = 80

EXPECTED_ERRORS = (FileNotFoundError, NotADirectoryError, OSError, RuntimeError, ValueError)


class _QueueWriter:
    """把 print 输出转发到线程安全队列。"""

    def __init__(self, log_queue: queue.Queue) -> None:
        self._queue = log_queue

    def write(self, text: str) -> None:
        if text:
            self._queue.put(text)

    def flush(self) -> None:
        pass


class TaskRunner:
    """在后台线程执行工具函数，同一时间只允许一个任务。"""

    def __init__(self, log_sink) -> None:
        self._log_sink = log_sink
        self._log_queue: queue.Queue = queue.Queue()
        self._result_queue: queue.Queue = queue.Queue()
        self._writer = _QueueWriter(self._log_queue)
        self.busy = False

    def submit(self, title: str, worker) -> bool:
        """提交任务；已有任务在执行时返回 False。"""
        if self.busy:
            return False
        self.busy = True
        self._log_queue.put(f"\n===== {title} =====\n")
        threading.Thread(target=self._run, args=(worker,), daemon=True).start()
        return True

    def _run(self, worker) -> None:
        try:
            with redirect_stdout(self._writer), redirect_stderr(self._writer):
                message = worker()
        except EXPECTED_ERRORS as exc:
            self._result_queue.put((f"错误: {exc}", False))
        except Exception:
            self._log_queue.put(traceback.format_exc())
            self._result_queue.put(("发生意外错误，详见运行日志。", False))
        else:
            self._result_queue.put((message, True))

    def poll(self):
        """由主线程周期调用：刷新日志并返回 (message, succeeded) 或 None。"""
        chunks = []
        try:
            while True:
                chunks.append(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        if chunks:
            self._log_sink("".join(chunks))
        try:
            result = self._result_queue.get_nowait()
        except queue.Empty:
            return None
        self.busy = False
        return result
