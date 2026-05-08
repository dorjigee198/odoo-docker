# -*- coding: utf-8 -*-
import json
import logging
import os
import tempfile
import time
from datetime import datetime
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)
_tlog = logging.getLogger("customer_support.timing")
_FWD_TIMING_LOG = os.path.join(tempfile.gettempdir(), "fwd_timing.log")


class CustomerReportsController(http.Controller):

    # ── Diagnostic ping (no DB) ───────────────────────────────────────────
    @http.route(
        "/customer_support/admin/report/ping",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def ping(self, **kw):
        return {"pong": True, "ts": time.time()}

    # ── Diagnostic: instant auth check ───────────────────────────────────
    @http.route(
        "/customer_support/admin/report/ping_auth",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def ping_auth(self, **kw):
        return {"pong": True, "uid": request.env.user.id, "ts": time.time()}

    # ── Admin: forward closure report to all project customers ────────────
    @http.route(
        "/customer_support/admin_dashboard/report/forward",
        type="jsonrpc",
        auth="user",
        csrf=False,
    )
    def forward_report(self, report_id=None, **kw):
        t0 = time.time()
        _logger.warning("FORWARD HIT report_id=%s uid=%s", report_id, request.env.user.id)
        with open(_FWD_TIMING_LOG, "a") as _f:
            _f.write(f"[{datetime.utcnow()}] FORWARD START report_id={report_id}\n")
        try:
            def _flog(msg):
                _logger.warning("FWD %s", msg)
                with open(_FWD_TIMING_LOG, "a") as _f:
                    _f.write(f"[{time.time()-t0:.3f}s] {msg}\n")

            if not request.env.user.has_group("base.group_system"):
                _flog("BLOCKED: not admin")
                return {"error": "Access denied"}
            _flog("A: group check done")

            if not report_id:
                return {"error": "Missing report_id"}

            rid    = int(report_id)
            env    = request.env
            report = env["customer_support.project.report"].sudo().browse(rid)
            if not report.exists():
                _flog("B: report not found")
                return {"error": "Report not found"}
            _flog("B: report found")

            customer_data = json.loads(report.customers or "[]")
            if not customer_data:
                return {"error": "No customers linked to this report"}
            _flog("C: customers parsed")

            # ── 1. Resolve partner IDs ────────────────────────────────────
            partner_map = {}

            id_based    = [c for c in customer_data if c.get("id")]
            email_based = [c for c in customer_data if not c.get("id") and c.get("email")]

            if id_based:
                pids = [int(c["id"]) for c in id_based]
                for p in env["res.partner"].sudo().browse(pids).exists():
                    partner_map[p.id] = p.name or ""
            _flog("D: id lookup done")

            if email_based:
                emails = list({c["email"].strip() for c in email_based if c.get("email", "").strip()})
                if emails:
                    for p in env["res.partner"].sudo().search([("email", "in", emails)]):
                        if p.id not in partner_map:
                            partner_map[p.id] = p.name or ""
            _flog("E: email lookup done")

            if not partner_map:
                return {"error": "No matching portal accounts found for these customers"}

            all_pids = list(partner_map)

            # ── 2. Skip already-forwarded ─────────────────────────────────
            existing_pids = {
                r.partner_id.id
                for r in env["customer_support.forwarded.report"].sudo().search([
                    ("project_report_id", "=", rid),
                    ("partner_id", "in", all_pids),
                ])
            }
            new_pids = [pid for pid in all_pids if pid not in existing_pids]
            _flog("F: existing check done")

            if not new_pids:
                return {"success": True, "forwarded": 0, "already_forwarded": len(existing_pids)}

            # ── 3. Create forwarded.report records ────────────────────────
            now = datetime.utcnow()
            env["customer_support.forwarded.report"].sudo().create([{
                "project_report_id": rid,
                "partner_id":        pid,
                "forwarded_by":      env.user.id,
                "forwarded_on":      now,
            } for pid in new_pids])
            _flog("G: records created")

            # ── 4. Queue notification emails (no force_send — cron handles it) ──
            base_url = (
                env["ir.config_parameter"].sudo().get_param("web.base.url", "") or ""
            ).rstrip("/")
            project_name = report.project_name or "a project"
            for pid in new_pids:
                partner = env["res.partner"].sudo().browse(pid)
                if not partner.email:
                    continue
                body = (
                    "<p>Dear {name},</p>"
                    "<p>The project closure report for <strong>{project}</strong> has been shared with you.</p>"
                    "<p>You can view it by logging into your portal and navigating to the <strong>Reports</strong> section.</p>"
                    "<p><a href='{url}/customer_support/dashboard'>View Reports</a></p>"
                    "<br><p>Regards,<br>Dragon Coders Support Team</p>"
                ).format(
                    name=partner.name or "Customer",
                    project=project_name,
                    url=base_url,
                )
                env["mail.mail"].sudo().create({
                    "subject":     f"Project Closure Report: {project_name}",
                    "body_html":   body,
                    "email_to":    partner.email,
                    "email_from":  env["ir.config_parameter"].sudo().get_param(
                                       "mail.default.from", "noreply@dragoncoders.com"
                                   ),
                    "auto_delete": True,
                })
            _flog("H: notification emails queued")

            _logger.info("Closure report %s forwarded to partner IDs: %s", rid, new_pids)
            result = {
                "success":           True,
                "forwarded":         len(new_pids),
                "already_forwarded": len(existing_pids),
            }
            _flog(f"H: returning {result}")
            return result

        except Exception as e:
            _tlog.info("FORWARD ERROR %.3fs: %s", time.time()-t0, e)
            with open(_FWD_TIMING_LOG, "a") as _f:
                _f.write(f"[{time.time()-t0:.3f}s] ERROR: {e}\n")
            _logger.error("forward_report error: %s", e)
            return {"error": str(e)}

    # ── Customer: list forwarded reports ─────────────────────────────────
    @http.route(
        "/customer_support/customer/reports/list",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def list_customer_reports(self, **kw):
        try:
            user = request.env.user
            if user._is_public():
                return {"error": "Not authenticated"}

            records = request.env["customer_support.forwarded.report"].sudo().search([
                ("partner_id", "=", user.partner_id.id),
            ])

            result = []
            for rec in records:
                rpt = rec.project_report_id
                result.append({
                    "id":           rec.id,
                    "project_name": rpt.project_name or "",
                    "project_key":  rpt.project_key or "",
                    "project_type": rpt.project_type or "",
                    "forwarded_on": rec.forwarded_on.strftime("%d %b %Y") if rec.forwarded_on else "",
                    "generated_on": rpt.generated_on.strftime("%d %b %Y") if rpt.generated_on else "",
                })
            return {"success": True, "reports": result}

        except Exception as e:
            _logger.error("list_customer_reports error: %s", e)
            return {"error": str(e)}

    # ── Customer: get full report data for preview/download ───────────────
    @http.route(
        "/customer_support/customer/report/detail",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def get_report_detail(self, report_id=None, **kw):
        try:
            user = request.env.user
            if user._is_public():
                return {"error": "Not authenticated"}

            fwd = request.env["customer_support.forwarded.report"].sudo().browse(int(report_id))
            if not fwd.exists() or fwd.partner_id.id != user.partner_id.id:
                return {"error": "Report not found or access denied"}

            r = fwd.project_report_id

            def _json(val, default=None):
                try:
                    return json.loads(val or ("[]" if default is None else "{}"))
                except Exception:
                    return default if default is not None else []

            sla_total    = (r.sla_met or 0) + (r.sla_breached or 0)
            sla_rate     = round(r.sla_met / sla_total * 100) if sla_total else 0
            resolve_rate = round(r.resolved_tickets / r.total_tickets * 100) if r.total_tickets else 0

            return {
                "success": True,
                "report": {
                    "customer_name":      fwd.partner_id.name or "",
                    "project_name":       r.project_name or "",
                    "project_key":        r.project_key or "",
                    "project_type":       r.project_type or "",
                    "focal_person":       r.focal_person or "",
                    "start_date":         str(r.start_date) if r.start_date else "",
                    "end_date":           str(r.end_date) if r.end_date else "",
                    "generated_on":       r.generated_on.strftime("%d %b %Y %I:%M %p") if r.generated_on else "",
                    "tech_languages":     r.tech_languages or "",
                    "tech_frameworks":    r.tech_frameworks or "",
                    "tech_databases":     r.tech_databases or "",
                    "project_goals":      r.project_goals or "",
                    "compliance_flags":   r.compliance_flags or "",
                    "team":               _json(r.team_members),
                    "customers":          _json(r.customers),
                    "total_tickets":      r.total_tickets or 0,
                    "resolved_tickets":   r.resolved_tickets or 0,
                    "open_tickets":       r.open_tickets or 0,
                    "avg_resolution_hrs": round(r.avg_resolution_hrs or 0, 1),
                    "sla_met":            r.sla_met or 0,
                    "sla_breached":       r.sla_breached or 0,
                    "sla_rate":           sla_rate,
                    "resolve_rate":       resolve_rate,
                    "all_ticket_details": _json(r.all_ticket_details),
                    "state_breakdown":    _json(r.state_breakdown, default={}),
                    "total_tasks":        r.total_tasks or 0,
                    "completed_tasks":    r.completed_tasks or 0,
                },
            }

        except Exception as e:
            _logger.error("get_report_detail error: %s", e)
            return {"error": str(e)}
