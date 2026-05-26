# ads_mcp/tools/write_assets.py

"""Write tools for ad assets / extensions: sitelinks, callouts, and linking."""

from typing import Optional

from ads_mcp.coordinator import mcp
from ads_mcp.tools._safety import (
    check_read_only,
    handle_googleads_exception,
)
from ads_mcp.utils import get_googleads_client
from google.ads.googleads.errors import GoogleAdsException


_VALID_ASSET_FIELD_TYPES = {
    "SITELINK",
    "CALLOUT",
    "STRUCTURED_SNIPPET",
    "MOBILE_APP",
    "HOTEL_CALLOUT",
    "CALL",
    "PRICE",
    "PROMOTION",
    "BUSINESS_NAME",
    "BUSINESS_LOGO",
}


@mcp.tool()
def create_sitelink_asset(
    customer_id: str,
    link_text: str,
    final_url: str,
    description1: Optional[str] = None,
    description2: Optional[str] = None,
) -> dict:
    """
    Creates a sitelink asset. Use attach_asset to link it to a campaign or
    customer-level scope.

    Args:
        customer_id: Google Ads customer ID.
        link_text: Anchor text shown in the ad (max 25 chars).
        final_url: Landing page URL.
        description1: Optional first description line (max 35 chars).
        description2: Optional second description line (max 35 chars).
            Both descriptions must be set together if either is set.

    Returns:
        dict with the asset's resource_name on success.
    """
    if err := check_read_only():
        return err

    if len(link_text) > 25:
        return {
            "success": False,
            "error": f"link_text exceeds 25 chars: '{link_text}'",
        }
    if description1 is not None and len(description1) > 35:
        return {"success": False, "error": "description1 exceeds 35 chars."}
    if description2 is not None and len(description2) > 35:
        return {"success": False, "error": "description2 exceeds 35 chars."}
    if (description1 is None) != (description2 is None):
        return {
            "success": False,
            "error": "description1 and description2 must both be set or both omitted.",
        }

    try:
        client = get_googleads_client()
        service = client.get_service("AssetService")

        op = client.get_type("AssetOperation")
        asset = op.create
        asset.final_urls.append(final_url)
        asset.sitelink_asset.link_text = link_text
        if description1 is not None:
            asset.sitelink_asset.description1 = description1
        if description2 is not None:
            asset.sitelink_asset.description2 = description2

        response = service.mutate_assets(
            customer_id=customer_id, operations=[op]
        )
        return {
            "success": True,
            "resource_name": response.results[0].resource_name,
            "message": (
                f"Sitelink asset created. Use attach_asset(field_type='SITELINK') "
                f"to link it to a campaign or the account."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def create_callout_asset(
    customer_id: str,
    callout_text: str,
) -> dict:
    """
    Creates a callout asset.

    Args:
        customer_id: Google Ads customer ID.
        callout_text: Callout text (max 25 chars).

    Returns:
        dict with the asset's resource_name on success.
    """
    if err := check_read_only():
        return err

    if len(callout_text) > 25:
        return {
            "success": False,
            "error": f"callout_text exceeds 25 chars: '{callout_text}'",
        }

    try:
        client = get_googleads_client()
        service = client.get_service("AssetService")

        op = client.get_type("AssetOperation")
        op.create.callout_asset.callout_text = callout_text

        response = service.mutate_assets(
            customer_id=customer_id, operations=[op]
        )
        return {
            "success": True,
            "resource_name": response.results[0].resource_name,
            "message": (
                "Callout asset created. Use attach_asset(field_type='CALLOUT')."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def attach_asset(
    customer_id: str,
    asset_resource_name: str,
    field_type: str,
    level: str = "CUSTOMER",
    campaign_id: Optional[str] = None,
) -> dict:
    """
    Links an existing asset to either the customer (account-wide) or a campaign.

    Args:
        customer_id: Google Ads customer ID.
        asset_resource_name: Full asset resource name returned by
            create_sitelink_asset / create_callout_asset.
        field_type: AssetFieldType — typically 'SITELINK' or 'CALLOUT'.
        level: 'CUSTOMER' (default, account-wide) or 'CAMPAIGN'.
        campaign_id: Required if level='CAMPAIGN'.

    Returns:
        dict with the link resource_name on success.
    """
    if err := check_read_only():
        return err

    if field_type not in _VALID_ASSET_FIELD_TYPES:
        return {
            "success": False,
            "error": (
                f"field_type must be one of {sorted(_VALID_ASSET_FIELD_TYPES)}"
            ),
        }
    if level not in ("CUSTOMER", "CAMPAIGN"):
        return {"success": False, "error": "level must be 'CUSTOMER' or 'CAMPAIGN'."}
    if level == "CAMPAIGN" and not campaign_id:
        return {
            "success": False,
            "error": "campaign_id is required when level='CAMPAIGN'.",
        }

    try:
        client = get_googleads_client()
        field_type_enum = client.enums.AssetFieldTypeEnum[field_type]

        if level == "CUSTOMER":
            service = client.get_service("CustomerAssetService")
            op = client.get_type("CustomerAssetOperation")
            op.create.asset = asset_resource_name
            op.create.field_type = field_type_enum
            response = service.mutate_customer_assets(
                customer_id=customer_id, operations=[op]
            )
        else:
            service = client.get_service("CampaignAssetService")
            op = client.get_type("CampaignAssetOperation")
            campaign_resource_name = client.get_service(
                "CampaignService"
            ).campaign_path(customer_id, campaign_id)
            op.create.asset = asset_resource_name
            op.create.campaign = campaign_resource_name
            op.create.field_type = field_type_enum
            response = service.mutate_campaign_assets(
                customer_id=customer_id, operations=[op]
            )

        return {
            "success": True,
            "resource_name": response.results[0].resource_name,
            "message": f"Asset linked at {level} level as {field_type}.",
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}
