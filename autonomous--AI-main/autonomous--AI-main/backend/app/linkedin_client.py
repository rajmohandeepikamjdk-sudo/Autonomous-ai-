"""
Thin client for LinkedIn's Posts API (part of the Community Management API).
Posting requires a member access token with the w_member_social scope,
obtained via LinkedIn's 3-legged OAuth flow (see README "Connecting
LinkedIn"). This module only handles the actual POST call — getting the
token is a one-time manual setup step, not something the agent does itself.
"""
import httpx

from app.config import get_settings
from app.logging_config import log_event

settings = get_settings()

LINKEDIN_POSTS_URL = "https://api.linkedin.com/rest/posts"


class LinkedInPublishError(Exception):
    pass


async def publish_to_linkedin(title: str, body: str, cycle_id: str | None = None) -> str | None:
    """Publishes a text post to the configured LinkedIn member profile.
    Returns the new post's URN on success, or None if LinkedIn posting is
    disabled/unconfigured. Raises LinkedInPublishError on a real API failure
    so the caller can decide whether that should be fatal (it shouldn't —
    see publisher.py, this is best-effort exactly like the vector memory
    write).
    """
    if not settings.LINKEDIN_ENABLED:
        return None
    if not settings.LINKEDIN_ACCESS_TOKEN or not settings.LINKEDIN_PERSON_URN:
        log_event("LinkedInPublisher", "LINKEDIN_ENABLED=true but token/URN missing, skipping", "WARNING", cycle_id)
        return None

    # LinkedIn posts are plain text (no markdown) with a practical length
    # LinkedIn itself enforces (~3000 chars) — trim so the API call doesn't
    # get rejected on very long drafts.
    commentary = f"{title}\n\n{body}".strip()
    if len(commentary) > 2900:
        commentary = commentary[:2897].rstrip() + "..."

    payload = {
        "author": settings.LINKEDIN_PERSON_URN,
        "commentary": commentary,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": settings.LINKEDIN_API_VERSION,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(LINKEDIN_POSTS_URL, json=payload, headers=headers)

    if resp.status_code not in (200, 201):
        raise LinkedInPublishError(f"LinkedIn API {resp.status_code}: {resp.text[:300]}")

    post_urn = resp.headers.get("x-restli-id") or resp.headers.get("X-RestLi-Id")
    log_event("LinkedInPublisher", f"Posted to LinkedIn (urn={post_urn})", cycle_id=cycle_id)
    return post_urn
