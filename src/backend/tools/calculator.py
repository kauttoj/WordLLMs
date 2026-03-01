import math
import operator
from langchain_core.tools import tool


# Safe math operations
SAFE_OPERATORS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "//": operator.floordiv,
    "%": operator.mod,
    "**": operator.pow,
}

SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "ceil": math.ceil,
    "floor": math.floor,
    "pi": math.pi,
    "e": math.e,
}


@tool
def calculate_tool(expression: str) -> str:
    """Evaluate a mathematical expression.

    Args:
        expression: A mathematical expression to evaluate (e.g., "2 + 2", "sqrt(16)", "sin(pi/2)").

    Returns:
        The result of the calculation as a string.
    """
    try:
        # Use Python's eval with restricted globals for safety
        result = eval(expression, {"__builtins__": {}}, SAFE_FUNCTIONS)
        return str(result)
    except Exception as e:
        return f"Calculation error: {e}"
