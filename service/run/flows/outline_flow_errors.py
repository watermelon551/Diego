from __future__ import annotations


class OutlineFlowStopped(Exception):
    """Internal control-flow signal after a terminal outline failure is recorded."""
