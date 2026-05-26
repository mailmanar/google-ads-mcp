# ads_mcp/tools/write.py

"""Write tools for Google Ads MCP — Responsive Search Ads."""

from typing import Optional

from ads_mcp.coordinator import mcp
from ads_mcp.tools._safety import (
    check_read_only,
    handle_googleads_exception,
)
from ads_mcp.utils import get_googleads_client
from google.ads.googleads.errors import GoogleAdsException


@mcp.tool()
def create_responsive_search_ad(
    customer_id: str,
    ad_group_id: str,
    final_url: str,
    headlines: list[str],
    descriptions: list[str],
    path1: str = "",
    path2: str = "",
) -> dict:
    """
    Creates a Responsive Search Ad (RSA) in an existing ad group.

    Args:
        customer_id: The Google Ads customer ID (no dashes), e.g. '1234567890'
        ad_group_id: The ad group ID where the RSA will be created
        final_url: The landing page URL, e.g. 'https://www.example.com'
        headlines: List of 3-15 headlines (max 30 chars each)
        descriptions: List of 2-4 descriptions (max 90 chars each)
        path1: Optional first display path (max 15 chars)
        path2: Optional second display path (max 15 chars), requires path1

    Returns:
        dict with the created ad's resource name
    """
    if err := check_read_only():
        return err

    if len(headlines) < 3:
        return {"error": "At least 3 headlines are required for an RSA."}
    if len(descriptions) < 2:
        return {"error": "At least 2 descriptions are required for an RSA."}
    if len(headlines) > 15:
        return {"error": "Maximum 15 headlines allowed for an RSA."}
    if len(descriptions) > 4:
        return {"error": "Maximum 4 descriptions allowed for an RSA."}

    for i, h in enumerate(headlines):
        if len(h) > 30:
            return {"error": f"Headline {i+1} exceeds 30 characters: '{h}'"}
    for i, d in enumerate(descriptions):
        if len(d) > 90:
            return {"error": f"Description {i+1} exceeds 90 characters: '{d}'"}
    if len(path1) > 15:
        return {"error": f"path1 exceeds 15 characters: '{path1}'"}
    if len(path2) > 15:
        return {"error": f"path2 exceeds 15 characters: '{path2}'"}

    try:
        client = get_googleads_client()
        ad_group_ad_service = client.get_service("AdGroupAdService")

        ad_group_resource_name = client.get_service(
            "AdGroupService"
        ).ad_group_path(customer_id, ad_group_id)

        operation = client.get_type("AdGroupAdOperation")
        operation.create.ad_group = ad_group_resource_name
        operation.create.status = client.enums.AdGroupAdStatusEnum.PAUSED
        operation.create.ad.final_urls.append(final_url)

        rsa = operation.create.ad.responsive_search_ad
        for headline_text in headlines:
            asset = client.get_type("AdTextAsset")
            asset.text = headline_text
            rsa.headlines.append(asset)
        for desc_text in descriptions:
            asset = client.get_type("AdTextAsset")
            asset.text = desc_text
            rsa.descriptions.append(asset)
        if path1:
            rsa.path1 = path1
        if path2:
            rsa.path2 = path2

        response = ad_group_ad_service.mutate_ad_group_ads(
            customer_id=customer_id,
            operations=[operation],
        )

        resource_name = response.results[0].resource_name
        return {
            "success": True,
            "resource_name": resource_name,
            "message": f"RSA created successfully (paused). Resource: {resource_name}",
            "note": "Ad was created in PAUSED status. Enable it manually or ask to enable it.",
        }

    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def update_responsive_search_ad(
    customer_id: str,
    ad_id: str,
    ad_group_id: str,
    final_url: Optional[str] = None,
    headlines: Optional[list[str]] = None,
    descriptions: Optional[list[str]] = None,
    path1: Optional[str] = None,
    path2: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """
    Updates an existing Responsive Search Ad (RSA).

    Args:
        customer_id: The Google Ads customer ID (no dashes), e.g. '1234567890'
        ad_id: The ID of the existing ad to update
        ad_group_id: The ad group ID that contains the ad
        final_url: New landing page URL (optional)
        headlines: New list of 3-15 headlines to replace existing ones (optional)
        descriptions: New list of 2-4 descriptions to replace existing ones (optional)
        path1: New first display path, max 15 chars (optional)
        path2: New second display path, max 15 chars (optional)
        status: New status — 'ENABLED' or 'PAUSED' (optional)

    Returns:
        dict with the updated ad's resource name
    """
    if err := check_read_only():
        return err

    if headlines is not None:
        if len(headlines) < 3:
            return {"error": "At least 3 headlines are required for an RSA."}
        if len(headlines) > 15:
            return {"error": "Maximum 15 headlines allowed."}
        for i, h in enumerate(headlines):
            if len(h) > 30:
                return {"error": f"Headline {i+1} exceeds 30 characters: '{h}'"}

    if descriptions is not None:
        if len(descriptions) < 2:
            return {"error": "At least 2 descriptions are required for an RSA."}
        if len(descriptions) > 4:
            return {"error": "Maximum 4 descriptions allowed."}
        for i, d in enumerate(descriptions):
            if len(d) > 90:
                return {"error": f"Description {i+1} exceeds 90 characters: '{d}'"}

    if path1 is not None and len(path1) > 15:
        return {"error": f"path1 exceeds 15 characters: '{path1}'"}
    if path2 is not None and len(path2) > 15:
        return {"error": f"path2 exceeds 15 characters: '{path2}'"}

    if status is not None and status not in ("ENABLED", "PAUSED"):
        return {"error": "status must be 'ENABLED' or 'PAUSED'."}

    try:
        client = get_googleads_client()
        ad_group_ad_service = client.get_service("AdGroupAdService")

        ad_group_ad_resource_name = ad_group_ad_service.ad_group_ad_path(
            customer_id, ad_group_id, ad_id
        )

        update_fields = []
        operation = client.get_type("AdGroupAdOperation")
        operation.update.resource_name = ad_group_ad_resource_name

        ad_headlines = []
        if headlines is not None:
            for headline_text in headlines:
                asset = client.get_type("AdTextAsset")
                asset.text = headline_text
                ad_headlines.append(asset)
            operation.update.ad.responsive_search_ad.headlines.extend(ad_headlines)
            update_fields.append("ad.responsive_search_ad.headlines")

        ad_descriptions = []
        if descriptions is not None:
            for desc_text in descriptions:
                asset = client.get_type("AdTextAsset")
                asset.text = desc_text
                ad_descriptions.append(asset)
            operation.update.ad.responsive_search_ad.descriptions.extend(ad_descriptions)
            update_fields.append("ad.responsive_search_ad.descriptions")

        if final_url is not None:
            operation.update.ad.final_urls.append(final_url)
            update_fields.append("ad.final_urls")

        if path1 is not None:
            operation.update.ad.responsive_search_ad.path1 = path1
            update_fields.append("ad.responsive_search_ad.path1")

        if path2 is not None:
            operation.update.ad.responsive_search_ad.path2 = path2
            update_fields.append("ad.responsive_search_ad.path2")

        if status is not None:
            operation.update.status = client.enums.AdGroupAdStatusEnum[status]
            update_fields.append("status")

        if not update_fields:
            return {
                "error": (
                    "No fields provided to update. Pass at least one of: "
                    "headlines, descriptions, final_url, path1, path2, status."
                )
            }

        from google.protobuf import field_mask_pb2

        operation.update_mask.CopyFrom(
            field_mask_pb2.FieldMask(paths=update_fields)
        )

        response = ad_group_ad_service.mutate_ad_group_ads(
            customer_id=customer_id,
            operations=[operation],
        )

        resource_name = response.results[0].resource_name
        return {
            "success": True,
            "resource_name": resource_name,
            "updated_fields": update_fields,
            "message": f"RSA updated successfully. Fields changed: {', '.join(update_fields)}",
        }

    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}


@mcp.tool()
def set_ad_status(
    customer_id: str,
    ad_group_id: str,
    ad_id: str,
    status: str,
) -> dict:
    """
    Pauses or enables an existing ad. Works for any ad type, not just RSAs.

    Args:
        customer_id: Google Ads customer ID (no dashes).
        ad_group_id: The ad group that contains the ad.
        ad_id: The ad's ID. Discover via the search tool:
            SELECT ad_group_ad.ad.id, ad_group_ad.status
            FROM ad_group_ad WHERE ad_group.id = <ad_group_id>
        status: 'ENABLED' or 'PAUSED'.

    Returns:
        dict with the ad's resource_name on success.
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
        ad_group_ad_service = client.get_service("AdGroupAdService")
        resource_name = ad_group_ad_service.ad_group_ad_path(
            customer_id, ad_group_id, ad_id
        )

        operation = client.get_type("AdGroupAdOperation")
        operation.update.resource_name = resource_name
        operation.update.status = client.enums.AdGroupAdStatusEnum[status]

        from google.protobuf import field_mask_pb2

        operation.update_mask.CopyFrom(
            field_mask_pb2.FieldMask(paths=["status"])
        )

        response = ad_group_ad_service.mutate_ad_group_ads(
            customer_id=customer_id, operations=[operation]
        )
        return {
            "success": True,
            "resource_name": response.results[0].resource_name,
            "message": f"Ad {ad_id} set to {status}.",
        }

    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}
