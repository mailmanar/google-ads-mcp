# ads_mcp/tools/write_audiences.py

"""Write tools for retargeting/remarketing audiences (UserList)."""

from typing import Optional

from ads_mcp.coordinator import mcp
from ads_mcp.tools._safety import (
    check_read_only,
    handle_googleads_exception,
)
from ads_mcp.utils import get_googleads_client
from google.ads.googleads.errors import GoogleAdsException


_VALID_URL_OPS = {"EQUALS", "CONTAINS", "STARTS_WITH", "ENDS_WITH"}


@mcp.tool()
def create_remarketing_user_list(
    customer_id: str,
    name: str,
    description: str,
    url_match_value: str,
    url_match_op: str = "CONTAINS",
    membership_lifespan_days: int = 540,
) -> dict:
    """
    Creates a rule-based remarketing UserList that captures visitors whose
    page URL matches a single rule. For more complex rule sets (multiple
    items / groups), edit in the Google Ads UI after creation.

    Args:
        customer_id: Google Ads customer ID.
        name: Unique list name.
        description: Human description of who is captured.
        url_match_value: The URL substring/value to match.
        url_match_op: 'EQUALS', 'CONTAINS' (default), 'STARTS_WITH', 'ENDS_WITH'.
        membership_lifespan_days: How long users stay in the list (1-540, default 540).

    Returns:
        dict with the user_list resource_name on success.
    """
    if err := check_read_only():
        return err

    if url_match_op not in _VALID_URL_OPS:
        return {
            "success": False,
            "error": f"url_match_op must be one of {sorted(_VALID_URL_OPS)}",
        }
    if not (1 <= membership_lifespan_days <= 540):
        return {
            "success": False,
            "error": "membership_lifespan_days must be between 1 and 540.",
        }
    if not url_match_value:
        return {"success": False, "error": "url_match_value is required."}

    try:
        client = get_googleads_client()
        service = client.get_service("UserListService")

        op = client.get_type("UserListOperation")
        ul = op.create
        ul.name = name
        ul.description = description
        ul.membership_status = client.enums.UserListMembershipStatusEnum.OPEN
        ul.membership_life_span = membership_lifespan_days

        # Rule: URL <op> url_match_value
        rule_item = client.get_type("UserListRuleItemInfo")
        rule_item.name = "url__"  # Google's reserved name for the page URL
        rule_item.string_rule_item.operator = (
            client.enums.UserListStringRuleItemOperatorEnum[url_match_op]
        )
        rule_item.string_rule_item.value = url_match_value

        rule_item_group = client.get_type("UserListRuleItemGroupInfo")
        rule_item_group.rule_items.append(rule_item)

        rule_info = ul.rule_based_user_list.flexible_rule_user_list.inclusive_rule_operands.add()
        rule_info.rule_item_groups.append(rule_item_group)

        ul.rule_based_user_list.flexible_rule_user_list.inclusive_operands_operator = (
            client.enums.UserListFlexibleRuleOperatorEnum.AND
        )

        response = service.mutate_user_lists(
            customer_id=customer_id, operations=[op]
        )
        return {
            "success": True,
            "resource_name": response.results[0].resource_name,
            "message": (
                f"Remarketing list '{name}' created with rule: "
                f"url {url_match_op} '{url_match_value}', lifespan "
                f"{membership_lifespan_days} days."
            ),
            "note": (
                "List will start populating once your remarketing tag fires "
                "on pages matching the rule."
            ),
        }
    except GoogleAdsException as ex:
        return handle_googleads_exception(ex)
    except Exception as ex:
        return {"success": False, "error": str(ex)}
