"""The dashboard. Route smoke tests, plus the two that matter: the human gate
holds on the web side too, and generated files cannot be read outside out/."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apply import db
from apply.models import Posting, Status
from conftest import posting_from


@pytest.fixture
def client(conn, ashcombe_jd, quillon_jd):
    from apply.web.app import app

    db.create_posting(conn, posting_from(ashcombe_jd, slug="ashcombe-investment-intern-2027"))
    db.create_posting(conn, posting_from(quillon_jd, slug="quillon-analyst-2027"))
    db.create_posting(conn, Posting(slug="undated-analyst-2027", company="Undated",
                                    role="Analyst", track="corporate", jd_raw="x"))
    return TestClient(app)


@pytest.mark.parametrize("path", ["/", "/add", "/digest",
                                  "/posting/ashcombe-investment-intern-2027"])
def test_pages_render(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "apply" in response.text


def test_the_pipeline_shows_an_undated_posting_as_unverified(client):
    body = client.get("/").text
    assert "no deadline — verify" in body
    assert "will not guess one" in body


def test_a_missing_posting_redirects_home(client):
    assert client.get("/posting/nope", follow_redirects=False).status_code == 303


def test_intake_parses_a_paste(client, ashcombe_jd):
    response = client.post("/add", data={"jd": ashcombe_jd})
    assert response.status_code == 200
    assert "Ashcombe Trust" in response.text
    assert "2026-10-14" in response.text


def test_intake_refuses_an_empty_paste(client):
    assert "Nothing to read" in client.post("/add", data={"jd": "   "}).text


def test_the_web_review_gate_refuses_without_a_letter(client, conn):
    """The dashboard's half of the human gate. A review with nothing to read is
    not a review, so it must not promote anything to `ready`."""
    row = db.row_for(conn, "ashcombe-investment-intern-2027")
    db.transition(conn, row.application.id, Status.GENERATED, via="gen")

    response = client.post(f"/app/{row.application.id}/review", follow_redirects=True)
    assert "no letter to read" in response.text
    assert db.get_application_by_id(conn, row.application.id).status == "generated"


def test_the_web_submit_gate_refuses_before_review(client, conn):
    row = db.row_for(conn, "quillon-analyst-2027")
    db.transition(conn, row.application.id, Status.GENERATED, via="gen")

    response = client.post(f"/app/{row.application.id}/submit", follow_redirects=True)
    assert "has not been read yet" in response.text
    assert db.get_application_by_id(conn, row.application.id).submitted_at is None


def test_files_outside_out_are_not_served(client):
    for attack in ("../../data/profile.yaml", "..%2f..%2fdata%2fprofile.yaml"):
        response = client.get(f"/file/ashcombe-investment-intern-2027/{attack}",
                              follow_redirects=False)
        assert response.status_code in (303, 404)
        assert "legal_first" not in response.text


# ------------------------------------------------------------ by track


def test_the_pipeline_filters_by_track(client):
    body = client.get("/?track=corporate").text
    assert "Undated" in body                                  # the corporate posting
    assert 'href="/?track=corporate" aria-current="page"' in body


def test_an_empty_track_says_so(client, conn):
    tracks = {r.posting.track for r in db.rows(conn)}
    empty = next(t for t in ("quant", "banking", "allocator", "corporate") if t not in tracks)
    body = client.get(f"/?track={empty}").text
    assert f"Nothing on the {empty} track" in body


def test_an_unknown_track_shows_everything(client):
    body = client.get("/?track=nonsense").text
    assert 'href="/" aria-current="page"' in body and "Undated" in body


def test_status_filters_by_track(client):
    from typer.testing import CliRunner

    from apply.cli import app

    result = CliRunner().invoke(app, ["status", "--track", "corporate"])
    assert result.exit_code == 0 and "Undated" in result.output
    bad = CliRunner().invoke(app, ["status", "--track", "hedge"])
    assert bad.exit_code != 0 and "unknown track" in bad.output
