#!/usr/bin/env python3
"""usdc_verifier.py — Verify USDC payment transactions on Base chain.

Standalone, stdlib-only tool. Given a transaction hash it fetches the
receipt from a Base JSON-RPC endpoint, parses USDC Transfer events and
emits a JSON verification report.

USDC on Base: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 (6 decimals)
Transfer topic: keccak256("Transfer(address,address,uint256)")
            = 0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef

Usage:
  python usdc_verifier.py <tx_hash> [--rpc URL] [--to 0xADDR] [--amount 1.5]
  python usdc_verifier.py --selftest          # offline fixture check

Exit code 0 = verified payment found, 1 = verification failed / error.
"""

import argparse
import hashlib
import json
import sys
import urllib.request

USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)
DEFAULT_RPC = "https://mainnet.base.org"
USDC_DECIMALS = 6


def rpc_call(rpc_url, method, params, timeout=20):
    """Minimal JSON-RPC POST. Returns the 'result' field or raises."""
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode()
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "usdc-verifier/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    if "error" in body:
        raise RuntimeError(f"RPC error: {body['error']}")
    return body.get("result")


def normalize_addr(addr):
    if not isinstance(addr, str):
        return None
    a = addr.lower()
    if a.startswith("0x") and len(a) == 42:
        try:
            int(a, 16)
            return a
        except ValueError:
            return None
    return None


def topic_to_address(topic):
    """Extract the low 20 bytes of a 32-byte address topic."""
    if not isinstance(topic, str) or not topic.startswith("0x") or len(topic) != 66:
        return None
    return "0x" + topic[-40:].lower()


def parse_transfer_logs(receipt, usdc_address=USDC_BASE):
    """Return list of {from,to,value_raw,value_usdc,log_index} for USDC Transfers."""
    transfers = []
    for log in receipt.get("logs", []):
        if (log.get("address") or "").lower() != usdc_address.lower():
            continue
        topics = log.get("topics", [])
        if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC:
            continue
        data = log.get("data", "0x")
        try:
            value_raw = int(data, 16)
        except ValueError:
            continue
        transfers.append(
            {
                "log_index": int(log.get("logIndex", "0x0"), 16)
                if isinstance(log.get("logIndex"), str)
                else log.get("logIndex", 0),
                "from": topic_to_address(topics[1]),
                "to": topic_to_address(topics[2]),
                "value_raw": str(value_raw),
                "value_usdc": value_raw / (10 ** USDC_DECIMALS),
            }
        )
    transfers.sort(key=lambda t: t["log_index"])
    return transfers


def verify_transaction(tx_hash, rpc_url=DEFAULT_RPC, expect_to=None, expect_amount=None):
    """Fetch and verify a transaction. Returns a report dict."""
    report = {
        "tool": "usdc_verifier",
        "version": "1.0.0",
        "chain": "base",
        "chain_id": 8453,
        "usdc_contract": USDC_BASE,
        "tx_hash": tx_hash,
        "checks": {},
        "transfers": [],
        "verified": False,
        "errors": [],
    }

    tx_hash = (tx_hash or "").strip().lower()
    if not (tx_hash.startswith("0x") and len(tx_hash) == 66):
        report["errors"].append("tx_hash must be a 0x-prefixed 32-byte hex string")
        return report

    try:
        tx = rpc_call(rpc_url, "eth_getTransactionByHash", [tx_hash])
    except Exception as e:  # noqa: BLE001 - report any transport failure
        report["errors"].append(f"eth_getTransactionByHash failed: {e}")
        return report

    if tx is None:
        report["errors"].append("transaction not found on Base")
        return report

    try:
        receipt = rpc_call(rpc_url, "eth_getTransactionReceipt", [tx_hash])
    except Exception as e:  # noqa: BLE001
        report["errors"].append(f"eth_getTransactionReceipt failed: {e}")
        return report

    if receipt is None:
        report["errors"].append("transaction receipt not found (still pending?)")
        return report

    status = receipt.get("status")
    report["checks"]["tx_exists"] = True
    report["checks"]["status_success"] = status == "0x1"
    report["block_number"] = int(receipt.get("blockNumber", "0x0"), 16)
    report["from"] = tx.get("from")
    report["to"] = tx.get("to")

    if status != "0x1":
        report["errors"].append(f"transaction status is {status} (not successful)")
        return report

    transfers = parse_transfer_logs(receipt)
    report["transfers"] = transfers
    report["checks"]["usdc_transfer_found"] = len(transfers) > 0

    if expect_to:
        want = normalize_addr(expect_to)
        report["checks"]["to_matches"] = any(t["to"] == want for t in transfers)
        if not report["checks"]["to_matches"]:
            report["errors"].append(
                f"no USDC transfer to expected address {want}"
            )
    if expect_amount is not None:
        report["checks"]["amount_matches"] = any(
            abs(t["value_usdc"] - float(expect_amount)) < 1e-9 for t in transfers
        )
        if not report["checks"]["amount_matches"]:
            report["errors"].append(
                f"no USDC transfer of {expect_amount} found"
            )

    core_ok = (
        report["checks"]["tx_exists"]
        and report["checks"]["status_success"]
        and report["checks"]["usdc_transfer_found"]
    )
    extras_ok = all(
        v for k, v in report["checks"].items() if k in ("to_matches", "amount_matches")
    )
    report["verified"] = bool(core_ok and extras_ok)
    return report


# --- offline self-test fixture -------------------------------------------

FIXTURE_RECEIPT = {
    "status": "0x1",
    "blockNumber": "0x100",
    "logs": [
        {
            "address": USDC_BASE,
            "logIndex": "0x0",
            "topics": [
                TRANSFER_TOPIC,
                "0x" + "11" * 12 + "aa" * 20,
                "0x" + "22" * 12 + "bb" * 20,
            ],
            "data": hex(1_500_000),  # 1.5 USDC
        },
        {
            "address": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            "logIndex": "0x1",
            "topics": [TRANSFER_TOPIC],
            "data": "0x0",
        },
    ],
}


def _selftest():
    transfers = parse_transfer_logs(FIXTURE_RECEIPT)
    assert len(transfers) == 1, transfers
    t = transfers[0]
    assert t["value_usdc"] == 1.5, t
    assert t["from"] == "0x" + "aa" * 20
    assert t["to"] == "0x" + "bb" * 20
    print(json.dumps({"selftest": "ok", "parsed": t}, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify USDC payments on Base")
    ap.add_argument("tx_hash", nargs="?", help="0x transaction hash")
    ap.add_argument("--rpc", default=DEFAULT_RPC, help="Base JSON-RPC URL")
    ap.add_argument("--to", help="expected recipient address (0x...)")
    ap.add_argument("--amount", type=float, help="expected USDC amount")
    ap.add_argument("--selftest", action="store_true", help="offline fixture check")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.tx_hash:
        ap.error("tx_hash required (or --selftest)")

    report = verify_transaction(
        args.tx_hash, rpc_url=args.rpc, expect_to=args.to, expect_amount=args.amount
    )
    print(json.dumps(report, indent=2))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
