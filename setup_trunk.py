"""One-shot LiveKit SIP trunk creator pointing at Vobiz.

Usage:  python setup_trunk.py
Writes OUTBOUND_TRUNK_ID back into .env on success.
"""
import asyncio, os, re
from pathlib import Path
from dotenv import load_dotenv
from livekit import api as lk_api

load_dotenv(".env")

async def main():
    url = os.environ["LIVEKIT_URL"]
    key = os.environ["LIVEKIT_API_KEY"]
    secret = os.environ["LIVEKIT_API_SECRET"]
    domain = os.environ["VOICELINK_SIP_DOMAIN"]
    username = os.environ["VOICELINK_USERNAME"]
    password = os.environ["VOICELINK_PASSWORD"]
    number = os.environ["VOICELINK_OUTBOUND_NUMBER"]

    lk = lk_api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
    try:
        # Look for existing trunk first
        existing = await lk.sip.list_sip_outbound_trunk(lk_api.ListSIPOutboundTrunkRequest())
        for t in (existing.items or []):
            if t.address == domain:
                print(f"REUSE existing trunk: {t.sip_trunk_id}")
                _write_env("OUTBOUND_TRUNK_ID", t.sip_trunk_id)
                return

        trunk = await lk.sip.create_sip_outbound_trunk(
            lk_api.CreateSIPOutboundTrunkRequest(
                trunk=lk_api.SIPOutboundTrunkInfo(
                    name="vobiz-outbound",
                    address=domain,
                    numbers=[number],
                    auth_username=username,
                    auth_password=password,
                )
            )
        )
        print(f"CREATED trunk: {trunk.sip_trunk_id}")
        _write_env("OUTBOUND_TRUNK_ID", trunk.sip_trunk_id)
    finally:
        await lk.aclose()


def _write_env(key: str, value: str):
    env_path = Path(".env")
    txt = env_path.read_text()
    if re.search(rf"^{key}=.*$", txt, re.MULTILINE):
        txt = re.sub(rf"^{key}=.*$", f"{key}={value}", txt, flags=re.MULTILINE)
    else:
        txt += f"\n{key}={value}\n"
    env_path.write_text(txt)
    print(f"   .env updated: {key}={value}")


if __name__ == "__main__":
    asyncio.run(main())
