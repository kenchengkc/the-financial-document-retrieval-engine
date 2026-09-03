"""Reviewed authoritative evidence manifest for the final HU-5 membership blockers."""

from __future__ import annotations

from datetime import date

from fdre.research.historical_universe_membership_adjudication import (
    EvidenceAuthority,
    IdentityRequirement,
    MembershipAdjudicationCase,
    MembershipAdjudicationEvidence,
    SiblingMembershipRequirement,
    SiblingRole,
)


def _e(
    authority: EvidenceAuthority,
    source_url: str,
    assertion: str,
) -> MembershipAdjudicationEvidence:
    return MembershipAdjudicationEvidence(
        authority=authority,
        source_url=source_url,
        assertion=assertion,
    )


def _identity(
    symbol: str,
    effective_from: str,
    effective_to: str | None,
    verification_status: str,
    source_hash: str,
) -> IdentityRequirement:
    return IdentityRequirement(
        symbol=symbol,
        effective_from=date.fromisoformat(effective_from),
        effective_to=date.fromisoformat(effective_to) if effective_to else None,
        verification_status=verification_status,
        source_hash=source_hash,
    )


def _sibling(
    role: SiblingRole,
    membership_id: int,
    security_id: int,
    cik: str,
    effective_from: str,
    effective_to: str | None,
    source_hash: str,
) -> SiblingMembershipRequirement:
    return SiblingMembershipRequirement(
        role=role,
        membership_id=membership_id,
        security_id=security_id,
        cik=cik,
        effective_from=date.fromisoformat(effective_from),
        effective_to=date.fromisoformat(effective_to) if effective_to else None,
        source_hash=source_hash,
    )


HU5_MEMBERSHIP_ADJUDICATION_CASES: tuple[MembershipAdjudicationCase, ...] = (
    MembershipAdjudicationCase(
        membership_id=863,
        security_id=933,
        cik="0001408198",
        prior_effective_from=date(2010, 1, 22),
        prior_effective_to=date(2010, 7, 12),
        prior_source_hash="2ca28694eb4cde9d4bebc04c90b7fca4d519878377734cffdbe8f0693d31942b",
        identity=_identity(
            "MXB",
            "2010-01-22",
            "2010-07-13",
            "verified",
            "0351e0b7b7c61d2cdca2007b8645fc4426c6b730caced8b78a369dc9165ed8d9",
        ),
        action="reject",
        target_effective_from=date(2010, 1, 22),
        target_effective_to=date(2010, 7, 12),
        evidence=(
            _e(
                "sp_dji",
                "https://press.spglobal.com/2018-03-28-MSCI-Set-to-Join-S-P-500-Lumentum-Holdings-to-Join-S-P-MidCap-400-C-J-Energy-Services-to-Join-S-P-SmallCap-600",
                "S&P DJI identifies MSCI as an S&P MidCap 400 constituent immediately before its first S&P 500 addition on 2018-04-04.",
            ),
        ),
        siblings=(),
        reason=(
            "MSCI's authoritative index history places the issuer outside the S&P 500 in 2010; "
            "the MXB row is not an S&P 500 membership interval."
        ),
    ),
    MembershipAdjudicationCase(
        membership_id=668,
        security_id=849,
        cik="0000865436",
        prior_effective_from=date(2011, 5, 25),
        prior_effective_to=date(2017, 8, 29),
        prior_source_hash="661a999abf192f2953e2703c4c202fdbf92e2aef8a40b7db2d1ba8028f42590d",
        identity=_identity(
            "WFM",
            "2011-05-25",
            "2017-08-30",
            "verified",
            "9f484fceebef42039220c27ff448274e5fdd025b755f743ab3d98df483da5ab4",
        ),
        action="correct_and_verify",
        target_effective_from=date(2011, 5, 20),
        target_effective_to=date(2017, 8, 29),
        evidence=(
            _e(
                "sec",
                "https://www.sec.gov/Archives/edgar/data/865436/000086543612000033/wfm10k2012.htm",
                "Whole Foods states that its common-stock ticker changed from WFMI to WFM effective 2011-05-06, proving issuer/security continuity across the source split.",
            ),
            _e(
                "sp_dji",
                "https://press.spglobal.com/2017-08-24-Charter-Communications-Set-to-Join-S-P-100-Quintiles-IMS-Holdings-and-SBA-Communications-to-Join-S-P-500",
                "S&P DJI removes Whole Foods from the S&P 500 prior to the 2017-08-29 open.",
            ),
        ),
        siblings=(
            _sibling(
                "predecessor",
                295,
                641,
                "0000865436",
                "2009-12-30",
                "2011-05-20",
                "c24ee2ddb19135be270e9f0ff84527069668b43de90e30cd9688e8fccf8cb80d",
            ),
        ),
        reason=(
            "The verified WFMI predecessor and SEC ticker-change evidence establish continuous "
            "Whole Foods membership; stitch this split row to the predecessor boundary and keep "
            "the independently confirmed 2017-08-29 removal."
        ),
    ),
    MembershipAdjudicationCase(
        membership_id=823,
        security_id=917,
        cik="0001301063",
        prior_effective_from=date(2011, 6, 9),
        prior_effective_to=date(2012, 10, 2),
        prior_source_hash="91c558bd38fd0d3b34c546723c3415ef252548de746a521df0a0ec56d68252ab",
        identity=_identity(
            "ANR",
            "2011-06-09",
            "2012-10-03",
            "verified",
            "17eb7ed6790ab866193106ff0231fa74d4fc1fa19914573525057a4d969bbe19",
        ),
        action="correct_and_verify",
        target_effective_from=date(2011, 6, 2),
        target_effective_to=date(2012, 10, 2),
        evidence=(
            _e(
                "sp_dji",
                "https://www.prnewswire.com/news-releases/standard--poors-announces-changes-to-us-indices-122534888.html",
                "Standard & Poor's announced Alpha Natural Resources would replace Massey after the 2011-06-01 close, making 2011-06-02 the first active trading session.",
            ),
            _e(
                "sp_dji",
                "https://press.spglobal.com/2012-09-25-Kraft-Foods-Group-Set-to-Join-the-S-P-500-Alpha-Natural-Resources-InterDigital-Genesee-Wyoming-to-Join-the-S-P-MidCap-400-and-Korn-Ferry-to-Join-the-S-P-SmallCap-600",
                "S&P DJI moved Alpha Natural Resources from the S&P 500 to the S&P MidCap 400 after the 2012-10-01 close, so the exclusive end is 2012-10-02.",
            ),
        ),
        siblings=(),
        reason="Authoritative S&P add/remove events establish the exact trading-session interval.",
    ),
    MembershipAdjudicationCase(
        membership_id=899,
        security_id=948,
        cik="0001518832",
        prior_effective_from=date(2012, 1, 2),
        prior_effective_to=date(2014, 3, 21),
        prior_source_hash="a64a653acdfb4dff11acdeaec8c0cf5021880317350283042668c8dccdf0919c",
        identity=_identity(
            "WPX",
            "2012-01-02",
            "2014-03-22",
            "verified",
            "d6201b8191e6f80327503292ce0516f9a7ef786a5cb338adf0f3a14e79ca8d2d",
        ),
        action="correct_and_verify",
        target_effective_from=date(2012, 1, 3),
        target_effective_to=date(2014, 3, 24),
        evidence=(
            _e(
                "sp_dji",
                "https://www.prnewswire.com/news-releases/sp-indices-announces-changes-to-us-indices-136108648.html",
                "S&P announced WPX would enter after the 2011-12-30 close; the next U.S. trading session after the weekend and New Year's holiday was 2012-01-03.",
            ),
            _e(
                "sp_dji",
                "https://press.spglobal.com/2014-03-14-Biogen-Idec-Set-to-Join-the-S-P-100-Keurig-Green-Mountain-to-Join-the-S-P-500-Changes-to-the-S-P-MidCap-400-and-the-S-P-SmallCap-600",
                "S&P DJI deleted WPX after the 2014-03-21 close, making 2014-03-24 the first session outside the S&P 500.",
            ),
        ),
        siblings=(),
        reason="Authoritative after-close events establish the next-trading-session membership bounds.",
    ),
    MembershipAdjudicationCase(
        membership_id=685,
        security_id=858,
        cik="0000884629",
        prior_effective_from=date(2013, 1, 24),
        prior_effective_to=date(2015, 6, 15),
        prior_source_hash="61d7b7d015047fefe27173aedc3a9b91725ddee85569abb4f4ad897c9fedaf82",
        identity=_identity(
            "ACT",
            "2013-01-24",
            "2015-06-16",
            "verified",
            "b19cfada3a05e3741a3572fe302630a0ec7aa42a7694416a263edad3f1921e0b",
        ),
        action="verify",
        target_effective_from=date(2013, 1, 24),
        target_effective_to=date(2015, 6, 15),
        evidence=(
            _e(
                "sec",
                "https://www.sec.gov/Archives/edgar/data/884629/000119312513082059/d448020d10k.htm",
                "Actavis states Watson changed its corporate name and ticker from WPI to ACT after the 2013-01-23 close.",
            ),
            _e(
                "sec",
                "https://www.sec.gov/Archives/edgar/data/1578845/000156459016027705/agn-10q_20160930.htm",
                "Allergan states ACT traded until the 2015-06-15 opening, when the same issuer changed its ticker to AGN.",
            ),
        ),
        siblings=(
            _sibling(
                "predecessor",
                308,
                646,
                "0000884629",
                "2009-12-30",
                "2013-01-24",
                "6546fb3f9a0b0927cb1d7ab82d6f3605f7c8ac1c1cd45969180652659c889bad",
            ),
        ),
        reason="SEC issuer continuity and the verified WPI predecessor corroborate the existing membership bounds.",
    ),
    MembershipAdjudicationCase(
        membership_id=543,
        security_id=778,
        cik="0000064040",
        prior_effective_from=date(2013, 5, 15),
        prior_effective_to=date(2016, 4, 27),
        prior_source_hash="156155aaa1f9eb36bfbb81d1d99d0e3571efbd29a9d794edc002e84e5612390a",
        identity=_identity(
            "MHFI",
            "2013-05-15",
            "2016-04-28",
            "verified",
            "db44097750c2f8617bbc2195d243a0d113975b9b1dadc77b29f7700b9710944b",
        ),
        action="correct_and_verify",
        target_effective_from=date(2013, 5, 15),
        target_effective_to=date(2016, 5, 3),
        evidence=(
            _e(
                "issuer",
                "https://press.spglobal.com/2013-05-14-McGraw-Hill-Financial-to-Begin-NYSE-Trading-Under-New-MHFI-Stock-Symbol-on-Tuesday-May-14-at-the-Opening-Bell",
                "McGraw Hill Financial states MHP and MHFI are the same common stock with an unchanged CUSIP.",
            ),
            _e(
                "issuer",
                "https://press.spglobal.com/2016-04-27-McGraw-Hill-Financial-Changes-Name-to-S-P-Global-Inc",
                "S&P Global states the same company's shares begin trading as SPGI on 2016-04-28.",
            ),
        ),
        siblings=(
            _sibling(
                "predecessor",
                110,
                546,
                "0000064040",
                "2009-12-30",
                "2013-05-15",
                "fe9f4d334e9ee267c259b5c5a838aa8296131892df7f7824d9754df587f75f5b",
            ),
            _sibling(
                "successor",
                544,
                413,
                "0000064040",
                "2016-05-03",
                None,
                "b146c4bfec581932363e659c2a38bf87cc672aa6bb780d800d40de5462000f46",
            ),
        ),
        reason=(
            "Issuer evidence proves the MHP/MHFI/SPGI ticker sequence is one security; stitch this "
            "membership split exactly between its verified predecessor and successor."
        ),
    ),
    MembershipAdjudicationCase(
        membership_id=837,
        security_id=923,
        cik="0001336920",
        prior_effective_from=date(2013, 10, 8),
        prior_effective_to=date(2013, 11, 3),
        prior_source_hash="988aa704fc76af23e13d6907322f74ac9818e800145ea60fb0fb6c892ecb2dbc",
        identity=_identity(
            "SAIC",
            "2013-10-08",
            "2013-11-04",
            "verified",
            "906234b46f68ffe33d3823d05557bce3b6b92335f55dc333a50a50fc06c52519",
        ),
        action="reject",
        target_effective_from=date(2013, 10, 8),
        target_effective_to=date(2013, 11, 3),
        evidence=(
            _e(
                "sp_dji",
                "https://press.spglobal.com/2013-09-11-Vertex-Ametek-Set-to-Join-the-S-P-500-Advanced-Micro-Devices-SAIC-to-Join-S-P-MidCap-400-Capstead-to-Join-S-P-SmallCap-600",
                "S&P DJI moved legacy SAIC (SAI) out of the S&P 500 and into the S&P MidCap 400 after the 2013-09-20 close.",
            ),
            _e(
                "sp_dji",
                "https://press.spglobal.com/2013-09-23-Cubist-Pharmaceuticals-Science-Applications-International-Set-to-Join-the-S-P-MidCap-400-Annies-Barnes-Noble-to-Join-S-P-SmallCap-600",
                "S&P DJI states the newly spun-off Science Applications International joined the S&P MidCap 400 while renamed Leidos remained there.",
            ),
        ),
        siblings=(),
        reason="The post-spin SAIC security was a MidCap 400 constituent, not an S&P 500 constituent.",
    ),
    MembershipAdjudicationCase(
        membership_id=834,
        security_id=921,
        cik="0001336917",
        prior_effective_from=date(2016, 8, 16),
        prior_effective_to=date(2016, 12, 7),
        prior_source_hash="c18e398523cadc16c7dcfe274d577fb41e840828eea32a540adc250ff73625e8",
        identity=_identity(
            "UA-C",
            "2016-08-16",
            "2016-12-08",
            "provisional",
            "ed1959b8b647c705920eea93496ad54424b68dea2398108455e7474235f93e50",
        ),
        action="reject",
        target_effective_from=date(2016, 8, 16),
        target_effective_to=date(2016, 12, 7),
        evidence=(
            _e(
                "sec",
                "https://www.sec.gov/Archives/edgar/data/1336917/000133691717000017/ua-20161231x10k.htm",
                "Under Armour identifies UA as its Class C common stock ticker after the 2016 ticker transition; UA-C is not a distinct constituent security from that Class C line.",
            ),
        ),
        siblings=(
            _sibling(
                "duplicate_cover",
                833,
                920,
                "0001336917",
                "2016-04-08",
                "2022-06-21",
                "0c4ac2fd44c51ddfc304a0b7df3fb352fd02b2664dca4608f452570d3905e568",
            ),
        ),
        reason=(
            "SEC evidence binds UA-C to the same Class C common stock represented by the verified "
            "UA sibling; verifying both memberships would double-count one share class."
        ),
    ),
    MembershipAdjudicationCase(
        membership_id=814,
        security_id=915,
        cik="0001279363",
        prior_effective_from=date(2018, 9, 12),
        prior_effective_to=date(2020, 1, 28),
        prior_source_hash="ad366f081368d2169491e226705fcc69a1190b7f25cdf67ec8c3d88d9c23dfef",
        identity=_identity(
            "WCG",
            "2018-09-12",
            "2020-01-29",
            "verified",
            "a15432d666b469834b64e42e0bb8839410522b3f0b9b09e1fa6e59ebb8762d68",
        ),
        action="correct_and_verify",
        target_effective_from=date(2018, 9, 17),
        target_effective_to=date(2020, 1, 28),
        evidence=(
            _e(
                "sp_dji",
                "https://press.spglobal.com/2018-09-11-WellCare-Health-Plans-Set-to-Join-S-P-500-HealthEquity-to-Join-S-P-MidCap-400-Laredo-Petroleum-to-Join-S-P-SmallCap-600",
                "S&P DJI added WellCare to the S&P 500 effective prior to the 2018-09-17 open.",
            ),
            _e(
                "sp_dji",
                "https://press.spglobal.com/2020-01-22-Paycom-Software-Set-to-Join-S-P-500",
                "S&P DJI removed WellCare effective prior to the 2020-01-28 open.",
            ),
        ),
        siblings=(),
        reason="S&P DJI provides exact before-open addition and removal boundaries for WCG.",
    ),
    MembershipAdjudicationCase(
        membership_id=657,
        security_id=842,
        cik="0000849399",
        prior_effective_from=date(2019, 11, 6),
        prior_effective_to=date(2022, 11, 9),
        prior_source_hash="5d62c5cc024c9e73cce087ba3db0cca76da51ea50cc3122e93534f9d9e80db2c",
        identity=_identity(
            "NLOK",
            "2019-11-06",
            "2022-11-10",
            "provisional",
            "99eb557af8b9d8a238e5f03362b1129fdb6f4a30ed82ef5094acb5487f3774c4",
        ),
        action="verify",
        target_effective_from=date(2019, 11, 6),
        target_effective_to=date(2022, 11, 9),
        evidence=(
            _e(
                "sec",
                "https://www.sec.gov/Archives/edgar/data/849399/000110465919059239/tm1921662d1_ex99-01.htm",
                "Symantec changed its name to NortonLifeLock and began trading as NLOK on 2019-11-05, establishing issuer/security continuity.",
            ),
            _e(
                "sec",
                "https://www.sec.gov/Archives/edgar/data/849399/000110465922115277/tm2229813d1_ex99-01.htm",
                "Gen Digital states GEN replaced NLOK beginning 2022-11-08, establishing the successor ticker on the same issuer/security.",
            ),
        ),
        siblings=(
            _sibling(
                "predecessor",
                288,
                635,
                "0000849399",
                "2009-12-30",
                "2019-11-06",
                "f7f0af7c783514ae1d9228f0572796d7d8711855d92c446be81b729368bdc210",
            ),
            _sibling(
                "successor",
                656,
                204,
                "0000849399",
                "2022-11-09",
                None,
                "6ef74093c45b8204787c3ca69efad8aee8101bac1500313470e7adec0928d784",
            ),
        ),
        reason=(
            "SEC proves SYMC/NLOK/GEN are ticker identities of one continuing issuer/security; the "
            "existing membership split exactly stitches the verified predecessor and successor."
        ),
    ),
    MembershipAdjudicationCase(
        membership_id=638,
        security_id=831,
        cik="0000813828",
        prior_effective_from=date(2019, 12, 5),
        prior_effective_to=date(2022, 2, 19),
        prior_source_hash="bf2f89ccc965f01bfa3ecbe7d675e577f8f09456fed4b05dddb1f65a5ba5a70e",
        identity=_identity(
            "VIAC",
            "2019-12-05",
            "2022-02-20",
            "verified",
            "1e7e37ae3f82c796a1fc0f713894809bd8de722be7b7333c59bd8f9a13eea14f",
        ),
        action="correct_and_verify",
        target_effective_from=date(2019, 12, 5),
        target_effective_to=date(2022, 2, 17),
        evidence=(
            _e(
                "sec",
                "https://www.sec.gov/Archives/edgar/data/813828/000081382822000011/viac-20220216.htm",
                "Paramount states VIAC ceased and PARA began at the 2022-02-17 market open on the same Class B common stock.",
            ),
        ),
        siblings=(
            _sibling(
                "predecessor",
                267,
                626,
                "0000813828",
                "2009-12-30",
                "2019-12-05",
                "f35d2ad3aace214f98bb9e8224e26559504bc3016e72244838cf2f66c2992e7d",
            ),
            _sibling(
                "successor",
                637,
                830,
                "0000813828",
                "2022-02-17",
                "2025-08-08",
                "bacf2fbf42728b1067f4894e8b4690d007ef4e976c584752a1fc587f52cf7b2f",
            ),
        ),
        reason=(
            "SEC proves VIAC/PARA are one Class B security; end VIAC exactly when the already-verified "
            "PARA successor begins so the membership representation does not overlap."
        ),
    ),
    MembershipAdjudicationCase(
        membership_id=662,
        security_id=846,
        cik="0000858470",
        prior_effective_from=date(2021, 10, 3),
        prior_effective_to=date(2026, 5, 7),
        prior_source_hash="360ad7bbded7fb35361a1afbd7a750e798bb4da8ba99e3df143c8c4adb1dcc22",
        identity=_identity(
            "CTRA",
            "2021-10-03",
            "2026-05-08",
            "provisional",
            "7661723c96c76eda44ebc152a09c1fa61a2d015798c24cfd6906b96a81f0a60a",
        ),
        action="verify",
        target_effective_from=date(2021, 10, 3),
        target_effective_to=date(2026, 5, 7),
        evidence=(
            _e(
                "sp_dji",
                "https://press.spglobal.com/2021-09-30-SunPower-Set-to-Join-S-P-MidCap-400",
                "S&P DJI explicitly identifies Cabot Oil & Gas (COG) as an S&P 500 constituent during the Coterra merger.",
            ),
            _e(
                "sec",
                "https://www.sec.gov/Archives/edgar/data/858470/000110465921122041/tm2129019d1_ex99-1.htm",
                "Cabot completed the merger and changed its name to Coterra; CTRA began trading at the 2021-10-04 open after COG, proving issuer/security continuity.",
            ),
            _e(
                "sp_dji",
                "https://press.spglobal.com/2026-04-30-Veeva-Systems-Set-to-Join-S-P-500",
                "S&P DJI removes Coterra from the S&P 500 effective prior to the 2026-05-07 open.",
            ),
        ),
        siblings=(
            _sibling(
                "predecessor",
                290,
                637,
                "0000858470",
                "2009-12-30",
                "2021-10-03",
                "62f055c8b5d9e107373013db6d47b2a0ee1bec45b4336deb14b7ac091c0d9a9f",
            ),
        ),
        reason=(
            "S&P and SEC evidence prove continuous S&P 500 issuer membership through the COG/CTRA "
            "ticker transition and the exact 2026 deletion; exact ticker-day repair remains identity work."
        ),
    ),
    MembershipAdjudicationCase(
        membership_id=997,
        security_id=983,
        cik="0002011641",
        prior_effective_from=date(2026, 8, 5),
        prior_effective_to=None,
        prior_source_hash="8d535914e568e2159f160c74e2c89049e0f4562425c07728bc4f33685878095c",
        identity=_identity(
            "FERG",
            "2026-08-05",
            None,
            "verified",
            "b79115a95a3cb9b4a0b4cda4bc10d694928b11a4bdc2fd700796485ef0376a6a",
        ),
        action="verify",
        target_effective_from=date(2026, 8, 5),
        target_effective_to=None,
        evidence=(
            _e(
                "sp_dji",
                "https://press.spglobal.com/2026-07-31-Ferguson-Enterprises-Set-to-Join-S-P-500-and-ADI-Global-Distribution-to-Join-S-P-SmallCap-600",
                "S&P DJI added Ferguson to the S&P 500 effective prior to the 2026-08-05 open.",
            ),
        ),
        siblings=(),
        reason="S&P DJI directly confirms the exact open-ended Ferguson membership start.",
    ),
    MembershipAdjudicationCase(
        membership_id=700,
        security_id=867,
        cik="0000906107",
        prior_effective_from=date(2026, 8, 18),
        prior_effective_to=None,
        prior_source_hash="9237cae866ba960cdc225eb4a4cb7b9bdd7046e0558c26c3bbdce266f97a751a",
        identity=_identity(
            "VMRK",
            "2026-08-18",
            None,
            "provisional",
            "b2223164d07d5599044db91224d63ec09396ed6cfaa6891b4afcd50cdacdfb68",
        ),
        action="verify",
        target_effective_from=date(2026, 8, 18),
        target_effective_to=None,
        evidence=(
            _e(
                "sp_dji",
                "https://www.prnewswire.com/news-releases/reddit-set-to-join-sp-500-and-sun-communities-to-join-sp-midcap-400-302851432.html",
                "S&P DJI states S&P 500 constituent Equity Residential's post-merger company will be renamed Vivmark Residential (VMRK) and will remain in the S&P 500.",
            ),
        ),
        siblings=(
            _sibling(
                "predecessor",
                323,
                166,
                "0000906107",
                "2009-12-30",
                "2026-08-18",
                "fb7b3e8ca0bcb5f13e0ad089bcbe59d46b9a35972e3b8f2c2b05874cc203dc9f",
            ),
        ),
        reason="S&P DJI explicitly says the EQR successor Vivmark remains in the S&P 500.",
    ),
    MembershipAdjudicationCase(
        membership_id=965,
        security_id=975,
        cik="0001713445",
        prior_effective_from=date(2026, 8, 18),
        prior_effective_to=None,
        prior_source_hash="8e52f4cf95882d6c72757f83550afa68af7c55c122f62db88b3e04caaad1093d",
        identity=_identity(
            "RDDT",
            "2026-08-18",
            None,
            "verified",
            "0f60ad3b4b9661e0fdadf006bcb6e1f8792d947861a161426f5895390f308ef1",
        ),
        action="verify",
        target_effective_from=date(2026, 8, 18),
        target_effective_to=None,
        evidence=(
            _e(
                "sp_dji",
                "https://www.prnewswire.com/news-releases/reddit-set-to-join-sp-500-and-sun-communities-to-join-sp-midcap-400-302851432.html",
                "S&P DJI added Reddit to the S&P 500 effective prior to the 2026-08-18 open.",
            ),
        ),
        siblings=(),
        reason="S&P DJI directly confirms the exact open-ended Reddit membership start.",
    ),
)
