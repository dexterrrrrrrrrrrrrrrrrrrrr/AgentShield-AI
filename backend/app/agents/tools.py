"""Tools have fixed schemas and no shell, file, network, or eval capabilities."""

import ast
import json
import math
import operator
import re

from pydantic import BaseModel, ConfigDict, Field

NAMES = ("calculator", "summarize_text", "format_json", "python_sandbox")


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    arguments: dict


class ToolRejected(ValueError):
    pass


def calculate(text: str) -> str:
    if len(text) > 200:
        raise ToolRejected("Expression too long")
    tree = ast.parse(text, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 50:
        raise ToolRejected("Expression too complex")
    operations = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            result = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(
            node.op, (ast.UAdd, ast.USub)
        ):
            result = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in operations:
            result = operations[type(node.op)](visit(node.left), visit(node.right))
        else:
            raise ToolRejected("Only numeric arithmetic (+ - * /) is allowed")
        if abs(result) > 1e12 or not math.isfinite(result):
            raise ToolRejected("Numeric result is out of bounds")
        return result

    return str(visit(tree.body))


def execute(request: ToolRequest, allowed: list[str]) -> str:
    if request.name not in NAMES or request.name not in allowed:
        raise ToolRejected("Tool is unknown or not permitted")
    if request.name == "python_sandbox":
        raise ToolRejected("Sandbox requires authenticated async policy dispatch")
    data = TextInput.model_validate(request.arguments)
    try:
        if request.name == "calculator":
            return calculate(data.text)
        if request.name == "format_json":
            formatted = json.dumps(
                json.loads(
                    data.text,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                ),
                indent=2,
                ensure_ascii=True,
                allow_nan=False,
            )
            if len(formatted) > 6000:
                raise ToolRejected("Formatted JSON exceeds the tool output limit")
            return formatted
        # Extractive summary: deterministic, local, and does not add provider requests.
        sentences = re.split(r"(?<=[.!?])\s+", data.text.strip())
        return " ".join(sentences[:3])[:1000]
    except (ValueError, SyntaxError, ArithmeticError, RecursionError, OverflowError):
        raise ToolRejected("Invalid or unsafe tool input") from None


def definitions(allowed: list[str]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": {
                    "calculator": "Bounded arithmetic using +, -, *, / and parentheses only.",
                    "summarize_text": "Extract the first three sentences of supplied text locally.",
                    "format_json": "Validate and pretty-print supplied JSON text.",
                    "python_sandbox": "Request isolated Python execution. Policy may require explicit human approval; never assume it ran.",
                }[name],
                "parameters": (
                    {
                        "type": "object",
                        "properties": {"code": {"type": "string", "maxLength": 32768}},
                        "required": ["code"],
                        "additionalProperties": False,
                    }
                    if name == "python_sandbox"
                    else TextInput.model_json_schema()
                ),
            },
        }
        for name in allowed
        if name in NAMES
    ]
