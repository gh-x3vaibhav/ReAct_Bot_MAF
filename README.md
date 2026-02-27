<div align="center">

# ReAct QA Agent

### Knowledge-Graph-Driven Test Case Generator

Built with **Microsoft Agent Framework** &middot; Powered by **Azure OpenAI Responses API**

---

</div>

## Overview

**ReAct QA Agent** is an intelligent CLI-based QA assistant that automatically generates comprehensive, traceable test cases from plain-English requirements. It leverages a **ReAct (Reasoning + Acting)** loop and an in-memory **Knowledge Graph** to ensure full coverage of every entity, relationship, and edge case in your specification.

Give it a requirement &mdash; it builds a knowledge graph, generates 10-15+ categorized test cases, and outputs a formatted report with full KG traceability.

---

## Key Features

| Feature | Description |
|---|---|
| **Knowledge Graph Construction** | Automatically extracts entities (Pages, Fields, Actions, Validations, User Roles, Security Controls) and their relationships from natural-language requirements |
| **Graph-Driven Test Generation** | Traverses every node and edge in the KG to produce Positive, Negative, Edge, UI, Navigation, Compatibility, and Security test cases |
| **Traceability** | Each test case references the exact KG nodes and relations it covers, with coverage metrics in the final report |
| **Formatted CLI Reports** | Clean, human-readable output displayed in the terminal and saved to `TC.txt` |
| **Detailed Logging** | Full execution trace (thoughts, actions, observations) persisted to `logs.txt` with rotating file support |

---

## Architecture

```
User Requirement
       │
       ▼
┌──────────────────────┐
│  1. KG Builder        │  ──▶  Extracts nodes & edges into an in-memory Knowledge Graph
└──────────────────────┘
       │
       ▼
┌──────────────────────┐
│  2. Test Generator    │  ──▶  Traverses the KG to produce comprehensive test cases
└──────────────────────┘
       │
       ▼
┌──────────────────────┐
│  3. Report Formatter  │  ──▶  Formats output with coverage stats & KG traceability
└──────────────────────┘
       │
       ▼
  TC.txt + CLI Output
```

### Tool Pipeline

| # | Tool | Purpose |
|---|---|---|
| 1 | `knowledge_graph_builder` | Parses the requirement into a directed graph of entities and relationships |
| 2 | `knowledge_graph_test_generator` | Uses the KG to generate categorized test cases with full node/edge coverage |
| 3 | `report_formatter` | Produces the final CLI report with KG summary and coverage metrics |

---

## Prerequisites

- **Python** 3.10+
- **Azure OpenAI** deployment with Responses API support
- **Azure CLI** (optional &mdash; for credential-based auth without API key)

---

## Getting Started

### 1. Clone the Repository

```bash
git clone <repository-url>
cd ReAct_Bot_MAF
```

### 2. Create & Activate Virtual Environment

```bash
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME=your-deployment-name
AZURE_OPENAI_API_VERSION=preview
AZURE_OPENAI_API_KEY=your-api-key          # Optional — omit to use Azure CLI auth
```

### 5. Run the Agent

```bash
python main.py
```

You will be prompted to enter a test scenario or requirement. The agent will process it through all three tools and display the results.

---

## Example Usage

```
Enter your test scenario / requirement: Google Login Page - user logs in with email and password

==========================================================================================
  INPUT: Google Login Page - user logs in with email and password
==========================================================================================

  KNOWLEDGE GRAPH SUMMARY
------------------------------------------------------------------------------------------
    Nodes : 8  |  Edges : 10
    Node types    : Feature(1), Page(1), Field(2), Action(2), Validation(1), UserRole(1)
    Relation types: HAS_FIELD(2), HAS_ACTION(2), VALIDATES(1), TRIGGERS(2), ROLE_ACCESSES(1)

  Test Case 1: Login with valid credentials (Positive)
    [KG Nodes: login_page, email_field, password_field, submit_btn, valid_user]
    [KG Relations: HAS_FIELD, HAS_ACTION, ROLE_ACCESSES]
------------------------------------------------------------------------------------------
    Step 1: Open browser and navigate to Google login page
             (Example: https://accounts.google.com/)
    Step 2: Enter valid email and click Next
             (Example: Email = qa.demo@gmail.com)
    ...

==========================================================================================
  Total Test Cases: 12
==========================================================================================
```

---

## Project Structure

```
ReAct_Bot_MAF/
├── main.py              # Entry point — agent setup, ReAct loop, report generation
├── tools.py             # Tool definitions (KG Builder, Test Generator, Report Formatter)
├── requirements.txt     # Python dependencies
├── .env                 # Azure OpenAI credentials (not tracked in git)
├── logs.txt             # Rotating execution logs
├── TC.txt               # Generated test case report (output)
└── README.md
```

---

## Knowledge Graph Node & Edge Types

### Node Types

| Type | Description |
|---|---|
| `Feature` | High-level feature being tested |
| `Page` | UI page or screen |
| `Field` | Input field (text, dropdown, checkbox, etc.) |
| `Action` | Button click, form submission, or user action |
| `Validation` | Validation rule applied to a field or action |
| `UserRole` | Type of user interacting with the system |
| `Data` | Data entity or payload |
| `SecurityControl` | Security mechanism (CAPTCHA, rate limiting, etc.) |

### Edge Relations

| Relation | Description |
|---|---|
| `HAS_FIELD` | Page contains a field |
| `HAS_ACTION` | Page or feature has an action |
| `VALIDATES` | Validation rule applies to a field |
| `NAVIGATES_TO` | Action leads to another page |
| `DEPENDS_ON` | Entity depends on another |
| `REQUIRES` | Precondition relationship |
| `TRIGGERS` | Action triggers a validation or event |
| `PRODUCES` | Action produces data or output |
| `PROTECTED_BY` | Entity is protected by a security control |
| `ROLE_ACCESSES` | User role accesses a page or feature |

---

## Test Case Categories

| Category | Focus Area |
|---|---|
| **Positive** | Valid inputs and expected happy-path flows |
| **Negative** | Invalid inputs, missing fields, unauthorized access |
| **Edge** | Boundary values, special characters, max-length inputs |
| **UI** | Layout, responsiveness, placeholder text, error message display |
| **Navigation** | Page transitions, back/forward behavior, deep linking |
| **Compatibility** | Cross-browser, cross-device, OS-specific behavior |
| **Security** | SQL injection, XSS, brute force, session handling |

---

## Authentication

The agent supports two authentication modes:

| Mode | Configuration |
|---|---|
| **API Key** | Set `AZURE_OPENAI_API_KEY` in `.env` |
| **Azure CLI** | Omit the API key &mdash; the agent falls back to `AzureCliCredential` automatically |

---

## Dependencies

| Package | Purpose |
|---|---|
| `agent-framework` | Microsoft Agent Framework (preview) |
| `azure-identity` | Azure authentication (CLI credential support) |
| `python-dotenv` | Environment variable loading from `.env` |
| `pydantic` | Data validation for tool parameters |

---

## License

This project is provided as-is for internal use. See your organization's licensing policy for details.
