# ads_mcp/tools/write_hierarchy.py

"""Write tools for campaign hierarchy: budgets, campaigns, ad groups, bidding."""

from typing import Optional

from ads_mcp.coordinator import mcp
from ads_mcp.tools._safety import (
    check_max_budget,
    check_read_only,
    handle_googleads_exception,
)
from ads_mcp.utils import get_googleads_client
from google.ads.googleads.errors import GoogleAdsException


_VALID_CHANNEL_TYPES = {"SEARCH", "DISPLAY", "VIDEO"}

# Bidding strategies that map to a oneof field on the Campaign resource.
# Some require a target value (target_cpa.target_cpa_micros etc.); see
# create_campaign / set_campaign_bidding_strategy below.
_VALID_BIDDING_STRATEGIES = {
    "MANUAL_CPC",
    "MANUAL_CPM",
    "MANUAL_CPV",
    "MAXIMIZE_CONVERSIONS",
    "MAXIMIZE_CONVERSION_VALUE",
    "TARGET_CPA",
    "TARGET_ROAS",
    "TARGET_SPEND",
    "TARGET_IMPRESSION_SHARE",
}

# Ad group types valid by channel — minimal set, the API will reject mismatches
# but we surface a clearer error upfront.
_AD_GROUP_TYPES_BY_CHANNEL = {
    "SEARCH": {"SEARCH_STANDARD"},
    "DISPLAY": {"DISPLAY_STANDARD"},
    "VIDEO": {
        "VIDEO_TRUE_VIEW_IN_STREAM",
        "VIDEO_TRUE_VIEW_IN_DISPLAY",
        "VIDEO_BUMPER",
        "VIDEO_NON_SKIPPABLE_IN_STREAM",
        "VIDEO_OUTSTREAM",
        "VIDEO_RESPONSIVE",
        "VIDEO_EFFICIENT_REACH",
    },
}


def _set_bidding_strategy(
    client,
    campaign,
    strategy_type: str,
    target_cpa_micros: Optional[int],
    target_roas: Optional[float],
    target_spend_micros: Optional[int],
) -> Optional[dict]:
    """Mutates `campaign` in place to set the bidding strategy oneof.

    Returns an error dict if validation fails, else None.
    """
    if strategy_type not in _VALID_BIDDING_STRATEGIES:
        return {
            "success": False,
            "error": (
                f"bidding_strategy_type must be one of "
                f"{sorted(_VALID_BIDDING_STRATEGIES)}"
            ),
        }

    # Proto-plus mode: select a oneof either by setting a sub-field (which
    # lazily creates the message and selects the oneof) or by assigning a
    # fresh empty instance with `=`. Do NOT use `.CopyFrom` on these — the
    # proto-plus wrappers don't expose it.
    if strategy_type == "MANUAL_CPC":
        # NOTE: enhanced_cpc_enabled was deprecated; setting it does not
        # reliably trigger oneof selection in v24. Assign an empty ManualCpc
        # explicitly instead.
        campaign.manual_cpc = client.get_type("ManualCpc")
    elif strategy_type == "MANUAL_CPM":
        campaign.manual_cpm = client.get_type("ManualCpm")
    elif strategy_type == "MANUAL_CPV":
        campaign.manual_cpv = client.get_type("ManualCpv")
    elif strategy_type == "MAXIMIZE_CONVERSIONS":
        campaign.maximize_conversions = client.get_type("MaximizeConversions")
        if target_cpa_micros is not None:
            campaign.maximize_conversions.target_cpa_micros = target_cpa_micros
    elif strategy_type == "MAXIMIZE_CONVERSION_VALUE":
        campaign.maximize_conversion_value = client.get_type(
            "MaximizeConversionValue"
        )
        if target_roas is not None:
            campaign.maximize_conversion_value.target_roas = target_roas
    elif strategy_type == "TARGET_CPA":
        if target_cpa_micros is None:
            return {
                "success": False,
                "error": "TARGET_CPA requires target_cpa_micros.",
            }
        campaign.target_cpa.target_cpa_micros = target_cpa_micros
    elif strategy_type == "TARGET_ROAS":
        if target_roas is None:
            return {
                "success": False,
                "error": "TARGET_ROAS requires target_roas (e.g. 3.5 for 350%).",
            }
        campaign.target_roas.target_roas = target_roas
    elif strategy_type == "TARGET_SPEND":
        campaign.target_spend = client.get_type("TargetSpend")
        if target_spend_micros is not None:
            campaign.target_spend.cpc_bid_ceiling_micros = target_spend_micros
    elif strategy_type == "TARGET_IMPRESSION_SHARE":
        # Sensible default: top of page, 80%.
        campaign.target_impression_share.location = (
            client.enums.TargetImpressionShareLocationEnum.TOP_OF_PAGE
        )
        campaign.target_impression_share.location_fraction_micros = 800_000
    return None


@mcp.tool()
def create_campaign_budget(
    customer_id: str,
    name: str,
    amount_micros: int,
    delivery_method: str = "STANDARD",
) -> dict:
    """
    Creates a campaign budget. Currency follows the customer's account currency.

    Args:
        customer_id: Google Ads customer ID (no dashes).
        name: Unique budget name within the account.
        amount_micros: Daily budget amount in micros (1_000_000 micros = 1 unit
            of the account currency, e.g. $1.00 USD = 1_000_000 micros).
        delivery_method: 'STANDARD' (default) or 'ACCELERATED'.

    Returns:
        dict with the created budget's resource_name on success.
    """
    if err := check_read_only():
        return err
    if err := check_max_budget(amount_micros):
        return err
    if delivery_method not in ("STANDARD", "ACCELERATED"):
        return {
            "success": False,
            "error": "delivery_method must be 'STANDARD' or 'ACCELERATED'.",
        }
    if amount_micros <= 0:
        return {"success": False, "error": "amount_micros must be > 0."}

    try:
        client = get_googleads_client()
        service = client.get_service("CampaignBudgetService")
        op = client.get_type("CampaignBudgetOperation")
        budget = op.create
        budget.name = name
        budget.amount_micros = amount_micros
        budget.delivery_method = client.enums.BudgetDeliveryMethodEnum[
            delivery_method
        ]
        budget.explicitly_shared = False

        response = service.mutate_campaign_budgets(
            customer_id=customer_id, operations=[op]
        )
        resource_name = response.results[0].resource_name
        return {
            "success": True,
            "resource_name": resource_name,
            "message": (
                f"Budget '{name}' created at {amount_micros} micros/day."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def remove_campaign_budget(
    customer_id: str,
    budget_id: str,
) -> dict:
    """
    Removes a campaign budget by ID.

    The Google Ads API will reject this if any campaign currently references
    the budget — detach those campaigns or remove them first.

    Args:
        customer_id: Google Ads customer ID.
        budget_id: Campaign budget ID (numeric, no resource-name prefix).

    Returns:
        dict with the removed budget's resource_name on success.
    """
    if err := check_read_only():
        return err

    try:
        client = get_googleads_client()
        service = client.get_service("CampaignBudgetService")
        op = client.get_type("CampaignBudgetOperation")
        op.remove = service.campaign_budget_path(customer_id, budget_id)

        response = service.mutate_campaign_budgets(
            customer_id=customer_id, operations=[op]
        )
        return {
            "success": True,
            "resource_name": response.results[0].resource_name,
            "message": f"Budget {budget_id} removed.",
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


_VALID_EU_POLITICAL = {
    "CONTAINS_EU_POLITICAL_ADVERTISING",
    "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
}


@mcp.tool()
def create_campaign(
    customer_id: str,
    name: str,
    budget_resource_name: str,
    channel_type: str = "SEARCH",
    bidding_strategy_type: str = "MANUAL_CPC",
    target_cpa_micros: Optional[int] = None,
    target_roas: Optional[float] = None,
    target_spend_micros: Optional[int] = None,
    contains_eu_political_advertising: str = "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
) -> dict:
    """
    Creates a campaign in PAUSED status.

    Schedule (start/end date) is left to the API's server-side default
    (today / no end date). To change schedule after creation, edit in the
    Google Ads UI or add a dedicated update tool.

    Args:
        customer_id: Google Ads customer ID (no dashes).
        name: Campaign name (must be unique in the account).
        budget_resource_name: Full resource name from create_campaign_budget,
            e.g. 'customers/123/campaignBudgets/456'.
        channel_type: 'SEARCH', 'DISPLAY', or 'VIDEO' (YouTube). Note that
            VIDEO requires the account to be enabled for video campaign
            creation (linked YouTube channel + policy approval); the API
            will return MUTATE_NOT_ALLOWED if it isn't.
        bidding_strategy_type: One of MANUAL_CPC, MANUAL_CPM, MANUAL_CPV,
            MAXIMIZE_CONVERSIONS, MAXIMIZE_CONVERSION_VALUE, TARGET_CPA,
            TARGET_ROAS, TARGET_SPEND, TARGET_IMPRESSION_SHARE. Note that
            valid combos depend on channel_type — the API will reject e.g.
            MANUAL_CPV on SEARCH.
        target_cpa_micros: Required for TARGET_CPA, optional for
            MAXIMIZE_CONVERSIONS.
        target_roas: Required for TARGET_ROAS (e.g. 3.5 = 350%).
        target_spend_micros: Optional cap for TARGET_SPEND.
        contains_eu_political_advertising: Required by the API since v23
            for EU political-ads compliance. Defaults to
            'DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING' (the right answer
            for ~all advertisers). Set to 'CONTAINS_EU_POLITICAL_ADVERTISING'
            ONLY if you're running EU political ads — those have additional
            disclosure and verification requirements outside this tool.

    Returns:
        dict with the campaign's resource_name on success.
    """
    if err := check_read_only():
        return err

    if channel_type not in _VALID_CHANNEL_TYPES:
        return {
            "success": False,
            "error": f"channel_type must be one of {sorted(_VALID_CHANNEL_TYPES)}",
        }
    if contains_eu_political_advertising not in _VALID_EU_POLITICAL:
        return {
            "success": False,
            "error": (
                f"contains_eu_political_advertising must be one of "
                f"{sorted(_VALID_EU_POLITICAL)}"
            ),
        }

    try:
        client = get_googleads_client()
        service = client.get_service("CampaignService")

        op = client.get_type("CampaignOperation")
        campaign = op.create
        campaign.name = name
        campaign.status = client.enums.CampaignStatusEnum.PAUSED
        campaign.advertising_channel_type = (
            client.enums.AdvertisingChannelTypeEnum[channel_type]
        )
        campaign.campaign_budget = budget_resource_name
        # NOTE: assigning a string here rather than the explicit
        # client.enums.ContainsEuPoliticalAdvertisingEnum[...] used elsewhere.
        # That enum class isn't registered under that name in some installed
        # google-ads versions ('_EnumGetter' has no attribute ...). Proto-plus
        # auto-coerces strings on enum-field assignment, so the string form
        # is portable across versions.
        campaign.contains_eu_political_advertising = (
            contains_eu_political_advertising
        )

        # Network settings — for SEARCH the standard combo is search-network on,
        # search-partners on, content (display) off. For DISPLAY only display.
        # For VIDEO we let defaults stand.
        if channel_type == "SEARCH":
            campaign.network_settings.target_google_search = True
            campaign.network_settings.target_search_network = True
            campaign.network_settings.target_content_network = False
            campaign.network_settings.target_partner_search_network = False
        elif channel_type == "DISPLAY":
            campaign.network_settings.target_google_search = False
            campaign.network_settings.target_search_network = False
            campaign.network_settings.target_content_network = True
            campaign.network_settings.target_partner_search_network = False

        bid_err = _set_bidding_strategy(
            client,
            campaign,
            bidding_strategy_type,
            target_cpa_micros,
            target_roas,
            target_spend_micros,
        )
        if bid_err:
            return bid_err

        response = service.mutate_campaigns(
            customer_id=customer_id, operations=[op]
        )
        resource_name = response.results[0].resource_name
        return {
            "success": True,
            "resource_name": resource_name,
            "message": (
                f"{channel_type} campaign '{name}' created in PAUSED status."
            ),
            "note": "Campaign is PAUSED. Add ad groups + ads, then enable.",
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def create_ad_group(
    customer_id: str,
    campaign_id: str,
    name: str,
    channel_type: str = "SEARCH",
    ad_group_type: Optional[str] = None,
    cpc_bid_micros: Optional[int] = None,
) -> dict:
    """
    Creates an ad group within an existing campaign in PAUSED status.

    Args:
        customer_id: Google Ads customer ID.
        campaign_id: Parent campaign ID.
        name: Ad group name.
        channel_type: Channel of the parent campaign — 'SEARCH', 'DISPLAY',
            or 'VIDEO'. Used to default ad_group_type.
        ad_group_type: Specific type. If omitted, defaults to SEARCH_STANDARD /
            DISPLAY_STANDARD / VIDEO_RESPONSIVE based on channel_type.
        cpc_bid_micros: Optional default CPC bid for the ad group.

    Returns:
        dict with the ad group's resource_name on success.
    """
    if err := check_read_only():
        return err

    if channel_type not in _VALID_CHANNEL_TYPES:
        return {
            "success": False,
            "error": f"channel_type must be one of {sorted(_VALID_CHANNEL_TYPES)}",
        }

    if ad_group_type is None:
        ad_group_type = {
            "SEARCH": "SEARCH_STANDARD",
            "DISPLAY": "DISPLAY_STANDARD",
            "VIDEO": "VIDEO_RESPONSIVE",
        }[channel_type]

    valid_types = _AD_GROUP_TYPES_BY_CHANNEL[channel_type]
    if ad_group_type not in valid_types:
        return {
            "success": False,
            "error": (
                f"ad_group_type '{ad_group_type}' not valid for "
                f"channel_type={channel_type}. Allowed: {sorted(valid_types)}"
            ),
        }

    try:
        client = get_googleads_client()
        service = client.get_service("AdGroupService")
        campaign_resource_name = client.get_service(
            "CampaignService"
        ).campaign_path(customer_id, campaign_id)

        op = client.get_type("AdGroupOperation")
        ag = op.create
        ag.name = name
        ag.campaign = campaign_resource_name
        ag.status = client.enums.AdGroupStatusEnum.PAUSED
        ag.type_ = client.enums.AdGroupTypeEnum[ad_group_type]
        if cpc_bid_micros is not None:
            ag.cpc_bid_micros = cpc_bid_micros

        response = service.mutate_ad_groups(
            customer_id=customer_id, operations=[op]
        )
        resource_name = response.results[0].resource_name
        return {
            "success": True,
            "resource_name": resource_name,
            "message": f"Ad group '{name}' created in PAUSED status.",
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


_VALID_FCAP_LEVELS = {"AD_GROUP_AD", "AD_GROUP", "CAMPAIGN"}
_VALID_FCAP_EVENT_TYPES = {"IMPRESSION", "VIDEO_VIEW"}
_VALID_FCAP_TIME_UNITS = {"DAY", "WEEK", "MONTH"}


@mcp.tool()
def set_frequency_caps(
    customer_id: str,
    campaign_id: str,
    caps: list[dict],
) -> dict:
    """
    Replaces the campaign's frequency caps with the supplied list.

    NOTE: This *replaces* all existing caps on the campaign. To remove caps,
    pass `caps=[]`.

    Args:
        customer_id: Google Ads customer ID.
        campaign_id: Campaign to update.
        caps: List of dicts, each with:
            - level: 'AD_GROUP_AD'|'AD_GROUP'|'CAMPAIGN' (counts at which level)
            - event_type: 'IMPRESSION'|'VIDEO_VIEW'
            - time_unit: 'DAY'|'WEEK'|'MONTH'
            - time_length: int (e.g. 7 with time_unit=DAY = "7 days")
            - cap: int (max impressions/views allowed in the window)

    Returns:
        dict with the campaign's resource_name on success.
    """
    if err := check_read_only():
        return err

    for i, c in enumerate(caps):
        if not isinstance(c, dict):
            return {"success": False, "error": f"caps[{i}] must be a dict."}
        if c.get("level") not in _VALID_FCAP_LEVELS:
            return {
                "success": False,
                "error": f"caps[{i}].level must be one of {sorted(_VALID_FCAP_LEVELS)}.",
            }
        if c.get("event_type") not in _VALID_FCAP_EVENT_TYPES:
            return {
                "success": False,
                "error": f"caps[{i}].event_type must be one of {sorted(_VALID_FCAP_EVENT_TYPES)}.",
            }
        if c.get("time_unit") not in _VALID_FCAP_TIME_UNITS:
            return {
                "success": False,
                "error": f"caps[{i}].time_unit must be one of {sorted(_VALID_FCAP_TIME_UNITS)}.",
            }
        if not isinstance(c.get("time_length"), int) or c["time_length"] < 1:
            return {
                "success": False,
                "error": f"caps[{i}].time_length must be a positive int.",
            }
        if not isinstance(c.get("cap"), int) or c["cap"] < 1:
            return {
                "success": False,
                "error": f"caps[{i}].cap must be a positive int.",
            }

    try:
        client = get_googleads_client()
        service = client.get_service("CampaignService")
        campaign_resource_name = service.campaign_path(customer_id, campaign_id)

        op = client.get_type("CampaignOperation")
        op.update.resource_name = campaign_resource_name

        for c in caps:
            entry = op.update.frequency_caps.add()
            entry.key.level = client.enums.FrequencyCapLevelEnum[c["level"]]
            entry.key.event_type = client.enums.FrequencyCapEventTypeEnum[
                c["event_type"]
            ]
            entry.key.time_unit = client.enums.FrequencyCapTimeUnitEnum[
                c["time_unit"]
            ]
            entry.key.time_length = c["time_length"]
            entry.cap = c["cap"]

        from google.protobuf import field_mask_pb2

        op.update_mask.CopyFrom(
            field_mask_pb2.FieldMask(paths=["frequency_caps"])
        )

        response = service.mutate_campaigns(
            customer_id=customer_id, operations=[op]
        )
        return {
            "success": True,
            "resource_name": response.results[0].resource_name,
            "message": (
                f"Replaced campaign frequency caps with {len(caps)} entr"
                f"{'y' if len(caps) == 1 else 'ies'}."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def set_campaign_bidding_strategy(
    customer_id: str,
    campaign_id: str,
    bidding_strategy_type: str,
    target_cpa_micros: Optional[int] = None,
    target_roas: Optional[float] = None,
    target_spend_micros: Optional[int] = None,
) -> dict:
    """
    Updates a campaign's standard (non-portfolio) bidding strategy.

    Args:
        customer_id: Google Ads customer ID.
        campaign_id: Campaign to update.
        bidding_strategy_type: New strategy. See create_campaign for valid values.
        target_cpa_micros: Required for TARGET_CPA.
        target_roas: Required for TARGET_ROAS.
        target_spend_micros: Optional cap for TARGET_SPEND.

    Returns:
        dict with the campaign's resource_name and updated_fields on success.
    """
    if err := check_read_only():
        return err

    try:
        client = get_googleads_client()
        service = client.get_service("CampaignService")
        campaign_resource_name = service.campaign_path(customer_id, campaign_id)

        op = client.get_type("CampaignOperation")
        op.update.resource_name = campaign_resource_name

        bid_err = _set_bidding_strategy(
            client,
            op.update,
            bidding_strategy_type,
            target_cpa_micros,
            target_roas,
            target_spend_micros,
        )
        if bid_err:
            return bid_err

        # The bidding-strategy oneof field name on the Campaign proto.
        oneof_field_by_strategy = {
            "MANUAL_CPC": "manual_cpc",
            "MANUAL_CPM": "manual_cpm",
            "MANUAL_CPV": "manual_cpv",
            "MAXIMIZE_CONVERSIONS": "maximize_conversions",
            "MAXIMIZE_CONVERSION_VALUE": "maximize_conversion_value",
            "TARGET_CPA": "target_cpa",
            "TARGET_ROAS": "target_roas",
            "TARGET_SPEND": "target_spend",
            "TARGET_IMPRESSION_SHARE": "target_impression_share",
        }
        update_path = oneof_field_by_strategy[bidding_strategy_type]

        from google.protobuf import field_mask_pb2

        op.update_mask.CopyFrom(
            field_mask_pb2.FieldMask(paths=[update_path])
        )

        response = service.mutate_campaigns(
            customer_id=customer_id, operations=[op]
        )
        return {
            "success": True,
            "resource_name": response.results[0].resource_name,
            "updated_fields": [update_path],
            "message": (
                f"Campaign bidding strategy set to {bidding_strategy_type}."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}
