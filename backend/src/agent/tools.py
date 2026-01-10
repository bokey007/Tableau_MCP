# =============================================================================
# Calculator Tool for LLM
# =============================================================================
"""Safe calculator tool for LLM to perform mathematical operations."""

import re
import math
from typing import Any, Dict, List, Union
from langchain_core.tools import tool

from src.core.logging import get_logger

logger = get_logger(__name__)


# Safe math functions available to the calculator
SAFE_MATH_FUNCS = {
    'abs': abs,
    'round': round,
    'min': min,
    'max': max,
    'sum': sum,
    'len': len,
    'pow': pow,
    'sqrt': math.sqrt,
    'log': math.log,
    'log10': math.log10,
    'exp': math.exp,
    'floor': math.floor,
    'ceil': math.ceil,
    'sin': math.sin,
    'cos': math.cos,
    'tan': math.tan,
    'pi': math.pi,
    'e': math.e,
}


def safe_eval(expression: str) -> Union[float, int, str]:
    """
    Safely evaluate a mathematical expression.
    Only allows numbers, basic operators, and whitelisted functions.
    """
    # Remove whitespace
    expr = expression.strip()
    
    # Validate expression contains only allowed characters
    # Allow: digits, operators, parentheses, decimal points, commas, function names
    allowed_pattern = r'^[\d\s\+\-\*\/\%\^\(\)\.\,a-zA-Z\_]+$'
    if not re.match(allowed_pattern, expr):
        return f"Error: Invalid characters in expression"
    
    # Check for dangerous patterns
    dangerous_patterns = [
        r'__', r'import', r'exec', r'eval', r'open', r'file',
        r'input', r'raw_input', r'compile', r'globals', r'locals',
        r'getattr', r'setattr', r'delattr', r'vars', r'dir',
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, expr.lower()):
            return f"Error: Expression contains forbidden pattern: {pattern}"
    
    try:
        # Replace ^ with ** for power operations
        expr = expr.replace('^', '**')
        
        # Evaluate with only safe functions available
        result = eval(expr, {"__builtins__": {}}, SAFE_MATH_FUNCS)
        
        # Format result
        if isinstance(result, float):
            # Round to reasonable precision
            if result == int(result):
                return int(result)
            return round(result, 6)
        return result
        
    except ZeroDivisionError:
        return "Error: Division by zero"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def calculate(expression: str) -> str:
    """
    Perform mathematical calculations. Use this tool for any arithmetic operations.
    
    Examples:
    - calculate("1500000 + 2500000") → 4000000
    - calculate("(45000 / 12) * 100") → 375000
    - calculate("sqrt(144)") → 12
    - calculate("round(3.14159, 2)") → 3.14
    - calculate("sum([100, 200, 300])") → 600
    - calculate("45000 / 36000 * 100") → 125.0 (for percentage)
    
    Args:
        expression: A mathematical expression to evaluate
        
    Returns:
        The result of the calculation as a string
    """
    logger.info("Calculator tool called", expression=expression)
    result = safe_eval(expression)
    logger.info("Calculator result", result=result)
    return str(result)


@tool
def calculate_percentage(value: float, total: float) -> str:
    """
    Calculate what percentage 'value' is of 'total'.
    
    Args:
        value: The part value
        total: The total/whole value
        
    Returns:
        The percentage as a string (e.g., "25.5%")
    """
    if total == 0:
        return "Error: Cannot divide by zero"
    
    percentage = (value / total) * 100
    return f"{round(percentage, 2)}%"


@tool  
def calculate_growth(old_value: float, new_value: float) -> str:
    """
    Calculate the growth rate between two values.
    
    Args:
        old_value: The original/baseline value
        new_value: The new/current value
        
    Returns:
        The growth percentage as a string (e.g., "+15.3%" or "-8.2%")
    """
    if old_value == 0:
        return "Error: Cannot calculate growth from zero"
    
    growth = ((new_value - old_value) / old_value) * 100
    sign = "+" if growth >= 0 else ""
    return f"{sign}{round(growth, 2)}%"


@tool
def calculate_statistics(numbers: List[float]) -> Dict[str, float]:
    """
    Calculate basic statistics for a list of numbers.
    
    Args:
        numbers: A list of numeric values
        
    Returns:
        Dictionary with sum, average, min, max, count
    """
    if not numbers:
        return {"error": "Empty list provided"}
    
    return {
        "sum": round(sum(numbers), 2),
        "average": round(sum(numbers) / len(numbers), 2),
        "min": round(min(numbers), 2),
        "max": round(max(numbers), 2),
        "count": len(numbers),
    }


# List of all calculator tools
CALCULATOR_TOOLS = [
    calculate,
    calculate_percentage,
    calculate_growth,
    calculate_statistics,
]
