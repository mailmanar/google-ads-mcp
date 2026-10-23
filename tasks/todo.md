# Write-tools expansion — plan

Adding mutate/write capabilities to the Google Ads MCP, beyond the existing RSA create/update.

## Open questions for Mariano (decide before building)

1. **Campaign type scope** — Search only, or also Display / Performance Max / Demand Gen?
   The Google Ads API surface diverges sharply by type:
   - Search: simple — campaign + ad groups + keyword criteria + RSAs.
   - Performance Max: no ad groups; uses asset groups, audience signals.
   - Display: similar to Search but different criterion options.

   *Building all four roughly triples the work and the test surface. Recommendation: Search-only for v1, expand later.*

2. **"Audience signals" vs "retargeting audiences"** — these are distinct API concepts:
   - **Audience signals** is a Performance Max term (`AssetGroupSignal`).
   - **Retargeting / remarketing** uses `UserList` + applying it as a `CampaignCriterion` or `AdGroupCriterion`.
   - Plain Search/Display "audiences" use `CampaignCriterion` with `AudienceInfo` / `UserListInfo`.

   Which do you actually want?

3. **Granularity** — one tool per operation (e.g. `create_campaign`, `create_campaign_budget`, `create_ad_group` separately) vs higher-level workflow tools (e.g. `create_search_campaign_with_adgroup` that creates budget + campaign + ad group atomically)?
   *Recommendation: low-level tools, since the LLM can compose them. Workflow tools come later if you find the LLM struggles to chain.*

4. **Bidding strategy scope** — standard (set on the campaign) or portfolio (`BiddingStrategy` resource shared across campaigns)?
   *Recommendation: standard for v1 — covers 90% of use cases and is one mutate call.*

5. **Extensions/assets level** — campaign, ad group, or customer (account-wide)?
   *Recommendation: support customer + campaign in v1; ad-group rare.*

## Assumed answers (challenge if wrong)

- Search campaigns only.
- "Audience signals" interpreted as **Search/Display audience targeting via `CampaignCriterion`** (most common).
- "Retargeting audiences" interpreted as **creating `UserList` resources** (rule-based remarketing lists).
- Low-level one-tool-per-operation.
- Standard bidding only.
- Customer + campaign level for assets.

## Phase 0 — Safety scaffold ✅

- [x] `check_read_only()` helper in `ads_mcp/tools/_safety.py`.
- [x] `check_max_budget(amount_micros)` helper.
- [x] `handle_googleads_exception(ex)` helper.
- [x] Refactored existing RSA create/update to use these helpers + dropped the dead-code block in create_responsive_search_ad.

## Phase 1 — Campaign hierarchy (in `write_hierarchy.py`) ✅

- [x] `create_campaign_budget` (status hardcode: `explicitly_shared=False`; budget cap enforced).
- [x] `create_campaign(channel_type=SEARCH|DISPLAY|VIDEO)` — supports YouTube via VIDEO channel; PAUSED hardcoded; bidding strategy selected from MANUAL_CPC, MANUAL_CPM, MANUAL_CPV, MAXIMIZE_CONVERSIONS, MAXIMIZE_CONVERSION_VALUE, TARGET_CPA, TARGET_ROAS, TARGET_SPEND, TARGET_IMPRESSION_SHARE.
- [x] `create_ad_group(channel_type, ad_group_type)` — defaults type per channel, validates combinations.
- [x] `set_campaign_bidding_strategy` with proper oneof field-mask path.

## Phase 2 — Targeting (in `write_targeting.py`) ✅

- [x] `add_keywords` — bulk insert, PAUSED, EXACT/PHRASE/BROAD.
- [x] `add_negative_keywords` — campaign or ad-group level.
- [x] `add_geo_targets` — accepts `geoTargetConstants/N` resource names; supports `negative=True`.
- [x] `add_audience_targets` — applies `UserList` resource as criterion at campaign or ad-group level.

## Phase 3 — Extensions / assets (in `write_assets.py`) ✅

- [x] `create_sitelink_asset` (link_text + final_url + optional description1/2 with paired-set validation).
- [x] `create_callout_asset`.
- [x] `attach_asset(level=CUSTOMER|CAMPAIGN, field_type)` — covers SITELINK, CALLOUT, plus 8 other field types.

## Phase 4 — Retargeting (in `write_audiences.py`) ✅

- [x] `create_remarketing_user_list` — single-rule URL match (CONTAINS/EQUALS/STARTS_WITH/ENDS_WITH), 1-540 day lifespan.

## Verification ✅

- [x] Container rebuilds clean, all imports succeed.
- [x] `tools/list` over MCP returns 17 tools (was 5; +12 new). All 12 expected names present.
- [x] `GOOGLE_ADS_READ_ONLY=true` blocks every one of the 14 write tools (verified via direct call to each fn body).
- [x] `MAX_DAILY_BUDGET_MICROS=500000` rejects 1M-micro budget; 400k passes through to the Google Ads API (which then 400'd on bogus customer_id — confirms full auth chain works).
- [ ] Manual end-to-end smoke test against a real customer: budget → campaign → ad group → keyword → RSA → sitelink → attach. **Pending — Mariano to run.**
- [ ] `nox -s lint` — pending; lint config exists, will likely flag minor whitespace.

## Out of scope (explicitly deferred)

- Performance Max / Demand Gen / Display campaigns
- Portfolio bidding strategies
- Customer Match / Similar Audiences user lists
- Ad-group level extensions
- Geo lookup by name (caller passes constants)
- Bulk / batched mutates across services

## YouTube video campaigns via Demand Gen (feat/demand-gen-video-campaign)

- [x] Confirmed the API cannot create VIDEO campaigns (Google docs, Oct 2026); Demand Gen is the supported path.
- [x] `create_demand_gen_video_campaign`: budget + DEMAND_GEN campaign (PAUSED) + ad group with YouTube-only channel controls + geo/language + YouTube video asset + logo (existing asset or URL) + DemandGenVideoResponsiveAd, in one atomic GoogleAdsService.Mutate. Supports validate_only.
- [x] Verified with validate_only on 1893155347 for video 0cpMc-7RFu8 with both logo paths. A fake video ID is rejected with VIDEO_NOT_FOUND.
- [ ] Not verified: a real (non-validate) create, and call_to_actions / breadcrumbs (not exposed yet).

## YouTube video upload (feat/youtube-video-upload)

- [x] `upload_youtube_video`: downloads a video from a link (Drive share links converted to direct downloads), uploads it via YouTubeVideoUploadService (Google-managed channel by default, UNLISTED), waits for PROCESSED and returns the video ID.
- [x] Verified: tool registers (29), Drive URL conversion, status query on you_tube_video_upload, HTML-page rejection, request built correctly with the upload RPC stubbed.
- [ ] Not verified: a real upload to YouTube.
