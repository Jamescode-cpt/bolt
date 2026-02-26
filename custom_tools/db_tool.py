"""BOLT custom tool — SQLite database browser and query tool (read-only)."""

TOOL_NAME = "db"
TOOL_DESC = """SQLite database browser and query tool (READ-ONLY).
Commands:
  open <filepath>             — show all tables and row counts
  tables <filepath>           — list all tables
  schema <filepath> [table]   — show CREATE TABLE statements
  query <filepath> <sql>      — run a READ-ONLY SQL query (SELECT/PRAGMA/EXPLAIN only)
  sample <filepath> <table>   — show first 10 rows of a table
Examples:
  <tool name="db">open ~/bolt/bolt.db</tool>
  <tool name="db">schema ~/bolt/bolt.db messages</tool>
  <tool name="db">query ~/bolt/bolt.db SELECT * FROM messages ORDER BY id DESC LIMIT 5</tool>
  <tool name="db">sample ~/bolt/bolt.db messages</tool>
  <tool name="db">tables ~/bolt/bolt.db</tool>
Path restricted to /home/mobilenode/. Read-only: only SELECT, PRAGMA, EXPLAIN allowed.
Results truncated to 50 rows."""

import os
import sqlite3

ALLOWED_PREFIX = "/home/mobilenode/"
MAX_ROWS = 50
MAX_COL_WIDTH = 60

# SQL statements that are ALLOWED (read-only)
ALLOWED_PREFIXES = ("select", "pragma", "explain")
# SQL statements that are explicitly BLOCKED
BLOCKED_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "vacuum", "reindex", "grant", "revoke",
    "begin", "commit", "rollback", "savepoint", "release",
)


def _validate_path(filepath):
    """Validate that path is within allowed directory and exists."""
    filepath = os.path.expanduser(filepath.strip())
    filepath = os.path.realpath(filepath)
    if not filepath.startswith(ALLOWED_PREFIX):
        return None, f"Access denied: path must be under {ALLOWED_PREFIX}"
    if not os.path.isfile(filepath):
        return None, f"File not found: {filepath}"
    return filepath, None


def _validate_sql(sql):
    """Ensure SQL is read-only. Returns (ok, error_message)."""
    sql_stripped = sql.strip().lower()

    # Remove leading comments
    import re
    sql_stripped = re.sub(r'^--[^\n]*\n?', '', sql_stripped, flags=re.MULTILINE).strip()
    sql_stripped = re.sub(r'/\*.*?\*/', '', sql_stripped, flags=re.DOTALL).strip()

    if not sql_stripped:
        return False, "Empty SQL query."

    # Check if starts with an allowed prefix
    starts_ok = any(sql_stripped.startswith(p) for p in ALLOWED_PREFIXES)
    if not starts_ok:
        return False, f"Only SELECT, PRAGMA, and EXPLAIN queries are allowed. Got: {sql_stripped[:50]}..."

    # Block multi-statement queries (semicolons within the query body)
    if ';' in sql.strip().rstrip(';'):
        return False, "Multi-statement queries are not allowed."

    # Also block dangerous keywords embedded anywhere (e.g., in subqueries or CTEs)
    # But be careful: "select delete_flag from..." should be allowed
    # Only block if the keyword appears as a standalone SQL keyword
    for kw in BLOCKED_KEYWORDS:
        # Match keyword as a whole word at the start of a statement (after ; or start)
        pattern = r'(?:^|;\s*)' + kw + r'\s'
        if re.search(pattern, sql_stripped):
            return False, f"Blocked: '{kw.upper()}' statements are not allowed. Read-only access only."

    return True, None


def _format_table(headers, rows):
    """Format rows as aligned columns."""
    if not headers:
        return "(no columns)"
    if not rows:
        return " | ".join(str(h) for h in headers) + "\n(no rows)"

    # Calculate column widths
    col_widths = [len(str(h)) for h in headers]
    display_rows = []
    for row in rows:
        display_row = []
        for i, val in enumerate(row):
            s = str(val) if val is not None else "NULL"
            if len(s) > MAX_COL_WIDTH:
                s = s[:MAX_COL_WIDTH - 3] + "..."
            display_row.append(s)
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(s))
            else:
                col_widths.append(len(s))
        display_rows.append(display_row)

    # Build output
    lines = []
    # Header
    header_line = " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
    lines.append(header_line)
    # Separator
    sep_line = "-+-".join("-" * w for w in col_widths)
    lines.append(sep_line)
    # Rows
    for row in display_rows:
        line = " | ".join(
            row[i].ljust(col_widths[i]) if i < len(row) else "".ljust(col_widths[i])
            for i in range(len(headers))
        )
        lines.append(line)

    return "\n".join(lines)


def run(args):
    """args is a string (everything between the <tool> tags). Returns a string."""
    try:
        args = args.strip()
        if not args:
            return ("Usage:\n"
                    "  open <filepath>             — show tables and row counts\n"
                    "  tables <filepath>           — list tables\n"
                    "  schema <filepath> [table]   — show CREATE TABLE statements\n"
                    "  query <filepath> <sql>      — read-only SQL query\n"
                    "  sample <filepath> <table>   — first 10 rows of a table")

        parts = args.split(None, 1)
        command = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        # Command: open <filepath>
        if command == "open":
            if not rest:
                return "Usage: open <filepath>"
            filepath, err = _validate_path(rest)
            if err:
                return err

            conn = sqlite3.connect(f"file:{filepath}?mode=ro", uri=True)
            conn.enable_load_extension(False)
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = [row[0] for row in cursor.fetchall()]
                if not tables:
                    return f"Database {filepath}: no tables found."

                lines = [f"Database: {filepath}", f"Tables ({len(tables)}):", ""]
                for t in tables:
                    try:
                        count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                        lines.append(f"  {t:40s} {count:>8,} rows")
                    except Exception:
                        lines.append(f"  {t:40s}  (error reading)")
                return "\n".join(lines)
            finally:
                conn.close()

        # Command: tables <filepath>
        elif command == "tables":
            if not rest:
                return "Usage: tables <filepath>"
            filepath, err = _validate_path(rest)
            if err:
                return err

            conn = sqlite3.connect(f"file:{filepath}?mode=ro", uri=True)
            conn.enable_load_extension(False)
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = [row[0] for row in cursor.fetchall()]
                if not tables:
                    return "No tables found."
                return "Tables:\n" + "\n".join(f"  {t}" for t in tables)
            finally:
                conn.close()

        # Command: schema <filepath> [table]
        elif command == "schema":
            if not rest:
                return "Usage: schema <filepath> [table_name]"

            # Split: first token is filepath, second (optional) is table name
            schema_parts = rest.split(None, 1)
            filepath_str = schema_parts[0]
            table_filter = schema_parts[1].strip() if len(schema_parts) > 1 else None

            filepath, err = _validate_path(filepath_str)
            if err:
                return err

            conn = sqlite3.connect(f"file:{filepath}?mode=ro", uri=True)
            conn.enable_load_extension(False)
            try:
                if table_filter:
                    cursor = conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                        (table_filter,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return f"Table '{table_filter}' not found."
                    return row[0] + ";"
                else:
                    cursor = conn.execute(
                        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
                    )
                    schemas = cursor.fetchall()
                    if not schemas:
                        return "No tables found."
                    lines = []
                    for name, sql in schemas:
                        lines.append(f"{sql};\n")
                    return "\n".join(lines)
            finally:
                conn.close()

        # Command: query <filepath> <sql>
        elif command == "query":
            if not rest:
                return "Usage: query <filepath> <SQL statement>"

            # First token is filepath, rest is SQL
            query_parts = rest.split(None, 1)
            if len(query_parts) < 2:
                return "Usage: query <filepath> <SQL statement>"

            filepath_str = query_parts[0]
            sql = query_parts[1].strip()

            # Check if the first token looks like a path
            filepath, err = _validate_path(filepath_str)
            if err:
                return err

            # Validate SQL is read-only
            ok, sql_err = _validate_sql(sql)
            if not ok:
                return sql_err

            conn = sqlite3.connect(f"file:{filepath}?mode=ro", uri=True)
            conn.enable_load_extension(False)
            try:
                cursor = conn.execute(sql)
                if cursor.description is None:
                    return "(Query executed, no results returned)"
                headers = [desc[0] for desc in cursor.description]
                rows = cursor.fetchmany(MAX_ROWS + 1)
                truncated = len(rows) > MAX_ROWS
                if truncated:
                    rows = rows[:MAX_ROWS]

                result = _format_table(headers, rows)
                if truncated:
                    result += f"\n\n... (showing first {MAX_ROWS} rows, more available)"
                return result
            finally:
                conn.close()

        # Command: sample <filepath> <table>
        elif command == "sample":
            if not rest:
                return "Usage: sample <filepath> <table_name>"

            sample_parts = rest.split(None, 1)
            if len(sample_parts) < 2:
                return "Usage: sample <filepath> <table_name>"

            filepath_str = sample_parts[0]
            table_name = sample_parts[1].strip()

            filepath, err = _validate_path(filepath_str)
            if err:
                return err

            # Validate table name (prevent injection)
            import re
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
                return f"Invalid table name: {table_name}"

            conn = sqlite3.connect(f"file:{filepath}?mode=ro", uri=True)
            conn.enable_load_extension(False)
            try:
                # Verify table exists
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                )
                if not cursor.fetchone():
                    return f"Table '{table_name}' not found."

                cursor = conn.execute(f'SELECT * FROM "{table_name}" LIMIT 10')
                headers = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

                # Also get total count
                count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]

                result = f"Sample: {table_name} ({count:,} total rows, showing first {len(rows)}):\n\n"
                result += _format_table(headers, rows)
                return result
            finally:
                conn.close()

        else:
            # Maybe they gave a filepath directly — treat as "open"
            filepath, err = _validate_path(args)
            if err is None:
                return run(f"open {args}")
            return (f"Unknown command: {command}\n"
                    "Usage: open | tables | schema | query | sample")

    except sqlite3.OperationalError as e:
        return f"SQLite error: {e}"
    except Exception as e:
        return f"DB tool error: {e}"
