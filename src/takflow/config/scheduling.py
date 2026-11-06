"""Generic scheduling / cycle / housekeep config models."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError


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

    @field_validator("start_date", "end_date")
    @classmethod
    def _check_calendar_date(cls, value: int) -> int:
        encoded = str(value)
        try:
            if len(encoded) != 8:
                raise ValueError
            date(int(encoded[:4]), int(encoded[4:6]), int(encoded[6:]))
        except ValueError:
            raise PydanticCustomError(
                "config_date_invalid",
                "must be a real calendar date in YYYYMMDD format",
            ) from None
        return value

    @field_validator("end_date")
    @classmethod
    def _check_date_order(cls, value: int, info: ValidationInfo) -> int:
        start_date = info.data.get("start_date")
        if start_date is not None and value < start_date:
            raise PydanticCustomError(
                "config_date_order", "end_date must be on or after start_date",
            )
        return value


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
