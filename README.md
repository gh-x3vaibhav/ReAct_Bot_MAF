# QA Agent (Microsoft Agent Framework + Azure OpenAI Responses)

This project is a CLI-based QA agent that:
- accepts a test scenario from the user
- can call 3 tools automatically:
  1) requirement_structure_tool
  2) generic_test_generator
  3) report_formatter
- logs steps to logs.txt

## Prerequisites
- Python 3.10+
- Azure OpenAI deployment that supports Responses API
- Azure OpenAI endpoint + deployment name + API version ("preview")  (per docs)

## Setup (Windows)
1. Create venv:
   python -m venv .venv
   .\.venv\Scripts\activate

2. Install dependencies:
   pip install -r requirements.txt

3. Create .env:
   Copy .env.example -> .env
   Fill AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_API_KEY

4. Run:
   python main.py

## Notes
- If AZURE_OPENAI_API_KEY is not set, the app will use AzureCliCredential.