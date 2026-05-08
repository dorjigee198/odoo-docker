# -*- coding: utf-8 -*-
"""
Customer Support Ticket Model (updated with Activity Log)
=========================================================
Changes from original:
  1. create()               → logs 'created' event
  2. write()                → logs 'status' and 'assign' events
                              (captures old values BEFORE the write)
  3. _cron_check_sla_breaches() → logs 'sla' warning and breach events
  Everything else is identical to the original.
"""

from odoo import models, fields, api
from datetime import timedelta
import logging
import secrets

_logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "new": "New",
    "assigned": "Assigned",
    "in_progress": "In Progress",
    "pending": "Pending",
    "resolved": "Resolved",
    "closed": "Closed",
}


class CustomerSupport(models.Model):
    _name = "customer.support"
    _description = "Customer Support Ticket"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="Ticket Number", required=True, copy=False, readonly=True, default="New"
    )
    subject = fields.Char(string="Subject", required=True, tracking=True)
    description = fields.Text(string="Description", required=True)

    # Project Information
    project_id = fields.Many2one(
        "customer_support.project",
        string="Project",
        required=False,
        tracking=True,
        help="The project this ticket belongs to",
    )

    # Customer Information
    customer_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        tracking=True,
        default=lambda self: self.env.user.partner_id,
    )
    customer_email = fields.Char(
        related="customer_id.email", string="Customer Email", store=True
    )
    customer_phone = fields.Char(
        related="customer_id.phone", string="Customer Phone", store=True
    )

    # Assignment
    assigned_to = fields.Many2one(
        "res.users", string="Assigned To (Focal Person)", tracking=True
    )
    assigned_by = fields.Many2one("res.users", string="Assigned By", tracking=True)
    assigned_date = fields.Datetime(string="Assigned Date", tracking=True)

    # Priority and Status
    priority = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent")],
        string="Priority",
        default="medium",
        required=True,
        tracking=True,
    )

    state = fields.Selection(
        [
            ("new", "New"),
            ("assigned", "Assigned"),
            ("in_progress", "In Progress"),
            ("pending", "Pending Customer"),
            ("resolved", "Resolved"),
            ("closed", "Closed"),
        ],
        string="Status",
        default="new",
        required=True,
        tracking=True,
    )

    # ── SLA Fields ────────────────────────────────────────────────────────────

    sla_policy_id = fields.Many2one(
        "customer.support.sla.policy",
        string="SLA Policy",
        tracking=True,
        help="The SLA policy applied to this ticket at assignment time",
    )

    sla_deadline = fields.Datetime(
        string="SLA Deadline",
        tracking=True,
        help="Auto-calculated: assigned_date + policy duration",
    )

    sla_status = fields.Selection(
        [
            ("none", "No SLA"),
            ("on_track", "On Track"),
            ("at_risk", "At Risk"),
            ("breached", "Breached"),
        ],
        string="SLA Status",
        compute="_compute_sla_status",
        store=True,
        help="Current SLA compliance status",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────

    resolved_date = fields.Datetime(string="Resolved Date", tracking=True)
    closed_date = fields.Datetime(string="Closed Date", tracking=True)

    # Notes
    internal_notes = fields.Text(string="Internal Notes")
    resolution_notes = fields.Text(string="Resolution Notes")

    # Board access token — allows team members to view the board without login
    board_token = fields.Char(
        string="Board Access Token",
        copy=False,
        index=True,
        readonly=True,
    )

    board_bg = fields.Char(
        string="Board Background",
        default="",
        help="CSS background value for the ticket board (color or gradient)",
    )

    # Computed Fields
    days_open = fields.Integer(
        string="Days Open", compute="_compute_days_open", store=True
    )
    is_overdue = fields.Boolean(string="Is Overdue", compute="_compute_is_overdue")

    # Cron deduplication flags — prevent repeated notifications
    sla_warning_sent = fields.Boolean(default=False, copy=False)
    sla_breach_notified = fields.Boolean(default=False, copy=False)
    overdue_notified = fields.Boolean(default=False, copy=False)

    # ── Compute Methods ───────────────────────────────────────────────────────

    @api.depends("sla_deadline", "state", "resolved_date", "closed_date")
    def _compute_sla_status(self):
        now = fields.Datetime.now()
        for record in self:
            if not record.sla_deadline:
                record.sla_status = "none"
                continue

            if record.state in ["resolved", "closed"]:
                end_time = record.resolved_date or record.closed_date or now
                record.sla_status = (
                    "on_track" if end_time <= record.sla_deadline else "breached"
                )
                continue

            if now > record.sla_deadline:
                record.sla_status = "breached"
            else:
                if record.assigned_date:
                    total = (record.sla_deadline - record.assigned_date).total_seconds()
                    remaining = (record.sla_deadline - now).total_seconds()
                    pct_remaining = (remaining / total * 100) if total > 0 else 100
                    record.sla_status = "on_track" if pct_remaining > 20 else "at_risk"
                else:
                    remaining_hours = (record.sla_deadline - now).total_seconds() / 3600
                    record.sla_status = "on_track" if remaining_hours > 2 else "at_risk"

    @api.depends("create_date", "closed_date")
    def _compute_days_open(self):
        for record in self:
            if record.create_date:
                delta = (
                    record.closed_date - record.create_date
                    if record.closed_date
                    else fields.Datetime.now() - record.create_date
                )
                record.days_open = delta.days
            else:
                record.days_open = 0

    @api.depends("state", "days_open")
    def _compute_is_overdue(self):
        for record in self:
            record.is_overdue = (
                record.days_open > 7
                if record.state not in ["resolved", "closed"]
                else False
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _calculate_sla_deadline(self, policy, start_time):
        if not policy or not start_time:
            return False
        try:
            if policy.time_unit == "hours":
                return start_time + timedelta(hours=policy.response_time)
            elif policy.time_unit == "weeks":
                return start_time + timedelta(weeks=policy.response_time)
            else:
                return start_time + timedelta(days=policy.response_time)
        except Exception as e:
            _logger.error(f"SLA deadline calculation failed: {e}")
            return False

    def _create_log(
        self,
        ticket_id,
        event_type,
        summary,
        detail=None,
        old_value=None,
        new_value=None,
        actor_id=None,
    ):
        """
        Safe helper — creates a customer.support.ticket.log record.
        Wrapped in try/except so a log failure never breaks the main operation.
        """
        try:
            self.env["customer.support.ticket.log"].sudo().create(
                {
                    "ticket_id": ticket_id,
                    "event_type": event_type,
                    "summary": summary,
                    "detail": detail,
                    "old_value": old_value,
                    "new_value": new_value,
                    "actor_id": actor_id or self.env.user.id,
                }
            )
        except Exception as e:
            _logger.warning(f"Ticket log creation failed [{event_type}]: {e}")

    def _get_auto_assignment_state(self):
        """Read runtime auto-assignment config from ir.config_parameter."""
        params = self.env["ir.config_parameter"].sudo()
        until_raw = params.get_param("customer_support.auto_assign_enabled_until") or ""
        strategy = (
            params.get_param("customer_support.auto_assign_strategy") or "round_robin"
        )
        last_user_raw = (
            params.get_param("customer_support.auto_assign_last_user_id") or "0"
        )

        enabled_until = False
        if until_raw:
            try:
                enabled_until = fields.Datetime.to_datetime(until_raw)
            except Exception:
                enabled_until = False

        try:
            last_user_id = int(last_user_raw)
        except Exception:
            last_user_id = 0

        if strategy not in ("round_robin", "least_load"):
            strategy = "round_robin"

        is_enabled = bool(enabled_until and enabled_until > fields.Datetime.now())
        return {
            "enabled": is_enabled,
            "enabled_until": enabled_until,
            "strategy": strategy,
            "last_user_id": last_user_id,
        }

    def _get_auto_assign_candidates(self):
        """Prefer focal persons from ticket project; fallback to active internal users."""
        self.ensure_one()

        members = self.env["customer_support.project.member"].sudo()
        candidates = self.env["res.users"].browse()

        if self.project_id:
            project_members = members.search(
                [
                    ("project_id", "=", self.project_id.id),
                    ("role", "=", "focal_person"),
                    ("user_id", "!=", False),
                    ("user_id.active", "=", True),
                ]
            )
            candidates = project_members.mapped("user_id")

        if not candidates:
            internal_group = self.env.ref("base.group_user")
            candidates = internal_group.users.filtered(
                lambda u: u.active and not u.has_group("base.group_system")
            )

        return candidates.sorted(lambda u: u.id)

    def _pick_round_robin_assignee(self, candidates, last_user_id):
        """Pick the next user after last_user_id in ascending id order."""
        if not candidates:
            return False

        for user in candidates:
            if user.id > last_user_id:
                return user
        return candidates[0]

    def _pick_least_load_assignee(self, candidates, workload_cache=None):
        """Pick assignee with the fewest currently open tickets."""
        if not candidates:
            return False

        if workload_cache is None:
            workload_cache = {}

        missing_ids = [uid for uid in candidates.ids if uid not in workload_cache]
        if missing_ids:
            grouped = (
                self.env["customer.support"]
                .sudo()
                .read_group(
                    [
                        ("assigned_to", "in", missing_ids),
                        ("state", "not in", ["resolved", "closed"]),
                    ],
                    ["assigned_to"],
                    ["assigned_to"],
                )
            )
            grouped_counts = {
                row["assigned_to"][0]: row["assigned_to_count"]
                for row in grouped
                if row.get("assigned_to")
            }
            for uid in missing_ids:
                workload_cache[uid] = grouped_counts.get(uid, 0)

        return min(candidates, key=lambda u: (workload_cache.get(u.id, 0), u.id))

    def _auto_assign_new_tickets(self):
        """Assign newly created unassigned tickets when auto-assignment is active."""
        state = self._get_auto_assignment_state()
        if not state["enabled"]:
            return

        params = self.env["ir.config_parameter"].sudo()
        system_user_id = self.env.ref("base.user_root").id
        last_user_id = state["last_user_id"]
        workload_cache = {}

        for ticket in self.filtered(lambda t: not t.assigned_to and t.state == "new"):
            candidates = ticket._get_auto_assign_candidates()
            if not candidates:
                continue

            if state["strategy"] == "least_load":
                assignee = ticket._pick_least_load_assignee(candidates, workload_cache)
            else:
                assignee = ticket._pick_round_robin_assignee(candidates, last_user_id)

            if not assignee:
                continue

            ticket.sudo().write(
                {
                    "assigned_to": assignee.id,
                    "assigned_by": system_user_id,
                    "assigned_date": fields.Datetime.now(),
                    "state": "assigned",
                }
            )

            if state["strategy"] == "least_load":
                workload_cache[assignee.id] = workload_cache.get(assignee.id, 0) + 1

            last_user_id = assignee.id

        params.set_param("customer_support.auto_assign_last_user_id", str(last_user_id))

    # ── CRUD ──────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        if not isinstance(vals_list, list):
            vals_list = [vals_list]

        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].sudo().next_by_code("customer.support")
                    or "New"
                )
            if not vals.get("board_token"):
                vals["board_token"] = secrets.token_urlsafe(32)

        records = super(CustomerSupport, self).create(vals_list)

        for record in records:
            # SLA deadline at creation (original logic — unchanged)
            if record.sla_policy_id and not record.sla_deadline:
                start = record.assigned_date or record.create_date
                deadline = record._calculate_sla_deadline(record.sla_policy_id, start)
                if deadline:
                    record.sudo().write({"sla_deadline": deadline})
                    _logger.info(
                        f"SLA deadline set at creation for {record.name}: {deadline}"
                    )

            # ── Log: ticket created ───────────────────────────────────────
            self._create_log(
                ticket_id=record.id,
                event_type="created",
                summary="Ticket Created",
                detail=(
                    f"Ticket {record.name} was submitted by "
                    f"{record.customer_id.name if record.customer_id else 'Unknown'}."
                ),
                actor_id=self.env.user.id,
            )
            # ─────────────────────────────────────────────────────────────

        records._auto_assign_new_tickets()

        return records

    def write(self, vals):
        # ── Capture old values BEFORE the write ──────────────────────────
        old_states = {r.id: r.state for r in self}
        old_assignees = {r.id: r.assigned_to for r in self}
        # ─────────────────────────────────────────────────────────────────

        # Reset SLA warning flag when deadline is rescheduled
        if 'sla_deadline' in vals:
            vals.setdefault('sla_warning_sent', False)

        result = super(CustomerSupport, self).write(vals)

        # Reset breach/overdue flags when a ticket is reopened
        if 'state' in vals and vals['state'] in ('new', 'in_progress', 'assigned', 'pending'):
            super(CustomerSupport, self).write({
                'sla_breach_notified': False,
                'overdue_notified': False,
            })

        # SLA deadline recalc (original logic — unchanged)
        if "sla_policy_id" in vals or "assigned_date" in vals:
            for record in self:
                if record.sla_policy_id:
                    start = record.assigned_date or record.create_date
                    deadline = record._calculate_sla_deadline(
                        record.sla_policy_id, start
                    )
                    if deadline:
                        super(CustomerSupport, record).write({"sla_deadline": deadline})
                        _logger.info(
                            f"SLA deadline recalculated for {record.name}: {deadline} "
                            f"(policy: {record.sla_policy_id.name}, start: {start})"
                        )
                else:
                    super(CustomerSupport, record).write({"sla_deadline": False})
                    _logger.info(f"SLA deadline cleared for {record.name} (no policy)")

        # ── Log: status change ────────────────────────────────────────────
        if "state" in vals:
            for record in self:
                old_state = old_states.get(record.id)
                new_state = vals["state"]
                if old_state and old_state != new_state:
                    self._create_log(
                        ticket_id=record.id,
                        event_type="status",
                        summary="Status Changed",
                        detail=f"Status updated by {self.env.user.name}.",
                        old_value=STATUS_LABELS.get(old_state, old_state),
                        new_value=STATUS_LABELS.get(new_state, new_state),
                    )

        # ── Log: assignment change ────────────────────────────────────────
        if "assigned_to" in vals and vals["assigned_to"]:
            for record in self:
                new_user = self.env["res.users"].browse(vals["assigned_to"])
                old_user = old_assignees.get(record.id)
                if old_user and old_user.id != vals["assigned_to"]:
                    summary = "Reassigned"
                    detail = f"Reassigned from {old_user.name} to {new_user.name}."
                else:
                    summary = "Ticket Assigned"
                    detail = f"Assigned to {new_user.name} by {self.env.user.name}."
                self._create_log(
                    ticket_id=record.id,
                    event_type="assign",
                    summary=summary,
                    detail=detail,
                    old_value=old_user.name if old_user else None,
                    new_value=new_user.name,
                )
        # ─────────────────────────────────────────────────────────────────

        return result

    # ── Action Methods (all unchanged from original) ──────────────────────────

    def action_assign(self):
        self.ensure_one()
        if self.assigned_to:
            now = fields.Datetime.now()
            write_vals = {
                "state": "assigned",
                "assigned_by": self.env.user.id,
                "assigned_date": now,
            }
            if self.sla_policy_id:
                deadline = self._calculate_sla_deadline(self.sla_policy_id, now)
                if deadline:
                    write_vals["sla_deadline"] = deadline
                    _logger.info(
                        f"SLA deadline set on assign for {self.name}: {deadline} "
                        f"(policy: {self.sla_policy_id.name})"
                    )
            self.write(write_vals)
            self.message_post(
                body=f"Ticket assigned to {self.assigned_to.name}",
                subject="Ticket Assigned",
            )
        return True

    def action_start_progress(self):
        self.ensure_one()
        self.write({"state": "in_progress"})
        self.message_post(
            body=f"Ticket moved to In Progress by {self.env.user.name}",
            subject="Ticket In Progress",
        )
        return True

    def action_resolve(self):
        self.ensure_one()
        self.write({"state": "resolved", "resolved_date": fields.Datetime.now()})
        if self.customer_id:
            self.message_post(
                body="Your ticket has been resolved. Please review the resolution.",
                subject="Ticket Resolved",
            )
        return True

    def action_close(self):
        self.ensure_one()
        self.write({"state": "closed", "closed_date": fields.Datetime.now()})
        self.message_post(
            body=f"Ticket closed by {self.env.user.name}",
            subject="Ticket Closed",
        )
        return True

    def action_reopen(self):
        self.ensure_one()
        self.write(
            {"state": "in_progress", "resolved_date": False, "closed_date": False}
        )
        self.message_post(
            body=f"Ticket reopened by {self.env.user.name}",
            subject="Ticket Reopened",
        )
        return True

    def action_pending(self):
        self.ensure_one()
        self.write({"state": "pending"})
        if self.customer_id:
            self.message_post(
                body="We need more information from you to proceed with this ticket.",
                subject="Ticket Pending - Action Required",
            )
        return True

    @api.model
    def _cron_check_overdue_tickets(self):
        overdue_tickets = self.search([
            ("state", "not in", ["resolved", "closed"]),
            ("days_open", ">", 7),
            ("overdue_notified", "=", False),
        ])
        for ticket in overdue_tickets:
            if ticket.assigned_to:
                ticket.message_post(
                    body=f"Reminder: This ticket has been open for {ticket.days_open} days.",
                    subject="Overdue Ticket Reminder",
                    partner_ids=[ticket.assigned_to.partner_id.id],
                )
            ticket.sudo().write({"overdue_notified": True})
        return True

    @api.model
    def _cron_check_sla_breaches(self):
        """
        Cron job: notify assigned agents when SLA is at risk or breached.
        Run every hour via a scheduled action.
        """
        now = fields.Datetime.now()

        # ── At-risk tickets (only notify once per deadline window) ───────
        at_risk = self.search([
            ("state", "not in", ["resolved", "closed"]),
            ("sla_deadline", "!=", False),
            ("sla_deadline", ">", now),
            ("sla_warning_sent", "=", False),
        ])
        for ticket in at_risk:
            remaining = (ticket.sla_deadline - now).total_seconds() / 3600
            if remaining <= 2:
                if ticket.assigned_to:
                    ticket.message_post(
                        body=f"⚠️ SLA Warning: Only {remaining:.1f} hours remaining to resolve this ticket.",
                        subject="SLA At Risk",
                        partner_ids=[ticket.assigned_to.partner_id.id],
                    )
                self._create_log(
                    ticket_id=ticket.id,
                    event_type="sla",
                    summary=f"SLA Warning — {remaining:.1f}h Remaining",
                    detail=(
                        f"Ticket is approaching SLA deadline. "
                        f"Resolution required before "
                        f"{ticket.sla_deadline.strftime('%b %d, %I:%M %p')}."
                    ),
                    actor_id=self.env.ref("base.user_root").id,
                )
                ticket.sudo().write({"sla_warning_sent": True})

        # ── Breached tickets (only notify once per breach) ────────────────
        breached = self.search([
            ("state", "not in", ["resolved", "closed"]),
            ("sla_deadline", "<", now),
            ("sla_breach_notified", "=", False),
        ])
        for ticket in breached:
            if ticket.assigned_to:
                ticket.message_post(
                    body=f"🚨 SLA Breached: This ticket passed its deadline on {ticket.sla_deadline}.",
                    subject="SLA Breached",
                    partner_ids=[ticket.assigned_to.partner_id.id],
                )
            self._create_log(
                ticket_id=ticket.id,
                event_type="sla",
                summary="SLA Breached",
                detail=(
                    f"Ticket passed its SLA deadline on "
                    f"{ticket.sla_deadline.strftime('%b %d, %Y at %I:%M %p')}."
                ),
                actor_id=self.env.ref("base.user_root").id,
            )
            ticket.sudo().write({"sla_breach_notified": True})

        return True
