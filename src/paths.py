"""Project paths and default configuration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
HTML_CACHE = CACHE_DIR / "html"
PDF_CACHE = CACHE_DIR / "pdf"
FETCH_CACHE_DIR = CACHE_DIR / "fetch_responses"
DOMAIN_CACHE_CSV = CACHE_DIR / "official_domains.csv"
WORKING_CSV = DATA_DIR / "prospects_working.csv"
REJECTED_CSV = DATA_DIR / "prospects_rejected.csv"
OUTREACH_CSV = DATA_DIR / "outreach.csv"
HARVEST_CONFIG_JSON = DATA_DIR / "harvest_config.json"
DEFAULT_MESSAGE_JSON = DATA_DIR / "default_message.json"
EXAMPLES_DIR = DATA_DIR / "examples"
JURISDICTIONS_CSV = DATA_DIR / "jurisdictions_filtered.csv"
MANUAL_URLS_CSV = DATA_DIR / "manual_urls.csv"
REVIEW_HTML = DATA_DIR / "review.html"
DIAGNOSTICS_CSV = DATA_DIR / "harvest_diagnostics.csv"

DEFAULT_STATES = "CT,DE,FL,GA,MI,MT,OR,PA,RI,VT,VA,WA,WI"
DEFAULT_MIN_POP = 20_000
DEFAULT_MAX_POP = 100_000

USER_AGENT = "ContactsDiscoveryTool/1.0 (local research; public .gov pages only)"

WORKING_COLUMNS = [
    "state",
    "jurisdiction_name",
    "geography_type",
    "population",
    "county_name",
    "official_website_url",
    "planning_department_url",
    "contact_name",
    "contact_title",
    "email",
    "email_source_url",
    "candidate_source_url",
    "discovery_method",
    "latest_plan_year_found",
    "active_update_signal",
    "prospect_priority",
    "prospect_priority_reason",
    "jurisdiction_match_status",
    "jurisdiction_match_notes",
    "notes",
    "review_status",
    "outreach_status",
    "_status",
]

OUTREACH_COLUMNS = [
    "approved",
    "greeting_name",
    "send_status",
    "sent_at",
    "reply_status",
    "first_reply_at",
    "meeting_requested",
    "meeting_scheduled_for",
    "meeting_completed",
    "follow_up_needed",
    "follow_up_at",
    "outreach_notes",
    "jurisdiction_type",
    "population",
    "jurisdiction_name",
    "state",
    "contact_name",
    "contact_title",
    "email",
    "jurisdiction_url",
    "email_source_url",
    "subject",
    "body",
    "message_customized",
    "default_message_version",
    "gmail_draft_id",
    "gmail_message_id",
    "prepared_at",
    "approved_at",
    "drafted_at",
    "error",
    "greeting_name_modified",
    "contact_name_modified",
    "contact_title_modified",
    "email_modified",
    "jurisdiction_type_modified",
    "population_modified",
    "jurisdiction_name_modified",
    "state_modified",
    "jurisdiction_url_modified",
    "email_source_url_modified",
    "reply_status_modified",
    "tracking_modified",
]

REPLY_STATUS_VALUES = (
    "not_sent",
    "sent_no_reply",
    "replied",
    "meeting_requested",
    "meeting_scheduled",
    "meeting_completed",
    "not_interested",
    "bounced",
    "wrong_contact",
    "do_not_contact",
)

EDITABLE_CONTENT_FIELDS = (
    "jurisdiction_type",
    "population",
    "jurisdiction_name",
    "state",
    "jurisdiction_url",
    "contact_name",
    "greeting_name",
    "contact_title",
    "email",
    "email_source_url",
)

EDITABLE_TRACKING_FIELDS = (
    "approved",
    "send_status",
    "reply_status",
    "first_reply_at",
    "meeting_requested",
    "meeting_scheduled_for",
    "meeting_completed",
    "follow_up_needed",
    "follow_up_at",
    "outreach_notes",
)

OUTREACH_PORT = 8765
EXPECTED_GMAIL_ACCOUNT = "vaidila@planzookie.com"
GMAIL_CACHE_DIR = CACHE_DIR / "gmail"

REJECTED_COLUMNS = [
    "state",
    "jurisdiction_name",
    "geography_type",
    "population",
    "rejection_reason",
    "email_found",
    "source_urls",
    "notes",
    "official_site_found",
    "planning_page_found",
    "pages_fetched_count",
    "pdfs_fetched_count",
    "raw_emails_found_count",
    "generic_emails_found_count",
    "candidate_titles_found_count",
    "direct_email_candidates_count",
    "best_rejection_reason",
    "search_urls_found",
    "search_urls_fetched",
    "manual_url_used",
    "manual_url_result",
    "candidate_source_url",
    "email_source_url",
    "discovery_method",
    "jurisdiction_match_notes",
    "candidate_name",
    "candidate_title",
]

DIAGNOSTICS_COLUMNS = [
    "state",
    "jurisdiction_name",
    "geography_type",
    "population",
    "official_domain",
    "planning_pages_found",
    "directory_pages_found",
    "staff_links_found",
    "profile_links_followed",
    "mailto_links_found",
    "emails_found",
    "candidate_titles_found",
    "pages_fetched",
    "search_queries_run",
    "found_contact",
    "final_rejection_reason",
    "elapsed_seconds",
    "cache_hits",
    "cache_misses",
    "profile_pages_followed",
    "early_stop",
    "max_page_limit_hit",
    "timeout_count",
    "fetch_error_count",
]
