
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


def log_block(title: str, content: str) -> None:
    msg = f"\n[{title}]\n{content}\n"
    logging.info(msg)
    print(msg)


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
        "You are an intelligent QA assistant.\n"
        "Decide which tools are necessary based on the user requirement.\n"
        "Do not call tools unnecessarily.\n"
        "If needed, call tools to structure requirement, generate test cases, then format report.\n"
        "Always ensure test cases are produced.\n"
    )

    return ChatAgent(
        chat_client=client,
        name="IntelligentQABot",
        instructions=instructions,
        tools=[
            tools_module.requirement_structure_tool,
            tools_module.generic_test_generator,
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

        if tools_module.LAST_TEST_CASES:
            print("\nFINAL TEST CASES\n")
            for i, tc in enumerate(tools_module.LAST_TEST_CASES, start=1):
                print(f"TC_{i:03d}: {tc}")
            print("")

            logging.info(
                "\n[FINAL TEST CASES]\n" +
                "\n".join(
                    [f"TC_{i:03d}: {tc}" for i, tc in enumerate(tools_module.LAST_TEST_CASES, start=1)]
                ) +
                "\n"
            )
        else:
            print("\nNo test cases were generated.\n")
            logging.info("\n[FINAL TEST CASES]\nNo test cases were generated.\n")

        log_block("END", "Agent execution completed successfully.")

    except KeyboardInterrupt:
        print("\nBot stopped by user.")
    except Exception as e:
        print(f"\nError: {e}")


if __name__ == "__main__":
    run_bot()