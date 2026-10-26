"""Print orchestration: validate everything, record history, send, record result."""
from __future__ import annotations

import getpass
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..domain.errors import DuplicateJobError, PayloadError, ValidationError
from ..domain.interfaces import (
    ILabelTemplateRepository,
    IPrinterAdapter,
    IPrintJobRepository,
    IQueryProfileRepository,
)
from ..domain.models import DataProfile, LabelTemplate, PrintJob, PrintStatus, new_id
from ..rendering.tspl import TsplRenderer
from .formatting import build_label_values, document_ref
from .qr_payload import QrPayloadBuilder

log = logging.getLogger("qrlabel.print")

MAX_COPIES = 999
MAX_RECORDS_PER_DISPATCH = 500


MIN_REASON_LENGTH = 3
_DONE_BAD = (PrintStatus.FAILED, PrintStatus.UNKNOWN_DELIVERY, PrintStatus.CANCELLED)
_SENT = {PrintStatus.SPOOLER_ACCEPTED, PrintStatus.SUBMITTED_TO_DEVICE, PrintStatus.UNKNOWN_DELIVERY}
# Which statuses an operator may set by hand, and from which current statuses.
MANUAL_TRANSITIONS: dict[PrintStatus, set[PrintStatus]] = {
    PrintStatus.CONFIRMED_PRINTED: _SENT,
    PrintStatus.FAILED: _SENT | {PrintStatus.PENDING, PrintStatus.SUBMITTING},
}


@dataclass
class PreparedLabel:
    document_ref: str
    data: bytes
    warnings: list[str]
    values: dict[str, str]


class PrintService:
    def __init__(
        self,
        jobs: IPrintJobRepository,
        app_version: str,
        renderer: TsplRenderer | None = None,
        payload_builder: QrPayloadBuilder | None = None,
        username: str | None = None,
        profiles: IQueryProfileRepository | None = None,
        templates: ILabelTemplateRepository | None = None,
    ) -> None:
        self.jobs = jobs
        self.app_version = app_version
        self.renderer = renderer or TsplRenderer()
        self.payloads = payload_builder or QrPayloadBuilder()
        self.username = username if username is not None else _windows_user()
        self.profiles = profiles
        self.templates = templates

    # ------------------------------------------------------------ reprint

    def plan_reprint(self, job_ids: list[str]) -> list[tuple[PrintJob, DataProfile, LabelTemplate, dict[str, Any]]]:
        """Load what is needed to reprint jobs exactly (same data, profile version and template version)."""
        if not job_ids:
            raise ValidationError("Select at least one job to reprint.")
        if self.profiles is None or self.templates is None:
            raise ValidationError("Reprint is not available.")
        plans = []
        for job_id in job_ids:
            job = self.jobs.get(job_id)
            if job is None:
                raise ValidationError("A selected job no longer exists.")
            if not job.record_json:
                raise ValidationError(
                    f"{job.document_ref}: this job was printed before reprint support was added. Search and print it again."
                )
            profile = self.profiles.get(job.profile_id, job.profile_version)
            template = self.templates.get(job.template_id, job.template_version)
            if profile is None or template is None:
                raise ValidationError(f"{job.document_ref}: the profile or template version used originally was not found.")
            plans.append((job, profile, template, json.loads(job.record_json)))
        return plans

    def reprint(
        self,
        *,
        job_ids: list[str],
        reason: str,
        adapter: IPrinterAdapter,
        copies: int | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[PrintJob]:
        """Print selected jobs again. Each reprint is a new job linked to the original by parent_job_id."""
        reason = " ".join((reason or "").split())
        if len(reason) < MIN_REASON_LENGTH:
            raise ValidationError("Enter a reason for the reprint.")
        plans = self.plan_reprint(job_ids)
        for job, profile, template, record in plans:  # validate everything before sending anything
            self.prepare([record], profile, template, copies or job.copies)
        out: list[PrintJob] = []
        for job, profile, template, record in plans:
            jobs = self.print_records(
                records=[record], profile=profile, template=template, adapter=adapter,
                copies=copies or job.copies, correlation_id=new_id(), reason=f"Reprint: {reason}",
                parent_job_id=job.id, should_cancel=should_cancel,
            )
            out.extend(jobs)
            if jobs[-1].status in _DONE_BAD:
                break  # never keep sending after a failed or uncertain job
        return out

    # ------------------------------------------------------ windows queue

    def cancel_in_queue(self, job_id: str, adapter) -> PrintJob:
        """Remove a job that is still waiting in the Windows queue and record it as Cancelled."""
        job = self.jobs.get(job_id)
        if job is None:
            raise ValidationError("The job no longer exists.")
        if job.status != PrintStatus.SPOOLER_ACCEPTED or not job.spool_job_id or adapter is None:
            raise ValidationError("Only jobs waiting in a Windows print queue can be cancelled here.")
        state = adapter.queue_state(job.spool_job_id)
        if not state.in_queue:
            raise ValidationError("The job is no longer in the Windows queue - it may already have printed. Check the printer.")
        adapter.cancel(job.spool_job_id)
        self.jobs.update_status(
            job.id, PrintStatus.CANCELLED, message=f"{self.username} cancelled the job in the Windows print queue",
            error_code="CANCELLED",
        )
        log.info("print_job cancelled in queue job=%s spool=%s user=%s", job.id, job.spool_job_id, self.username)
        return self.jobs.get(job_id)

    # ------------------------------------------------------ operator check

    def confirm(self, job_id: str, status: PrintStatus, note: str = "") -> PrintJob:
        """Operator records what physically happened at the printer."""
        job = self.jobs.get(job_id)
        if job is None:
            raise ValidationError("The job no longer exists.")
        allowed = MANUAL_TRANSITIONS.get(status)
        if not allowed or job.status not in allowed:
            raise ValidationError(f"A job that is '{job.status.value}' cannot be marked '{status.value}'.")
        what = "checked the printer: label printed" if status == PrintStatus.CONFIRMED_PRINTED else "checked the printer: label did NOT print"
        message = f"{self.username} {what}" + (f" - {note.strip()}" if note.strip() else "")
        self.jobs.update_status(job.id, status, message=message, error_code="" if status == PrintStatus.CONFIRMED_PRINTED else "OPERATOR")
        log.info("print_job manual status=%s job=%s doc=%s user=%s", status.value, job.id, job.document_ref, self.username)
        return self.jobs.get(job_id)

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
            prepared.append(PreparedLabel(ref, data, warnings, values))
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
                record_json=json.dumps(p.values, ensure_ascii=False),
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
