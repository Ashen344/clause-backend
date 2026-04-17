"""
agents/analyst.py — Clause Analyst Agent.

Answers questions about contract clauses by:
1. Searching the knowledge base for relevant clause text.
2. Analysing the retrieved clauses against the user's question.
3. Returning a structured analysis with risk flags, plain-English summaries,
   and recommendations.

The agent runs a function-calling loop with Gemini until it has
enough context to answer and stops calling tools.
"""

import json
import logging

from tools import (
    search_clauses, TOOL_SCHEMAS,
    parse_tool_call, generate_text,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Clause Analyst for a Contract Lifecycle Management (CLM) platform.
Your job is to analyse contract clauses and provide clear, actionable insights.

When answering a question about clauses:
1. Call search_clauses() to retrieve relevant clauses from the knowledge base.
2. Analyse the retrieved clauses in the context of the user's question.
3. Provide a structured response with:
   - SUMMARY: plain-English explanation of what the clause(s) say
   - RISKS: any concerning terms, unusual language, or missing protections
   - COMPARISON: how this compares to standard market practice (based on retrieved examples)
   - RECOMMENDATION: what action the user should consider

To call a tool, respond ONLY with a JSON object like:
{"name": "search_clauses", "arguments": {"query": "...", "top_k": 5}}

Always base your analysis on the retrieved clause text. If no relevant clauses are found,
say so clearly and provide general guidance from legal best practices.
Be precise, professional, and concise. Avoid legal jargon where plain language suffices."""


# Tool schemas filtered to only what the analyst needs
ANALYST_TOOL_SCHEMAS = [s for s in TOOL_SCHEMAS if s["function"]["name"] == "search_clauses"]


def _execute_tool(name: str, arguments: dict) -> str:
    if name == "search_clauses":
        return search_clauses(**arguments)
    return json.dumps({"error": f"Unknown tool: {name}"})


def run(
    question: str,
    doc_type: str = None,
    document_text: str = None,
    max_iterations: int = 2
) -> dict:
    """
    Run the Clause Analyst agent.

    Args:
        question:       User's question about a clause or contract topic.
        doc_type:       Optional filter for knowledge base search (SLA, MSA, etc.).
        document_text:  Optional raw contract text to analyse directly.
        max_iterations: Max tool-call rounds.

    Returns:
        {
            "analysis":     str,   # structured analysis text
            "clauses_found": int,  # number of relevant clauses retrieved
            "sources":      list,  # source documents referenced
        }
    """
    tools_json = json.dumps(ANALYST_TOOL_SCHEMAS)

    user_message = f"Question: {question}"
    if doc_type:
        user_message += f"\nFocus on contract type: {doc_type.upper()}"
    if document_text:
        snippet = document_text[:3000]
        user_message += f"\n\nContract text to analyse:\n{snippet}"
    user_message += f"\n\nAvailable tools (JSON):\n{tools_json}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_message}
    ]

    clauses_found = 0
    sources = []
    analysis = None

    for iteration in range(max_iterations):
        logger.info(f"[analyst] iteration {iteration + 1}")

        response_text = generate_text(messages, max_tokens=1024, temperature=0.3, task="analyst")

        tool_call = parse_tool_call(response_text)

        if tool_call and tool_call["name"] == "search_clauses":
            tool_args = tool_call["arguments"]
            if doc_type and "doc_type" not in tool_args:
                tool_args["doc_type"] = doc_type.upper()

            logger.info(f"[analyst] searching: {tool_args}")
            tool_result = _execute_tool("search_clauses", tool_args)
            results = json.loads(tool_result)
            clauses_found += len(results)

            for r in results:
                src = r.get("source", "")
                if src and src not in sources:
                    sources.append(src)

            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "tool", "content": f"Tool result (search_clauses):\n{tool_result}"})

        else:
            analysis = response_text
            break

    if not analysis:
        analysis = "Unable to generate analysis. Please try rephrasing your question."

    return {
        "analysis":      analysis,
        "clauses_found": clauses_found,
        "sources":       sources,
    }
