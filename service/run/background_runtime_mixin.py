from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from typing import Any

logger = logging.getLogger(__name__)


class RunBackgroundRuntimeMixin:
    def _spawn(self, coro: Any, *, run_id: str | None = None) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:

            def runner() -> None:
                asyncio.run(coro)

            threading.Thread(target=runner, daemon=True).start()
            return

        if threading.current_thread() is not threading.main_thread():
            future = asyncio.run_coroutine_threadsafe(
                coro,
                self._ensure_background_loop(),
            )
            future.add_done_callback(
                lambda f: self._on_background_future_done(f, run_id=run_id)
            )
            return

        task = loop.create_task(coro)
        task.add_done_callback(
            lambda t: self._on_background_task_done(t, run_id=run_id)
        )

    def _ensure_background_loop(self) -> asyncio.AbstractEventLoop:
        with self._background_loop_lock:
            loop = self._background_loop
            thread = self._background_loop_thread
            if loop is not None and thread is not None and thread.is_alive():
                return loop

            ready = threading.Event()
            holder: dict[str, asyncio.AbstractEventLoop] = {}

            def runner() -> None:
                background_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(background_loop)
                holder["loop"] = background_loop
                ready.set()
                background_loop.run_forever()

            thread = threading.Thread(
                target=runner,
                name="diego-background-loop",
                daemon=True,
            )
            thread.start()
            ready.wait()
            self._background_loop = holder["loop"]
            self._background_loop_thread = thread
            return self._background_loop

    def _on_background_task_done(
        self, task: asyncio.Task[Any], *, run_id: str | None = None
    ) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            traceback.print_exc()
            if run_id:
                self._mark_run_failed_on_unhandled_exception(run_id, task)

    def _on_background_future_done(
        self, future: Any, *, run_id: str | None = None
    ) -> None:
        try:
            future.result()
        except asyncio.CancelledError:
            return
        except Exception:
            traceback.print_exc()
            if run_id:
                self._mark_run_failed_on_unhandled_exception(run_id, future)

    def _mark_run_failed_on_unhandled_exception(
        self, run_id: str, task_or_future: Any
    ) -> None:
        """Safety net: mark run as FAILED if an unhandled exception escapes the generation task."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self._fail_run(
                    run_id,
                    "UNKNOWN",
                    "UNHANDLED_BACKGROUND_EXCEPTION",
                    retryable=True,
                    error_details={
                        "reason": "Background task raised an unhandled exception. See server logs for traceback.",
                    },
                )
            )
        except RuntimeError:
            # No running loop — try from background loop
            bg_loop = getattr(self, "_background_loop", None)
            if bg_loop and bg_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._fail_run(
                        run_id,
                        "UNKNOWN",
                        "UNHANDLED_BACKGROUND_EXCEPTION",
                        retryable=True,
                        error_details={
                            "reason": "Background task raised an unhandled exception. See server logs for traceback.",
                        },
                    ),
                    bg_loop,
                )
            else:
                logger.error(
                    "Could not mark run %s as FAILED: no available event loop",
                    run_id,
                )
