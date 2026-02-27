import json
import logging
import re
from typing import Annotated, List, Dict, Any, Optional
from pydantic import Field
from agent_framework import ai_function

TOOL_OBSERVATIONS: List[str] = []
LAST_TEST_CASES: List[Dict[str, Any]] = []
FINAL_REPORT: str = ""


# ================================================================== #
#  Robust JSON helpers
# ================================================================== #
def _fix_invalid_escapes(s: str) -> str:
    """Fix invalid JSON escape sequences produced by LLMs (e.g. \\w, \\d, \\.).

    JSON only allows: \\\", \\\\, \\/, \\b, \\f, \\n, \\r, \\t, \\uXXXX.
    Anything else (like \\w from regex) must be double-escaped.
    """
    return re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', s)


def _safe_json_loads(s: str) -> Any:
    """Parse a JSON string with multiple fallback strategies.

    Handles: invalid escape sequences, trailing commas, missing brackets.
    NEVER raises — returns an empty list on total failure.
    """
    # Strategy 1: direct parse
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: fix invalid escape sequences (LLM puts regex like \\w in JSON)
    try:
        return json.loads(_fix_invalid_escapes(s))
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 3: strip trailing commas + ensure array brackets + fix escapes
    try:
        cleaned = _fix_invalid_escapes(s.strip().rstrip(","))
        if not cleaned.startswith("["):
            cleaned = "[" + cleaned + "]"
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    # Total failure — return empty list so the tool never crashes
    logging.warning("[JSON PARSE] All strategies failed. Returning empty list.")
    return []


# ================================================================== #
#  In-memory Knowledge Graph
# ================================================================== #
class KnowledgeGraph:
    """Simple in-memory directed knowledge graph."""

    def __init__(self) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = {}   # id -> {label, type, properties}
        self.edges: List[Dict[str, str]] = []         # [{source, target, relation}]

    # ---- mutation ----
    def add_node(self, node_id: str, label: str, node_type: str, properties: Optional[Dict[str, Any]] = None) -> None:
        self.nodes[node_id] = {"label": label, "type": node_type, "properties": properties or {}}

    def add_edge(self, source: str, target: str, relation: str) -> None:
        self.edges.append({"source": source, "target": target, "relation": relation})

    # ---- query helpers ----
    def get_nodes_by_type(self, node_type: str) -> List[Dict[str, Any]]:
        return [{"id": nid, **data} for nid, data in self.nodes.items() if data["type"] == node_type]

    def get_neighbors(self, node_id: str) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for e in self.edges:
            if e["source"] == node_id and e["target"] in self.nodes:
                result.append({"id": e["target"], "relation": e["relation"], **self.nodes[e["target"]]})
            elif e["target"] == node_id and e["source"] in self.nodes:
                result.append({"id": e["source"], "relation": e["relation"], **self.nodes[e["source"]]})
        return result

    def get_all_paths(self, start: str, max_depth: int = 4) -> List[List[str]]:
        """BFS to enumerate simple paths from *start* up to *max_depth*."""
        paths: List[List[str]] = []
        queue: List[List[str]] = [[start]]
        while queue:
            path = queue.pop(0)
            if len(path) > 1:
                paths.append(path)
            if len(path) >= max_depth:
                continue
            current = path[-1]
            for neighbor in self.get_neighbors(current):
                nid = neighbor["id"]
                if nid not in path:
                    queue.append(path + [nid])
        return paths

    def summary(self) -> Dict[str, Any]:
        type_counts: Dict[str, int] = {}
        for data in self.nodes.values():
            type_counts[data["type"]] = type_counts.get(data["type"], 0) + 1
        relation_counts: Dict[str, int] = {}
        for e in self.edges:
            relation_counts[e["relation"]] = relation_counts.get(e["relation"], 0) + 1
        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "node_types": type_counts,
            "relation_types": relation_counts,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {"nodes": self.nodes, "edges": self.edges}

    def clear(self) -> None:
        self.nodes.clear()
        self.edges.clear()


# Global knowledge graph instance
KNOWLEDGE_GRAPH = KnowledgeGraph()


def _pretty(obj) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)


def _log_action(tool_name: str, args: dict) -> None:
    logging.info(f"\n[ACTION]\nTool: {tool_name}\nArgs: {_pretty(args)}\n")
    # Flush file handlers so every step is persisted immediately
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass


def _observe(payload) -> None:
    TOOL_OBSERVATIONS.append(str(payload))


# ------------------------------------------------------------------ #
# Tool 1 – Build a Knowledge Graph from the requirement
# ------------------------------------------------------------------ #
@ai_function
def knowledge_graph_builder(
    requirement: Annotated[str, Field(description="Plain English requirement or validation rule.")],
    feature: Annotated[str, Field(description="Short feature name extracted from the requirement (e.g. 'Google Login').")],
    nodes_json: Annotated[
        str,
        Field(
            description=(
                "A JSON array of node objects extracted from the requirement. "
                "Each node MUST have: "
                '"id" (unique snake_case identifier), '
                '"label" (human-readable name), '
                '"type" (one of: Feature | Page | Field | Action | Validation | UserRole | Data | SecurityControl), '
                '"properties" (object with simple key-value metadata ONLY — use plain strings '
                "and numbers, do NOT include regex patterns or special escape sequences). "
                "Extract ALL entities: pages/screens, input fields, buttons/actions, "
                "validation rules, user roles, data items, and security controls. "
                "Example: "
                '[{"id":"login_page","label":"Login Page","type":"Page","properties":{"url":"https://accounts.google.com/"}},'
                '{"id":"email_field","label":"Email/Phone Field","type":"Field","properties":{"required":true,"format":"email_or_phone"}},'
                '{"id":"password_field","label":"Password Field","type":"Field","properties":{"required":true,"min_length":8}},'
                '{"id":"submit_btn","label":"Next/Sign In Button","type":"Action","properties":{"triggers":"authentication"}},'
                '{"id":"valid_user","label":"Valid Registered User","type":"UserRole","properties":{"has_credentials":true}},'
                '{"id":"email_format_check","label":"Email Format Validation","type":"Validation","properties":{"validates":"email format"}}]'
            )
        ),
    ],
    edges_json: Annotated[
        str,
        Field(
            description=(
                "A JSON array of edge/relationship objects connecting the nodes. "
                "Each edge MUST have: "
                '"source" (node id), '
                '"target" (node id), '
                '"relation" (one of: HAS_FIELD | HAS_ACTION | VALIDATES | NAVIGATES_TO | '
                "DEPENDS_ON | REQUIRES | TRIGGERS | PRODUCES | PROTECTED_BY | ROLE_ACCESSES). "
                "Map ALL relationships between entities: which page has which fields, "
                "which action triggers which validation, which field depends on another, etc. "
                "Example: "
                '[{"source":"login_page","target":"email_field","relation":"HAS_FIELD"},'
                '{"source":"login_page","target":"password_field","relation":"HAS_FIELD"},'
                '{"source":"login_page","target":"submit_btn","relation":"HAS_ACTION"},'
                '{"source":"submit_btn","target":"email_format_check","relation":"TRIGGERS"},'
                '{"source":"email_format_check","target":"email_field","relation":"VALIDATES"},'
                '{"source":"valid_user","target":"login_page","relation":"ROLE_ACCESSES"}]'
            )
        ),
    ],
    url: Annotated[str, Field(description="Application URL relevant to the requirement (e.g. 'https://accounts.google.com/').")] = "",
) -> str:
    """Build a knowledge graph from the requirement. Extracts entities as nodes and
    their relationships as edges, storing them in an in-memory graph used by
    downstream tools to generate thorough, graph-driven test cases."""
    try:
        args = {"requirement": requirement, "feature": feature, "url": url,
                "nodes_json": "(see log)", "edges_json": "(see log)"}
        _log_action("knowledge_graph_builder", args)

        logging.info(f"\n[KG NODES RAW]\n{nodes_json}\n")
        logging.info(f"\n[KG EDGES RAW]\n{edges_json}\n")
        for h in logging.getLogger().handlers:
            try:
                h.flush()
            except Exception:
                pass

        # ---- Parse nodes (robust) ----
        nodes_list: list = _safe_json_loads(nodes_json)

        # ---- Parse edges (robust) ----
        edges_list: list = _safe_json_loads(edges_json)

        # ---- Populate global knowledge graph ----
        KNOWLEDGE_GRAPH.clear()
        for node in nodes_list:
            if isinstance(node, dict) and "id" in node:
                KNOWLEDGE_GRAPH.add_node(
                    node_id=node["id"],
                    label=node.get("label", node["id"]),
                    node_type=node.get("type", "Entity"),
                    properties=node.get("properties", {}),
                )
        for edge in edges_list:
            if isinstance(edge, dict) and "source" in edge and "target" in edge:
                KNOWLEDGE_GRAPH.add_edge(
                    source=edge["source"],
                    target=edge["target"],
                    relation=edge.get("relation", "RELATED_TO"),
                )

        kg_summary = KNOWLEDGE_GRAPH.summary()
        result = json.dumps({
            "feature": feature,
            "url": url,
            "knowledge_graph": kg_summary,
            "status": "Knowledge Graph Built",
        })
        _observe(result)
        return result

    except Exception as exc:
        # SAFETY NET: tool must NEVER raise — always return a valid string
        err_msg = f"knowledge_graph_builder partial failure: {exc}"
        logging.error(err_msg, exc_info=True)
        _observe(err_msg)
        return json.dumps({"status": "error", "message": str(exc)})


# ------------------------------------------------------------------ #
# Tool 2 – Generate test cases driven by the Knowledge Graph
# ------------------------------------------------------------------ #
@ai_function
def knowledge_graph_test_generator(
    test_cases_json: Annotated[
        str,
        Field(
            description=(
                "A JSON string representing an array of test-case objects. "
                "Use the Knowledge Graph built in the previous step to drive test generation: "
                "traverse every node and relationship to ensure full coverage. "
                "For each Field node, generate positive, negative, and edge-case tests. "
                "For each Action node, test valid triggers and error paths. "
                "For each Validation node, test pass and fail scenarios. "
                "For each SecurityControl node, test injection, XSS, brute force, etc. "
                "For each NAVIGATES_TO relationship, test navigation flows. "
                "For each DEPENDS_ON relationship, test dependency breaking. "
                "\n"
                "Each object MUST have: "
                '"title" (string – test case name), '
                '"type" (string – Positive | Negative | Edge | UI | Navigation | Compatibility | Security), '
                '"kg_nodes" (array of node ids from the knowledge graph that this test covers), '
                '"kg_relations" (array of relation names from the knowledge graph exercised by this test), '
                '"steps" (array of objects each with "step" (string) and "example" (string)). '
                "Generate as many test cases as needed to fully cover every node and edge in the graph "
                "(positive, negative, edge, UI, security, compatibility, etc.). "
                "Example: "
                '[{"title":"Login with valid email and valid password","type":"Positive",'
                '"kg_nodes":["login_page","email_field","password_field","submit_btn","valid_user"],'
                '"kg_relations":["HAS_FIELD","HAS_ACTION","ROLE_ACCESSES"],'
                '"steps":[{"step":"Open browser and go to Google login page","example":"https://accounts.google.com/"},'
                '{"step":"Enter valid email/phone and click Next","example":"Email = qa.demo.login@gmail.com"},'
                '{"step":"Enter valid password and click Next","example":"Password = Valid@12345"},'
                '{"step":"Verify login is successful","example":"User lands on Google Account/Home page"}]}]'
            )
        ),
    ],
) -> str:
    """Store the fully-detailed, knowledge-graph-driven test cases produced by the LLM.
    Each test case references the KG nodes and relations it covers for traceability."""
    global LAST_TEST_CASES

    try:
        _log_action("knowledge_graph_test_generator", {"test_cases_json": "(see below)"})
        logging.info(f"\n[RAW TEST JSON]\n{test_cases_json}\n")
        for h in logging.getLogger().handlers:
            try:
                h.flush()
            except Exception:
                pass

        parsed: list = _safe_json_loads(test_cases_json)
        LAST_TEST_CASES = parsed

        # ---- Coverage analysis against the knowledge graph ----
        covered_nodes: set = set()
        covered_relations: set = set()
        for tc in parsed:
            if isinstance(tc, dict):
                covered_nodes.update(tc.get("kg_nodes", []))
                covered_relations.update(tc.get("kg_relations", []))

        all_node_ids = set(KNOWLEDGE_GRAPH.nodes.keys())
        all_relations = {e["relation"] for e in KNOWLEDGE_GRAPH.edges}
        uncovered_nodes = all_node_ids - covered_nodes
        uncovered_relations = all_relations - covered_relations

        coverage = {
            "status": "ok",
            "test_case_count": len(parsed),
            "titles": [tc.get("title", "") for tc in parsed if isinstance(tc, dict)],
            "kg_node_coverage": f"{len(covered_nodes & all_node_ids)}/{len(all_node_ids)}",
            "kg_relation_coverage": f"{len(covered_relations & all_relations)}/{len(all_relations)}",
            "uncovered_nodes": list(uncovered_nodes),
            "uncovered_relations": list(uncovered_relations),
        }

        result = json.dumps(coverage)
        _observe(result)
        return result

    except Exception as exc:
        err_msg = f"knowledge_graph_test_generator partial failure: {exc}"
        logging.error(err_msg, exc_info=True)
        _observe(err_msg)
        return json.dumps({"status": "error", "message": str(exc)})


# ------------------------------------------------------------------ #
# Tool 3 – Format & print the final report (with KG traceability)
# ------------------------------------------------------------------ #
@ai_function
def report_formatter(
    header: Annotated[str, Field(description="Report header / input scenario text.")] = "QA Test Cases",
) -> str:
    """Format LAST_TEST_CASES into a human-readable CLI report with knowledge-graph
    traceability and return it."""
    global FINAL_REPORT

    try:
        _log_action("report_formatter", {"header": header})

        if not LAST_TEST_CASES:
            report = "No test cases were generated."
            _observe(report)
            FINAL_REPORT = report
            return json.dumps({"report": report})

        sep = "=" * 90
        thin = "-" * 90
        lines: List[str] = []
        lines.append("")
        lines.append(sep)
        lines.append(f"  INPUT: {header}")
        lines.append(sep)

        # ---- Knowledge Graph summary section ----
        if KNOWLEDGE_GRAPH.nodes:
            kg_sum = KNOWLEDGE_GRAPH.summary()
            lines.append("")
            lines.append("  KNOWLEDGE GRAPH SUMMARY")
            lines.append(thin)
            lines.append(f"    Nodes : {kg_sum['total_nodes']}  |  Edges : {kg_sum['total_edges']}")
            lines.append(f"    Node types    : {', '.join(f'{k}({v})' for k, v in kg_sum['node_types'].items())}")
            lines.append(f"    Relation types: {', '.join(f'{k}({v})' for k, v in kg_sum['relation_types'].items())}")
            lines.append("")

        # ---- Test cases ----
        for idx, tc in enumerate(LAST_TEST_CASES, start=1):
            title = tc.get("title", "Untitled")
            tc_type = tc.get("type", "General")
            steps = tc.get("steps", [])
            kg_nodes = tc.get("kg_nodes", [])
            kg_relations = tc.get("kg_relations", [])

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
        if KNOWLEDGE_GRAPH.nodes:
            covered_nodes: set = set()
            covered_rels: set = set()
            for tc in LAST_TEST_CASES:
                covered_nodes.update(tc.get("kg_nodes", []))
                covered_rels.update(tc.get("kg_relations", []))
            all_nodes = set(KNOWLEDGE_GRAPH.nodes.keys())
            all_rels = {e["relation"] for e in KNOWLEDGE_GRAPH.edges}
            lines.append(thin)
            lines.append(f"  KG NODE COVERAGE    : {len(covered_nodes & all_nodes)}/{len(all_nodes)}")
            lines.append(f"  KG RELATION COVERAGE: {len(covered_rels & all_rels)}/{len(all_rels)}")

        lines.append(sep)
        lines.append(f"  Total Test Cases: {len(LAST_TEST_CASES)}")
        lines.append(sep)
        lines.append("")

        report = "\n".join(lines)
        _observe(report)
        FINAL_REPORT = report
        return json.dumps({"report": report})

    except Exception as exc:
        err_msg = f"report_formatter failure: {exc}"
        logging.error(err_msg, exc_info=True)
        _observe(err_msg)
        return json.dumps({"report": "Error generating report", "error": str(exc)})
