"""BOLT custom tool — safe math calculator.

Uses ast.parse() to evaluate expressions safely — no eval().
Supports basic math ops + math module functions (sqrt, sin, cos, log, etc.).
"""

import ast
import math
import operator

TOOL_NAME = "calc"
TOOL_DESC = (
    "Safe math calculator. "
    'Usage: <tool name="calc">2**10 + sqrt(144)</tool> — '
    "supports +, -, *, /, //, %, **, and math functions (sqrt, sin, cos, log, pi, e, etc.)"
)

# Allowed binary operators
_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

# Allowed unary operators
_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Allowed math functions and constants
_MATH_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "ceil": math.ceil,
    "floor": math.floor,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "factorial": math.factorial,
    "gcd": math.gcd,
    "radians": math.radians,
    "degrees": math.degrees,
    "hypot": math.hypot,
}

_MATH_CONSTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
}

MAX_EXPR_LEN = 200
MAX_EXPONENT = 10000


def _safe_eval(node):
    """Recursively evaluate an AST node safely."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BINOPS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        # Exponent safety cap
        if op_type is ast.Pow:
            if isinstance(right, (int, float)) and abs(right) > MAX_EXPONENT:
                raise ValueError(f"Exponent too large: {right} (max {MAX_EXPONENT})")
        return _BINOPS[op_type](left, right)

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARYOPS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        return _UNARYOPS[op_type](_safe_eval(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls allowed (e.g. sqrt(x))")
        fname = node.func.id
        if fname not in _MATH_FUNCS:
            raise ValueError(f"Unknown function: {fname}. Available: {', '.join(sorted(_MATH_FUNCS))}")
        func = _MATH_FUNCS[fname]
        eval_args = [_safe_eval(a) for a in node.args]
        return func(*eval_args)

    if isinstance(node, ast.Name):
        name = node.id
        if name in _MATH_CONSTS:
            return _MATH_CONSTS[name]
        raise ValueError(f"Unknown variable: {name}. Available constants: {', '.join(sorted(_MATH_CONSTS))}")

    raise ValueError(f"Unsupported expression type: {type(node).__name__}")


def run(args):
    """Evaluate a math expression safely.

    Args is the expression string, e.g. '2**10 + sqrt(144)'.
    """
    expr = args.strip() if args else ""
    if not expr:
        return "No expression provided. Usage: <tool name=\"calc\">2**10 + sqrt(144)</tool>"

    if len(expr) > MAX_EXPR_LEN:
        return f"Expression too long ({len(expr)} chars, max {MAX_EXPR_LEN})"

    try:
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval(tree)
        # Format nicely
        if isinstance(result, float) and result == int(result) and abs(result) < 1e15:
            return str(int(result))
        return str(result)
    except SyntaxError:
        return f"Invalid expression: {expr}"
    except ZeroDivisionError:
        return "Error: division by zero"
    except Exception as e:
        return f"Calc error: {e}"
