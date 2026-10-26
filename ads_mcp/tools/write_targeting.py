# ads_mcp/tools/write_targeting.py

"""Write tools for criteria/targeting: keywords, geo, audiences."""

from typing import Optional

from ads_mcp.coordinator import mcp
from ads_mcp.tools._safety import (
    check_read_only,
    handle_googleads_exception,
)
from ads_mcp.utils import get_googleads_client
from google.ads.googleads.errors import GoogleAdsException


_VALID_MATCH_TYPES = {"EXACT", "PHRASE", "BROAD"}


@mcp.tool()
def add_keywords(
    customer_id: str,
    ad_group_id: str,
    keywords: list[dict],
    cpc_bid_micros: Optional[int] = None,
) -> dict:
    """
    Adds positive keywords to an existing ad group, in PAUSED status.

    Args:
        customer_id: Google Ads customer ID.
        ad_group_id: Target ad group.
        keywords: List of {"text": str, "match_type": "EXACT"|"PHRASE"|"BROAD"}.
        cpc_bid_micros: Optional per-criterion CPC override.

    Returns:
        dict with `created_resource_names` on success.
    """
    if err := check_read_only():
        return err

    if not keywords:
        return {"success": False, "error": "keywords list is empty."}
    for i, kw in enumerate(keywords):
        if not isinstance(kw, dict) or "text" not in kw or "match_type" not in kw:
            return {
                "success": False,
                "error": f"keywords[{i}] must be {{'text': str, 'match_type': str}}.",
            }
        if kw["match_type"] not in _VALID_MATCH_TYPES:
            return {
                "success": False,
                "error": (
                    f"keywords[{i}].match_type must be one of "
                    f"{sorted(_VALID_MATCH_TYPES)}"
                ),
            }

    try:
        client = get_googleads_client()
        service = client.get_service("AdGroupCriterionService")
        ag_resource_name = client.get_service("AdGroupService").ad_group_path(
            customer_id, ad_group_id
        )

        operations = []
        for kw in keywords:
            op = client.get_type("AdGroupCriterionOperation")
            crit = op.create
            crit.ad_group = ag_resource_name
            crit.status = client.enums.AdGroupCriterionStatusEnum.PAUSED
            crit.keyword.text = kw["text"]
            crit.keyword.match_type = client.enums.KeywordMatchTypeEnum[
                kw["match_type"]
            ]
            if cpc_bid_micros is not None:
                crit.cpc_bid_micros = cpc_bid_micros
            operations.append(op)

        response = service.mutate_ad_group_criteria(
            customer_id=customer_id, operations=operations
        )
        return {
            "success": True,
            "created_resource_names": [r.resource_name for r in response.results],
            "message": f"Created {len(response.results)} keyword(s) in PAUSED status.",
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def set_keyword_status(
    customer_id: str,
    ad_group_id: str,
    criterion_id: str,
    status: str,
) -> dict:
    """
    Pauses or enables an existing keyword (ad group criterion).

    Args:
        customer_id: Google Ads customer ID.
        ad_group_id: Ad group that contains the keyword.
        criterion_id: The keyword's criterion ID. Discover via the search tool:
            SELECT ad_group_criterion.criterion_id,
                   ad_group_criterion.keyword.text,
                   ad_group_criterion.status
            FROM ad_group_criterion
            WHERE ad_group_criterion.type = 'KEYWORD'
              AND ad_group.id = <ad_group_id>
        status: 'ENABLED' or 'PAUSED'.

    Returns:
        dict with the criterion's resource_name on success.
    """
    if err := check_read_only():
        return err
    if status not in ("ENABLED", "PAUSED"):
        return {
            "success": False,
            "error": "status must be 'ENABLED' or 'PAUSED'.",
        }

    try:
        client = get_googleads_client()
        service = client.get_service("AdGroupCriterionService")
        resource_name = service.ad_group_criterion_path(
            customer_id, ad_group_id, criterion_id
        )

        op = client.get_type("AdGroupCriterionOperation")
        op.update.resource_name = resource_name
        op.update.status = client.enums.AdGroupCriterionStatusEnum[status]

        from google.protobuf import field_mask_pb2

        op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["status"]))

        response = service.mutate_ad_group_criteria(
            customer_id=customer_id, operations=[op]
        )
        return {
            "success": True,
            "resource_name": response.results[0].resource_name,
            "message": f"Keyword {criterion_id} set to {status}.",
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def add_negative_keywords(
    customer_id: str,
    level: str,
    parent_id: str,
    keywords: list[dict],
) -> dict:
    """
    Adds negative keywords at either CAMPAIGN or AD_GROUP level.

    Args:
        customer_id: Google Ads customer ID.
        level: 'CAMPAIGN' or 'AD_GROUP'.
        parent_id: Campaign ID (if level=CAMPAIGN) or ad group ID (if AD_GROUP).
        keywords: List of {"text": str, "match_type": "EXACT"|"PHRASE"|"BROAD"}.

    Returns:
        dict with created resource names.
    """
    if err := check_read_only():
        return err

    if level not in ("CAMPAIGN", "AD_GROUP"):
        return {
            "success": False,
            "error": "level must be 'CAMPAIGN' or 'AD_GROUP'.",
        }
    if not keywords:
        return {"success": False, "error": "keywords list is empty."}
    for i, kw in enumerate(keywords):
        if not isinstance(kw, dict) or "text" not in kw or "match_type" not in kw:
            return {
                "success": False,
                "error": f"keywords[{i}] must be {{'text': str, 'match_type': str}}.",
            }
        if kw["match_type"] not in _VALID_MATCH_TYPES:
            return {
                "success": False,
                "error": (
                    f"keywords[{i}].match_type must be one of "
                    f"{sorted(_VALID_MATCH_TYPES)}"
                ),
            }

    try:
        client = get_googleads_client()
        operations = []

        if level == "CAMPAIGN":
            service = client.get_service("CampaignCriterionService")
            campaign_resource_name = client.get_service(
                "CampaignService"
            ).campaign_path(customer_id, parent_id)
            for kw in keywords:
                op = client.get_type("CampaignCriterionOperation")
                crit = op.create
                crit.campaign = campaign_resource_name
                crit.negative = True
                crit.keyword.text = kw["text"]
                crit.keyword.match_type = client.enums.KeywordMatchTypeEnum[
                    kw["match_type"]
                ]
                operations.append(op)
            response = service.mutate_campaign_criteria(
                customer_id=customer_id, operations=operations
            )
        else:  # AD_GROUP
            service = client.get_service("AdGroupCriterionService")
            ag_resource_name = client.get_service(
                "AdGroupService"
            ).ad_group_path(customer_id, parent_id)
            for kw in keywords:
                op = client.get_type("AdGroupCriterionOperation")
                crit = op.create
                crit.ad_group = ag_resource_name
                crit.negative = True
                crit.keyword.text = kw["text"]
                crit.keyword.match_type = client.enums.KeywordMatchTypeEnum[
                    kw["match_type"]
                ]
                operations.append(op)
            response = service.mutate_ad_group_criteria(
                customer_id=customer_id, operations=operations
            )

        return {
            "success": True,
            "created_resource_names": [r.resource_name for r in response.results],
            "message": (
                f"Added {len(response.results)} negative keyword(s) at {level} level."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def add_language_targets(
    customer_id: str,
    campaign_id: str,
    language_constants: list[str],
) -> dict:
    """
    Adds language targeting criteria to a campaign.

    Args:
        customer_id: Google Ads customer ID.
        campaign_id: Campaign to apply targeting to.
        language_constants: List of language constant resource names, e.g.
            ['languageConstants/1000'] for English, ['languageConstants/1003']
            for Spanish. Discover IDs via the search tool with the
            `language_constant` resource.

    Returns:
        dict with created resource names.
    """
    if err := check_read_only():
        return err

    if not language_constants:
        return {"success": False, "error": "language_constants list is empty."}
    for i, lc in enumerate(language_constants):
        if not isinstance(lc, str) or not lc.startswith("languageConstants/"):
            return {
                "success": False,
                "error": (
                    f"language_constants[{i}] must be a resource name like "
                    f"'languageConstants/1000', got: {lc!r}"
                ),
            }

    try:
        client = get_googleads_client()
        service = client.get_service("CampaignCriterionService")
        campaign_resource_name = client.get_service(
            "CampaignService"
        ).campaign_path(customer_id, campaign_id)

        operations = []
        for lc in language_constants:
            op = client.get_type("CampaignCriterionOperation")
            crit = op.create
            crit.campaign = campaign_resource_name
            crit.language.language_constant = lc
            operations.append(op)

        response = service.mutate_campaign_criteria(
            customer_id=customer_id, operations=operations
        )
        return {
            "success": True,
            "created_resource_names": [r.resource_name for r in response.results],
            "message": f"Targeted {len(response.results)} language(s).",
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


_VALID_DAYS = {
    "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY",
    "FRIDAY", "SATURDAY", "SUNDAY",
}
_VALID_MINUTES = {"ZERO", "FIFTEEN", "THIRTY", "FORTY_FIVE"}


@mcp.tool()
def add_ad_schedules(
    customer_id: str,
    campaign_id: str,
    schedules: list[dict],
) -> dict:
    """
    Adds ad-schedule (dayparting) criteria to a campaign.

    Each schedule defines a window during which ads can serve. Multiple
    schedules combine as a union — e.g. {Mon-Fri 9-17} + {Sat 10-14} runs
    weekdays 9am-5pm and Saturdays 10am-2pm. Hours not covered serve nothing.

    Args:
        customer_id: Google Ads customer ID.
        campaign_id: Campaign to apply schedules to.
        schedules: List of dicts, each with:
            - day_of_week: 'MONDAY'..'SUNDAY' (required)
            - start_hour: int 0-23 (required)
            - start_minute: 'ZERO'|'FIFTEEN'|'THIRTY'|'FORTY_FIVE' (default 'ZERO')
            - end_hour: int 0-24 (required; 24 means end of day)
            - end_minute: same enum (default 'ZERO')
            - bid_modifier: optional float (e.g. 1.2 for +20%)

    Returns:
        dict with created resource names.
    """
    if err := check_read_only():
        return err

    if not schedules:
        return {"success": False, "error": "schedules list is empty."}
    for i, s in enumerate(schedules):
        if not isinstance(s, dict):
            return {"success": False, "error": f"schedules[{i}] must be a dict."}
        if s.get("day_of_week") not in _VALID_DAYS:
            return {
                "success": False,
                "error": f"schedules[{i}].day_of_week must be one of {sorted(_VALID_DAYS)}.",
            }
        if not isinstance(s.get("start_hour"), int) or not (0 <= s["start_hour"] <= 23):
            return {
                "success": False,
                "error": f"schedules[{i}].start_hour must be int 0-23.",
            }
        if not isinstance(s.get("end_hour"), int) or not (0 <= s["end_hour"] <= 24):
            return {
                "success": False,
                "error": f"schedules[{i}].end_hour must be int 0-24.",
            }
        if s.get("start_minute", "ZERO") not in _VALID_MINUTES:
            return {
                "success": False,
                "error": f"schedules[{i}].start_minute must be one of {sorted(_VALID_MINUTES)}.",
            }
        if s.get("end_minute", "ZERO") not in _VALID_MINUTES:
            return {
                "success": False,
                "error": f"schedules[{i}].end_minute must be one of {sorted(_VALID_MINUTES)}.",
            }

    try:
        client = get_googleads_client()
        service = client.get_service("CampaignCriterionService")
        campaign_resource_name = client.get_service(
            "CampaignService"
        ).campaign_path(customer_id, campaign_id)

        operations = []
        for s in schedules:
            op = client.get_type("CampaignCriterionOperation")
            crit = op.create
            crit.campaign = campaign_resource_name
            crit.ad_schedule.day_of_week = client.enums.DayOfWeekEnum[
                s["day_of_week"]
            ]
            crit.ad_schedule.start_hour = s["start_hour"]
            crit.ad_schedule.end_hour = s["end_hour"]
            crit.ad_schedule.start_minute = client.enums.MinuteOfHourEnum[
                s.get("start_minute", "ZERO")
            ]
            crit.ad_schedule.end_minute = client.enums.MinuteOfHourEnum[
                s.get("end_minute", "ZERO")
            ]
            if "bid_modifier" in s:
                crit.bid_modifier = float(s["bid_modifier"])
            operations.append(op)

        response = service.mutate_campaign_criteria(
            customer_id=customer_id, operations=operations
        )
        return {
            "success": True,
            "created_resource_names": [r.resource_name for r in response.results],
            "message": f"Added {len(response.results)} ad schedule(s).",
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


_VALID_DEVICES = {"MOBILE", "TABLET", "DESKTOP", "CONNECTED_TV", "OTHER"}


@mcp.tool()
def add_device_bid_adjustments(
    customer_id: str,
    campaign_id: str,
    adjustments: list[dict],
) -> dict:
    """
    Adds device-level bid modifier criteria to a campaign.

    A `bid_modifier` of 1.0 = no change, 1.2 = +20%, 0.5 = -50%, 0.0 = pause
    that device entirely for this campaign.

    Args:
        customer_id: Google Ads customer ID.
        campaign_id: Campaign to apply adjustments to.
        adjustments: List of dicts, each with:
            - device: 'MOBILE'|'TABLET'|'DESKTOP'|'CONNECTED_TV'|'OTHER'
            - bid_modifier: float (0.0 = pause, otherwise typically 0.1-10.0)

    Returns:
        dict with created resource names.
    """
    if err := check_read_only():
        return err

    if not adjustments:
        return {"success": False, "error": "adjustments list is empty."}
    for i, a in enumerate(adjustments):
        if not isinstance(a, dict):
            return {"success": False, "error": f"adjustments[{i}] must be a dict."}
        if a.get("device") not in _VALID_DEVICES:
            return {
                "success": False,
                "error": f"adjustments[{i}].device must be one of {sorted(_VALID_DEVICES)}.",
            }
        bm = a.get("bid_modifier")
        if not isinstance(bm, (int, float)) or bm < 0:
            return {
                "success": False,
                "error": f"adjustments[{i}].bid_modifier must be a non-negative number.",
            }

    try:
        client = get_googleads_client()
        service = client.get_service("CampaignCriterionService")
        campaign_resource_name = client.get_service(
            "CampaignService"
        ).campaign_path(customer_id, campaign_id)

        operations = []
        for a in adjustments:
            op = client.get_type("CampaignCriterionOperation")
            crit = op.create
            crit.campaign = campaign_resource_name
            crit.device.type_ = client.enums.DeviceEnum[a["device"]]
            crit.bid_modifier = float(a["bid_modifier"])
            operations.append(op)

        response = service.mutate_campaign_criteria(
            customer_id=customer_id, operations=operations
        )
        return {
            "success": True,
            "created_resource_names": [r.resource_name for r in response.results],
            "message": f"Added {len(response.results)} device bid adjustment(s).",
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def add_geo_targets(
    customer_id: str,
    campaign_id: str,
    geo_target_constants: list[str],
    negative: bool = False,
) -> dict:
    """
    Adds geographic targeting criteria to a campaign.

    Args:
        customer_id: Google Ads customer ID.
        campaign_id: Campaign to apply targeting to.
        geo_target_constants: List of geo target constant resource names,
            e.g. ['geoTargetConstants/2840'] for the United States. Look up
            constants via the search tool with the GeoTargetConstant resource.
        negative: When True, exclude these geos instead of targeting them.

    Returns:
        dict with created resource names.
    """
    if err := check_read_only():
        return err

    if not geo_target_constants:
        return {"success": False, "error": "geo_target_constants list is empty."}
    for i, g in enumerate(geo_target_constants):
        if not isinstance(g, str) or not g.startswith("geoTargetConstants/"):
            return {
                "success": False,
                "error": (
                    f"geo_target_constants[{i}] must be a resource name like "
                    f"'geoTargetConstants/2840', got: {g!r}"
                ),
            }

    try:
        client = get_googleads_client()
        service = client.get_service("CampaignCriterionService")
        campaign_resource_name = client.get_service(
            "CampaignService"
        ).campaign_path(customer_id, campaign_id)

        operations = []
        for g in geo_target_constants:
            op = client.get_type("CampaignCriterionOperation")
            crit = op.create
            crit.campaign = campaign_resource_name
            crit.location.geo_target_constant = g
            crit.negative = negative
            operations.append(op)

        response = service.mutate_campaign_criteria(
            customer_id=customer_id, operations=operations
        )
        return {
            "success": True,
            "created_resource_names": [r.resource_name for r in response.results],
            "message": (
                f"{'Excluded' if negative else 'Targeted'} "
                f"{len(response.results)} geo location(s)."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


def _apply_criterion_at_level(
    client,
    customer_id: str,
    level: str,
    parent_id: str,
    set_criterion_field,
    items: list[str],
):
    """Helper: applies one criterion-builder per item at CAMPAIGN or AD_GROUP level.

    `set_criterion_field(crit, item)` mutates the criterion proto in place to
    point at `item` (e.g. crit.user_list.user_list = item).
    """
    operations = []
    if level == "CAMPAIGN":
        service = client.get_service("CampaignCriterionService")
        parent_rn = client.get_service("CampaignService").campaign_path(
            customer_id, parent_id
        )
        for item in items:
            op = client.get_type("CampaignCriterionOperation")
            crit = op.create
            crit.campaign = parent_rn
            set_criterion_field(crit, item)
            operations.append(op)
        return service.mutate_campaign_criteria(
            customer_id=customer_id, operations=operations
        )
    else:
        service = client.get_service("AdGroupCriterionService")
        parent_rn = client.get_service("AdGroupService").ad_group_path(
            customer_id, parent_id
        )
        for item in items:
            op = client.get_type("AdGroupCriterionOperation")
            crit = op.create
            crit.ad_group = parent_rn
            set_criterion_field(crit, item)
            operations.append(op)
        return service.mutate_ad_group_criteria(
            customer_id=customer_id, operations=operations
        )


@mcp.tool()
def add_audience_targets(
    customer_id: str,
    level: str,
    parent_id: str,
    user_list_resource_names: list[str],
) -> dict:
    """
    Applies user-list audience targeting at CAMPAIGN or AD_GROUP level.

    For Search/Display, this is the typical "audience targeting" entry point —
    pass UserList resource names (created via create_remarketing_user_list)
    and they'll be added as positive criteria.

    Args:
        customer_id: Google Ads customer ID.
        level: 'CAMPAIGN' or 'AD_GROUP'.
        parent_id: Campaign or ad group ID matching `level`.
        user_list_resource_names: List of UserList resource names,
            e.g. ['customers/123/userLists/456'].

    Returns:
        dict with created resource names.
    """
    if err := check_read_only():
        return err

    if level not in ("CAMPAIGN", "AD_GROUP"):
        return {
            "success": False,
            "error": "level must be 'CAMPAIGN' or 'AD_GROUP'.",
        }
    if not user_list_resource_names:
        return {
            "success": False,
            "error": "user_list_resource_names list is empty.",
        }

    try:
        client = get_googleads_client()
        response = _apply_criterion_at_level(
            client,
            customer_id,
            level,
            parent_id,
            lambda crit, ul: setattr(crit.user_list, "user_list", ul),
            user_list_resource_names,
        )
        return {
            "success": True,
            "created_resource_names": [r.resource_name for r in response.results],
            "message": (
                f"Applied {len(response.results)} audience target(s) at {level} level."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def add_user_interest_targets(
    customer_id: str,
    level: str,
    parent_id: str,
    user_interest_resource_names: list[str],
) -> dict:
    """
    Applies in-market or affinity audience targeting via UserInterest criteria.

    In-market and affinity are both Google-defined taxonomies exposed as
    `userInterests/N` resources. Discover IDs via the search tool, e.g.

        SELECT user_interest.user_interest_id, user_interest.name,
               user_interest.taxonomy_type
        FROM user_interest
        WHERE user_interest.taxonomy_type IN ('IN_MARKET','AFFINITY')

    Args:
        customer_id: Google Ads customer ID.
        level: 'CAMPAIGN' or 'AD_GROUP'.
        parent_id: Campaign or ad group ID matching `level`.
        user_interest_resource_names: List of UserInterest resource names,
            e.g. ['userInterests/92931'].

    Returns:
        dict with created resource names.
    """
    if err := check_read_only():
        return err

    if level not in ("CAMPAIGN", "AD_GROUP"):
        return {
            "success": False,
            "error": "level must be 'CAMPAIGN' or 'AD_GROUP'.",
        }
    if not user_interest_resource_names:
        return {
            "success": False,
            "error": "user_interest_resource_names list is empty.",
        }
    for i, ui in enumerate(user_interest_resource_names):
        if not isinstance(ui, str) or not ui.startswith("userInterests/"):
            return {
                "success": False,
                "error": (
                    f"user_interest_resource_names[{i}] must look like "
                    f"'userInterests/N', got: {ui!r}"
                ),
            }

    try:
        client = get_googleads_client()
        response = _apply_criterion_at_level(
            client,
            customer_id,
            level,
            parent_id,
            lambda crit, ui: setattr(
                crit.user_interest, "user_interest_category", ui
            ),
            user_interest_resource_names,
        )
        return {
            "success": True,
            "created_resource_names": [r.resource_name for r in response.results],
            "message": (
                f"Applied {len(response.results)} in-market/affinity target(s) "
                f"at {level} level."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def add_custom_audience_targets(
    customer_id: str,
    level: str,
    parent_id: str,
    custom_audience_resource_names: list[str],
) -> dict:
    """
    Applies custom-audience criteria (the modern API surface for what was
    previously called "custom affinity" and "custom intent" audiences).

    Discover IDs via the search tool:
        SELECT custom_audience.id, custom_audience.name, custom_audience.type,
               custom_audience.status
        FROM custom_audience
        WHERE custom_audience.status = 'ENABLED'

    Args:
        customer_id: Google Ads customer ID.
        level: 'CAMPAIGN' or 'AD_GROUP'.
        parent_id: Campaign or ad group ID matching `level`.
        custom_audience_resource_names: List of CustomAudience resource names,
            e.g. ['customers/123/customAudiences/456'].

    Returns:
        dict with created resource names.
    """
    if err := check_read_only():
        return err

    if level not in ("CAMPAIGN", "AD_GROUP"):
        return {
            "success": False,
            "error": "level must be 'CAMPAIGN' or 'AD_GROUP'.",
        }
    if not custom_audience_resource_names:
        return {
            "success": False,
            "error": "custom_audience_resource_names list is empty.",
        }
    for i, ca in enumerate(custom_audience_resource_names):
        if not isinstance(ca, str) or "/customAudiences/" not in ca:
            return {
                "success": False,
                "error": (
                    f"custom_audience_resource_names[{i}] must look like "
                    f"'customers/N/customAudiences/M', got: {ca!r}"
                ),
            }

    try:
        client = get_googleads_client()
        response = _apply_criterion_at_level(
            client,
            customer_id,
            level,
            parent_id,
            lambda crit, ca: setattr(
                crit.custom_audience, "custom_audience", ca
            ),
            custom_audience_resource_names,
        )
        return {
            "success": True,
            "created_resource_names": [r.resource_name for r in response.results],
            "message": (
                f"Applied {len(response.results)} custom-audience target(s) "
                f"at {level} level."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def set_ad_group_audience(
    customer_id: str,
    ad_group_id: str,
    audience_resource_name: str,
    replace_existing: bool = False,
    validate_only: bool = False,
) -> dict:
    """
    Targets an ad group at an Audience: the combined audience object built in
    Google Ads' audience manager (segments + demographics + exclusions), as
    opposed to a single user list. Demand Gen ad groups only accept this kind
    of audience; add_audience_targets (user lists) is rejected there.

    An ad group holds one Audience. Discover them via the search tool:
        SELECT audience.resource_name, audience.name, audience.status
        FROM audience WHERE audience.status = 'ENABLED'

    Args:
        customer_id: Google Ads customer ID.
        ad_group_id: Ad group to target.
        audience_resource_name: e.g. 'customers/123/audiences/456'.
        replace_existing: When the ad group already has an Audience, swap it
            for this one (in one atomic request). Without it, the tool refuses
            and reports the current one.
        validate_only: When True, Google validates without changing anything.

    Returns:
        dict with the created criterion resource name.
    """
    if err := check_read_only():
        return err

    if (
        not isinstance(audience_resource_name, str)
        or "/audiences/" not in audience_resource_name
    ):
        return {
            "success": False,
            "error": (
                "audience_resource_name must look like "
                f"'customers/N/audiences/M', got: {audience_resource_name!r}"
            ),
        }

    try:
        client = get_googleads_client()
        ad_group_rn = client.get_service("AdGroupService").ad_group_path(
            customer_id, ad_group_id
        )
        query = (
            "SELECT ad_group_criterion.resource_name, "
            "ad_group_criterion.audience.audience "
            "FROM ad_group_criterion "
            f"WHERE ad_group.id = {int(ad_group_id)} "
            "AND ad_group_criterion.type = 'AUDIENCE' "
            "AND ad_group_criterion.status != 'REMOVED'"
        )
        existing = [
            row.ad_group_criterion
            for row in client.get_service("GoogleAdsService").search(
                customer_id=customer_id, query=query
            )
        ]
        if any(c.audience.audience == audience_resource_name for c in existing):
            return {
                "success": True,
                "message": "The ad group already targets this audience.",
            }
        if existing and not replace_existing:
            return {
                "success": False,
                "error": (
                    "The ad group already targets "
                    f"{[c.audience.audience for c in existing]}. Pass "
                    "replace_existing=True to swap it."
                ),
            }

        operations = []
        for criterion in existing:
            op = client.get_type("AdGroupCriterionOperation")
            op.remove = criterion.resource_name
            operations.append(op)
        op = client.get_type("AdGroupCriterionOperation")
        crit = op.create
        crit.ad_group = ad_group_rn
        crit.audience.audience = audience_resource_name
        operations.append(op)

        request = client.get_type("MutateAdGroupCriteriaRequest")
        request.customer_id = customer_id
        request.operations = operations
        request.validate_only = validate_only
        response = client.get_service(
            "AdGroupCriterionService"
        ).mutate_ad_group_criteria(request=request)

        replaced = [c.audience.audience for c in existing]
        if validate_only:
            return {
                "success": True,
                "validate_only": True,
                "replaced": replaced,
                "message": (
                    f"Valid: would target {audience_resource_name} on ad "
                    f"group {ad_group_id}. Nothing was changed."
                ),
            }
        return {
            "success": True,
            "resource_name": response.results[-1].resource_name,
            "replaced": replaced,
            "message": f"Ad group {ad_group_id} now targets {audience_resource_name}.",
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}
