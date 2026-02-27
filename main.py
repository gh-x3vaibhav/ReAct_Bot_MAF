
import os
import logging
import asyncio
from pathlib import Path
from logging.handlers import RotatingFileHandler

from azure.identity import AzureCliCredential
from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIResponsesClient

import tools as tools_module


# ------------------------
# LOGGER SETUP 
# ------------------------
def setup_logger(log_file: str = "logs.txt") -> None:
    logger = logging.getLogger()  # root logger
    logger.setLevel(logging.INFO)

    log_path = Path(log_file)
    if not log_path.is_absolute():
        log_path = Path(__file__).resolve().parent / log_path
    log_path = log_path.resolve()

    # Avoid adding duplicate rotating handler for the same file
    for h in logger.handlers:
        if isinstance(h, RotatingFileHandler):
            existing_file = getattr(h, "baseFilename", "")
            if existing_file and Path(existing_file).resolve() == log_path:
                return

    formatter = logging.Formatter(
        fmt="%(asctime)s -\n%(message)s\n",
        datefmt="%H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        str(log_path), maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


# ------------------------
# MAIN BOT CODE
# ------------------------
setup_logger("logs.txt")


def _is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.strip().lower()
    return "<" in normalized or ">" in normalized or "your-" in normalized


def _load_raw_env() -> dict[str, str]:
    env_path = Path(__file__).with_name(".env")
    parsed: dict[str, str] = {}

    if not env_path.exists():
        return parsed

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")

    return parsed


def _get_env_value(primary: str, *aliases: str, default: str | None = None) -> str | None:
    keys = (primary, *aliases)
    fallback_placeholder: str | None = None

    for key in keys:
        val = os.getenv(key)
        if val is not None and val.strip() != "":
            candidate = val.strip()
            if _is_placeholder(candidate):
                fallback_placeholder = fallback_placeholder or candidate
                continue
            return candidate

    raw_env = _load_raw_env()
    for key in keys:
        val = raw_env.get(key)
        if val is not None and val.strip() != "":
            candidate = val.strip()
            if _is_placeholder(candidate):
                fallback_placeholder = fallback_placeholder or candidate
                continue
            return candidate

    if fallback_placeholder is not None:
        return fallback_placeholder

    return default


def _flush_log_handlers() -> None:
    """Force all file handlers to flush to disk."""
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass


def log_block(title: str, content: str) -> None:
    msg = f"\n[{title}]\n{content}\n"
    logging.info(msg)
    _flush_log_handlers()
    print(msg)


def _build_tc_report(header: str) -> str:
    """Build the test-case report string from tools_module.LAST_TEST_CASES."""
    sep = "=" * 90
    thin = "-" * 90
    lines: list[str] = []
    lines.append("")
    lines.append(sep)
    lines.append(f"  INPUT: {header}")
    lines.append(sep)

    # ---- Knowledge Graph summary section ----
    kg = tools_module.KNOWLEDGE_GRAPH
    if kg.nodes:
        kg_sum = kg.summary()
        lines.append("")
        lines.append("  KNOWLEDGE GRAPH SUMMARY")
        lines.append(thin)
        lines.append(f"    Nodes : {kg_sum['total_nodes']}  |  Edges : {kg_sum['total_edges']}")
        lines.append(f"    Node types    : {', '.join(f'{k}({v})' for k, v in kg_sum['node_types'].items())}")
        lines.append(f"    Relation types: {', '.join(f'{k}({v})' for k, v in kg_sum['relation_types'].items())}")
        lines.append("")

    for idx, tc in enumerate(tools_module.LAST_TEST_CASES, start=1):
        title = tc.get("title", "Untitled") if isinstance(tc, dict) else str(tc)
        tc_type = tc.get("type", "General") if isinstance(tc, dict) else ""
        steps = tc.get("steps", []) if isinstance(tc, dict) else []
        kg_nodes = tc.get("kg_nodes", []) if isinstance(tc, dict) else []
        kg_relations = tc.get("kg_relations", []) if isinstance(tc, dict) else []

        lines.append("")
        lines.append(f"  Test Case {idx}: {title} ({tc_type})")
        if kg_nodes:
            lines.append(f"    [KG Nodes: {', '.join(kg_nodes)}]")
        if kg_relations:
            lines.append(f"    [KG Relations: {', '.join(kg_relations)}]")
        lines.append(thin)

        for si, step_obj in enumerate(steps, start=1):
            if isinstance(step_obj, dict):
                step_text = step_obj.get("step", "")
                example = step_obj.get("example", "")
            else:
                step_text = str(step_obj)
                example = ""

            lines.append(f"    Step {si}: {step_text}")
            if example:
                lines.append(f"             (Example: {example})")

        lines.append("")

    # ---- Coverage summary ----
    if kg.nodes:
        covered_nodes: set = set()
        covered_rels: set = set()
        for tc in tools_module.LAST_TEST_CASES:
            if isinstance(tc, dict):
                covered_nodes.update(tc.get("kg_nodes", []))
                covered_rels.update(tc.get("kg_relations", []))
        all_nodes = set(kg.nodes.keys())
        all_rels = {e["relation"] for e in kg.edges}
        lines.append(thin)
        lines.append(f"  KG NODE COVERAGE    : {len(covered_nodes & all_nodes)}/{len(all_nodes)}")
        lines.append(f"  KG RELATION COVERAGE: {len(covered_rels & all_rels)}/{len(all_rels)}")

    lines.append(sep)
    lines.append(f"  Total Test Cases: {len(tools_module.LAST_TEST_CASES)}")
    lines.append(sep)
    lines.append("")
    return "\n".join(lines)


def _save_tc_file(report_text: str) -> None:
    """Write the test-case report to TC.txt alongside main.py."""
    tc_path = Path(__file__).resolve().parent / "TC.txt"
    tc_path.write_text(report_text, encoding="utf-8")
    print(f"\n[INFO] Test cases saved to {tc_path}")
    logging.info(f"Test cases saved to {tc_path}")


def create_agent():
    endpoint = _get_env_value("AZURE_OPENAI_ENDPOINT")
    deployment = _get_env_value(
        "AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME",
        "Deployment name",
    )
    api_version = _get_env_value(
        "AZURE_OPENAI_API_VERSION",
        "OPENAI_API_VERSION",
        default="preview",
    )
    api_key = _get_env_value("AZURE_OPENAI_API_KEY")

    if api_version and api_version.strip().lower() != "preview":
        logging.info(
            "[CONFIG] OPENAI/AZURE API version '%s' is not supported by Responses API; using 'preview'.",
            api_version,
        )
        api_version = "preview"

    if _is_placeholder(endpoint) or _is_placeholder(deployment):
        raise RuntimeError(
            "Set real values for AZURE_OPENAI_ENDPOINT and "
            "AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME in .env"
        )

    if api_key is not None and _is_placeholder(api_key):
        raise RuntimeError(
            "Set a real AZURE_OPENAI_API_KEY in .env or remove it to use AzureCliCredential"
        )

    client = AzureOpenAIResponsesClient(
        endpoint=endpoint,
        deployment_name=deployment,
        api_version=api_version,
        api_key=api_key or None,
        credential=None if api_key else AzureCliCredential(),
        env_file_path=str(Path(__file__).with_name(".env.responses.local")),
    )

    instructions = (
        "You are an expert QA Test Engineer assistant that uses Knowledge Graphs for traceability.\n"
        "When the user provides a requirement or scenario, you MUST:\n"
        "\n"
        "1. Call knowledge_graph_builder to build a Knowledge Graph from the requirement.\n"
        "   Extract ALL entities as nodes with types:\n"
        "   - Feature, Page, Field, Action, Validation, UserRole, Data, SecurityControl\n"
        "   Map ALL relationships as edges with relations:\n"
        "   - HAS_FIELD, HAS_ACTION, VALIDATES, NAVIGATES_TO, DEPENDS_ON, REQUIRES,\n"
        "     TRIGGERS, PRODUCES, PROTECTED_BY, ROLE_ACCESSES\n"
        "   Be thorough: every UI element, validation rule, user role, security concern,\n"
        "   and navigation path should appear as a node with edges connecting them.\n"
        "   IMPORTANT: In node properties, use ONLY plain strings, numbers, and booleans.\n"
        "   Do NOT include regex patterns or special backslash sequences in properties.\n"
        "   Example good property: {\"validates\": \"email format\", \"required\": true}\n"
        "   Example BAD property:  {\"regex\": \"^[\\\\w]+@\"} — NEVER do this.\n"
        "\n"
        "2. Call knowledge_graph_test_generator with a comprehensive JSON array of test cases.\n"
        "   Use the Knowledge Graph to drive test generation — traverse every node and edge\n"
        "   to ensure full coverage:\n"
        "   - For each Field node: positive, negative, and edge-case tests\n"
        "   - For each Action node: valid triggers and error paths\n"
        "   - For each Validation node: pass and fail scenarios\n"
        "   - For each SecurityControl node: injection, XSS, brute force tests\n"
        "   - For each NAVIGATES_TO edge: navigation flow tests\n"
        "   - For each DEPENDS_ON edge: dependency-breaking tests\n"
        "   Generate 10-15+ test cases covering ALL categories:\n"
        "   Positive, Negative, Edge, UI, Navigation, Compatibility, Security\n"
        "\n"
        "   Each test case MUST have:\n"
        '   - "title": descriptive name\n'
        '   - "type": one of Positive|Negative|Edge|UI|Navigation|Compatibility|Security\n'
        '   - "kg_nodes": array of node ids from the knowledge graph this test covers\n'
        '   - "kg_relations": array of relation names exercised by this test\n'
        '   - "steps": array of objects with "step" (action description) and "example" (concrete example value)\n'
        "\n"
        "   Use realistic example data (emails, passwords, URLs) relevant to the scenario.\n"
        "   Each test case should have 2-5 steps.\n"
        "   Aim for 100%% node and relation coverage across all test cases.\n"
        "\n"
        "3. Call report_formatter with the input scenario as header to produce the final CLI report.\n"
        "\n"
        "Always call all three tools in sequence. Do NOT skip any tool.\n"
        "Do NOT return test cases as plain text — always pass them through the tools.\n"
    )

    return ChatAgent(
        chat_client=client,
        name="IntelligentQABot",
        instructions=instructions,
        tools=[
            tools_module.knowledge_graph_builder,
            tools_module.knowledge_graph_test_generator,
            tools_module.report_formatter,
        ],
    )


def run_bot():
    try:
        user_input = input("Enter your test scenario / requirement: ").strip()
        if not user_input:
            print("Error: Scenario cannot be empty.")
            return

        tools_module.TOOL_OBSERVATIONS.clear()
        tools_module.LAST_TEST_CASES.clear()
        tools_module.FINAL_REPORT = ""
        tools_module.KNOWLEDGE_GRAPH.clear()

        log_block("INPUT SCENARIO", user_input)
        log_block(
            "THOUGHT",
            "The user has provided a requirement.\n"
            "The agent will analyze the requirement, generate QA test cases,\n"
            "and format them into a final report."
        )

        agent = create_agent()
        _ = asyncio.run(agent.run(user_input))

        for obs in tools_module.TOOL_OBSERVATIONS:
            log_block("OBSERVATION", str(obs))

        # ---- Display the formatted report in CLI & save to TC.txt + logs.txt ----
        if tools_module.FINAL_REPORT:
            report_text = tools_module.FINAL_REPORT
        elif tools_module.LAST_TEST_CASES:
            report_text = _build_tc_report(user_input)
        else:
            report_text = ""

        if report_text:
            print(report_text)
            _save_tc_file(report_text)
            log_block("FINAL TEST CASE REPORT", report_text)
        else:
            print("\nNo test cases were generated. Please try a more specific scenario.\n")
            logging.info("No test cases were generated.")

        log_block("END", "Agent execution completed successfully.")
        _flush_log_handlers()

    except KeyboardInterrupt:
        print("\nBot stopped by user.")
        logging.info("Bot stopped by user.")
    except Exception as e:
        print(f"\nError: {e}")
        logging.error(f"Error: {e}", exc_info=True)
    finally:
        _flush_log_handlers()


if __name__ == "__main__":
    run_bot()
