"""PatentLoop: an autonomous prior-art loop over one raw idea.

Trigger -> research -> patent search -> feasibility gate -> decision gate ->
either a drafted provisional application or a reasoned kill report.
"""

from .config import Config
from .orchestrator import Orchestrator, run_idea
from .schemas import DRAFTED, KILLED_INFEASIBLE, KILLED_SATURATED

__all__ = ["Config", "Orchestrator", "run_idea", "DRAFTED", "KILLED_INFEASIBLE", "KILLED_SATURATED"]
