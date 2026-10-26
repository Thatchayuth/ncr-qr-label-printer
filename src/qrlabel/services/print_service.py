"""Print orchestration: validate everything, record history, send, record result."""
from __future__ import annotations

import getpass
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..domain.errors import DuplicateJobError, PayloadError, ValidationError
from ..domain.interfaces import IPrinterAdapter, IPrintJobRepository
from ..domain.models import DataProfile, LabelTemplate, PrintJob, PrintStatus, new_id
from ..rendering.tspl import TsplRenderer
from .formatting import build_label_values, document_ref
from .qr_payload import QrPayloadBuilder

log = logging.getLogger("qrlabel.print")

MAX_COPIES = 999
MAX_RECORDS_PER_DISPATCH = 500


@dataclass
class PreparedLabel:
    document_ref: str
    data: bytes
    warnings: list[str]


class PrintService:
    def __init__(
        self,
        jobs: IPrintJobRepository,
        app_version: str,
        renderer: TsplRenderer | None = None,
        payload_builder: QrPayloadBuilder | None = None,
        username: str | None = None,
    ) -> None:
        self.jobs = jobs
        self.app_version = app_version
        self.renderer = renderer or TsplRenderer()
        self.payloads = payload_builder or QrPayloadBuilder()
        self.username = username if username is not None else _windows_user()

    def prepare(self, records: list[dict[str, Any]], profile: DataProfile, template: LabelTemplate, copies: int) -> list[PreparedLabel]:
        """Build TSPL for every record. Raises before anything is printed if any record is invalid."""
        if not records:
            raise ValidationError("Select at least one record to print.")
        if len(records) > MAX_RECORDS_PER_DISPATCH:
            raise ValidationError(f"Too many records selected (max {MAX_RECORDS_PER_DISPATCH}).")
        if not 1 <= int(copies) <= MAX_COPIES:
            raise ValidationError(f"Copies must be between 1 and {MAX_COPIES}.")
        prepared = []
        for rec in records:
            values = build_label_values(profile, rec)
            ref = document_ref(profile, values)
            try:
                payload = self.payloads.build(rec, profile)
            except PayloadError as e:
                raise PayloadError(f"Record '{ref}': {e.message}") from None
            data, warnings = self.renderer.render_job(
                template, [(values, payload.text)], copies, ecc=payload.error_correction
            )
            prepared.append(PreparedLabel(ref, data, warnings))
        return prepared

    def print_records(
        self,
        *,
        records: list[dict[str, Any]],
        profile: DataProfile,
        template: LabelTemplate,
        adapter: IPrinterAdapter,
        copies: int,
        correlation_id: str,
        reason: str = "",
        parent_job_id: str = "",
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[PrintJob]:
        if self.jobs.correlation_exists(correlation_id):
            raise DuplicateJobError("This print request was already submitted. Check Print History before printing again.")
        prepared = self.prepare(records, profile, template, copies)

        jobs = []
        for p in prepared:
            job = PrintJob(
                id=new_id(), correlation_id=correlation_id, document_ref=p.document_ref,
                printer_name=adapter.target, adapter=adapter.kind, copies=int(copies),
                profile_id=profile.id, profile_version=profile.version,
                template_id=template.id, template_version=template.version,
                username=self.username, app_version=self.app_version,
                parent_job_id=parent_job_id, reason=reason,
            )
            self.jobs.create(job)
            jobs.append(job)

        stop_reason = ""
        for job, p in zip(jobs, prepared):
            if not stop_reason and should_cancel and should_cancel():
                stop_reason = "Cancelled by operator"
            if stop_reason:
                self._set(job, PrintStatus.CANCELLED, stop_reason)
                continue
            self._set(job, PrintStatus.SUBMITTING, "")
            try:
                result = adapter.send(p.data, f"QRLabel {p.document_ref}")
            except Exception as e:  # unexpected adapter bug: delivery state unknown
                log.exception("Adapter crashed job=%s", job.id)
                self._set(job, PrintStatus.UNKNOWN_DELIVERY, f"Unexpected error: {e}", error_code="ADAPTER")
                stop_reason = "Stopped after a previous label failed"
                continue
            self._set(job, result.status, result.message, spool_job_id=result.spool_job_id, error_code=result.error_code)
            if result.status in (PrintStatus.FAILED, PrintStatus.UNKNOWN_DELIVERY):
                # never keep sending after an uncertain or failed delivery
                stop_reason = "Stopped after a previous label failed"
        return jobs

    def _set(self, job: PrintJob, status: PrintStatus, message: str, *, spool_job_id: int | None = None, error_code: str = "") -> None:
        job.status = status
        if spool_job_id is not None:
            job.spool_job_id = spool_job_id
        job.error_code = error_code
        job.error_message = message if error_code else ""
        self.jobs.update_status(job.id, status, message=message, spool_job_id=spool_job_id, error_code=error_code)
        log.info(
            "print_job status=%s job=%s corr=%s doc=%s printer=%s copies=%s profile=%s/v%s template=%s/v%s user=%s err=%s",
            status.value, job.id, job.correlation_id, job.document_ref, job.printer_name, job.copies,
            job.profile_id, job.profile_version, job.template_id, job.template_version, job.username, error_code,
        )


def _windows_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"
