"""Regression tests for _infer_domain word-boundary and telecom domain fixes."""

from builder.workbench import _infer_domain


PHONE_BILLING_DOMAIN = "Phone Billing Support"


class TestInferDomainWordBoundary:
    """The old code matched 'it ' as a substring, catching phrases like 'it should'."""

    def test_it_helpdesk_explicit(self):
        assert _infer_domain("Build an IT support chatbot") == "IT Helpdesk"

    def test_it_helpdesk_vpn(self):
        assert _infer_domain("Agent for VPN troubleshooting") == "IT Helpdesk"

    def test_it_helpdesk_password(self):
        assert _infer_domain("Help users reset their password") == "IT Helpdesk"

    def test_it_should_not_match_helpdesk(self):
        """Regression: 'it should help explain' must not trigger IT Helpdesk."""
        brief = "Build an agent. It should help explain billing charges."
        assert _infer_domain(brief) != "IT Helpdesk"

    def test_it_in_sentence_not_helpdesk(self):
        brief = "The agent should do it well and help customers."
        assert _infer_domain(brief) != "IT Helpdesk"


class TestInferDomainTelecom:
    """New telecom/billing domain patterns."""

    def test_billing_keyword(self):
        assert _infer_domain("Build a billing support agent") == PHONE_BILLING_DOMAIN

    def test_phone_company(self):
        assert _infer_domain("Verizon-like phone company agent") == PHONE_BILLING_DOMAIN

    def test_telecom(self):
        assert _infer_domain("Telecom customer support bot") == PHONE_BILLING_DOMAIN

    def test_monthly_bill(self):
        assert _infer_domain("Help customers understand their monthly bill") == PHONE_BILLING_DOMAIN

    def test_charges(self):
        assert _infer_domain("Explain charges on a wireless bill") == PHONE_BILLING_DOMAIN

    def test_wireless(self):
        assert _infer_domain("Wireless plan comparison agent") == PHONE_BILLING_DOMAIN

    def test_mobile_plan(self):
        assert _infer_domain("Help with mobile plan selection") == PHONE_BILLING_DOMAIN


class TestInferDomainExistingDomains:
    """Existing domains still work correctly."""

    def test_airline(self):
        assert _infer_domain("Build a flight booking agent") == "Airline Support"

    def test_refund(self):
        assert _infer_domain("Handle refund requests") == "Refund Support"

    def test_sales(self):
        assert _infer_domain("Build a sales qualification bot") == "Sales Qualification"

    def test_healthcare(self):
        assert _infer_domain("Patient intake workflow") == "Healthcare Intake"

    def test_mna(self):
        assert _infer_domain("M&A deal analysis agent") == "M&A Analyst"

    def test_generic(self):
        assert _infer_domain("Build a general purpose assistant") == "Agent"
