"""
agents/architect.py — Document Architect Agent.

Generates contract documents (NDA, MSA, SOW, SLA) by:
1. Searching the knowledge base for relevant clauses from similar contracts.
2. Merging retrieved clauses with user-supplied fields.
3. Rendering the appropriate template to produce the final document.

The agent runs a function-calling loop with Gemini until the model
decides to render the template and stop.
"""

import re
import json
import logging

from tools import (
    search_clauses, render_template, TOOL_SCHEMAS,
    parse_tool_call, generate_text,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Document Architect for a Contract Lifecycle Management (CLM) platform.
Your job is to generate professional, legally sound contract documents based on:
- User-provided details (parties, dates, terms, amounts)
- Relevant clauses retrieved from the contract knowledge base

Follow this process:
1. Call search_clauses() to retrieve relevant clause examples for the requested contract type.
2. Review the retrieved clauses to identify standard language and key terms.
3. Combine the retrieved clauses with the user-provided fields.
4. Call render_template() with the doc_type and all populated fields to produce the final document.
5. If any required fields are missing, include them as {placeholder} in the output and list what is still needed.

To call a tool, respond ONLY with a JSON object like:
{"name": "search_clauses", "arguments": {"query": "...", "top_k": 5}}
{"name": "render_template", "arguments": {"doc_type": "nda", "fields": {...}}}

Always produce complete, professional contracts. Never leave a document half-finished.
After calling render_template, respond only with the final contract text — do not add commentary."""


def _execute_tool(name: str, arguments: dict) -> str:
    """Dispatch a tool call from the model to the actual function."""
    if name == "search_clauses":
        return search_clauses(**arguments)
    elif name == "render_template":
        return render_template(**arguments)
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


def run(
    doc_type: str,
    user_fields: dict,
    extra_context: str = "",
    max_iterations: int = 3
) -> dict:
    """
    Run the Document Architect agent.

    Args:
        doc_type:       Contract type: nda, msa, sow, sla.
        user_fields:    Dict of field values provided by the caller.
        extra_context:  Any additional free-text instructions from the user.
        max_iterations: Max tool-call rounds before forcing output.

    Returns:
        {
            "document": str,       # final rendered contract
            "missing_fields": list, # placeholders still unfilled
            "clauses_used": int,   # number of KB clauses retrieved
        }
    """
    tools_json = json.dumps(TOOL_SCHEMAS)

    user_message = (
        f"Generate a {doc_type.upper()} contract with the following details:\n"
        f"{json.dumps(user_fields, indent=2)}\n"
        f"\nAvailable tools (JSON):\n{tools_json}"
    )
    if extra_context:
        user_message += f"\nAdditional instructions: {extra_context}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_message}
    ]

    clauses_used = 0
    final_document = None

    for iteration in range(max_iterations):
        logger.info(f"[architect] iteration {iteration + 1}")

        response_text = generate_text(messages, max_tokens=2048, temperature=0.2, task="architect")

        # Check if model wants to call a tool
        tool_call = parse_tool_call(response_text)

        if tool_call:
            tool_name = tool_call["name"]
            tool_args = tool_call["arguments"]
            logger.info(f"[architect] calling tool: {tool_name}({tool_args})")

            tool_result = _execute_tool(tool_name, tool_args)

            if tool_name == "search_clauses":
                clauses_used += len(json.loads(tool_result))

            if tool_name == "render_template":
                final_document = tool_result
                break

            # Feed tool result back to model
            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "tool",      "content": f"Tool result ({tool_name}):\n{tool_result}"})

        else:
            # Model produced final text — use it directly
            final_document = response_text
            break

    if not final_document:
        # Fallback — render template with whatever fields we have
        final_document = render_template(doc_type, user_fields)

    # Find any remaining unfilled placeholders
    missing = re.findall(r'\{([^}]+)\}', final_document)

    return {
        "document":      final_document,
        "missing_fields": list(set(missing)),
        "clauses_used":   clauses_used,
    }
