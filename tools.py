import json
import logging
from typing import Annotated, List, Dict
from pydantic import Field
from agent_framework import ai_function

TOOL_OBSERVATIONS: List[str] = []
LAST_TEST_CASES: List[str] = []

def _pretty(obj) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)

def _log_action(tool_name: str, args: dict) -> None:
    logging.info(f"\n[ACTION]\nTool: {tool_name}\nArgs: {_pretty(args)}\n")

def _observe(payload) -> None:
    TOOL_OBSERVATIONS.append(str(payload))

@ai_function
def requirement_structure_tool(
    requirement: Annotated[str, Field(description="Plain English requirement or validation rule.")]
) -> Dict[str, object]:
    args = {"requirement": requirement}
    _log_action("requirement_structure_tool", args)

    words = [w for w in (requirement or "").strip().split() if w]
    result = {"analyzed_length": len(words), "status": "Requirement Received & Parsed"}
    _observe(result)
    return result

@ai_function
def generic_test_generator(
    action: Annotated[str, Field(description="User action or step to validate, phrased as an action statement.")],
    expected_outcome: Annotated[str, Field(description="Expected result when the action is performed correctly.")],
) -> Dict[str, List[str]]:
    global LAST_TEST_CASES

    args = {"action": action, "expected_outcome": expected_outcome}
    _log_action("generic_test_generator", args)

    test_cases = [
        f"POSITIVE: Verify user can '{action}' and see '{expected_outcome}'.",
        f"NEGATIVE: Verify '{action}' with empty data does NOT show '{expected_outcome}'.",
        f"BOUNDARY: Verify '{action}' with max character limit handles gracefully.",
        f"SECURITY: Verify '{action}' is protected against common vulnerabilities.",
    ]

    LAST_TEST_CASES = test_cases

    result = {"test_cases": test_cases}
    _observe(result)
    return result

@ai_function
def report_formatter(
    test_cases: Annotated[List[str], Field(description="List of generated test case statements.")]
) -> str:
    args = {"test_cases": test_cases}
    _log_action("report_formatter", args)

    lines = ["--- QA AUTOMATION REPORT ---"]
    for i, tc in enumerate(test_cases, start=1):
        lines.append(f"TC_{i:03d}: {tc}")
    lines.append("----------------------------")

    report = "\n".join(lines)
    _observe(report)
    return report