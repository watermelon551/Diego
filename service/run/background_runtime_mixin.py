from __future__ import annotations

import asyncio
import threading
import traceback
from typing import Any


class RunBackgroundRuntimeMixin:
    def _spawn(self, coro: Any) -> None:
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
            future.add_done_callback(self._on_background_future_done)
            return

        task = loop.create_task(coro)
        task.add_done_callback(self._on_background_task_done)

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

    @staticmethod
    def _on_background_task_done(task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            traceback.print_exc()

    @staticmethod
    def _on_background_future_done(future: Any) -> None:
        try:
            future.result()
        except asyncio.CancelledError:
            return
        except Exception:
            traceback.print_exc()
