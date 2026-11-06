"""Tools have fixed schemas and no shell, file, network, or eval capabilities."""

import ast
import json
import math
import operator
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..guards import strict_json
from ..sandbox.policy import CodeRequest

NAMES = (
    "calculator",
    "summarize_text",
    "format_json",
    "python_sandbox",
    "execute_code",
)


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=64)
    arguments: dict

    @field_validator("arguments")
    @classmethod
    def bounded_arguments(cls, value):
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
        if len(encoded.encode()) > 40000:
            raise ValueError("Tool arguments exceed size limit")
        strict_json(encoded)
        return value


class PythonInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(min_length=1, max_length=32768)

    @field_validator("code")
    @classmethod
    def valid_code(cls, value):
        if len(value.encode()) > 32768 or not value.strip() or "\0" in value:
            raise ValueError("Invalid code")
        return value


class ExecuteCodeInput(PythonInput):
    language: str
    stdin: str = Field(default="", max_length=8192)

    @field_validator("language")
    @classmethod
    def registered_language(cls, value):
        return CodeRequest.registered_language(value)

    @field_validator("stdin")
    @classmethod
    def bounded_stdin(cls, value):
        return CodeRequest.stdin_bytes(value)


def validate_request(request, allowed):
    if request.name not in NAMES or request.name not in allowed:
        raise ToolRejected("Tool is unknown or not permitted")
    model = (
        ExecuteCodeInput
        if request.name == "execute_code"
        else PythonInput
        if request.name == "python_sandbox"
        else TextInput
    )
    return model.model_validate(request.arguments)


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
    if request.name in ("python_sandbox", "execute_code"):
        raise ToolRejected("Sandbox requires authenticated async policy dispatch")
    data = TextInput.model_validate(request.arguments)
    try:
        if request.name == "calculator":
            return calculate(data.text)
        if request.name == "format_json":
            formatted = json.dumps(
                strict_json(data.text),
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
                    "execute_code": "Request isolated execution in an approved language. Policy and human approval apply; never assume it ran.",
                }[name],
                "parameters": (
                    ExecuteCodeInput.model_json_schema()
                    if name == "execute_code"
                    else {
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
