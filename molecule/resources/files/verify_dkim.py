#!/usr/bin/env python3
"""Verify a delivered test mail's DKIM signatures without real DNS.

Usage: verify_dkim.py MBOX SUBJECT RECORDS_FILE EXPECTED_SELECTOR[,...]

RECORDS_FILE holds "<name>. <TXT value>" lines (what the role reported);
dkimpy is handed those instead of querying DNS. Fails unless the mail is
signed by exactly the expected selectors and every signature verifies.
"""

import email
import mailbox
import sys

import dkim


def main():
    mbox_path, subject, records_path, expected = sys.argv[1:5]
    expected = set(expected.split(","))

    records = {}
    with open(records_path) as f:
        for line in f:
            name, _, value = line.strip().partition(" ")
            if name:
                records[name] = value.encode()

    def fake_dns(name, timeout=5):
        if isinstance(name, bytes):
            name = name.decode()
        return records.get(name if name.endswith(".") else name + ".")

    box = mailbox.mbox(mbox_path)
    raw = None
    for key in box.keys():
        candidate = box.get_bytes(key)
        if email.message_from_bytes(candidate)["Subject"] == subject:
            raw = candidate
    if raw is None:
        sys.exit(f"no mail with subject {subject!r} in {mbox_path}")

    headers = email.message_from_bytes(raw).get_all("DKIM-Signature") or []
    if not headers:
        sys.exit("mail carries no DKIM-Signature header")

    selectors = set()
    for header in headers:
        tags = dict(
            part.strip().split("=", 1) for part in header.split(";") if "=" in part
        )
        selectors.add("".join(tags["s"].split()))
    if selectors != expected:
        sys.exit(f"signed by selectors {sorted(selectors)}, expected {sorted(expected)}")

    verifier = dkim.DKIM(raw)
    for idx in range(len(headers)):
        try:
            ok = verifier.verify(idx=idx, dnsfunc=fake_dns)
        except dkim.DKIMException as e:
            sys.exit(f"DKIM signature #{idx} did not verify: {e}")
        if not ok:
            sys.exit(f"DKIM signature #{idx} did not verify")

    print(f"OK: {len(headers)} signature(s) by {sorted(selectors)} verified")


if __name__ == "__main__":
    main()
