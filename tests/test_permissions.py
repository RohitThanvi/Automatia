from security.permissions import RiskTier, requires_confirmation, risk_of


def test_known_low_risk_tool():
    assert risk_of("open_application") == RiskTier.LOW


def test_known_high_risk_tool():
    assert risk_of("delete_file") == RiskTier.HIGH


def test_unknown_tool_defaults_high():
    assert risk_of("some_made_up_tool") == RiskTier.HIGH


def test_low_risk_auto_approved():
    assert requires_confirmation("open_application", auto_approve_low_risk=True) is False


def test_low_risk_confirmation_forced_when_disabled():
    assert requires_confirmation("open_application", auto_approve_low_risk=False) is True


def test_medium_and_high_always_confirm():
    assert requires_confirmation("close_application", auto_approve_low_risk=True) is True
    assert requires_confirmation("delete_file", auto_approve_low_risk=True) is True
