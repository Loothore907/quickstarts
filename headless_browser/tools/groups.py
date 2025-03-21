from typing import Dict, List, Literal, TypedDict, Type

from .base import BaseAnthropicTool
from .bash import BashTool20241022, BashTool20250124
from .computer import ComputerTool20241022, ComputerTool20250124
from .edit import EditTool20241022, EditTool20250124

ToolVersion = Literal["computer_use_20250124", "computer_use_20241022"]
BetaFlag = Literal["computer-use-2024-10-22", "computer-use-2025-01-24"]

class ToolGroup(TypedDict):
    version: ToolVersion
    tools: List[Type[BaseAnthropicTool]]
    beta_flag: BetaFlag | None

TOOL_GROUPS_BY_VERSION: Dict[ToolVersion, ToolGroup] = {
    "computer_use_20241022": {
        "version": "computer_use_20241022",
        "tools": [BashTool20241022, ComputerTool20241022, EditTool20241022],
        "beta_flag": "computer-use-2024-10-22",
    },
    "computer_use_20250124": {
        "version": "computer_use_20250124",
        "tools": [BashTool20250124, ComputerTool20250124, EditTool20250124],
        "beta_flag": "computer-use-2025-01-24",
    },
}
