"""
═══════════════════════════════════════════════════════════════════════════════
HIGH-14 — Missing Tenant Isolation in Conversation Service Layer
═══════════════════════════════════════════════════════════════════════════════

Pre-fix (conversation_manager.py:139-424, verified 2026-03-06):

    def get_conversation_history(self, thread_id: str, limit: int = 10):
        sql = "... FROM conversation_messages WHERE thread_id = %s ..."
        #                                      ^^^^^^^^^^^^^^^^^
        #                                      thread_id only — no user_id

F-33 (CRIT-10, 2026-03-05) added require_conversation_owner() at the API layer,
which fetches the thread's owner via get_thread_metadata() and 403s if it
doesn't match the caller. That check is correct and stays. But it's the ONLY
check — the service layer trusted whatever thread_id it was handed. Any caller
that doesn't route through api/chat.py (a scheduled summarizer job, an admin
"show me user X's conversations" tool, a new endpoint where someone forgot to
call require_conversation_owner) could read/write any thread.

Schema reality: only conversation_threads has a user_id column. The three child
tables (conversation_messages, query_intents, agent_executions) are FK'd via
thread_id. So service-layer isolation goes through an EXISTS on the parent.

Fix — two defense primitives + 7 scoped methods:

  _OWNED_THREAD           EXISTS subquery predicate for SELECTs. Non-owners get
                          zero rows — the thread simply doesn't exist from their
                          perspective. Silent filter, the "WHERE user_id = $N"
                          semantic for reads.

  _assert_thread_owner()  Pre-write check inside the txn. PermissionError if the
                          caller's user_id doesn't match (or thread is absent —
                          we don't distinguish, so existence doesn't leak).
                          add_message reuses this for its FOR UPDATE lock.

  get_thread_metadata     INTENTIONALLY UNSCOPED. It's the ownership-lookup
                          primitive — require_conversation_owner() calls it to
                          FETCH the owner's user_id and compare. Scoping it would
                          make the comparison circular. The exemption is pinned
                          by a test here so a well-meaning "fix" can't land.

The API layer check (F-33) stays. It runs first, gives 403 + audit log. The
service layer is the floor — quiet, no audit event, just doesn't return data
that isn't yours. Both layers must agree.
"""

import inspect
from unittest.mock import MagicMock, patch

import pytest

from backend.services.conversation_manager import (
    ConversationManager,
    _assert_thread_owner,
    _OWNED_THREAD,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

ALICE = "a11ce000-0000-4000-8000-000000000001"
MALLORY = "bad00000-0000-4000-8000-000000000666"
THREAD = "c0ffee00-0000-4000-8000-000000000042"


@pytest.fixture
def spy_on_sql():
    """
    Captures every (sql, params) pair executed by a service method without
    touching a real DB. The conn/cursor context-manager shape is replicated
    so `with conn: with conn.cursor() as cur:` works unmodified.
    """
    captured: list[tuple[str, tuple]] = []

    cur = MagicMock()
    cur.execute = lambda sql, params=(): captured.append((sql, params))
    # Reads: fetchall returns [] so the post-processing loops are no-ops.
    # Writes: fetchone must satisfy three distinct callers —
    #   1. _assert_thread_owner → `if cur.fetchone() is None` → (0,) is not None → passes
    #   2. MAX(ordering_index)  → `row[0] + 1` → 0 + 1 → fine
    #   3. INSERT ... RETURNING → `row[0]` → 0 → tests don't assert on the value
    # A single (0,) threads that needle; side_effect lists would couple the
    # fixture to each method's internal statement count.
    cur.fetchall.return_value = []
    cur.fetchone.return_value = (0,)

    cursor_cm = MagicMock()
    cursor_cm.__enter__.return_value = cur
    cursor_cm.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cursor_cm
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False

    with patch("backend.services.conversation_manager._get_conn", return_value=conn), \
         patch("backend.services.conversation_manager._put_conn"):
        yield captured


# ═════════════════════════════════════════════════════════════════════════════
# Signature pin — every data-access method MUST take user_id
# ═════════════════════════════════════════════════════════════════════════════

class TestConversationManagerSignatures:
    """
    HIGH-14 signature tripwire. If someone refactors a method and drops the
    user_id param, this fails before any SQL-shape test runs — clearer signal.
    """

    # Every public + private method that touches a child table.
    # create_thread already took user_id (stamps ownership on INSERT).
    # get_thread_metadata is the exempted ownership-lookup primitive — tested
    # separately below.
    SCOPED_METHODS = [
        "add_message",
        "get_conversation_history",
        "save_query_intent",
        "save_agent_execution",
        "get_context_for_query",
        "_fetch_recent_intents",
        "_fetch_recent_messages",
    ]

    @pytest.mark.parametrize("method_name", SCOPED_METHODS)
    def test_method_requires_user_id(self, method_name):
        method = getattr(ConversationManager, method_name)
        sig = inspect.signature(method)

        assert "user_id" in sig.parameters, (
            f"HIGH-14 REGRESSION: ConversationManager.{method_name} has no "
            f"user_id parameter. Pre-fix, this method filtered by thread_id "
            f"only → any caller bypassing api/chat.py's require_conversation_owner() "
            f"could read/write any user's thread. Params: {list(sig.parameters)}"
        )

        # It must be REQUIRED (no default). A default of None would let a
        # careless caller omit it and silently lose isolation.
        param = sig.parameters["user_id"]
        assert param.default is inspect.Parameter.empty, (
            f"HIGH-14: {method_name}(user_id=...) has a default value "
            f"({param.default!r}). Required params can't be forgotten; "
            f"optional ones with None defaults reintroduce the bug."
        )

    def test_user_id_is_second_positional_after_thread_id(self):
        """
        Consistency pin — (thread_id, user_id, ...) ordering across all methods.
        Not security-load-bearing, but a caller doing `cm.method(tid, uid)`
        positionally will be wrong if one method reorders them.
        """
        for name in self.SCOPED_METHODS:
            params = list(inspect.signature(getattr(ConversationManager, name)).parameters)
            # params[0] is self
            assert params[1] == "thread_id" and params[2] == "user_id", (
                f"{name} param order is {params[1:3]}, expected "
                f"['thread_id', 'user_id'] — keep the ordering consistent."
            )

    def test_get_thread_metadata_intentionally_unscoped(self):
        """
        The exemption. get_thread_metadata is the ownership-LOOKUP primitive —
        require_conversation_owner() at chat.py:65 calls it to fetch the owner's
        user_id, then compares. Scoping it would make that comparison circular
        (you'd need to be the owner to find out if you're the owner) and would
        collapse F-33's 404-vs-403 distinction into 404-only.

        This test FAILS if someone adds user_id to the signature. That's on
        purpose — read the docstring in conversation_manager.py before "fixing".
        """
        sig = inspect.signature(ConversationManager.get_thread_metadata)
        assert "user_id" not in sig.parameters, (
            "get_thread_metadata is INTENTIONALLY unscoped — it's the primitive "
            "require_conversation_owner() uses to fetch the owner for comparison. "
            "Adding user_id here breaks the API-layer 404/403 semantics. "
            "See the HIGH-14 docstring in conversation_manager.py:get_thread_metadata."
        )
        # Positive: the exemption IS documented inline, so a reader of the
        # source sees why before they "helpfully" add the param.
        doc = ConversationManager.get_thread_metadata.__doc__ or ""
        assert "HIGH-14" in doc and "INTENTIONALLY UNSCOPED" in doc, (
            "The exemption must be documented in the method docstring so "
            "future readers don't re-add user_id without understanding why."
        )


# ═════════════════════════════════════════════════════════════════════════════
# SQL shape — SELECTs carry the EXISTS ownership predicate
# ═════════════════════════════════════════════════════════════════════════════

class TestSelectQueriesFilterByOwner:
    """
    HIGH-14 PRIMARY REGRESSION for reads. Pre-fix SQL:
        WHERE thread_id = %s ORDER BY ...
    Post-fix SQL:
        WHERE thread_id = %s AND EXISTS (... ct.user_id = %s) ORDER BY ...

    We capture the exact (sql, params) tuple and assert both the predicate
    string AND the parameter binding position. Matching the string alone isn't
    enough — if the param tuple still had (thread_id, limit), psycopg2 would
    raise on arity mismatch, but that's a runtime crash not a security
    guarantee. We want the test to fail on the REVERT, not the crash.
    """

    def _find_select(self, captured: list) -> tuple[str, tuple]:
        """The guard may inject an ownership SELECT first; find the data SELECT."""
        selects = [(s, p) for s, p in captured if s.lstrip().upper().startswith("SELECT")]
        assert selects, f"no SELECT captured: {captured}"
        # For read methods there's exactly one; return the last to skip guards.
        return selects[-1]

    def test_get_conversation_history_filters_by_user(self, spy_on_sql):
        ConversationManager().get_conversation_history(THREAD, ALICE, limit=7)

        sql, params = self._find_select(spy_on_sql)

        # The predicate — EXISTS on conversation_threads scoped by user_id.
        # Casefold for whitespace-insensitive match on the shared constant.
        assert "conversation_threads" in sql and "user_id" in sql, (
            f"HIGH-14 REGRESSION: get_conversation_history SQL has no ownership "
            f"filter. Pre-fix, this returned ANY thread's messages given only "
            f"the thread_id.\n  SQL: {sql}\n  params: {params}"
        )
        assert _OWNED_THREAD in sql, (
            f"Expected the shared _OWNED_THREAD predicate in the query. "
            f"Using a one-off EXISTS string risks drift between methods.\n  SQL: {sql}"
        )

        # Parameter binding — (thread_id, thread_id_for_exists, user_id, limit).
        # Alice's uid must be in params; a revert to (thread_id, limit) won't have it.
        assert ALICE in params, (
            f"HIGH-14 REGRESSION: user_id {ALICE!r} not bound into the query "
            f"params. The EXISTS predicate is in the SQL text but nothing is "
            f"filling the %s.\n  params: {params}"
        )
        assert params == (THREAD, THREAD, ALICE, 7), (
            f"Param ordering mismatch — the EXISTS subquery takes "
            f"(thread_id, user_id) and the outer WHERE takes thread_id first.\n"
            f"  expected: {(THREAD, THREAD, ALICE, 7)}\n  actual:   {params}"
        )

    def test_fetch_recent_messages_filters_by_user(self, spy_on_sql):
        ConversationManager()._fetch_recent_messages(THREAD, ALICE, limit=5)

        sql, params = self._find_select(spy_on_sql)
        assert _OWNED_THREAD in sql
        assert params == (THREAD, THREAD, ALICE, 5), (
            f"HIGH-14: _fetch_recent_messages params don't carry user_id "
            f"at the EXISTS binding position: {params}"
        )

    def test_fetch_recent_intents_filters_by_user(self, spy_on_sql):
        ConversationManager()._fetch_recent_intents(THREAD, ALICE, limit=3)

        sql, params = self._find_select(spy_on_sql)
        assert _OWNED_THREAD in sql
        assert "query_intents" in sql  # right table
        assert params == (THREAD, THREAD, ALICE, 3)

    def test_get_context_for_query_threads_user_id_through(self, spy_on_sql):
        """
        get_context_for_query itself issues no SQL — it delegates to the two
        _fetch_* helpers. Assert BOTH captured SELECTs carry Alice's uid.
        A partial revert (forgot one of the two) would be caught here.
        """
        ConversationManager().get_context_for_query(THREAD, ALICE)

        selects = [(s, p) for s, p in spy_on_sql if "SELECT" in s.upper()]
        assert len(selects) == 2, (
            f"Expected 2 SELECTs (intents + messages), got {len(selects)}: "
            f"{[s[:60] for s, _ in selects]}"
        )
        for sql, params in selects:
            assert ALICE in params, (
                f"HIGH-14: get_context_for_query delegate didn't receive "
                f"user_id — one of _fetch_recent_intents/_fetch_recent_messages "
                f"was reverted.\n  SQL: {sql[:80]}\n  params: {params}"
            )

    def test_owned_thread_predicate_shape(self):
        """
        The shared constant itself. conversation_threads + user_id equality,
        and it's an EXISTS (not a JOIN — JOINs on a subquery are fine but
        EXISTS short-circuits on first match, which is the right semantic
        for a yes/no ownership check against a PK).
        """
        normalized = " ".join(_OWNED_THREAD.split())
        assert normalized.startswith("EXISTS")
        assert "conversation_threads" in normalized
        assert "thread_id = %s" in normalized
        assert "user_id = %s" in normalized
        # Two %s placeholders — both bound at call time, no string interpolation.
        assert _OWNED_THREAD.count("%s") == 2


# ═════════════════════════════════════════════════════════════════════════════
# Write paths — ownership check BEFORE the INSERT
# ═════════════════════════════════════════════════════════════════════════════

class TestWriteGuardRaisesForNonOwner:
    """
    HIGH-14 PRIMARY REGRESSION for writes. INSERTs have no WHERE clause, so the
    remediation for write paths is a pre-check inside the transaction: SELECT 1
    against conversation_threads scoped by user_id, raise if zero rows.

    The F-33 API-layer check runs first in production, so a raise here means
    something bypassed chat.py. That's exactly the scenario HIGH-14 is about.
    """

    def test_assert_thread_owner_passes_when_row_found(self):
        cur = MagicMock()
        cur.fetchone.return_value = (1,)  # row exists → owner confirmed

        _assert_thread_owner(cur, THREAD, ALICE)  # no raise

        # The query it ran must be scoped by BOTH thread_id AND user_id.
        sql, params = cur.execute.call_args[0]
        assert "conversation_threads" in sql
        assert "thread_id = %s" in sql and "user_id = %s" in sql, (
            f"HIGH-14: ownership guard SELECT missing user_id filter: {sql}"
        )
        assert params == (THREAD, ALICE)
        assert "FOR UPDATE" not in sql  # default: no lock

    def test_assert_thread_owner_raises_when_no_row(self):
        """
        THE write-path regression. fetchone() is None → caller does not own
        the thread (or it doesn't exist — we deliberately don't distinguish,
        so Mallory can't enumerate thread_ids by watching for 404-vs-403).
        """
        cur = MagicMock()
        cur.fetchone.return_value = None

        with pytest.raises(PermissionError) as exc:
            _assert_thread_owner(cur, THREAD, MALLORY)

        assert "HIGH-14" in str(exc.value)

    def test_assert_thread_owner_for_update_flag_adds_lock(self):
        """
        add_message needs the FOR UPDATE (ordering_index race — two concurrent
        inserts would both see MAX(ordering_index)=5 and both write 6 without
        the lock). The ownership guard carries the lock so we get both with
        one round-trip.
        """
        cur = MagicMock()
        cur.fetchone.return_value = (1,)

        _assert_thread_owner(cur, THREAD, ALICE, for_update=True)

        sql = cur.execute.call_args[0][0]
        assert sql.rstrip().endswith("FOR UPDATE"), (
            f"add_message's guard must lock the thread row (ordering_index "
            f"safety). for_update=True should append FOR UPDATE: {sql!r}"
        )

    @pytest.mark.parametrize(
        "method_name, call_kwargs, expect_for_update",
        [
            (
                "add_message",
                dict(role="user", content="hi", message_type="query"),
                True,  # add_message's guard also locks (ordering_index race)
            ),
            (
                "save_query_intent",
                dict(
                    message_id="m1", original_query="q", rewritten_query=None,
                    intent_type="cost", intent_confidence=0.9, extracted_dimensions={},
                ),
                False,
            ),
            (
                "save_agent_execution",
                dict(
                    agent_name="a", agent_type="t", input_query="q",
                    output_response={}, tools_used=[], execution_time_ms=1, status="ok",
                ),
                False,
            ),
        ],
    )
    def test_write_method_guard_runs_before_insert(
        self, spy_on_sql, method_name, call_kwargs, expect_for_update
    ):
        """
        Ordering: the ownership SELECT must execute BEFORE the INSERT.
        If it ran after, a non-owner's write would already be in the DB
        when the check fires — useless.

        spy_on_sql's fetchone returns a truthy tuple, so the guard passes
        and we can observe the full statement sequence.
        """
        getattr(ConversationManager(), method_name)(THREAD, ALICE, **call_kwargs)

        # First statement: the guard SELECT.
        guard_sql, guard_params = spy_on_sql[0]
        assert "conversation_threads" in guard_sql and "user_id = %s" in guard_sql, (
            f"HIGH-14: {method_name} — first statement is not the ownership "
            f"guard. Guard must run BEFORE the INSERT.\n"
            f"  captured[0]: {guard_sql!r}"
        )
        assert guard_params == (THREAD, ALICE)
        if expect_for_update:
            assert "FOR UPDATE" in guard_sql, (
                f"{method_name} must hold the thread lock (ordering_index safety)"
            )

        # A later statement: the INSERT itself. Guard preceded it.
        inserts = [s for s, _ in spy_on_sql if s.lstrip().upper().startswith("INSERT")]
        assert inserts, (
            f"{method_name} never reached its INSERT — guard is over-blocking "
            f"the owner path. Captured: {[s[:50] for s, _ in spy_on_sql]}"
        )

    @pytest.mark.parametrize(
        "method_name, call_kwargs",
        [
            ("add_message", dict(role="user", content="hi", message_type="query")),
            (
                "save_query_intent",
                dict(
                    message_id="m1", original_query="q", rewritten_query=None,
                    intent_type="cost", intent_confidence=0.9, extracted_dimensions={},
                ),
            ),
            (
                "save_agent_execution",
                dict(
                    agent_name="a", agent_type="t", input_query="q",
                    output_response={}, tools_used=[], execution_time_ms=1, status="ok",
                ),
            ),
        ],
    )
    def test_write_method_raises_for_non_owner(self, method_name, call_kwargs):
        """
        End-to-end non-owner path. The guard's fetchone → None → PermissionError
        propagates out of the service method. The INSERT never runs.

        Can't reuse spy_on_sql here — its fetchone is hardwired truthy. Build a
        bespoke cursor where fetchone is None so the guard sees "not owner".
        """
        cur = MagicMock()
        executed = []
        cur.execute = lambda sql, params=(): executed.append((sql, params))
        cur.fetchone.return_value = None  # ← guard fails: Mallory doesn't own THREAD

        cursor_cm = MagicMock(__enter__=MagicMock(return_value=cur), __exit__=MagicMock(return_value=False))
        conn = MagicMock(cursor=MagicMock(return_value=cursor_cm),
                         __enter__=MagicMock(return_value=MagicMock(cursor=MagicMock(return_value=cursor_cm))),
                         __exit__=MagicMock(return_value=False))
        # ^ the `with conn:` returns conn itself, whose .cursor() returns cursor_cm
        conn.__enter__.return_value = conn

        with patch("backend.services.conversation_manager._get_conn", return_value=conn), \
             patch("backend.services.conversation_manager._put_conn"):
            with pytest.raises(PermissionError):
                getattr(ConversationManager(), method_name)(THREAD, MALLORY, **call_kwargs)

        # Only the guard ran — no INSERT.
        assert all("INSERT" not in s.upper() for s, _ in executed), (
            f"HIGH-14 REGRESSION: {method_name} executed an INSERT for a "
            f"non-owner. PermissionError raised too late (or not at all):\n"
            + "\n".join(f"  {s[:80]}" for s, _ in executed)
        )


# ═════════════════════════════════════════════════════════════════════════════
# Source-level tripwire — no thread_id-only WHERE clauses remain
# ═════════════════════════════════════════════════════════════════════════════

class TestNoUnscopedSqlInSource:
    """
    AST tripwire. Walks every string constant in conversation_manager.py
    looking for SQL that hits a child table (conversation_messages,
    query_intents, agent_executions) with a thread_id filter but no
    user_id / ownership predicate.

    Why AST and not regex-on-source: the SQL strings use multi-line
    concatenation and f-strings. ast.walk over Constant/JoinedStr nodes sees
    the resolved fragments; regex on raw source would miss the f-string
    splice of _OWNED_THREAD.

    Catches: someone adds a new method, copies an old SELECT, forgets the
    ownership clause. The signature test wouldn't catch it (new method might
    take user_id but not use it). This one does.
    """

    CHILD_TABLES = {"conversation_messages", "query_intents", "agent_executions"}

    def _collect_sql_strings(self):
        import ast
        import backend.services.conversation_manager as mod

        tree = ast.parse(inspect.getsource(mod))

        # Which function each string lives in (for the failure message).
        strings: list[tuple[str, str, int]] = []  # (func_name, string, lineno)

        class Collector(ast.NodeVisitor):
            def __init__(self):
                self.func = "<module>"

            def visit_FunctionDef(self, node):
                old, self.func = self.func, node.name
                self.generic_visit(node)
                self.func = old

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Constant(self, node):
                if isinstance(node.value, str) and len(node.value) > 20:
                    strings.append((self.func, node.value, node.lineno))

            def visit_JoinedStr(self, node):
                # f-string — concat the literal parts. The {_OWNED_THREAD}
                # splice point shows up as a FormattedValue which we skip;
                # we'll see the surrounding literals.
                parts = "".join(
                    p.value for p in node.values
                    if isinstance(p, ast.Constant) and isinstance(p.value, str)
                )
                if len(parts) > 20:
                    strings.append((self.func, parts, node.lineno))

        Collector().visit(tree)
        return strings

    def test_every_child_table_select_has_ownership_clause(self):
        """
        Any SELECT that touches a child table AND filters by thread_id MUST
        also reference user_id (directly or via the EXISTS predicate constant).

        The f-string splice `{_OWNED_THREAD}` means the collected literal
        won't contain "user_id" textually — but it WILL contain "AND " right
        before the splice point and nothing after "thread_id = %s". So we
        check: if the literal ends at "thread_id = %s" with trailing ORDER/LIMIT
        and nothing in between, that's the old pattern. The fixed pattern has
        "AND " after "thread_id = %s".
        """
        violations = []
        for func, s, line in self._collect_sql_strings():
            s_norm = " ".join(s.split()).upper()

            # Only care about SELECT/DELETE/UPDATE on child tables with thread_id.
            if not any(t.upper() in s_norm for t in self.CHILD_TABLES):
                continue
            if "THREAD_ID = %S" not in s_norm:
                continue
            if not any(verb in s_norm for verb in ("SELECT", "UPDATE", "DELETE")):
                continue  # INSERT is guarded by _assert_thread_owner, not WHERE

            # The exemption: get_thread_metadata queries conversation_threads
            # directly (not a child table) so it won't match the CHILD_TABLES
            # filter above. No special-case needed.

            # The MAX(ordering_index) SELECT in add_message is guarded at the
            # method top — _assert_thread_owner(..., for_update=True) runs first
            # inside the same transaction with the row locked. The aggregate
            # returns an integer (not tenant data), and if the guard failed
            # this line is never reached. Scoped by control flow, not WHERE.
            if func == "add_message" and "MAX(ORDERING_INDEX)" in s_norm:
                continue

            # Scoped pattern: "THREAD_ID = %S AND" — something follows the
            # thread_id filter. Unscoped: "THREAD_ID = %S ORDER" or
            # "THREAD_ID = %S LIMIT" — nothing between filter and sort/limit.
            after_tid = s_norm.split("THREAD_ID = %S", 1)[1].lstrip()
            if after_tid.startswith("AND"):
                continue  # scoped ✓ — either _OWNED_THREAD spliced, or explicit user_id

            violations.append(
                f"  {func}() line {line}: {s.strip()[:100]!r}"
            )

        assert not violations, (
            "HIGH-14 REGRESSION — SQL filters by thread_id only, no ownership clause:\n"
            + "\n".join(violations)
            + "\n\nEvery SELECT/UPDATE/DELETE on conversation_messages, query_intents, "
            "or agent_executions must include `AND {_OWNED_THREAD}` after the "
            "thread_id filter. Pre-fix, a caller bypassing api/chat.py could "
            "read any thread given only its ID."
        )

    def test_write_guard_helper_is_used_not_inlined(self):
        """
        Positive pin — the three write methods call _assert_thread_owner by
        name. If someone inlines the check (copy-paste the SELECT 1), the
        behaviour is still correct but the single-point-of-change is lost.
        Next time the policy changes (e.g., admins bypass ownership), three
        places need updating instead of one. Keep it centralized.
        """
        import ast
        import backend.services.conversation_manager as mod

        tree = ast.parse(inspect.getsource(mod))

        write_methods = {"add_message", "save_query_intent", "save_agent_execution"}
        found_guards: dict[str, bool] = {m: False for m in write_methods}

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in write_methods:
                for child in ast.walk(node):
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Name)
                        and child.func.id == "_assert_thread_owner"
                    ):
                        found_guards[node.name] = True

        missing = [m for m, ok in found_guards.items() if not ok]
        assert not missing, (
            f"HIGH-14: write methods {missing} don't call _assert_thread_owner. "
            f"Use the shared helper — inlined checks drift."
        )
