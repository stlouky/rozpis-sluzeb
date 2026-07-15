"""Solver rozpisu služeb — čisté API nad OR-Tools CP-SAT."""

from .config import Config, Employee, Obsazeni, Pravidla, Vahy, config_from_dict, load_config
from .core import NelzeSestavitError, generate_schedule
from .schedule import Schedule

__all__ = [
    "Config",
    "Employee",
    "Obsazeni",
    "Pravidla",
    "Vahy",
    "config_from_dict",
    "load_config",
    "NelzeSestavitError",
    "generate_schedule",
    "Schedule",
]
