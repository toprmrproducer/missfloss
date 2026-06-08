#!/usr/bin/env python3
"""
Outbound call dispatcher.

Usage — single call:
  python make_call.py --phone +919876543210 --lead "Rahul Sharma" \
      --business "HealthFirst Clinic" --service "Dental Checkup"

Usage — batch from CSV:
  python make_call.py --batch leads.csv --delay 3

CSV format (header row required):
  phone,lead_name,business_name,service_type

Optional — inject a custom system prompt from a file:
  python make_call.py --phone +91... --system_prompt_file my_script.txt
"""

import argparse
import asyncio
import csv
import json
import os
import random
import sys
from pathlib import Path

from dotenv import load_dotenv
from livekit import api

load_dotenv(".env")


async def dispatch_call(
    lk_api: api.LiveKitAPI,
    phone: str,
    lead_name: str = "there",
    business_name: str = "our company",
    service_type: str = "our service",
    system_prompt: str = None,
) -> dict:
    """
    Dispatch one outbound call job to the LiveKit worker.
    Returns the dispatch result dict.
    """
    room_name = f"call-{phone.replace('+', '')}-{random.randint(1000, 9999)}"

    metadata = {
        "phone_number": phone,
        "lead_name": lead_name,
        "business_name": business_name,
        "service_type": service_type,
        "system_prompt": system_prompt,
    }

    request = api.CreateAgentDispatchRequest(
        agent_name="outbound-caller-shreyas",
        room=room_name,
        metadata=json.dumps(metadata),
    )

    dispatch = await lk_api.agent_dispatch.create_dispatch(request)
    return {"dispatch_id": dispatch.id, "room": room_name, "phone": phone}


async def run_single(args) -> None:
    system_prompt = None
    if args.system_prompt_file:
        system_prompt = Path(args.system_prompt_file).read_text(encoding="utf-8")

    lk_api = _make_api_client()
    try:
        result = await dispatch_call(
            lk_api,
            phone=args.phone,
            lead_name=args.lead or "there",
            business_name=args.business or "our company",
            service_type=args.service or "our service",
            system_prompt=system_prompt,
        )
        print(f"\n✅ Call dispatched!")
        print(f"   Phone    : {result['phone']}")
        print(f"   Room     : {result['room']}")
        print(f"   Dispatch : {result['dispatch_id']}")
    except Exception as exc:
        print(f"\n❌ Dispatch failed: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        await lk_api.aclose()


async def run_batch(args) -> None:
    csv_path = Path(args.batch)
    if not csv_path.exists():
        print(f"❌ CSV file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    rows = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        print("❌ CSV file is empty.", file=sys.stderr)
        sys.exit(1)

    delay = max(1, int(args.delay or 3))
    print(f"📋 Batch: {len(rows)} calls, {delay}s delay between each\n")

    lk_api = _make_api_client()
    try:
        for i, row in enumerate(rows, start=1):
            phone = row.get("phone", "").strip()
            if not phone:
                print(f"  [{i}/{len(rows)}] SKIP — no phone number")
                continue
            if not phone.startswith("+"):
                print(f"  [{i}/{len(rows)}] SKIP — phone must start with '+': {phone}")
                continue

            try:
                result = await dispatch_call(
                    lk_api,
                    phone=phone,
                    lead_name=row.get("lead_name", "there").strip(),
                    business_name=row.get("business_name", "our company").strip(),
                    service_type=row.get("service_type", "our service").strip(),
                )
                print(
                    f"  [{i}/{len(rows)}] ✅ {phone} → room {result['room']} "
                    f"(dispatch {result['dispatch_id']})"
                )
            except Exception as exc:
                print(f"  [{i}/{len(rows)}] ❌ {phone} → {exc}")

            if i < len(rows):
                await asyncio.sleep(delay)

    finally:
        await lk_api.aclose()

    print(f"\n✅ Batch complete — {len(rows)} calls dispatched.")


def _make_api_client() -> api.LiveKitAPI:
    url = os.getenv("LIVEKIT_URL")
    key = os.getenv("LIVEKIT_API_KEY")
    secret = os.getenv("LIVEKIT_API_SECRET")

    if not (url and key and secret):
        print(
            "❌ Missing LiveKit credentials. Set LIVEKIT_URL, LIVEKIT_API_KEY, "
            "LIVEKIT_API_SECRET in your .env file.",
            file=sys.stderr,
        )
        sys.exit(1)

    return api.LiveKitAPI(url=url, api_key=key, api_secret=secret)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dispatch outbound AI calls via LiveKit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Single-call args
    parser.add_argument("--phone", help="Phone number to call (E.164 format, e.g. +91...)")
    parser.add_argument("--lead", help="Lead's full name")
    parser.add_argument("--business", help="Business / clinic name")
    parser.add_argument("--service", help="Service type being offered")
    parser.add_argument(
        "--system_prompt_file",
        help="Path to a .txt file containing a custom system prompt",
    )

    # Batch args
    parser.add_argument("--batch", help="Path to CSV file for batch calling")
    parser.add_argument(
        "--delay",
        type=int,
        default=3,
        help="Seconds to wait between batch calls (default: 3)",
    )

    args = parser.parse_args()

    if args.batch:
        asyncio.run(run_batch(args))
    elif args.phone:
        if not args.phone.startswith("+"):
            print("❌ Phone number must start with '+' and include the country code.")
            sys.exit(1)
        asyncio.run(run_single(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
