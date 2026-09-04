"""Compact reviewed manifest for the final 45 HU-5 identity actions."""

from __future__ import annotations

from datetime import date
from typing import Any

from fdre.research.historical_universe_identity_adjudication import (
    CorrectionSpec,
    IdentityAdjudicationDecision,
    IdentityEvidence,
    InsertSpec,
    build_reviewed_identity_plan,
)


def _e(authority: str, source_url: str, assertion: str) -> IdentityEvidence:
    return IdentityEvidence(
        authority=authority,
        source_url=source_url,
        assertion=assertion,
    )


VERIFY_IDENTITY_IDS = (
    56,
    75,
    93,
    107,
    110,
    112,
    113,
    119,
    229,
    246,
    265,
    288,
    336,
    353,
    373,
    1006,
    1019,
    1032,
    1038,
    1067,
    1068,
    1094,
    1095,
    1118,
    1131,
    1139,
    1159,
    1202,
    1299,
    1331,
    1357,
    1407,
    1423,
    1437,
    1465,
    1469,
    1471,
)

# These current-snapshot rows are supported by an exact, adjacent, already-verified
# same-security/same-CIK identity carrying the same symbol. They are intentionally not
# downgraded merely because the bounded residual SEC crawl found no TradingSymbol fact.
CONTINUITY_VERIFY_IDS = frozenset(
    {
        56,
        93,
        107,
        110,
        113,
        119,
        229,
        246,
        265,
        288,
        336,
        353,
        1357,
    }
)

AUTHORITATIVE_VERIFY_EVIDENCE = {
    1038: (
        _e(
            "sec",
            "https://www.sec.gov/Archives/edgar/data/50104/000005010418000054/andv201710-k.htm",
            "Andeavor's 2017 Form 10-K states that the issuer changed its name from "
            "Tesoro effective 2017-08-01 and that its common stock traded on the NYSE "
            "as ANDV, covering the asserted identity interval.",
        ),
    ),
    1068: (
        _e(
            "sec",
            "https://www.sec.gov/Archives/edgar/data/96223/000119312518172047/d578190d8k.htm",
            "Jefferies' 2018 Form 8-K states that Leucadia became Jefferies Financial "
            "Group and would trade on the NYSE as JEF beginning 2018-05-24, before "
            "the asserted identity interval.",
        ),
    ),
    1202: (
        _e(
            "sec",
            "https://www.sec.gov/Archives/edgar/data/906107/000114036126033377/ef20080318_8k.htm",
            "Vivmark Residential's Form 8-K states that the same common shares would "
            "continue trading on the NYSE as VMRK beginning 2026-08-18.",
        ),
        _e(
            "sp_dji",
            "https://www.prnewswire.com/news-releases/reddit-set-to-join-sp-500-and-sun-communities-to-join-sp-midcap-400-302851432.html",
            "S&P DJI states that S&P 500 constituent Equity Residential's post-merger "
            "company would be renamed Vivmark Residential, trade as VMRK, and remain "
            "in the S&P 500.",
        ),
    ),
}

CORRECTION_SPECS = (
    CorrectionSpec(
        identity_id=399,
        target_from=None,
        target_to=date(2026, 6, 24),
        sec_status="sec_symbol_conflict",
        evidence=(
            _e(
                "issuer",
                "https://ir.echostar.com/news-releases/news-release-details/echostar-changing-stocker-ticker-sats-echo-marking-companys-next",
                "EchoStar states that its common stock would change from SATS to ECHO "
                "effective 2026-06-24 and that the common-stock CUSIP was unchanged.",
            ),
        ),
        reason=(
            "End SATS exactly when EchoStar's unchanged common stock began trading as "
            "ECHO; the frozen 2026-08-03 SEC filing reporting ECHO is a real successor "
            "symbol, not an issuer conflict."
        ),
    ),
    CorrectionSpec(
        identity_id=1164,
        target_from=date(2021, 10, 4),
        target_to="preserve",
        sec_status="sec_supported",
        evidence=(
            _e(
                "sec",
                "https://www.sec.gov/Archives/edgar/data/858470/000110465921122041/tm2129019d1_ex99-1.htm",
                "Coterra states that Cabot completed the merger and CTRA would begin "
                "NYSE trading at the open on Monday 2021-10-04.",
            ),
        ),
        reason=(
            "Move CTRA from Sunday 2021-10-03 to its issuer-confirmed first trading "
            "date, preserving COG through the intervening calendar day."
        ),
    ),
    CorrectionSpec(
        identity_id=1170,
        target_from=date(2011, 5, 20),
        target_to=date(2017, 8, 30),
        evidence=(
            _e(
                "sec",
                "https://www.sec.gov/Archives/edgar/data/865436/000086543612000033/wfm10k2012.htm",
                "Whole Foods states that its common-stock ticker changed from WFMI to "
                "WFM effective 2011-05-06, establishing continuity across the "
                "source-created 2011-05-20 through 2011-05-25 identity gap.",
            ),
        ),
        reason=(
            "Extend verified WFM identity 1170 backward to the verified membership "
            "boundary."
        ),
    ),
    CorrectionSpec(
        identity_id=1325,
        target_from=date(2011, 6, 2),
        target_to=date(2012, 10, 3),
        evidence=(
            _e(
                "sp_dji",
                "https://www.prnewswire.com/news-releases/standard--poors-announces-changes-to-us-indices-122534888.html",
                "Standard & Poor's announced Alpha Natural Resources would replace "
                "Massey after the 2011-06-01 close, making 2011-06-02 the first "
                "active S&P session.",
            ),
        ),
        reason="Extend verified ANR identity 1325 to the exact first S&P active session.",
    ),
    CorrectionSpec(
        identity_id=1401,
        target_from=date(2012, 1, 2),
        target_to=date(2014, 3, 24),
        evidence=(
            _e(
                "sp_dji",
                "https://press.spglobal.com/2014-03-14-Biogen-Idec-Set-to-Join-the-S-P-100-Keurig-Green-Mountain-to-Join-the-S-P-500-Changes-to-the-S-P-MidCap-400-and-the-S-P-SmallCap-600",
                "S&P DJI deleted WPX after the 2014-03-21 close, so the verified WPX "
                "identity remains valid through the weekend up to the exclusive "
                "2014-03-24 boundary.",
            ),
        ),
        reason="Extend verified WPX identity 1401 through the source-created weekend gap.",
    ),
)

INSERT_SPECS = (
    InsertSpec(
        case_id="insert-spgi-2016-04-28",
        security_id=778,
        cik="0000064040",
        symbol="SPGI",
        target_from=date(2016, 4, 28),
        target_to=date(2016, 5, 3),
        name="S&P Global Inc.",
        exchange="NYSE",
        evidence=(
            _e(
                "issuer",
                "https://press.spglobal.com/2016-04-27-McGraw-Hill-Financial-Changes-Name-to-S-P-Global-Inc",
                "S&P Global states that the same company's shares began NYSE trading "
                "as SPGI on 2016-04-28.",
            ),
        ),
        reason="Fill the exact MHFI-to-successor-security identity gap with SPGI.",
    ),
    InsertSpec(
        case_id="insert-cog-2021-10-03",
        security_id=846,
        cik="0000858470",
        symbol="COG",
        target_from=date(2021, 10, 3),
        target_to=date(2021, 10, 4),
        name="Cabot Oil & Gas Corporation",
        exchange="NYSE",
        evidence=(
            _e(
                "sec",
                "https://www.sec.gov/Archives/edgar/data/858470/000110465921122041/tm2129019d1_ex99-1.htm",
                "Cabot states that its name changed to Coterra and CTRA began trading "
                "at the 2021-10-04 open, leaving COG as the prior symbol through "
                "Sunday 2021-10-03.",
            ),
        ),
        reason="Bridge the calendar-day identity interval before CTRA began trading.",
    ),
    InsertSpec(
        case_id="insert-echo-2026-06-24",
        security_id=399,
        cik="0001415404",
        symbol="ECHO",
        target_from=date(2026, 6, 24),
        target_to=None,
        name="EchoStar Corporation",
        exchange="Nasdaq",
        evidence=(
            _e(
                "issuer",
                "https://ir.echostar.com/news-releases/news-release-details/echostar-changing-stocker-ticker-sats-echo-marking-companys-next",
                "EchoStar states that its unchanged common stock began Nasdaq trading "
                "as ECHO on 2026-06-24.",
            ),
        ),
        reason="Insert ECHO as the exact same-security successor to SATS.",
    ),
)


def build_hu5_identity_adjudication_cases(
    *,
    topology: dict[str, Any],
    residual_sec: dict[str, Any],
) -> tuple[IdentityAdjudicationDecision, ...]:
    return build_reviewed_identity_plan(
        topology=topology,
        residual_sec=residual_sec,
        verify_identity_ids=VERIFY_IDENTITY_IDS,
        continuity_verify_ids=CONTINUITY_VERIFY_IDS,
        authoritative_verify_evidence=AUTHORITATIVE_VERIFY_EVIDENCE,
        correction_specs=CORRECTION_SPECS,
        insert_specs=INSERT_SPECS,
    )
