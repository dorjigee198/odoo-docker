from odoo.tests.common import HttpCase


class CSBaseCase(HttpCase):
    """Shared test data for all customer_support test cases."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        portal_group = cls.env.ref("base.group_portal")

        # Portal user A — ticket owner
        cls.user_a = cls.env["res.users"].sudo().with_context(no_reset_password=True).create({
            "name": "CS Test Customer A",
            "login": "cs_test_a@example.com",
            "email": "cs_test_a@example.com",
            "password": "TestPass_A1!",
            "groups_id": [(6, 0, [portal_group.id])],
        })
        cls.partner_a = cls.user_a.partner_id

        # Portal user B — different customer, must not see A's ticket
        cls.user_b = cls.env["res.users"].sudo().with_context(no_reset_password=True).create({
            "name": "CS Test Customer B",
            "login": "cs_test_b@example.com",
            "email": "cs_test_b@example.com",
            "password": "TestPass_B1!",
            "groups_id": [(6, 0, [portal_group.id])],
        })
        cls.partner_b = cls.user_b.partner_id

        # Internal (focal) user
        internal_group = cls.env.ref("base.group_user")
        cls.focal_user = cls.env["res.users"].sudo().with_context(no_reset_password=True).create({
            "name": "CS Test Focal",
            "login": "cs_test_focal@example.com",
            "email": "cs_test_focal@example.com",
            "password": "TestPass_F1!",
            "groups_id": [(6, 0, [internal_group.id])],
        })

        # Ticket owned by user_a
        cls.ticket_a = cls.env["customer.support"].sudo().create({
            "subject": "CI Test Ticket — Customer A",
            "description": "Created by automated CI test suite.",
            "customer_id": cls.partner_a.id,
        })
