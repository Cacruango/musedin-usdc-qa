#!/usr/bin/env python3
"""Unit tests for usdc_verifier.py — stdlib unittest, no network."""

import unittest
from unittest.mock import patch

import usdc_verifier as uv


GOOD_TX = "0x" + "ab" * 32
USDC = uv.USDC_BASE
TT = uv.TRANSFER_TOPIC


def _log(frm_byte, to_byte, raw, idx=0, contract=USDC):
    return {
        "address": contract,
        "logIndex": hex(idx),
        "topics": [
            TT,
            "0x" + "00" * 12 + frm_byte * 20,
            "0x" + "00" * 12 + to_byte * 20,
        ],
        "data": hex(raw),
    }


def _receipt(logs, status="0x1", block="0x100"):
    return {"status": status, "blockNumber": block, "logs": logs}


def _tx():
    return {"from": "0x" + "cc" * 20, "to": "0x" + "dd" * 20}


class FakeRPC:
    """Scriptable stand-in for uv.rpc_call."""

    def __init__(self, tx=None, receipt=None, raise_on=None):
        self.tx = tx
        self.receipt = receipt
        self.raise_on = raise_on or set()

    def __call__(self, url, method, params, timeout=20):
        if method in self.raise_on:
            raise RuntimeError("boom")
        if method == "eth_getTransactionByHash":
            return self.tx
        if method == "eth_getTransactionReceipt":
            return self.receipt
        raise AssertionError(method)


class ParseTests(unittest.TestCase):
    def test_parses_single_transfer(self):
        logs = [_log("aa", "bb", 2_500_000, idx=3)]
        out = uv.parse_transfer_logs(_receipt(logs))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["value_usdc"], 2.5)
        self.assertEqual(out[0]["from"], "0x" + "aa" * 20)
        self.assertEqual(out[0]["to"], "0x" + "bb" * 20)

    def test_ignores_non_usdc_contract(self):
        logs = [_log("aa", "bb", 1000, contract="0x" + "99" * 20)]
        self.assertEqual(uv.parse_transfer_logs(_receipt(logs)), [])

    def test_ignores_non_transfer_topic(self):
        log = _log("aa", "bb", 1000)
        log["topics"][0] = "0x" + "ff" * 32
        self.assertEqual(uv.parse_transfer_logs(_receipt([log])), [])

    def test_sorts_by_log_index(self):
        logs = [_log("aa", "bb", 1_000_000, idx=5), _log("cc", "dd", 2_000_000, idx=1)]
        out = uv.parse_transfer_logs(_receipt(logs))
        self.assertEqual([t["value_usdc"] for t in out], [2.0, 1.0])

    def test_bad_data_skipped(self):
        log = _log("aa", "bb", 0)
        log["data"] = "0xzz"
        self.assertEqual(uv.parse_transfer_logs(_receipt([log])), [])


class VerifyTests(unittest.TestCase):
    def _run(self, tx, receipt, **kw):
        with patch.object(uv, "rpc_call", FakeRPC(tx=tx, receipt=receipt)):
            return uv.verify_transaction(GOOD_TX, **kw)

    def test_happy_path_verified(self):
        r = self._run(
            _tx(),
            _receipt([_log("aa", "bb", 1_000_000)]),
        )
        self.assertTrue(r["verified"])
        self.assertTrue(r["checks"]["usdc_transfer_found"])

    def test_failed_tx_not_verified(self):
        r = self._run(_tx(), _receipt([_log("aa", "bb", 1)], status="0x0"))
        self.assertFalse(r["verified"])
        self.assertFalse(r["checks"]["status_success"])
        self.assertTrue(any("status" in e for e in r["errors"]))

    def test_no_usdc_log_not_verified(self):
        r = self._run(_tx(), _receipt([]))
        self.assertFalse(r["verified"])
        self.assertFalse(r["checks"]["usdc_transfer_found"])

    def test_tx_not_found(self):
        with patch.object(uv, "rpc_call", FakeRPC(tx=None)):
            r = uv.verify_transaction(GOOD_TX)
        self.assertFalse(r["verified"])
        self.assertTrue(any("not found" in e for e in r["errors"]))

    def test_pending_receipt(self):
        r = self._run(_tx(), None)
        self.assertFalse(r["verified"])
        self.assertTrue(any("pending" in e for e in r["errors"]))

    def test_to_match_pass(self):
        r = self._run(
            _tx(),
            _receipt([_log("aa", "bb", 1_000_000)]),
            expect_to="0x" + "bb" * 20,
        )
        self.assertTrue(r["checks"]["to_matches"])
        self.assertTrue(r["verified"])

    def test_to_match_fail(self):
        r = self._run(
            _tx(),
            _receipt([_log("aa", "bb", 1_000_000)]),
            expect_to="0x" + "ee" * 20,
        )
        self.assertFalse(r["checks"]["to_matches"])
        self.assertFalse(r["verified"])

    def test_amount_match(self):
        r = self._run(
            _tx(),
            _receipt([_log("aa", "bb", 2_000_000)]),
            expect_amount=2.0,
        )
        self.assertTrue(r["checks"]["amount_matches"])
        self.assertTrue(r["verified"])

    def test_amount_mismatch(self):
        r = self._run(
            _tx(),
            _receipt([_log("aa", "bb", 2_000_000)]),
            expect_amount=3.0,
        )
        self.assertFalse(r["checks"]["amount_matches"])

    def test_bad_tx_hash(self):
        r = uv.verify_transaction("not-a-hash")
        self.assertFalse(r["verified"])
        self.assertTrue(any("32-byte" in e for e in r["errors"]))

    def test_rpc_error_reported(self):
        with patch.object(
            uv, "rpc_call", FakeRPC(raise_on={"eth_getTransactionByHash"})
        ):
            r = uv.verify_transaction(GOOD_TX)
        self.assertFalse(r["verified"])
        self.assertTrue(any("failed" in e for e in r["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
