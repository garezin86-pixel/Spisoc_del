# src/schemas/stats.py
from typing import NamedTuple

class UsersStats(NamedTuple):
    total_users: int
    active_users: int
    admin_users: int

class TasksStats(NamedTuple):
    total_tasks: int
    done_tasks: int
    pending_tasks: int