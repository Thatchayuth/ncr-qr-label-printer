import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from qrlabel.domain.errors import ValidationError
from qrlabel.domain.models import PrintStatus
from qrlabel.infrastructure.printing.adapters import (
    MockPrinterAdapter,
    QueueState,
    describe_job_status,
    describe_printer_status,
)
from qrlabel.infrastructure.storage.database import Database
from qrlabel.infrastructure.storage.repositories import (
    SqlitePrintJobRepository,
    SqliteProfileRepository,
    SqliteTemplateRepository,
)
from qrlabel.services.print_service import PrintService


@pytest.fixture
def env(db, profile, template, tmp_path):
    profiles, templates = SqliteProfileRepository(db), SqliteTemplateRepository(db)
    profiles.save(profile)
    templates.save(template)
    svc = PrintService(SqlitePrintJobRepository(db), "test", username="tester", profiles=profiles, templates=templates)
    return svc, MockPrinterAdapter(tmp_path / "out")


def _print(svc, adapter, profile, template, ids, corr="c1", copies=2):
    return svc.print_records(records=[{"ASSETID": i, "NAME": "โต๊ะ"} for i in ids], profile=profile,
                             template=template, adapter=adapter, copies=copies, correlation_id=corr)


# --------------------------------------------------------------- database

def test_migration_from_v1_adds_record_json(tmp_path):
    path = tmp_path / "old.sqlite3"
    from qrlabel.infrastructure.storage import database as dbmod

    conn = sqlite3.connect(path)
    conn.executescript(dbmod._MIGRATIONS[1] + "PRAGMA user_version = 1;")
    conn.execute(
        "INSERT INTO print_jobs (id, correlation_id, document_ref, printer_name, adapter, copies, profile_id, "
        "profile_version, template_id, template_version, status, username, app_version, created_at, updated_at) "
        "VALUES ('old', 'c', 'FA-1', 'p', 'mock', 1, 'asset', 1, 't', 1, 'SpoolerAccepted', 'u', '0.1', 'x', 'x')"
    )
    conn.commit()
    conn.close()
    db = Database(path)
    job = SqlitePrintJobRepository(db).get("old")
    assert job.document_ref == "FA-1" and job.record_json == ""
    assert (tmp_path / "old.sqlite3.bak-v1").exists()


def test_record_snapshot_saved(env, profile, template):
    svc, adapter = env
    job = _print(svc, adapter, profile, template, ["FA-1"])[0]
    assert json.loads(svc.jobs.get(job.id).record_json)["ASSETID"] == "FA-1"


# ---------------------------------------------------------------- reprint

def test_reprint_links_to_original_and_uses_original_versions(env, profile, template):
    svc, adapter = env
    original = _print(svc, adapter, profile, template, ["FA-1"])[0]
    first_bytes = adapter.sent[-1]
    template.elements[0].x_mm = 5  # a later template version must not affect the reprint
    svc.templates.save(template)

    jobs = svc.reprint(job_ids=[original.id], reason="  sticker   damaged ", adapter=adapter)
    assert len(jobs) == 1
    r = svc.jobs.get(jobs[0].id)
    assert r.parent_job_id == original.id
    assert r.reason == "Reprint: sticker damaged"
    assert r.template_version == 1 and r.copies == 2
    assert adapter.sent[-1] == first_bytes  # identical label
    assert [c.id for c in svc.jobs.children(original.id)] == [r.id]


def test_reprint_copies_override_and_reason_required(env, profile, template):
    svc, adapter = env
    original = _print(svc, adapter, profile, template, ["FA-1"])[0]
    with pytest.raises(ValidationError):
        svc.reprint(job_ids=[original.id], reason=" ", adapter=adapter)
    r = svc.reprint(job_ids=[original.id], reason="lost", adapter=adapter, copies=1)[0]
    assert r.copies == 1


def test_reprint_old_job_without_snapshot_is_refused(env, profile, template):
    svc, adapter = env
    original = _print(svc, adapter, profile, template, ["FA-1"])[0]
    with svc.jobs.db.connect() as c:
        c.execute("UPDATE print_jobs SET record_json = '' WHERE id = ?", (original.id,))
    with pytest.raises(ValidationError):
        svc.reprint(job_ids=[original.id], reason="lost", adapter=adapter)


def test_reprint_stops_after_failure(env, profile, template, tmp_path):
    svc, adapter = env
    jobs = _print(svc, adapter, profile, template, ["FA-1", "FA-2"])
    failing = MockPrinterAdapter(tmp_path / "f", fail_with=PrintStatus.FAILED)
    out = svc.reprint(job_ids=[j.id for j in jobs], reason="test", adapter=failing)
    assert [j.status for j in out] == [PrintStatus.FAILED]  # second one never sent


# ---------------------------------------------------------- operator marks

def test_confirm_transitions(env, profile, template):
    svc, adapter = env
    job = _print(svc, adapter, profile, template, ["FA-1"])[0]
    done = svc.confirm(job.id, PrintStatus.CONFIRMED_PRINTED, "checked")
    assert done.status == PrintStatus.CONFIRMED_PRINTED
    assert "tester checked the printer: label printed - checked" in [m for _, _, m in svc.jobs.events(job.id)]
    with pytest.raises(ValidationError):  # already confirmed
        svc.confirm(job.id, PrintStatus.FAILED)
    with pytest.raises(ValidationError):  # not a manual status
        svc.confirm(job.id, PrintStatus.SPOOLER_ACCEPTED)


def test_unknown_delivery_can_be_marked_failed(env, profile, template, tmp_path):
    svc, _ = env
    bad = MockPrinterAdapter(tmp_path, fail_with=PrintStatus.UNKNOWN_DELIVERY)
    job = _print(svc, bad, profile, template, ["FA-1"])[0]
    out = svc.confirm(job.id, PrintStatus.FAILED, "nothing came out")
    assert out.status == PrintStatus.FAILED and out.error_code == "OPERATOR"


# ------------------------------------------------------------------ queue

class FakeQueue:
    def __init__(self, in_queue):
        self.in_queue, self.cancelled = in_queue, []

    def queue_state(self, spool_id):
        return QueueState(self.in_queue, "x")

    def cancel(self, spool_id):
        self.cancelled.append(spool_id)


def test_cancel_in_queue(env, profile, template):
    svc, adapter = env
    job = _print(svc, adapter, profile, template, ["FA-1"])[0]
    q = FakeQueue(in_queue=True)
    assert svc.cancel_in_queue(job.id, q).status == PrintStatus.CANCELLED
    assert q.cancelled == [job.spool_job_id]


def test_cancel_refused_when_already_left_queue(env, profile, template):
    svc, adapter = env
    job = _print(svc, adapter, profile, template, ["FA-1"])[0]
    with pytest.raises(ValidationError):
        svc.cancel_in_queue(job.id, FakeQueue(in_queue=False))
    assert svc.jobs.get(job.id).status == PrintStatus.SPOOLER_ACCEPTED


def test_status_descriptions():
    assert describe_job_status(0x10) == ("Printing", False)
    text, problem = describe_job_status(0x40 | 0x10)
    assert problem and "Out of paper" in text
    assert describe_job_status(0) == ("Waiting in queue", False)
    assert describe_printer_status(0x80 | 0x10) == ["out of paper", "printer offline"]
    assert "Use printer offline" in describe_printer_status(0, 0x400)[0]


# ----------------------------------------------------------------- filter

def test_list_filtered(env, profile, template, tmp_path):
    svc, adapter = env
    _print(svc, adapter, profile, template, ["FA-1", "FB-2"], corr="a")
    _print(svc, MockPrinterAdapter(tmp_path, fail_with=PrintStatus.FAILED), profile, template, ["FC-3"], corr="b")
    repo = svc.jobs
    assert {j.document_ref for j in repo.list_filtered(text="fb")} == {"FB-2"}
    assert {j.document_ref for j in repo.list_filtered(statuses=[PrintStatus.FAILED])} == {"FC-3"}
    now = datetime.now(timezone.utc)
    assert len(repo.list_filtered(start=now - timedelta(hours=1), end=now + timedelta(hours=1))) == 3
    assert repo.list_filtered(start=now + timedelta(hours=1)) == []
    assert repo.list_filtered(text="100%_") == []  # wildcards are literal
