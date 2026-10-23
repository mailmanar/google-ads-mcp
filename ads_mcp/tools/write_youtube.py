# ads_mcp/tools/write_youtube.py

"""Write tool for uploading videos to YouTube through the Google Ads API."""

import os
import re
import shutil
import tempfile
import time
import urllib.request
from typing import Optional

from ads_mcp.coordinator import mcp
from ads_mcp.tools._safety import check_read_only, handle_googleads_exception
from ads_mcp.utils import get_googleads_client
from google.ads.googleads.errors import GoogleAdsException


_VALID_PRIVACY = {"UNLISTED", "PUBLIC"}
_VALID_DISCLOSURE = {"NON_GENERATIVE_CONTENT", "GENERATIVE_CONTENT"}
_FINAL_STATES = {"PROCESSED", "FAILED", "REJECTED", "UNAVAILABLE"}
_DRIVE_FILE_ID = re.compile(
    r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:.*&)?id=)([\w-]+)"
)


def _direct_download_url(url: str) -> str:
    """Turns a Google Drive share link into a direct download link.

    The usercontent endpoint with confirm=t skips the virus-scan warning page
    Drive shows for large files. Other URLs are returned unchanged.
    """
    match = _DRIVE_FILE_ID.search(url)
    if match:
        return (
            "https://drive.usercontent.google.com/download"
            f"?id={match.group(1)}&export=download&confirm=t"
        )
    return url


def _upload_state(client, customer_id: str, resource_name: str):
    query = (
        "SELECT you_tube_video_upload.state, you_tube_video_upload.video_id "
        "FROM you_tube_video_upload "
        f"WHERE you_tube_video_upload.resource_name = '{resource_name}'"
    )
    service = client.get_service("GoogleAdsService")
    for row in service.search(customer_id=customer_id, query=query):
        upload = row.you_tube_video_upload
        return upload.state.name, upload.video_id
    return None, None


@mcp.tool()
def upload_youtube_video(
    customer_id: str,
    video_url: str,
    title: str,
    description: str = "",
    channel_id: Optional[str] = None,
    privacy: str = "UNLISTED",
    generative_content_disclosure: Optional[str] = None,
    wait_seconds: int = 240,
) -> dict:
    """
    Uploads a video file to YouTube through the Google Ads API, so it can be
    used in ads (e.g. create_demand_gen_video_campaign's youtube_video_id).

    The MCP server runs remotely, so it cannot read files on the caller's
    computer: pass a link it can download. Google Drive share links work if
    the file is shared as "Anyone with the link"; Dropbox links need ?dl=1.

    Args:
        customer_id: Google Ads customer ID (no dashes).
        video_url: Public download link of the video file (mp4, mov, ...).
        title: Video title, required, max 100 characters, no '<' or '>'.
        description: Optional, max 5000 characters, no '<' or '>'.
        channel_id: The advertiser's own YouTube channel ID ('UC...', 24
            characters). Omit to upload to the Google-managed channel of the
            Ads account, which only allows UNLISTED videos.
        privacy: 'UNLISTED' (default) or 'PUBLIC' (own channel only).
        generative_content_disclosure: 'GENERATIVE_CONTENT' if the video
            contains realistic AI-generated content, else
            'NON_GENERATIVE_CONTENT'. Optional.
        wait_seconds: How long to wait for YouTube to finish processing and
            return the video ID (0 to return right after the upload). If it
            is not done in time, check later with the search tool:
            SELECT you_tube_video_upload.state, you_tube_video_upload.video_id
            FROM you_tube_video_upload

    Returns:
        dict with the upload resource_name, state and, once processed, the
        youtube_video_id.
    """
    if err := check_read_only():
        return err

    if not title or len(title) > 100:
        return {"success": False, "error": "title is required, max 100 characters."}
    if len(description) > 5000:
        return {"success": False, "error": "description max is 5000 characters."}
    if privacy not in _VALID_PRIVACY:
        return {
            "success": False,
            "error": f"privacy must be one of {sorted(_VALID_PRIVACY)}",
        }
    if privacy == "PUBLIC" and not channel_id:
        return {
            "success": False,
            "error": (
                "PUBLIC needs channel_id: the Google-managed channel only "
                "allows UNLISTED."
            ),
        }
    if (
        generative_content_disclosure
        and generative_content_disclosure not in _VALID_DISCLOSURE
    ):
        return {
            "success": False,
            "error": (
                f"generative_content_disclosure must be one of "
                f"{sorted(_VALID_DISCLOSURE)}"
            ),
        }

    # Stream to a temporary file rather than memory: videos can be large.
    tmp = tempfile.NamedTemporaryFile(suffix=".video", delete=False)
    try:
        try:
            req = urllib.request.Request(
                _direct_download_url(video_url),
                headers={"User-Agent": "google-ads-mcp"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                content_type = resp.headers.get("Content-Type", "")
                shutil.copyfileobj(resp, tmp, length=1024 * 1024)
            tmp.close()
        except Exception as ex:
            return {
                "success": False,
                "error": f"Could not download video_url: {ex}",
            }

        if content_type.startswith("text/html"):
            return {
                "success": False,
                "error": (
                    "video_url returned a web page, not a video file. Share "
                    "the file publicly or use a direct download link."
                ),
            }
        size = os.path.getsize(tmp.name)

        try:
            client = get_googleads_client()
            service = client.get_service("YouTubeVideoUploadService")
            request = client.get_type("CreateYouTubeVideoUploadRequest")
            request.customer_id = customer_id
            upload = request.you_tube_video_upload
            upload.video_title = title
            if description:
                upload.video_description = description
            if channel_id:
                upload.channel_id = channel_id
            upload.video_privacy = privacy
            if generative_content_disclosure:
                upload.video_content_metadata.generative_content_disclosure = (
                    generative_content_disclosure
                )
            with open(tmp.name, "rb") as stream:
                response = service.create_you_tube_video_upload(
                    stream=stream, request=request, retry=None
                )
            resource_name = response.resource_name

            state, video_id = _upload_state(client, customer_id, resource_name)
            deadline = time.monotonic() + max(0, wait_seconds)
            while state not in _FINAL_STATES and time.monotonic() < deadline:
                time.sleep(10)
                state, video_id = _upload_state(
                    client, customer_id, resource_name
                )
        except GoogleAdsException as ex:
            return handle_googleads_exception(ex)
        except Exception as ex:
            return {"success": False, "error": str(ex)}

        out = {
            "success": state not in {"FAILED", "REJECTED", "UNAVAILABLE"},
            "resource_name": resource_name,
            "state": state,
            "bytes_uploaded": size,
        }
        if video_id:
            out["youtube_video_id"] = video_id
            out["youtube_url"] = f"https://www.youtube.com/watch?v={video_id}"
        if state == "PROCESSED":
            out["message"] = f"Video uploaded and processed: {video_id}."
        elif out["success"]:
            out["message"] = (
                "Uploaded; YouTube is still processing it. Check the state "
                "later with the search tool on you_tube_video_upload."
            )
        else:
            out["error"] = f"YouTube reported the upload as {state}."
        return out
    finally:
        tmp.close()
        os.unlink(tmp.name)
