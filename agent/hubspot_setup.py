"""
Creates all custom contact properties needed by the Conversion Engine.
Run once before using hubspot_handler.py.

Usage:
    uv run python agent/hubspot_setup.py
"""

import os
from dotenv import load_dotenv
from hubspot import HubSpot
from hubspot.crm.properties import PropertyCreate, PropertyGroupCreate
from hubspot.crm.properties.exceptions import ApiException

load_dotenv()

client = HubSpot(access_token=os.environ["HUBSPOT_ACCESS_TOKEN"])

# All custom properties to create
CUSTOM_PROPERTIES = [
    {
        "name": "lead_source",
        "label": "Lead Source (CE)",
        "type": "string",
        "field_type": "text",
        "description": "Where the lead came from: crunchbase_outbound, inbound_form, partner_referral",
    },
    {
        "name": "icp_segment",
        "label": "ICP Segment",
        "type": "string",
        "field_type": "text",
        "description": "ICP segment: recently_funded, restructuring, leadership_transition, capability_gap",
    },
    {
        "name": "ai_maturity_score",
        "label": "AI Maturity Score",
        "type": "number",
        "field_type": "number",
        "description": "0-3 integer scoring AI readiness from public signals",
    },
    {
        "name": "ai_maturity_conf",
        "label": "AI Maturity Confidence",
        "type": "string",
        "field_type": "text",
        "description": "Confidence in AI maturity score: high, medium, low",
    },
    {
        "name": "had_layoffs",
        "label": "Had Layoffs (120d)",
        "type": "enumeration",
        "field_type": "booleancheckbox",
        "description": "Whether the company had layoffs in the last 120 days per layoffs.fyi",
        "options": [
            {"label": "Yes", "value": "true", "displayOrder": 0, "hidden": False},
            {"label": "No",  "value": "false", "displayOrder": 1, "hidden": False},
        ],
    },
    {
        "name": "total_funding_usd",
        "label": "Total Funding (USD)",
        "type": "number",
        "field_type": "number",
        "description": "Total funding in USD from Crunchbase ODM",
    },
    {
        "name": "employee_count",
        "label": "Employee Count",
        "type": "number",
        "field_type": "number",
        "description": "Headcount from Crunchbase firmographics",
    },
    {
        "name": "booking_url",
        "label": "Booking URL",
        "type": "string",
        "field_type": "text",
        "description": "Cal.com booking link sent to the prospect",
    },
    {
        "name": "enrichment_timestamp",
        "label": "Enrichment Timestamp",
        "type": "string",
        "field_type": "text",
        "description": "ISO timestamp of the last enrichment pipeline run",
    },
    {
        "name": "pitch_angle",
        "label": "Pitch Angle",
        "type": "string",
        "field_type": "text",
        "description": "Which pitch angle was used for this prospect",
    },
    {
        "name": "signal_summary",
        "label": "Signal Summary",
        "type": "string",
        "field_type": "textarea",
        "description": "Human-readable summary of all hiring signals used for outreach",
    },
    {
        "name": "outreach_status",
        "label": "Outreach Status",
        "type": "string",
        "field_type": "text",
        "description": "Current outreach state: pending, contacted, replied, qualified, booked, opted_out",
    },
]

GROUP_NAME = "conversion_engine"


def ensure_group():
    """Create the property group if it doesn't exist."""
    try:
        client.crm.properties.groups_api.create(
            object_type="contacts",
            property_group_create=PropertyGroupCreate(
                name=GROUP_NAME,
                label="Conversion Engine",
            ),
        )
        print(f"  Created property group: {GROUP_NAME}")
    except ApiException as e:
        if "already exists" in str(e).lower() or e.status == 409:
            print(f"  Property group already exists: {GROUP_NAME}")
        else:
            raise


def create_property(prop: dict):
    """Create one custom property, skip if it already exists."""
    try:
        options = prop.pop("options", [])
        property_create = PropertyCreate(
            name=prop["name"],
            label=prop["label"],
            type=prop["type"],
            field_type=prop["field_type"],
            description=prop.get("description", ""),
            group_name=GROUP_NAME,
            options=options,
        )
        client.crm.properties.core_api.create(
            object_type="contacts",
            property_create=property_create,
        )
        print(f"  ✓ Created: {prop['name']}")
    except ApiException as e:
        if "already exists" in str(e).lower() or e.status == 409:
            print(f"  — Skipped (exists): {prop['name']}")
        else:
            print(f"  ✗ Failed: {prop['name']} — {e}")


def main():
    print("Setting up HubSpot custom properties...\n")
    ensure_group()
    print()
    for prop in CUSTOM_PROPERTIES:
        create_property(prop)
    print("\nDone. Re-run run_prospect.py now.")


if __name__ == "__main__":
    main()
