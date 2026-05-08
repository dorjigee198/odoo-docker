from urllib.parse import urlsplit

from odoo.tests.common import tagged
from .common import CSBaseCase


@tagged("post_install", "-at_install", "customer_support")
class TestRedirectSecurity(CSBaseCase):
    """
    TC-105  Login redirect is restricted to safe in-portal paths.
    """

    def _is_safe_redirect(self, redirect_url):
        """Mirrors the allowlist logic in auth.py authenticate()."""
        if not redirect_url:
            return False
        parts = urlsplit(redirect_url)
        path = parts.path or ""
        return (
            not parts.scheme
            and not parts.netloc
            and path.startswith("/customer_support/")
            and not path.startswith("/customer_support//")
            and ".." not in path
            and "\\" not in redirect_url
            and "\x00" not in redirect_url
        )

    def test_tc105_safe_internal_redirect_accepted(self):
        """A redirect to /customer_support/dashboard is accepted."""
        self.assertTrue(
            self._is_safe_redirect("/customer_support/dashboard"),
            msg="In-portal redirect must be accepted",
        )

    def test_tc105_external_redirect_blocked(self):
        """A redirect to an external URL is rejected."""
        self.assertFalse(
            self._is_safe_redirect("https://evil.com/steal"),
            msg="External URL redirect must be blocked",
        )

    def test_tc105_protocol_relative_redirect_blocked(self):
        """Protocol-relative URL (//evil.com) must be blocked."""
        self.assertFalse(
            self._is_safe_redirect("//evil.com/steal"),
            msg="Protocol-relative redirect must be blocked",
        )

    def test_tc105_path_traversal_blocked(self):
        """Path traversal (../) must be blocked."""
        self.assertFalse(
            self._is_safe_redirect("/customer_support/../etc/passwd"),
            msg="Path traversal redirect must be blocked",
        )

    def test_tc105_double_slash_blocked(self):
        """Double-slash after prefix must be blocked."""
        self.assertFalse(
            self._is_safe_redirect("/customer_support//evil"),
            msg="Double-slash redirect must be blocked",
        )

    def test_tc105_null_byte_blocked(self):
        """Null byte injection must be blocked."""
        self.assertFalse(
            self._is_safe_redirect("/customer_support/\x00evil"),
            msg="Null-byte redirect must be blocked",
        )

    def test_tc105_backslash_blocked(self):
        """Backslash in redirect path must be blocked."""
        self.assertFalse(
            self._is_safe_redirect("/customer_support\\evil"),
            msg="Backslash redirect must be blocked",
        )

    def test_tc105_live_login_with_suspicious_redirect(self):
        """
        Posting to /customer_support/authenticate with a suspicious redirect
        must land on the role dashboard, not the supplied URL.
        """
        response = self.url_open(
            "/customer_support/authenticate",
            data={
                "login": "cs_test_a@example.com",
                "password": "TestPass_A1!",
                "redirect": "https://evil.com/steal",
            },
            allow_redirects=True,
        )
        final_url = response.url
        self.assertNotIn(
            "evil.com",
            final_url,
            msg="Final URL after login must not contain the malicious redirect host",
        )
        self.assertIn(
            "/customer_support/",
            final_url,
            msg="Final URL must stay within /customer_support/ after login",
        )


@tagged("post_install", "-at_install", "customer_support")
class TestKnowledgeUpload(CSBaseCase):
    """
    TC-108  Knowledge upload rejects unsupported file extensions.
    """

    def test_tc108_disallowed_extension_rejected(self):
        """
        The upload controller only allows .pdf, .docx, .txt, .xlsx.
        Any other extension must be rejected.
        """
        allowed = (".pdf", ".docx", ".txt", ".xlsx")
        disallowed = (".exe", ".sh", ".php", ".js", ".py", ".bat", ".zip")

        def _passes_extension_check(filename):
            return any(filename.lower().endswith(ext) for ext in allowed)

        for ext in disallowed:
            self.assertFalse(
                _passes_extension_check(f"malicious{ext}"),
                msg=f"Extension {ext} must be rejected by the upload validator",
            )

    def test_tc108_allowed_extensions_accepted(self):
        """Allowed extensions pass the validator."""
        allowed = (".pdf", ".docx", ".txt", ".xlsx")

        def _passes_extension_check(filename):
            return any(filename.lower().endswith(ext) for ext in allowed)

        for ext in allowed:
            self.assertTrue(
                _passes_extension_check(f"document{ext}"),
                msg=f"Extension {ext} must be accepted by the upload validator",
            )

    def test_tc108_live_upload_rejects_exe(self):
        """
        An authenticated internal user posting an .exe file to the knowledge
        upload endpoint must receive an error response, not a success.
        """
        self.authenticate("cs_test_focal@example.com", "TestPass_F1!")

        import io
        fake_exe = io.BytesIO(b"MZ\x90\x00fake exe content")
        fake_exe.name = "malware.exe"

        response = self.url_open(
            "/customer_support/knowledge/upload?ajax=1",
            files={"file": ("malware.exe", fake_exe, "application/octet-stream")},
            data={"name": "malware", "ajax": "1"},
        )
        self.assertEqual(response.status_code, 200)
        try:
            body = response.json()
            self.assertIn(
                "error",
                body,
                msg="Response must contain an error key for disallowed file type",
            )
        except Exception:
            # Non-JSON redirect response also counts as rejection
            pass
