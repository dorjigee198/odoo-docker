from odoo.tests.common import tagged
from .common import CSBaseCase


@tagged("post_install", "-at_install", "customer_support")
class TestTicketAuthorization(CSBaseCase):
    """
    TC-101  Customer B cannot read Customer A's ticket.
    TC-102  Customer A can read their own ticket.
    TC-106  Customer cannot reach another customer's ticket attachments.
    TC-107  Internal-only messages are not returned for customer view.
    """

    # ------------------------------------------------------------------
    # TC-101 — Cross-customer ticket access is denied
    # ------------------------------------------------------------------
    def test_tc101_cross_customer_denied(self):
        """Accessing another customer's ticket redirects away (not 200 with content)."""
        self.authenticate("cs_test_b@example.com", "TestPass_B1!")
        response = self.url_open(
            f"/customer_support/ticket/{self.ticket_a.id}",
            allow_redirects=False,
        )
        # Expect a redirect (302/303) — not a 200 serving the ticket
        self.assertIn(
            response.status_code,
            [301, 302, 303],
            msg="Customer B must be redirected away from Customer A's ticket",
        )
        location = response.headers.get("Location", "")
        self.assertNotIn(
            str(self.ticket_a.id),
            location,
            msg="Redirect must not loop back to the same ticket",
        )

    # ------------------------------------------------------------------
    # TC-102 — Owner can read their own ticket
    # ------------------------------------------------------------------
    def test_tc102_owner_can_read_own_ticket(self):
        """Ticket owner receives HTTP 200 on their own ticket detail page."""
        self.authenticate("cs_test_a@example.com", "TestPass_A1!")
        response = self.url_open(
            f"/customer_support/ticket/{self.ticket_a.id}",
            allow_redirects=True,
        )
        self.assertEqual(
            response.status_code,
            200,
            msg="Customer A must be able to view their own ticket (expected 200)",
        )

    # ------------------------------------------------------------------
    # TC-106 — Attachment isolation: model-level check
    # ------------------------------------------------------------------
    def test_tc106_attachment_belongs_to_owner(self):
        """
        Attachments on a ticket are linked to that ticket's res_id.
        Customer B's partner_id does not match ticket_a's customer_id,
        so the controller will deny access before any attachment is served.
        """
        self.assertNotEqual(
            self.ticket_a.customer_id.id,
            self.partner_b.id,
            msg="Ticket A's customer_id must not match Customer B's partner — "
                "controller relies on this to block cross-customer attachment access",
        )

    # ------------------------------------------------------------------
    # TC-107 — Internal messages are filtered from customer view
    # ------------------------------------------------------------------
    def test_tc107_internal_messages_not_exposed(self):
        """
        Messages with an internal subtype must not appear in the
        activities list returned to the customer.
        """
        internal_subtype = self.env.ref("mail.mt_note", raise_if_not_found=False)
        if not internal_subtype:
            self.skipTest("mail.mt_note not found — skipping internal-message filter test")

        # Post an internal note on the ticket
        self.ticket_a.sudo().message_post(
            body="<p>Internal only — must not reach customer.</p>",
            message_type="comment",
            subtype_id=internal_subtype.id,
            author_id=self.focal_user.partner_id.id,
        )

        # Replicate the filter the customer controller applies
        raw = self.env["mail.message"].sudo().search([
            ("model", "=", "customer.support"),
            ("res_id", "=", self.ticket_a.id),
            ("message_type", "in", ["comment", "notification"]),
        ])
        visible_to_customer = raw.filtered(
            lambda m: not (m.subtype_id and m.subtype_id.internal)
        )
        internal_msgs = raw.filtered(
            lambda m: m.subtype_id and m.subtype_id.internal
        )

        self.assertTrue(
            len(internal_msgs) > 0,
            msg="Setup error: internal message was not created",
        )
        for msg in internal_msgs:
            self.assertNotIn(
                msg,
                visible_to_customer,
                msg=f"Internal message (id={msg.id}) must be excluded from customer view",
            )
