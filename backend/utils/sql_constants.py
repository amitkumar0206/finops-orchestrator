"""
SQL Constants and Helper Functions

Centralizes SQL-related string literals and patterns used across the codebase.
This improves maintainability, consistency, and makes security auditing easier.

Usage:
    from backend.utils.sql_constants import (
        SQL_VALUE_SEPARATOR,
        SQL_AND,
        SQL_OR,
        quote_sql_string,
        build_sql_in_list,
        build_sql_placeholders,
    )
"""

from typing import List, Iterable

# =============================================================================
# SQL SEPARATORS AND OPERATORS
# =============================================================================

# Separator for SQL IN clause values (comma with space)
SQL_VALUE_SEPARATOR = ", "

# Separator for joining pre-quoted SQL strings (quote-comma-quote)
SQL_QUOTED_SEPARATOR = "','"

# SQL logical operators with proper spacing
SQL_AND = " AND "
SQL_OR = " OR "

# SQL UNION operators
SQL_UNION = "\nUNION\n"
SQL_UNION_ALL = "\nUNION ALL\n"

# =============================================================================
# SQL PLACEHOLDERS
# =============================================================================

# Parameterized query placeholder for psycopg2/asyncpg
SQL_PLACEHOLDER = "%s"

# =============================================================================
# SQL CLAUSE TEMPLATES
# =============================================================================

# IN clause templates
SQL_IN_CLAUSE = "IN ({values})"
SQL_NOT_IN_CLAUSE = "NOT IN ({values})"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def quote_sql_string(value: str) -> str:
    """
    Quote a string value for SQL inclusion.

    Args:
        value: The string value to quote

    Returns:
        Quoted string, e.g., "'value'"

    Note:
        This is for building SQL strings with validated values only.
        Always validate input before using this function.
    """
    return f"'{value}'"


def build_sql_in_list(values: Iterable[str], quoted: bool = True) -> str:
    """
    Build a comma-separated list of values for SQL IN clause.

    Args:
        values: Iterable of string values
        quoted: If True, wrap each value in single quotes (default True)

    Returns:
        Comma-separated string, e.g., "'val1', 'val2', 'val3'"

    Example:
        >>> build_sql_in_list(['a', 'b', 'c'])
        "'a', 'b', 'c'"
        >>> build_sql_in_list(['1', '2', '3'], quoted=False)
        "1, 2, 3"
    """
    if quoted:
        return SQL_VALUE_SEPARATOR.join(quote_sql_string(v) for v in values)
    return SQL_VALUE_SEPARATOR.join(values)


def build_sql_placeholders(count: int) -> str:
    """
    Build a comma-separated list of SQL placeholders.

    Args:
        count: Number of placeholders needed

    Returns:
        Comma-separated placeholders, e.g., "%s, %s, %s"

    Example:
        >>> build_sql_placeholders(3)
        "%s, %s, %s"
    """
    return SQL_VALUE_SEPARATOR.join([SQL_PLACEHOLDER] * count)


def build_in_clause(column: str, values: Iterable[str], negated: bool = False) -> str:
    """
    Build a complete SQL IN clause.

    Args:
        column: Column name to filter
        values: Iterable of values (will be quoted)
        negated: If True, use NOT IN instead of IN

    Returns:
        Complete IN clause, e.g., "column IN ('val1', 'val2')"

    Example:
        >>> build_in_clause('status', ['active', 'pending'])
        "status IN ('active', 'pending')"
        >>> build_in_clause('status', ['deleted'], negated=True)
        "status NOT IN ('deleted')"
    """
    values_str = build_sql_in_list(values)
    operator = SQL_NOT_IN_CLAUSE if negated else SQL_IN_CLAUSE
    return f"{column} {operator.format(values=values_str)}"


def join_conditions(conditions: List[str], operator: str = SQL_AND) -> str:
    """
    Join multiple SQL conditions with a logical operator.

    Args:
        conditions: List of SQL condition strings
        operator: Logical operator to use (default: SQL_AND)

    Returns:
        Joined conditions string

    Example:
        >>> join_conditions(["a = 1", "b = 2"])
        "a = 1 AND b = 2"
        >>> join_conditions(["x = 1", "y = 2"], SQL_OR)
        "x = 1 OR y = 2"
    """
    return operator.join(conditions)


# =============================================================================
# DISPLAY SEPARATORS (for logging/UI, not SQL)
# =============================================================================

# Separator for human-readable lists in logs and UI
DISPLAY_LIST_SEPARATOR = ", "


def format_display_list(values: Iterable[str]) -> str:
    """
    Format a list of values for display in logs or UI.

    Args:
        values: Iterable of string values

    Returns:
        Comma-separated string for display

    Example:
        >>> format_display_list(['service1', 'service2'])
        "service1, service2"
    """
    return DISPLAY_LIST_SEPARATOR.join(values)
