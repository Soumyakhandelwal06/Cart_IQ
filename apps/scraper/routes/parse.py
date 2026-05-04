"""
Agentic Query Parser — Converts natural language grocery queries into structured JSON
using a Groq Llama-3 agent with multi-step tool-calling (ReAct pattern).

The agent can:
  1. expand_query  — expand vague queries like "pasta dinner" into specific ingredients
  2. resolve_unit  — clarify ambiguous units (e.g. "half a dozen" → 6)
  3. finalize_cart — output the final structured JSON cart (terminates the loop)
"""
import os
import json
import re
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from groq import Groq

router = APIRouter()

# ── Pydantic Models ────────────────────────────────────────────────────────────

class GroceryItem(BaseModel):
    name: str
    quantity: int
    weight: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None

class ParsedQuery(BaseModel):
    items: list[GroceryItem]
    constraints: dict = {}
    raw_query: str

class QueryRequest(BaseModel):
    query: str

# ── Agent Tools ────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "expand_query",
            "description": (
                "Expand a vague or recipe-based user query into a list of specific "
                "grocery items. Use this when the user asks for something generic like "
                "'pasta dinner', 'birthday cake ingredients', or 'salad'. "
                "Returns concrete item names."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "original_query": {
                        "type": "string",
                        "description": "The vague or recipe-based user query to expand."
                    },
                    "expanded_items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of specific grocery item names inferred from the query."
                    }
                },
                "required": ["original_query", "expanded_items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_unit",
            "description": (
                "Resolve an ambiguous quantity or unit into a standard integer quantity "
                "and optional weight string. Use this when the user says things like "
                "'a dozen', 'half a kg', 'a pack', 'some', 'a few', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "original_text": {
                        "type": "string",
                        "description": "The ambiguous quantity text (e.g. 'half a dozen')"
                    },
                    "resolved_quantity": {
                        "type": "integer",
                        "description": "The resolved integer quantity."
                    },
                    "resolved_weight": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Optional weight/volume string (e.g. '500g', '1L') or null if not applicable."
                    }
                },
                "required": ["original_text", "resolved_quantity"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "finalize_cart",
            "description": (
                "Output the final structured grocery cart as JSON. Call this LAST, "
                "after all expansions and unit resolutions are complete."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Generic product name in lowercase"},
                                "quantity": {"type": "integer"},
                                "weight": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "e.g. '500g', '1L' or null"},
                                "brand": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "Brand name or null"},
                                "category": {
                                    "type": "string",
                                    "enum": ["produce", "dairy", "bakery", "beverages", "snacks", "staples", "other"]
                                }
                            },
                            "required": ["name", "quantity"]
                        }
                    },
                    "constraints": {
                        "type": "object",
                        "properties": {
                            "max_delivery_minutes": {"type": "integer"}
                        }
                    }
                },
                "required": ["items"]
            }
        }
    }
]

SYSTEM_PROMPT = """You are an intelligent grocery shopping agent for a quick commerce price comparison app in India.

Your job is to parse the user's grocery query into a structured cart. You MUST use tools to do this:

1. If the query is VAGUE or recipe-based (e.g. "pasta ingredients", "birthday cake stuff"), 
   call expand_query FIRST to break it into specific items.
2. If any quantity/unit is AMBIGUOUS (e.g. "a dozen eggs", "half a kg", "a few apples"), 
   call resolve_unit to normalize it.
3. Always call finalize_cart LAST to output the final structured JSON.

For CLEAR queries like "2kg onions + 500ml Amul milk", you can directly call finalize_cart.

Rules for finalize_cart items:
- name: generic lowercase (e.g. "onion", "butter", "bread")
- quantity: integer number of units
- weight: string like "2kg", "500g", "1L" if mentioned, otherwise null
- For total-weight requests like "2kg onions" or "1L milk", set quantity=1 and weight="2kg"/"1L".
- For repeated packs like "2 packs of 500g butter", set quantity=2 and weight="500g".
- brand: brand name if mentioned (e.g. "Amul", "Britannia"), otherwise null
- category: one of produce, dairy, bakery, beverages, snacks, staples, other
"""

# ── Agent Loop ─────────────────────────────────────────────────────────────────

def _run_agent(client: Groq, user_query: str) -> dict:
    """
    Multi-step agentic loop: the LLM reasons and calls tools until
    finalize_cart is invoked, producing the final structured cart.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query}
    ]

    tool_results_log = []
    max_iterations = 5

    for step in range(max_iterations):
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=2048,
            timeout=15.0
        )

        message = response.choices[0].message

        # No tool calls — model tried to respond in text, extract JSON if possible
        if not message.tool_calls:
            raw = message.content or ""
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw.strip())
            try:
                return json.loads(raw)
            except Exception:
                raise ValueError(f"Agent returned non-JSON text on step {step}: {raw[:200]}")

        # Process tool calls
        messages.append({"role": "assistant", "content": message.content, "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in message.tool_calls
        ]})

        for tool_call in message.tool_calls:
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)

            print(f"[Agent Step {step+1}] Tool: {fn_name} | Args: {fn_args}")

            if fn_name == "finalize_cart":
                # ✅ Terminal action — we have our answer
                return fn_args

            elif fn_name == "expand_query":
                result_str = (
                    f"Expanded '{fn_args.get('original_query')}' into: "
                    + ", ".join(fn_args.get("expanded_items", []))
                )
                tool_results_log.append(result_str)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"status": "ok", "expanded": fn_args.get("expanded_items", [])})
                })

            elif fn_name == "resolve_unit":
                result_str = (
                    f"'{fn_args.get('original_text')}' → quantity={fn_args.get('resolved_quantity')}, "
                    f"weight={fn_args.get('resolved_weight', 'null')}"
                )
                tool_results_log.append(result_str)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({
                        "status": "ok",
                        "resolved_quantity": fn_args.get("resolved_quantity"),
                        "resolved_weight": fn_args.get("resolved_weight")
                    })
                })

            else:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"status": "unknown tool"})
                })

    raise ValueError("Agent did not reach finalize_cart within max iterations.")


# ── Route ──────────────────────────────────────────────────────────────────────

@router.post("/", response_model=ParsedQuery)
async def parse_query(request: QueryRequest):
    """
    Agentic grocery query parser — uses Groq LLM with tool-calling to
    intelligently convert natural language into a structured grocery cart.
    """
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    client = Groq(api_key=groq_api_key)

    try:
        result = _run_agent(client, f"Parse this grocery query: {request.query}")

        items = []
        for item in result.get("items", []):
            items.append(GroceryItem(
                name=item.get("name", "").lower().strip(),
                quantity=int(item.get("quantity", 1)),
                weight=item.get("weight"),
                brand=item.get("brand"),
                category=item.get("category", "other")
            ))

        return ParsedQuery(
            items=items,
            constraints=result.get("constraints", {}),
            raw_query=request.query
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")
