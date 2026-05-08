# controllers/customer_support_project_controller.py
from odoo import http
from odoo.http import request
import logging
import json
from ..services.email_service import EmailService

_logger = logging.getLogger(__name__)


class CustomerSupportProjectController(http.Controller):
    @http.route(
        "/customer_support/admin_dashboard/system_configuration",
        type="http",
        auth="user",
        website=True,
    )
    def system_configuration_page(self, **kwargs):
        """Display the system configuration page"""
        projects = request.env["customer_support.project"].sudo().search(
            [], order="name asc"
        )
        return request.render(
            "customer_support.system_configuration_template",
            {
                "page_name": "system_configuration",
                "projects": projects,
            },
        )

    @http.route(
        "/customer_support/admin_dashboard/projects/create",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def customer_support_create_project(self, **post):
        """Handle project + project configuration form submission"""
        try:
            project_name = (post.get("project_name") or "").strip()
            project_type = (post.get("project_type") or "").strip()
            start_date = (post.get("start_date") or "").strip()

            if not project_name:
                return request.redirect(
                    "/customer_support/admin_dashboard/system_configuration?error=1&error_msg=Project+name+is+required&tab=project"
                )
            if not project_type:
                return request.redirect(
                    "/customer_support/admin_dashboard/system_configuration?error=1&error_msg=Project+type+is+required&tab=project"
                )
            if not start_date:
                return request.redirect(
                    "/customer_support/admin_dashboard/system_configuration?error=1&error_msg=Start+date+is+required&tab=project"
                )

            # Models
            ProjectModel = request.env["customer_support.project"].sudo()
            ConfigModel = request.env["customer_support.project.config"].sudo()

            # Step 1: Create main project
            project = ProjectModel.create(
                {
                    "name": project_name,
                    "code": post.get("project_key"),
                }
            )

            # Step 2: Prepare compliance booleans
            compliance_fields = ["gdpr", "hipaa", "pci_dss", "iso27001"]
            compliance_kwargs = {
                f"compliance_{c}": bool(post.get(f"compliance_{c}"))
                for c in compliance_fields
            }

            # Step 3: Create project configuration
            ConfigModel.create(
                {
                    "project_id": project.id,
                    "project_type": project_type,
                    "start_date": start_date,
                    "end_date": post.get("end_date"),
                    "programming_languages": post.get("programming_languages"),
                    "frameworks": post.get("frameworks"),
                    "databases": post.get("databases"),
                    "project_goals": post.get("project_goals"),
                    **compliance_kwargs,
                }
            )

            _logger.info(f"Project + Config created: {project.name} (ID: {project.id})")

            return request.redirect(
                f"/customer_support/admin_dashboard?tab=system-configuration&project_created=1&project_id={project.id}"
            )

        except Exception as e:
            _logger.error(f"Error creating project configuration: {str(e)}")
            return request.redirect(
                f"/customer_support/admin_dashboard/system_configuration?error=1&error_msg={str(e)}&tab=project"
            )

    @http.route(
        "/customer_support/admin_dashboard/projects/update/<int:project_id>",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def customer_support_update_project(self, project_id, **post):
        """Handle project + config update"""
        try:
            ProjectModel = request.env["customer_support.project"].sudo()
            ConfigModel = request.env["customer_support.project.config"].sudo()

            project = ProjectModel.browse(project_id)
            config = ConfigModel.search([("project_id", "=", project.id)], limit=1)

            if not project.exists():
                return request.redirect(
                    "/customer_support/admin_dashboard/system_configuration?error=1&error_msg=Project not found&tab=project"
                )

            # Update main project
            project.write(
                {
                    "name": post.get("project_name"),
                    "code": post.get("project_key"),
                }
            )

            # Update or create config
            compliance_fields = ["gdpr", "hipaa", "pci_dss", "iso27001"]
            compliance_kwargs = {
                f"compliance_{c}": bool(post.get(f"compliance_{c}"))
                for c in compliance_fields
            }

            config_vals = {
                "project_type": post.get("project_type"),
                "start_date": post.get("start_date"),
                "end_date": post.get("end_date"),
                "programming_languages": post.get("programming_languages"),
                "frameworks": post.get("frameworks"),
                "databases": post.get("databases"),
                "project_goals": post.get("project_goals"),
                **compliance_kwargs,
            }

            if config.exists():
                config.write(config_vals)
            else:
                ConfigModel.create({**config_vals, "project_id": project.id})

            _logger.info(f"Project + Config updated: {project.name} (ID: {project.id})")

            return request.redirect(
                f"/customer_support/admin_dashboard?tab=system-configuration&project_updated=1&project_id={project.id}"
            )

        except Exception as e:
            _logger.error(f"Error updating project configuration: {str(e)}")
            return request.redirect(
                f"/customer_support/admin_dashboard/system_configuration?error=1&error_msg={str(e)}&tab=project"
            )

    @http.route(
        "/customer_support/admin_dashboard/projects/delete/<int:project_id>",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def customer_support_delete_project(self, project_id, **post):
        """Generate closure report then delete the project."""
        try:
            ProjectModel  = request.env["customer_support.project"].sudo()
            ConfigModel   = request.env["customer_support.project.config"].sudo()
            MemberModel   = request.env["customer_support.project.member"].sudo()
            TicketModel   = request.env["customer.support"].sudo()
            TaskModel     = request.env["customer_support.ticket.task"].sudo()
            ReportModel   = request.env["customer_support.project.report"].sudo()

            project = ProjectModel.browse(project_id)
            if not project.exists():
                return request.redirect(
                    "/customer_support/admin_dashboard"
                    "?tab=system-configuration&modal=projects&error=Project not found"
                )

            config  = ConfigModel.search([("project_id", "=", project.id)], limit=1)
            members = MemberModel.search([("project_id", "=", project.id)])
            tickets = TicketModel.search([("project_id", "=", project.id)])

            # ── Tech stack & goals (from config) ──────────────────────
            tech_languages  = config.programming_languages or "" if config else ""
            tech_frameworks = config.frameworks or "" if config else ""
            tech_databases  = config.databases or "" if config else ""
            project_goals   = config.project_goals or "" if config else ""

            compliance_parts = []
            if config:
                if config.compliance_gdpr:    compliance_parts.append("GDPR")
                if config.compliance_hipaa:   compliance_parts.append("HIPAA")
                if config.compliance_pci_dss: compliance_parts.append("PCI-DSS")
                if config.compliance_iso27001: compliance_parts.append("ISO 27001")
            compliance_flags = ", ".join(compliance_parts) if compliance_parts else "None"

            # ── Ticket stats ──────────────────────────────────────────
            total_tickets    = len(tickets)
            resolved_tickets = len(tickets.filtered(lambda t: t.state in ("resolved", "closed")))
            open_at_closure  = tickets.filtered(lambda t: t.state not in ("resolved", "closed"))
            open_tickets     = len(open_at_closure)

            priority_counts = {"low": 0, "medium": 0, "high": 0, "urgent": 0}
            state_counts    = {"new": 0, "assigned": 0, "in_progress": 0,
                               "pending": 0, "resolved": 0, "closed": 0}
            for t in tickets:
                p = (t.priority or "medium").lower()
                if p in priority_counts:
                    priority_counts[p] += 1
                s = t.state or "new"
                if s in state_counts:
                    state_counts[s] += 1

            # Open ticket details (for future follow-up reference)
            open_ticket_details = [
                {
                    "name":     t.name,
                    "subject":  t.subject or "",
                    "priority": (t.priority or "medium").title(),
                    "state":    t.state.replace("_", " ").title() if t.state else "",
                    "customer": t.customer_id.name if t.customer_id else "",
                }
                for t in open_at_closure
            ]

            # Full ticket register — all tickets with complete resolution details
            def _resolved_on(t):
                rd = getattr(t, "resolved_date", None)
                if rd:
                    return rd.strftime("%Y-%m-%d")
                if t.state in ("resolved", "closed") and t.write_date:
                    return t.write_date.strftime("%Y-%m-%d")
                return "-"

            all_ticket_details = [
                {
                    "ticket_id":   t.name,
                    "subject":     t.subject or "",
                    "description": (t.description or "")[:100],
                    "customer":    t.customer_id.name if t.customer_id else "-",
                    "raised_on":   t.create_date.strftime("%Y-%m-%d") if t.create_date else "-",
                    "resolved_on": _resolved_on(t),
                    "solved_by":   t.assigned_to.name if getattr(t, "assigned_to", None) and t.assigned_to else "-",
                    "sla_status":  t.sla_status or "on_track",
                    "priority":    (t.priority or "medium").title(),
                    "state":       t.state.replace("_", " ").title() if t.state else "-",
                }
                for t in tickets
            ]

            # Unique customers
            seen = set()
            customers = []
            for t in tickets:
                if t.customer_id and t.customer_id.id not in seen:
                    seen.add(t.customer_id.id)
                    customers.append({
                        "id":    t.customer_id.id,
                        "name":  t.customer_id.name,
                        "email": t.customer_id.email or "",
                    })

            # Avg resolution hours
            avg_hrs = 0.0
            resolved = tickets.filtered(lambda t: t.state in ("resolved", "closed"))
            if resolved:
                total_secs = sum(
                    (t.write_date - t.create_date).total_seconds()
                    for t in resolved if t.write_date and t.create_date
                )
                avg_hrs = round(total_secs / 3600 / len(resolved), 1)

            sla_met      = len(tickets.filtered(lambda t: t.sla_status == "on_track"))
            sla_breached = len(tickets.filtered(lambda t: t.sla_status == "breached"))

            # ── Task stats ────────────────────────────────────────────
            ticket_ids = tickets.ids
            all_tasks  = (TaskModel.search([("ticket_id", "in", ticket_ids)])
                          if ticket_ids else TaskModel.browse())
            total_tasks = len(all_tasks)
            done_tasks  = len(all_tasks.filtered(lambda t: t.is_done))

            # ── Team ──────────────────────────────────────────────────
            focal = members.filtered(lambda m: m.role == "focal_person")
            focal_name = focal[0].user_id.name if focal and focal[0].user_id else ""
            team_data  = [
                {"name": m.user_id.name if m.user_id else (m.member_name or ""),
                 "role": m.role_label}
                for m in members
            ]

            # ── Persist report ────────────────────────────────────────
            ReportModel.create({
                "project_name":         project.name,
                "project_key":          project.code or "",
                "project_type":         config.project_type.replace("_", " ").title()
                                        if config and config.project_type else "",
                "start_date":           config.start_date if config else False,
                "end_date":             config.end_date if config else False,
                "tech_languages":       tech_languages,
                "tech_frameworks":      tech_frameworks,
                "tech_databases":       tech_databases,
                "project_goals":        project_goals,
                "compliance_flags":     compliance_flags,
                "focal_person":         focal_name,
                "team_members":         json.dumps(team_data),
                "customers":            json.dumps(customers),
                "total_tickets":        total_tickets,
                "resolved_tickets":     resolved_tickets,
                "open_tickets":         open_tickets,
                "avg_resolution_hrs":   avg_hrs,
                "priority_low":         priority_counts["low"],
                "priority_medium":      priority_counts["medium"],
                "priority_high":        priority_counts["high"],
                "priority_urgent":      priority_counts["urgent"],
                "state_breakdown":      json.dumps(state_counts),
                "open_ticket_details":  json.dumps(open_ticket_details),
                "all_ticket_details":   json.dumps(all_ticket_details),
                "sla_met":              sla_met,
                "sla_breached":         sla_breached,
                "total_tasks":          total_tasks,
                "completed_tasks":      done_tasks,
            })

            project_name = project.name
            config.unlink()
            project.unlink()

            _logger.info(f"Project deleted & report generated: {project_name}")

            return request.redirect(
                "/customer_support/admin_dashboard"
                "?tab=system-configuration&project_deleted=1"
            )

        except Exception as e:
            _logger.error(f"Error deleting project: {str(e)}")
            import traceback
            _logger.error(traceback.format_exc())
            return request.redirect(
                "/customer_support/admin_dashboard"
                f"?tab=system-configuration&error={str(e)}"
            )

    @http.route(
        "/customer_support/admin_dashboard/project_reports",
        type="jsonrpc",
        auth="user",
        csrf=False,
    )
    def list_project_reports(self, **kw):
        """Return all project closure reports as JSON."""
        try:
            reports = request.env["customer_support.project.report"].sudo().search([])
            data = []
            for r in reports:
                def _json(field):
                    try:
                        return json.loads(field or "[]")
                    except Exception:
                        return []
                data.append({
                    "id":                   r.id,
                    "project_name":         r.project_name,
                    "project_key":          r.project_key or "",
                    "project_type":         r.project_type or "",
                    "start_date":           r.start_date.strftime("%b %d, %Y") if r.start_date else "-",
                    "end_date":             r.end_date.strftime("%b %d, %Y") if r.end_date else "-",
                    "generated_on":         r.generated_on.strftime("%b %d, %Y %H:%M") if r.generated_on else "",
                    "tech_languages":       r.tech_languages or "",
                    "tech_frameworks":      r.tech_frameworks or "",
                    "tech_databases":       r.tech_databases or "",
                    "project_goals":        r.project_goals or "",
                    "compliance_flags":     r.compliance_flags or "None",
                    "focal_person":         r.focal_person or "-",
                    "team":                 _json(r.team_members),
                    "customers":            _json(r.customers),
                    "total_tickets":        r.total_tickets,
                    "resolved_tickets":     r.resolved_tickets,
                    "open_tickets":         r.open_tickets,
                    "avg_resolution_hrs":   r.avg_resolution_hrs,
                    "priority_low":         r.priority_low,
                    "priority_medium":      r.priority_medium,
                    "priority_high":        r.priority_high,
                    "priority_urgent":      r.priority_urgent,
                    "state_breakdown":      _json(r.state_breakdown) if r.state_breakdown else {},
                    "open_ticket_details":  _json(r.open_ticket_details),
                    "all_ticket_details":   _json(r.all_ticket_details),
                    "sla_met":              r.sla_met,
                    "sla_breached":         r.sla_breached,
                    "total_tasks":          r.total_tasks,
                    "completed_tasks":      r.completed_tasks,
                })
            return {"success": True, "reports": data}
        except Exception as e:
            _logger.error(f"list_project_reports error: {e}")
            return {"success": False, "error": str(e)}

    @http.route(
        "/customer_support/admin_dashboard/projects/get/<int:project_id>",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def customer_support_get_project(self, project_id):
        """Get project + config details (AJAX)"""
        try:
            ProjectModel = request.env["customer_support.project"].sudo()
            ConfigModel = request.env["customer_support.project.config"].sudo()

            project = ProjectModel.browse(project_id)
            config = ConfigModel.search([("project_id", "=", project.id)], limit=1)

            if not project.exists():
                return {"error": "Project not found"}

            # Parse compliance
            compliance = []
            if config.exists():
                for c in ["gdpr", "hipaa", "pci_dss", "iso27001"]:
                    if getattr(config, f"compliance_{c}"):
                        compliance.append(c.upper())

            return {
                "success": True,
                "project": {
                    "id": project.id,
                    "name": project.name,
                    "project_key": project.code,
                    "project_type": config.project_type if config.exists() else "",
                    "goals_objectives": config.project_goals if config.exists() else "",
                    "start_date": (
                        config.start_date.strftime("%Y-%m-%d")
                        if config.exists() and config.start_date
                        else ""
                    ),
                    "end_date": (
                        config.end_date.strftime("%Y-%m-%d")
                        if config.exists() and config.end_date
                        else ""
                    ),
                    "programming_languages": (
                        config.programming_languages if config.exists() else ""
                    ),
                    "frameworks": config.frameworks if config.exists() else "",
                    "databases": config.databases if config.exists() else "",
                    "compliance_standards": compliance,
                },
            }

        except Exception as e:
            _logger.error(f"Error fetching project configuration: {str(e)}")
            return {"error": str(e)}

    # =========================================================================
    # PROJECT MEMBERS — helper
    # =========================================================================

    def _member_dict(self, m):
        name = m.user_id.name if m.user_id else (m.member_name or "")
        email = m.user_id.email if m.user_id else (m.member_email or "")
        initials = "".join(p[0].upper() for p in name.split()[:2]) if name else "?"
        return {
            "id": m.id,
            "user_id": m.user_id.id if m.user_id else False,
            "name": name,
            "email": email,
            "role": m.role,
            "role_label": m.role_label,
            "initials": initials,
        }

    # =========================================================================
    # FOCAL PERSON — load list & assign to project
    # =========================================================================

    @http.route(
        "/customer_support/admin_dashboard/focal_persons",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def get_focal_persons(self, **kw):
        """Return all active internal (focal person) users for the dropdown."""
        try:
            internal_group_id = request.env.ref("base.group_user").id
            system_group_id = request.env.ref("base.group_system").id
            users = (
                request.env["res.users"]
                .sudo()
                .search([
                    ("active", "=", True),
                    ("share", "=", False),
                    ("group_ids", "in", [internal_group_id]),
                    ("group_ids", "not in", [system_group_id]),
                ])
            )
            return {
                "success": True,
                "users": [
                    {
                        "id": u.id,
                        "name": u.name,
                        "email": u.email or "",
                        "initials": "".join(p[0].upper() for p in u.name.split()[:2]),
                    }
                    for u in users
                ],
            }
        except Exception as e:
            _logger.error(f"get_focal_persons error: {e}")
            return {"error": str(e)}

    @http.route(
        "/customer_support/admin_dashboard/projects/<int:project_id>/focal/assign",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def assign_focal_person(self, project_id, **kw):
        """Assign (or replace) the focal person for a project."""
        try:
            user_id = kw.get("user_id")
            if not user_id:
                return {"error": "user_id is required"}

            project = request.env["customer_support.project"].sudo().browse(project_id)
            if not project.exists():
                return {"error": "Project not found"}

            # Remove any existing focal person records for this project
            existing_focal = (
                request.env["customer_support.project.member"]
                .sudo()
                .search([("project_id", "=", project_id), ("role", "=", "focal_person")])
            )
            existing_focal.unlink()

            # Create the new focal person record
            member = request.env["customer_support.project.member"].sudo().create({
                "project_id": project_id,
                "user_id": user_id,
                "role": "focal_person",
            })

            return {"success": True, "member": self._member_dict(member)}
        except Exception as e:
            _logger.error(f"assign_focal_person error: {e}")
            return {"error": str(e)}

    @http.route(
        "/customer_support/admin_dashboard/projects/<int:project_id>/focal/remove",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def remove_focal_person(self, project_id, **kw):
        """Remove the focal person assignment from a project."""
        try:
            existing_focal = (
                request.env["customer_support.project.member"]
                .sudo()
                .search([("project_id", "=", project_id), ("role", "=", "focal_person")])
            )
            existing_focal.unlink()
            return {"success": True}
        except Exception as e:
            _logger.error(f"remove_focal_person error: {e}")
            return {"error": str(e)}

    # =========================================================================
    # TEAM MEMBERS (non-focal, name+email entries)
    # =========================================================================

    @http.route(
        "/customer_support/admin_dashboard/projects/<int:project_id>/members",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def get_project_members(self, project_id, **kw):
        """Return focal person + team members for a project."""
        try:
            members = (
                request.env["customer_support.project.member"]
                .sudo()
                .search([("project_id", "=", project_id)])
            )
            focal = [m for m in members if m.role == "focal_person"]
            team = [m for m in members if m.role != "focal_person"]
            return {
                "success": True,
                "focal": self._member_dict(focal[0]) if focal else None,
                "members": [self._member_dict(m) for m in team],
            }
        except Exception as e:
            _logger.error(f"get_project_members error: {e}")
            return {"error": str(e)}

    @http.route(
        "/customer_support/admin_dashboard/projects/<int:project_id>/members/add",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def add_project_member(self, project_id, **kw):
        """Add a team member (non-focal) by name + email + role."""
        try:
            name = (kw.get("name") or "").strip()
            email = (kw.get("email") or "").strip()
            role = kw.get("role") or "other"

            if not name:
                return {"error": "Name is required"}
            if role == "focal_person":
                return {"error": "Use the focal person section to assign a focal person"}

            project = request.env["customer_support.project"].sudo().browse(project_id)
            if not project.exists():
                return {"error": "Project not found"}

            member = request.env["customer_support.project.member"].sudo().create({
                "project_id": project_id,
                "member_name": name,
                "member_email": email,
                "role": role,
            })

            # Send board invite emails for every active ticket in this project
            if email:
                try:
                    base_url = request.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
                    tickets = request.env["customer.support"].sudo().search([
                        ("project_id", "=", project_id),
                        ("state", "not in", ["closed"]),
                    ])
                    for ticket in tickets:
                        if not ticket.board_token:
                            import secrets
                            ticket.sudo().write({"board_token": secrets.token_urlsafe(32)})
                        board_url = f"{base_url}/board/{ticket.board_token}"
                        sent = EmailService.send_board_invite(name, email, ticket, board_url)
                        if not sent:
                            _logger.warning(
                                "Board invite email was not sent for ticket %s to %s",
                                ticket.id,
                                email,
                            )
                except Exception as mail_err:
                    _logger.warning(f"Board invite email failed: {mail_err}")

            return {"success": True, "member": self._member_dict(member)}
        except Exception as e:
            _logger.error(f"add_project_member error: {e}")
            return {"error": str(e)}

    @http.route(
        "/customer_support/admin_dashboard/projects/members/<int:member_id>/remove",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def remove_project_member(self, member_id, **kw):
        """Remove a team member from a project."""
        try:
            member = (
                request.env["customer_support.project.member"]
                .sudo()
                .browse(member_id)
            )
            if not member.exists():
                return {"error": "Member record not found"}
            member.unlink()
            return {"success": True}
        except Exception as e:
            _logger.error(f"remove_project_member error: {e}")
            return {"error": str(e)}

    @http.route(
        "/customer_support/admin_dashboard/projects/<int:project_id>/documents",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def get_project_documents(self, project_id, **kw):
        """Return documents linked to a project."""
        try:
            if not request.env.user.has_group("base.group_system"):
                return {"error": "Access denied"}
            docs = (
                request.env["dc.knowledge.document"]
                .sudo()
                .search([("project_id", "=", project_id), ("active", "=", True)],
                        order="create_date desc")
            )
            return {
                "success": True,
                "documents": [
                    {
                        "id": d.id,
                        "name": d.name,
                        "filename": d.filename or "",
                        "file_type": d.file_type or "other",
                        "category": d.category or "other",
                        "state": d.state or "pending",
                        "created": d.create_date.strftime("%b %d, %Y") if d.create_date else "",
                    }
                    for d in docs
                ],
            }
        except Exception as e:
            _logger.error(f"get_project_documents error: {e}")
            return {"error": str(e)}

    @http.route(
        "/customer_support/admin_dashboard/documents/<int:doc_id>/delete",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def delete_project_document(self, doc_id, **kw):
        """Delete a knowledge document."""
        try:
            if not request.env.user.has_group("base.group_system"):
                return {"error": "Access denied"}
            doc = request.env["dc.knowledge.document"].sudo().browse(doc_id)
            if not doc.exists():
                return {"error": "Document not found"}
            doc.unlink()
            return {"success": True}
        except Exception as e:
            _logger.error(f"delete_project_document error: {e}")
            return {"error": str(e)}
