# ads_mcp/tools/write_demand_gen.py

"""Write tool for YouTube video ads, via a Demand Gen campaign.

The Google Ads API cannot create or mutate VIDEO campaigns ("You cannot create
new Video campaigns or update existing ones using the Google Ads API"). Demand
Gen is the supported path: a DemandGenVideoResponsiveAd serves a YouTube video,
and the ad group's channel controls can restrict it to YouTube placements.
"""

import urllib.request
from typing import Optional

from ads_mcp.coordinator import mcp
from ads_mcp.tools._safety import (
    check_max_budget,
    check_read_only,
    handle_googleads_exception,
)
from ads_mcp.tools.write_hierarchy import _set_bidding_strategy
from ads_mcp.utils import get_googleads_client
from google.ads.googleads.errors import GoogleAdsException


# Bidding strategies Demand Gen accepts (a subset of _VALID_BIDDING_STRATEGIES).
_DEMAND_GEN_BIDDING_STRATEGIES = {
    "MAXIMIZE_CONVERSIONS",
    "MAXIMIZE_CONVERSION_VALUE",
    "TARGET_CPA",
    "TARGET_ROAS",
    "TARGET_SPEND",
}

# Fields of AdGroup.DemandGenAdGroupSettings.DemandGenChannelControls
# .DemandGenSelectedChannels.
_ALL_CHANNELS = (
    "youtube_in_stream",
    "youtube_in_feed",
    "youtube_shorts",
    "discover",
    "gmail",
    "display",
    "maps",
)
_YOUTUBE_CHANNELS = ["youtube_in_stream", "youtube_in_feed", "youtube_shorts"]

_MAX_LOGO_BYTES = 5 * 1024 * 1024


def _download_image(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "google-ads-mcp"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read(_MAX_LOGO_BYTES + 1)
    if len(data) > _MAX_LOGO_BYTES:
        raise ValueError(f"Logo image is larger than {_MAX_LOGO_BYTES} bytes.")
    return data


@mcp.tool()
def create_demand_gen_video_campaign(
    customer_id: str,
    campaign_name: str,
    daily_budget_micros: int,
    youtube_video_id: str,
    final_url: str,
    business_name: str,
    headlines: list[str],
    long_headlines: list[str],
    descriptions: list[str],
    logo_asset_resource_name: Optional[str] = None,
    logo_image_url: Optional[str] = None,
    ad_group_name: Optional[str] = None,
    channels: Optional[list[str]] = None,
    geo_target_constants: Optional[list[str]] = None,
    language_constants: Optional[list[str]] = None,
    bidding_strategy_type: str = "MAXIMIZE_CONVERSIONS",
    target_cpa_micros: Optional[int] = None,
    target_roas: Optional[float] = None,
    target_spend_micros: Optional[int] = None,
    contains_eu_political_advertising: str = "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
    validate_only: bool = False,
) -> dict:
    """
    Creates a YouTube video ad campaign in one atomic request: budget, Demand
    Gen campaign (PAUSED), ad group, YouTube video asset, logo asset and a
    Demand Gen video responsive ad. Nothing is left behind if any part fails.

    Use this for "YouTube campaign for video X". Classic VIDEO campaigns cannot
    be created through the Google Ads API; Demand Gen restricted to YouTube
    channels is Google's supported replacement.

    Args:
        customer_id: Google Ads customer ID (no dashes).
        campaign_name: Campaign name (unique in the account). The budget is
            named after it.
        daily_budget_micros: Daily budget in micros (40 USD = 40000000). Must
            meet the Demand Gen per-day minimum for the account currency.
        youtube_video_id: The YouTube video ID, e.g. '0cpMc-7RFu8' (the part
            after 'v=' or 'youtu.be/'). The video must be public or unlisted.
        final_url: Landing page URL for the ad.
        business_name: Advertiser or brand name (max 25 characters).
        headlines: 1-5 headlines (max 40 characters each).
        long_headlines: 1-5 long headlines (max 90 characters each).
        descriptions: 1-5 descriptions (max 90 characters each).
        logo_asset_resource_name: An existing square image asset to use as the
            logo, e.g. 'customers/123/assets/456'. Find one with the search
            tool: SELECT asset.resource_name, asset.name,
            asset.image_asset.full_size.width_pixels,
            asset.image_asset.full_size.height_pixels FROM asset
            WHERE asset.type = 'IMAGE'.
        logo_image_url: Alternative to logo_asset_resource_name: a public URL
            of a square logo (1:1, at least 128x128, max 5 MB) to upload.
            Exactly one of the two logo arguments is required.
        ad_group_name: Defaults to '<campaign_name> - Video'.
        channels: Where the ad may serve. Defaults to YouTube only:
            ['youtube_in_stream', 'youtube_in_feed', 'youtube_shorts'].
            Also allowed: 'discover', 'gmail', 'display', 'maps'.
        geo_target_constants: Locations to target, e.g.
            ['geoTargetConstants/2032'] for Argentina. Omit to target all.
        language_constants: Languages to target, e.g.
            ['languageConstants/1003'] for Spanish. Omit to target all.
        bidding_strategy_type: MAXIMIZE_CONVERSIONS (default),
            MAXIMIZE_CONVERSION_VALUE, TARGET_CPA, TARGET_ROAS or TARGET_SPEND
            (maximize clicks).
        target_cpa_micros: Required for TARGET_CPA, optional for
            MAXIMIZE_CONVERSIONS.
        target_roas: Required for TARGET_ROAS, optional for
            MAXIMIZE_CONVERSION_VALUE.
        target_spend_micros: Optional max CPC for TARGET_SPEND.
        contains_eu_political_advertising: As in create_campaign.
        validate_only: When True, Google validates the whole request without
            creating anything. Use it to check before creating for real.

    Returns:
        dict with the resource names created (or, with validate_only, a
        confirmation that the request is valid).
    """
    if err := check_read_only():
        return err
    if err := check_max_budget(daily_budget_micros):
        return err

    if daily_budget_micros <= 0:
        return {"success": False, "error": "daily_budget_micros must be > 0."}
    if bool(logo_asset_resource_name) == bool(logo_image_url):
        return {
            "success": False,
            "error": (
                "Pass exactly one of logo_asset_resource_name or "
                "logo_image_url. Demand Gen video ads require a logo."
            ),
        }
    for label, texts in (
        ("headlines", headlines),
        ("long_headlines", long_headlines),
        ("descriptions", descriptions),
    ):
        if not texts or len(texts) > 5:
            return {
                "success": False,
                "error": f"{label} must have between 1 and 5 entries.",
            }
    if bidding_strategy_type not in _DEMAND_GEN_BIDDING_STRATEGIES:
        return {
            "success": False,
            "error": (
                f"bidding_strategy_type must be one of "
                f"{sorted(_DEMAND_GEN_BIDDING_STRATEGIES)} for Demand Gen."
            ),
        }
    channels = channels or _YOUTUBE_CHANNELS
    unknown = set(channels) - set(_ALL_CHANNELS)
    if unknown:
        return {
            "success": False,
            "error": (
                f"Unknown channels {sorted(unknown)}. Allowed: "
                f"{list(_ALL_CHANNELS)}"
            ),
        }
    for label, items, prefix in (
        ("geo_target_constants", geo_target_constants, "geoTargetConstants/"),
        ("language_constants", language_constants, "languageConstants/"),
    ):
        for item in items or []:
            if not isinstance(item, str) or not item.startswith(prefix):
                return {
                    "success": False,
                    "error": (
                        f"{label} entries must look like '{prefix}<id>', "
                        f"got: {item!r}"
                    ),
                }

    try:
        logo_data = _download_image(logo_image_url) if logo_image_url else None
    except Exception as ex:
        return {
            "success": False,
            "error": f"Could not download logo_image_url: {ex}",
        }

    try:
        client = get_googleads_client()
        service = client.get_service("GoogleAdsService")
        operations = []

        # Temporary (negative) IDs let later operations reference earlier
        # ones inside the same atomic mutate.
        budget_rn = f"customers/{customer_id}/campaignBudgets/-1"
        campaign_rn = f"customers/{customer_id}/campaigns/-2"
        ad_group_rn = f"customers/{customer_id}/adGroups/-3"
        video_rn = f"customers/{customer_id}/assets/-4"
        logo_rn = logo_asset_resource_name or f"customers/{customer_id}/assets/-5"

        op = client.get_type("MutateOperation")
        budget = op.campaign_budget_operation.create
        budget.resource_name = budget_rn
        budget.name = f"{campaign_name} - Budget"
        budget.amount_micros = daily_budget_micros
        budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
        # Demand Gen campaigns cannot use shared budgets.
        budget.explicitly_shared = False
        operations.append(op)

        op = client.get_type("MutateOperation")
        campaign = op.campaign_operation.create
        campaign.resource_name = campaign_rn
        campaign.name = campaign_name
        campaign.status = client.enums.CampaignStatusEnum.PAUSED
        campaign.advertising_channel_type = (
            client.enums.AdvertisingChannelTypeEnum.DEMAND_GEN
        )
        campaign.campaign_budget = budget_rn
        campaign.contains_eu_political_advertising = (
            contains_eu_political_advertising
        )
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
        operations.append(op)

        op = client.get_type("MutateOperation")
        ad_group = op.ad_group_operation.create
        ad_group.resource_name = ad_group_rn
        ad_group.name = ad_group_name or f"{campaign_name} - Video"
        ad_group.campaign = campaign_rn
        ad_group.status = client.enums.AdGroupStatusEnum.ENABLED
        selected = (
            ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels
        )
        for channel in _ALL_CHANNELS:
            setattr(selected, channel, channel in channels)
        operations.append(op)

        # Demand Gen targets locations and languages at the ad group level.
        for geo in geo_target_constants or []:
            op = client.get_type("MutateOperation")
            crit = op.ad_group_criterion_operation.create
            crit.ad_group = ad_group_rn
            crit.location.geo_target_constant = geo
            operations.append(op)
        for lang in language_constants or []:
            op = client.get_type("MutateOperation")
            crit = op.ad_group_criterion_operation.create
            crit.ad_group = ad_group_rn
            crit.language.language_constant = lang
            operations.append(op)

        op = client.get_type("MutateOperation")
        video = op.asset_operation.create
        video.resource_name = video_rn
        video.name = f"YouTube video {youtube_video_id}"
        video.youtube_video_asset.youtube_video_id = youtube_video_id
        operations.append(op)

        if logo_data is not None:
            op = client.get_type("MutateOperation")
            logo = op.asset_operation.create
            logo.resource_name = logo_rn
            logo.name = f"{business_name} logo"
            logo.type_ = client.enums.AssetTypeEnum.IMAGE
            logo.image_asset.data = logo_data
            operations.append(op)

        op = client.get_type("MutateOperation")
        ad_group_ad = op.ad_group_ad_operation.create
        ad_group_ad.ad_group = ad_group_rn
        ad_group_ad.status = client.enums.AdGroupAdStatusEnum.ENABLED
        ad = ad_group_ad.ad
        ad.name = f"{campaign_name} - {youtube_video_id}"
        ad.final_urls.append(final_url)
        info = ad.demand_gen_video_responsive_ad
        info.business_name.text = business_name
        for text, field in (
            (headlines, info.headlines),
            (long_headlines, info.long_headlines),
            (descriptions, info.descriptions),
        ):
            for t in text:
                asset = client.get_type("AdTextAsset")
                asset.text = t
                field.append(asset)
        video_ref = client.get_type("AdVideoAsset")
        video_ref.asset = video_rn
        info.videos.append(video_ref)
        logo_ref = client.get_type("AdImageAsset")
        logo_ref.asset = logo_rn
        info.logo_images.append(logo_ref)
        operations.append(op)

        request = client.get_type("MutateGoogleAdsRequest")
        request.customer_id = customer_id
        request.mutate_operations = operations
        request.validate_only = validate_only
        response = service.mutate(request=request)

        if validate_only:
            return {
                "success": True,
                "validate_only": True,
                "message": (
                    f"Valid: would create Demand Gen campaign "
                    f"'{campaign_name}' (PAUSED) with video "
                    f"{youtube_video_id} on {channels}. Nothing was created."
                ),
            }

        created = {}
        for result in response.mutate_operation_responses:
            kind = result._pb.WhichOneof("response")
            rn = getattr(result, kind).resource_name
            created.setdefault(kind.removesuffix("_result"), []).append(rn)
        return {
            "success": True,
            "created": created,
            "message": (
                f"Demand Gen campaign '{campaign_name}' created in PAUSED "
                f"status with video {youtube_video_id} on {channels}."
            ),
            "note": (
                "Campaign is PAUSED. Review it, then enable it in the Google "
                "Ads UI. The ad goes through policy review once enabled."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}
