"""plan_ai_run (a read-only, grant-gated preview of an AI extraction run),
get_ai_runs (the caller's own runs) and cancel_ai_run (one audited, idempotent cancel)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.mcp import session as mcp_session
from app.models.extraction_attempt import ExtractionAttempt
from app.services.extraction_batch_service import ExtractionBatchService
from app.utils.compact_json import RESULT_CAP, compact_json
from app.worker import queue_health
from tests.integration.conftest import SEED
from tests.integration.helpers.batch_fixtures import make_agent_batch, make_article, make_batch
from tests.integration.mcp.ai_run_helpers import plan_args as _args
from tests.integration.mcp.ai_run_helpers import ready_article as _article
from tests.integration.mcp.ai_run_helpers import ready_env
from tests.integration.mcp.ai_run_helpers import set_policy as _policy
from tests.integration.mcp.ai_run_helpers import set_rung as _rung
from tests.integration.mcp.article_seed import insert_pdf
from tests.integration.mcp.conftest import _seed_pat
from tests.integration.mcp.tool_calls import call_tool, error_payload, structured
from tests.integration.test_extraction_batch_guards import _extract_run

_TOKEN = re.compile(r"^aip1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


@pytest.fixture(autouse=True)
def _ready_env(monkeypatch: pytest.MonkeyPatch) -> None:
    ready_env(monkeypatch)


def _payload(token: str) -> dict[str, Any]:
    segment = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def _blockers(plan: dict) -> list[tuple[str, str | None]]:
    return [(b["code"], b["reason_code"]) for b in plan["blockers"]]


async def test_ready_plan_defaults_the_template_and_mints_a_bound_token(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession
) -> None:
    await _policy(db_session)
    first, second = await _article(db_session, "ready one"), await _article(db_session, "ready two")
    await db_session.flush()
    actions = "SELECT count(*) FROM public.agent_actions"
    before = (await db_session.execute(text(actions))).scalar_one()

    plan = structured(
        await call_tool(mcp_client, pat_primary_rw_ai_run, "plan_ai_run", _args(first, second))
    )

    assert plan["template"]["id"] == str(SEED.primary_template)
    assert plan["can_start"] is True and plan["blockers"] == []
    assert plan["payer"] == "your_key"
    assert plan["counts"] == {
        "requested": 2,
        "will_run": 2,
        "skipped": 0,
        "remaining_beyond_cap": 0,
    }
    assert _TOKEN.match(plan["plan_token"])
    claims = _payload(plan["plan_token"])
    expected_digest = hashlib.sha256(
        "".join(sorted([str(first), str(second)])).encode()
    ).hexdigest()
    assert claims["will_run_digest"] == expected_digest
    assert claims["will_run_count"] == plan["counts"]["will_run"] == 2
    assert claims["token_id"] == str(pat_primary_rw_ai_run.principal.token_id)
    assert claims["project_id"] == str(SEED.primary_project)
    assert plan["confirm"]["article_count"] == 2
    assert plan["confirm"]["payer"] == "your_key"
    assert plan["confirm"]["model"] == f"{plan['engine']['provider']}:{plan['engine']['model']}"
    assert "AI only adds suggestions" in plan["confirmation"]
    assert plan["expires_at"] is not None
    assert "plan-suite-key" not in json.dumps(plan)
    assert not db_session.new and not db_session.dirty
    assert (await db_session.execute(text(actions))).scalar_one() == before


async def test_no_active_extraction_template_lists_the_templates(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession
) -> None:
    await _policy(db_session)
    await db_session.execute(
        text(
            "UPDATE public.project_extraction_templates SET is_active = false WHERE project_id = :p"
        ),
        {"p": str(SEED.primary_project)},
    )

    err = error_payload(
        await call_tool(mcp_client, pat_primary_rw_ai_run, "plan_ai_run", _args(uuid4()))
    )

    assert err["code"] == "INVALID_ARGUMENT"
    assert err["field"] == "template_id"
    assert isinstance(err["templates"], list)
    assert err["untrusted_fields"] == ["templates[].name"]


@pytest.mark.parametrize(
    ("rung", "payer", "blocker"),
    [
        ("user", "your_key", None),
        ("project", "project_key", None),
        ("global", None, ("AI_NOT_CONFIGURED", "DEPLOYMENT_KEY_NOT_ALLOWED")),
        (None, None, ("AI_NOT_CONFIGURED", "MISSING_API_KEY")),
    ],
    ids=["user-key", "project-key", "deployment-only", "no-key"],
)
async def test_payer_follows_the_credential_rung(
    mcp_client,
    pat_primary_rw_ai_run,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    rung: str | None,
    payer: str | None,
    blocker: tuple[str, str] | None,
) -> None:
    _rung(monkeypatch, rung)
    await _policy(db_session)
    article = await _article(db_session)

    plan = structured(
        await call_tool(mcp_client, pat_primary_rw_ai_run, "plan_ai_run", _args(article))
    )

    assert plan["payer"] == payer
    if blocker is None:
        assert plan["can_start"] is True
    else:
        assert blocker in _blockers(plan)
        assert plan["can_start"] is False and plan["plan_token"] is None
        assert plan["confirm"] is None and plan["confirmation"] is None


_BLOCKER_CASES = [
    "AGENT_RUNS_OFF",
    "MANAGERS_ONLY",
    "TEMPLATE_NOT_PUBLISHED",
    "AI_RUN_ACTIVE",
    "AI_RUN_LIMIT",
    "SERVICE_UNAVAILABLE",
    "NOTHING_TO_RUN",
]


@pytest.mark.parametrize("case", _BLOCKER_CASES, ids=_BLOCKER_CASES)
async def test_blocker_matrix(
    mcp_client,
    pat_primary_rw_ai_run,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    pat = pat_primary_rw_ai_run
    await _policy(
        db_session,
        {"AGENT_RUNS_OFF": "off", "MANAGERS_ONLY": "managers"}.get(case, "reviewers"),
        daily=1 if case == "AI_RUN_LIMIT" else 100,
    )
    articles = [await _article(db_session, pdf=case != "NOTHING_TO_RUN")]
    batch_id = None
    if case == "MANAGERS_ONLY":
        pat = await _seed_pat(db_session, SEED.reviewer_profile, "read_write", ai_run=True)
    elif case == "TEMPLATE_NOT_PUBLISHED":
        await db_session.execute(
            text(
                "UPDATE public.extraction_template_versions SET is_active = false "
                "WHERE project_template_id = :t"
            ),
            {"t": str(SEED.primary_template)},
        )
    elif case == "AI_RUN_ACTIVE":
        batch_id = await make_batch(
            db_session,
            owner_id=SEED.primary_profile,
            project_id=SEED.primary_project,
            template_id=SEED.primary_template,
            article_ids=[await make_article(db_session, SEED.primary_project, "queued")],
        )
    elif case == "AI_RUN_LIMIT":
        articles.append(await _article(db_session, "second"))
    elif case == "SERVICE_UNAVAILABLE":
        monkeypatch.setattr(queue_health, "is_queue_available", lambda: False)

    plan = structured(await call_tool(mcp_client, pat, "plan_ai_run", _args(*articles)))

    codes = [b["code"] for b in plan["blockers"]]
    assert case in codes
    assert plan["can_start"] is False and plan["plan_token"] is None
    row = next(b for b in plan["blockers"] if b["code"] == case)
    assert row["message"] and row["fix"]
    if case == "AI_RUN_ACTIVE":
        assert row["batch_id"] == str(batch_id)
    if case == "AI_RUN_LIMIT":
        assert row["reason_code"] == "DAILY_CAP"
        assert plan["limits"]["daily_remaining"] == 1
    if case == "NOTHING_TO_RUN":
        assert plan["articles"] == [
            {
                "article_id": str(articles[0]),
                "title": "plan article",
                "will_run": False,
                "reason_code": "NO_PDF",
            }
        ]
        assert plan["skipped_by_reason"] == {"NO_PDF": 1}


async def test_warnings_carry_static_messages(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession
) -> None:
    await _policy(db_session)
    unparsed = await make_article(db_session, SEED.primary_project, "unparsed")
    await insert_pdf(db_session, SEED.primary_project, unparsed)

    plan = structured(
        await call_tool(mcp_client, pat_primary_rw_ai_run, "plan_ai_run", _args(unparsed))
    )

    warning = next(w for w in plan["warnings"] if w["code"] == "ARTICLES_UNPARSED")
    assert warning["message"]


async def test_one_hundred_articles_fit_the_result_cap(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession
) -> None:
    await _policy(db_session, per_run=100, daily=1000)
    ids = [await _article(db_session, f"{i:03d} " + "T" * 300) for i in range(100)]

    result = await call_tool(mcp_client, pat_primary_rw_ai_run, "plan_ai_run", _args(*ids))
    plan = structured(result)

    assert plan["can_start"] is True
    assert len(plan["articles"]) == 100
    assert all(len(row["title"]) <= 80 for row in plan["articles"])
    assert len(compact_json(plan)) <= RESULT_CAP
    assert len(plan["plan_token"]) <= 4096


async def test_hints_are_read_only(mcp_client, pat_primary_rw_ai_run) -> None:
    async with mcp_client(pat_primary_rw_ai_run) as client:
        tool = next(t for t in (await client.list_tools()).tools if t.name == "plan_ai_run")
    a = tool.annotations
    assert (a.read_only_hint, a.destructive_hint, a.idempotent_hint, a.open_world_hint) == (
        True,
        False,
        True,
        False,
    )
    assert "anthropic/requiresUserInteraction" not in (tool.meta or {})


async def test_foreign_article_is_not_found(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession
) -> None:
    await _policy(db_session)
    foreign = await make_article(db_session, SEED.secondary_project, "foreign")

    err = error_payload(
        await call_tool(mcp_client, pat_primary_rw_ai_run, "plan_ai_run", _args(foreign))
    )

    assert err["code"] == "NOT_FOUND"


async def test_hidden_and_refused_without_the_grant(mcp_client, pat_primary_rw) -> None:
    async with mcp_client(pat_primary_rw) as client:
        names = {t.name for t in (await client.list_tools()).tools}

    err = error_payload(await call_tool(mcp_client, pat_primary_rw, "plan_ai_run", _args(uuid4())))

    assert "plan_ai_run" not in names
    assert err["code"] == "SCOPE_INSUFFICIENT"
    assert err["required_scope"] == "ai_run"


async def test_viewer_is_refused(mcp_client, pat_viewer_ai_run) -> None:
    err = error_payload(
        await call_tool(mcp_client, pat_viewer_ai_run, "plan_ai_run", _args(uuid4()))
    )

    assert err["code"] == "REVIEWER_REQUIRED"


# --- get_ai_runs and cancel_ai_run -------------------------------------------


def _project(**extra: Any) -> dict[str, Any]:
    return {"project_id": str(SEED.primary_project), **extra}


async def _ui_batch(
    db: AsyncSession, count: int = 1, *, owner: UUID = SEED.primary_profile, **fields: Any
) -> UUID:
    return await make_agent_batch(
        db,
        owner_id=owner,
        project_id=SEED.primary_project,
        template_id=SEED.primary_template,
        token_id=None,
        count=count,
        **fields,
    )


async def _items(db: AsyncSession, batch_id: UUID) -> list[UUID]:
    rows = await db.execute(
        text(
            "SELECT article_id FROM public.extraction_batch_items "
            "WHERE batch_id = :b ORDER BY created_at, id"
        ),
        {"b": str(batch_id)},
    )
    return list(rows.scalars())


async def _attach_attempt(
    db: AsyncSession, batch_id: UUID, article_id: UUID, status: str, result: dict | None = None
) -> None:
    """Dispatch ``article_id``'s item onto a fresh attempt in ``status``."""
    run_id = await _extract_run(db, article_id)
    attempt = ExtractionAttempt(
        request_id=uuid4(),
        owner_id=SEED.primary_profile,
        project_id=SEED.primary_project,
        article_id=article_id,
        template_id=SEED.primary_template,
        run_id=run_id,
        request_payload={},
        status=status,
        result=result,
    )
    db.add(attempt)
    await db.flush()
    await db.execute(
        text(
            "UPDATE public.extraction_batch_items SET status = 'dispatched', attempt_id = :a "
            "WHERE batch_id = :b AND article_id = :r"
        ),
        {"a": str(attempt.id), "b": str(batch_id), "r": str(article_id)},
    )


async def _applied(db: AsyncSession, batch_id: UUID) -> list[dict]:
    rows = await db.execute(
        text(
            "SELECT before, after FROM public.agent_actions "
            "WHERE tool = 'cancel_ai_run' AND outcome = 'applied' "
            "AND after->>'batch_id' = :b"
        ),
        {"b": str(batch_id)},
    )
    return [{"before": r[0], "after": r[1]} for r in rows]


async def test_get_ai_runs_lists_nothing_in_a_project_without_batches(
    mcp_client, pat_primary_read
) -> None:
    body = structured(
        await call_tool(
            mcp_client,
            pat_primary_read,
            "get_ai_runs",
            {"project_id": str(SEED.secondary_project)},
        )
    )

    assert (body["mode"], body["runs"], body["run"]) == ("list", [], None)
    assert body["project_name"]


async def _with_and_without_apps(mcp_client, pat, tool: str, args: dict) -> tuple[Any, Any]:
    async with mcp_client(pat) as client:
        plain = await client.call_tool(tool, args)
    async with mcp_client(pat, apps=True) as client:
        with_apps = await client.call_tool(tool, args)
    return plain, with_apps


async def test_blocked_plan_is_identical_with_and_without_apps(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession
) -> None:
    article = await _article(db_session, "apps plan")
    await db_session.flush()

    plain, with_apps = await _with_and_without_apps(
        mcp_client, pat_primary_rw_ai_run, "plan_ai_run", _args(article)
    )

    assert not plain.is_error
    assert plain.structured_content["can_start"] is False  # precondition: no policy set
    assert plain.structured_content["plan_token"] is None
    assert plain.structured_content["expires_at"] is None
    assert plain.structured_content == with_apps.structured_content
    assert plain.content[0].text == with_apps.content[0].text


@pytest.mark.parametrize("mode", ["list", "detail"])
async def test_get_ai_runs_is_identical_with_and_without_apps(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession, mode: str
) -> None:
    batch_id = await _ui_batch(db_session)
    args = _project(batch_id=str(batch_id)) if mode == "detail" else _project()

    plain, with_apps = await _with_and_without_apps(
        mcp_client, pat_primary_rw_ai_run, "get_ai_runs", args
    )

    assert not plain.is_error
    assert plain.structured_content["mode"] == mode
    assert plain.structured_content["runs"] or plain.structured_content["run"]
    assert plain.structured_content == with_apps.structured_content
    assert plain.content[0].text == with_apps.content[0].text


async def test_get_ai_runs_labels_ui_and_agent_runs_active_first(
    mcp_client, pat_primary_read, db_session: AsyncSession
) -> None:
    finished = await _ui_batch(db_session)
    await db_session.execute(
        text("UPDATE public.extraction_batch_items SET status = 'skipped' WHERE batch_id = :b"),
        {"b": str(finished)},
    )
    agent = await make_agent_batch(
        db_session,
        owner_id=SEED.primary_profile,
        project_id=SEED.primary_project,
        template_id=SEED.primary_template,
        token_id=pat_primary_read.principal.token_id,
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )

    body = structured(await call_tool(mcp_client, pat_primary_read, "get_ai_runs", _project()))

    runs = {r["batch_id"]: r for r in body["runs"]}
    assert (runs[str(finished)]["started_by_agent"], runs[str(finished)]["agent_token_name"]) == (
        False,
        None,
    )
    assert (runs[str(agent)]["started_by_agent"], runs[str(agent)]["agent_token_name"]) == (
        True,
        "pytest-read",
    )
    order = [r["batch_id"] for r in body["runs"]]
    assert order.index(str(agent)) < order.index(str(finished))  # active first, though older
    assert runs[str(finished)]["state"] == "finished"


async def test_get_ai_runs_lists_at_most_twenty(
    mcp_client, pat_primary_read, db_session: AsyncSession
) -> None:
    for _ in range(21):
        await _ui_batch(db_session)

    body = structured(await call_tool(mcp_client, pat_primary_read, "get_ai_runs", _project()))

    assert len(body["runs"]) == 20


async def test_detail_of_a_finished_run_sums_its_work_and_needs_no_attention(
    mcp_client, pat_primary_read, db_session: AsyncSession
) -> None:
    batch_id = await _ui_batch(db_session)
    (article,) = await _items(db_session, batch_id)
    await _attach_attempt(
        db_session,
        batch_id,
        article,
        "completed",
        {
            "total_suggestions_created": 3,
            "failed_sections": 0,
            "total_sections": 2,
            "sections": [{"tokens_used": 100}, {"tokens_used": 50}, {"success": False}],
        },
    )

    body = structured(
        await call_tool(
            mcp_client, pat_primary_read, "get_ai_runs", _project(batch_id=str(batch_id))
        )
    )

    run = body["run"]
    assert (body["mode"], body["runs"]) == ("detail", [])
    assert (run["state"], run["attention_items"], run["next_cursor"]) == ("finished", [], None)
    assert (run["suggestions_created"], run["tokens_used"]) == (3, 150)
    assert run["review_hint"].startswith("Review the AI suggestions in prumo")


async def test_detail_pages_attention_items_within_the_result_cap(
    mcp_client, pat_primary_read, db_session: AsyncSession
) -> None:
    batch_id = await _ui_batch(db_session, 100)
    await db_session.execute(
        text("UPDATE public.articles SET title = :t WHERE id = ANY(:ids)"),
        {"t": "\u0001" * 500, "ids": [str(a) for a in await _items(db_session, batch_id)]},
    )
    await db_session.execute(
        text(
            "UPDATE public.extraction_batch_items SET status = 'failed', reason_code = 'LLM_ERROR' "
            "WHERE id IN (SELECT id FROM public.extraction_batch_items WHERE batch_id = :b "
            "ORDER BY created_at, id LIMIT 60)"
        ),
        {"b": str(batch_id)},
    )
    args = _project(batch_id=str(batch_id))

    first = structured(await call_tool(mcp_client, pat_primary_read, "get_ai_runs", args))
    second = structured(
        await call_tool(
            mcp_client,
            pat_primary_read,
            "get_ai_runs",
            {**args, "cursor": first["run"]["next_cursor"]},
        )
    )

    assert len(first["run"]["attention_items"]) == 50 and first["run"]["next_cursor"]
    assert len(second["run"]["attention_items"]) == 10 and second["run"]["next_cursor"] is None
    seen = [i["article_id"] for page in (first, second) for i in page["run"]["attention_items"]]
    assert len(set(seen)) == 60
    item = first["run"]["attention_items"][0]
    assert (item["outcome"], item["reason_code"]) == ("needs_attention", "LLM_ERROR")
    assert len(item["title"]) <= 80
    for page in (first, second):
        assert len(compact_json(page)) <= RESULT_CAP


async def test_get_ai_runs_rejects_a_bad_cursor(
    mcp_client, pat_primary_read, db_session: AsyncSession
) -> None:
    batch_id = await _ui_batch(db_session)

    err = error_payload(
        await call_tool(
            mcp_client,
            pat_primary_read,
            "get_ai_runs",
            _project(batch_id=str(batch_id), cursor="not-a-cursor"),
        )
    )

    assert (err["code"], err["field"]) == ("INVALID_ARGUMENT", "cursor")


async def test_get_ai_runs_hides_foreign_other_project_and_missing_runs(
    mcp_client, pat_primary_read, db_session: AsyncSession
) -> None:
    foreign = await _ui_batch(db_session, owner=SEED.reviewer_profile)
    own = await _ui_batch(db_session)
    cases = [
        _project(batch_id=str(foreign)),
        {"project_id": str(SEED.secondary_project), "batch_id": str(own)},
        _project(batch_id=str(uuid4())),
    ]

    codes = [
        error_payload(await call_tool(mcp_client, pat_primary_read, "get_ai_runs", args))["code"]
        for args in cases
    ]

    assert codes == ["NOT_FOUND"] * 3


async def test_cancel_stops_queued_counts_in_flight_and_writes_one_row(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession
) -> None:
    await _policy(db_session, "off")  # never read by cancel
    batch_id = await _ui_batch(db_session, 3)
    running, *_ = await _items(db_session, batch_id)
    await _attach_attempt(db_session, batch_id, running, "running")
    args = _project(batch_id=str(batch_id))

    first = structured(await call_tool(mcp_client, pat_primary_rw_ai_run, "cancel_ai_run", args))
    again = structured(await call_tool(mcp_client, pat_primary_rw_ai_run, "cancel_ai_run", args))

    assert first["already_finished"] is False
    assert (first["cancelled_queued"], first["in_flight_finishing"]) == (2, 1)
    assert first["state"] == "active"  # the in-flight article still finishes
    assert again["already_finished"] is True and again["cancelled_queued"] == 0
    rows = await _applied(db_session, batch_id)
    assert rows == [
        {"before": {"state": "active"}, "after": {"batch_id": str(batch_id), "cancelled_queued": 2}}
    ]


async def test_cancel_of_a_stopped_run_writes_nothing(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession
) -> None:
    batch_id = await _ui_batch(db_session, 2, stop_code="MISSING_API_KEY")

    body = structured(
        await call_tool(
            mcp_client, pat_primary_rw_ai_run, "cancel_ai_run", _project(batch_id=str(batch_id))
        )
    )

    assert body["already_finished"] is True
    assert await _applied(db_session, batch_id) == []


async def test_cancel_of_a_finished_run_writes_nothing(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession
) -> None:
    batch_id = await _ui_batch(db_session)
    await db_session.execute(
        text("UPDATE public.extraction_batch_items SET status = 'skipped' WHERE batch_id = :b"),
        {"b": str(batch_id)},
    )

    body = structured(
        await call_tool(
            mcp_client, pat_primary_rw_ai_run, "cancel_ai_run", _project(batch_id=str(batch_id))
        )
    )
    cancelled_at = (
        await db_session.execute(
            text("SELECT cancelled_at FROM public.extraction_batches WHERE id = :b"),
            {"b": str(batch_id)},
        )
    ).scalar_one()

    assert (body["already_finished"], body["state"]) == (True, "finished")
    assert cancelled_at is None
    assert await _applied(db_session, batch_id) == []


async def test_viewer_cancels_their_own_run(
    mcp_client, pat_viewer_ai_run, db_session: AsyncSession
) -> None:
    batch_id = await _ui_batch(db_session, owner=SEED.reviewer_profile)

    body = structured(
        await call_tool(
            mcp_client, pat_viewer_ai_run, "cancel_ai_run", _project(batch_id=str(batch_id))
        )
    )

    assert (body["already_finished"], body["cancelled_queued"]) == (False, 1)


async def test_cancel_is_hidden_and_refused_without_the_grant(
    mcp_client, pat_primary_rw, pat_primary_read
) -> None:
    async with mcp_client(pat_primary_rw) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    async with mcp_client(pat_primary_read) as client:
        read_names = {t.name for t in (await client.list_tools()).tools}

    err = error_payload(
        await call_tool(
            mcp_client, pat_primary_rw, "cancel_ai_run", _project(batch_id=str(uuid4()))
        )
    )

    assert "cancel_ai_run" not in names and "get_ai_runs" in read_names
    assert (err["code"], err["required_scope"]) == ("SCOPE_INSUFFICIENT", "ai_run")


async def test_cancel_has_its_own_rate_tier(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession
) -> None:
    batch_id = await _ui_batch(db_session)
    args = _project(batch_id=str(batch_id))

    async with mcp_client(pat_primary_rw_ai_run) as client:
        cancels = [await client.call_tool("cancel_ai_run", args) for _ in range(21)]
        write = await client.call_tool(
            "update_project_details",
            _project(fields={"description": "tier probe"}, expected={"description": "x"}),
        )

    assert all(not r.is_error for r in cancels[:20])
    assert cancels[20].structured_content["code"] == "RATE_LIMITED"
    assert not write.is_error or write.structured_content["code"] != "RATE_LIMITED"


async def test_cancel_deadlock_is_an_audited_retry(
    mcp_client,
    pat_primary_rw_ai_run,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch_id = await _ui_batch(db_session)

    class _Pg(Exception):
        sqlstate = "40P01"

    async def deadlock(*_args: Any, **_kwargs: Any) -> None:
        raise DBAPIError("UPDATE", {}, _Pg())

    monkeypatch.setattr(ExtractionBatchService, "cancel", deadlock)

    err = error_payload(
        await call_tool(
            mcp_client, pat_primary_rw_ai_run, "cancel_ai_run", _project(batch_id=str(batch_id))
        )
    )
    refused = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM public.agent_actions WHERE tool = 'cancel_ai_run' "
                "AND outcome = 'refused' AND error_code = 'RETRY' AND token_id = :t"
            ),
            {"t": str(pat_primary_rw_ai_run.principal.token_id)},
        )
    ).scalar_one()

    assert err["code"] == "RETRY" and err["retryable"] is True
    assert refused == 1


async def test_cancel_that_loses_to_a_stop_reports_the_state_after_the_stop(
    mcp_client,
    pat_primary_rw_ai_run,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stop lands between the first read and the conditional cancel: the reply
    is read again, never the pre-stop snapshot, and nothing is audited."""
    batch_id = await _ui_batch(db_session)
    original = ExtractionBatchService.cancel

    async def stop_wins_first(self: ExtractionBatchService, *args: Any, **kwargs: Any) -> Any:
        assert await self.batches.stop(batch_id, "MISSING_API_KEY", None)
        await self.batches.cancel_queued(batch_id, "STOPPED_MISSING_API_KEY")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(ExtractionBatchService, "cancel", stop_wins_first)

    body = structured(
        await call_tool(
            mcp_client, pat_primary_rw_ai_run, "cancel_ai_run", _project(batch_id=str(batch_id))
        )
    )

    assert body["already_finished"] is True and body["cancelled_queued"] == 0
    assert body["state"] == "stopped"  # not the pre-stop "active"
    assert await _applied(db_session, batch_id) == []


@pytest.mark.mcp_real_sessions
async def test_concurrent_cancels_write_one_applied_row(mcp_client) -> None:
    async with mcp_session.session_factory() as db:
        pat = await _seed_pat(db, SEED.primary_profile, "read_write", ai_run=True)
        batch_id = await _ui_batch(db, 2)
        articles = await _items(db, batch_id)
        await db.commit()
    args = _project(batch_id=str(batch_id))
    try:
        results = await asyncio.gather(
            call_tool(mcp_client, pat, "cancel_ai_run", args),
            call_tool(mcp_client, pat, "cancel_ai_run", args),
        )

        replies = [structured(r) for r in results]
        assert sorted(r["already_finished"] for r in replies) == [False, True]
        async with mcp_session.session_factory() as db:
            assert len(await _applied(db, batch_id)) == 1
    finally:
        async with mcp_session.session_factory() as db:
            await db.execute(
                text("DELETE FROM public.agent_actions WHERE token_id = :t"),
                {"t": str(pat.principal.token_id)},
            )
            await db.execute(
                text("DELETE FROM public.extraction_batches WHERE id = :b"), {"b": str(batch_id)}
            )
            await db.execute(
                text("DELETE FROM public.articles WHERE id = ANY(:a)"),
                {"a": [str(a) for a in articles]},
            )
            await db.execute(
                text("DELETE FROM public.personal_access_tokens WHERE id = :t"),
                {"t": str(pat.principal.token_id)},
            )
            await db.commit()


async def test_a_host_model_id_is_capped_untrusted_text(
    mcp_client, pat_primary_rw_ai_run, db_session: AsyncSession
) -> None:
    """A host connection's model id is text its owner typed: capped at 200
    chars in ``engine.model``; ``confirm.model`` stays the exact echo."""
    from app.services.user_engine_service import set_user_engine
    from tests.integration.helpers.engine_setup import make_host_connection

    await _policy(db_session)
    long_model = "m" * 230  # older than the 200-char create cap
    cid = await make_host_connection(db_session, label="long-model")
    await db_session.execute(
        text("UPDATE public.llm_connections SET allowed_models = CAST(:m AS jsonb) WHERE id = :id"),
        {"m": json.dumps([long_model]), "id": str(cid)},
    )
    await set_user_engine(
        db_session,
        user_id=SEED.primary_profile,
        project_id=SEED.primary_project,
        provider="openai_compatible",
        model=long_model,
        mode="fast",
        connection_id=cid,
        is_manager=True,
    )

    plan = structured(
        await call_tool(
            mcp_client, pat_primary_rw_ai_run, "plan_ai_run", _args(await _article(db_session))
        )
    )

    assert plan["engine"]["model"] == "m" * 200
    assert {"engine.model", "confirm.model"} <= set(plan["untrusted_fields"])
