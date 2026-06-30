"""Generic scheduling / cycle / housekeep config models.

Copied verbatim from the mcv baseline to preserve behavior during extraction
(Phase 1). The richer variants (e.g. RepeatDay) are unified in a later phase.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class SchedulingConfig(BaseModel):
    """Time scheduling config. Defaults to a date list (RepeatDate).

    Attributes
    ----------
    scheduling_type : str
        Scheduling type, currently ``"RepeatDate"``.
    start_date : int
        Start date, ``YYYYMMDD``.
    end_date : int
        End date, ``YYYYMMDD``.
    """

    scheduling_type: Literal["RepeatDate"] = "RepeatDate"
    start_date: int
    end_date: int


class CycleConfig(BaseModel):
    """Per-cycle config, only meaningful in ecFlow mode.

    Attributes
    ----------
    cycle_label : str
        Cycle label (ecFlow variable CYCLE_LABEL), default ``"12"``.
    time : str or None
        Cycle start time; if omitted the cycle starts immediately.
    """

    cycle_label: str = "12"
    time: Optional[str] = None


class HousekeepConfig(BaseModel):
    """Housekeeping (cleanup) config.

    Attributes
    ----------
    clear_day : int
        Number of days run directories are kept, default 3.
    time : str or None
        Cleanup start time; if omitted, runs after all other modules complete.
    """

    clear_day: int = 3
    time: Optional[str] = None


__all__ = ["SchedulingConfig", "CycleConfig", "HousekeepConfig"]
