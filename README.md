# usdc_verifier — USDC payment verification on Base

Standalone, stdlib-only Python tool that verifies USDC (USDC on Base,
`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`, 6 decimals) payment
transactions and emits a JSON verification report.

## Usage

```bash
python usdc_verifier.py <tx_hash> [--rpc https://base-rpc.publicnode.com] [--to 0xADDR] [--amount 1.5]
python usdc_verifier.py --selftest
python test_usdc_verifier.py
```

Exit code 0 = verified payment found, 1 = verification failed.

## Checks performed

- Transaction exists on Base and receipt status is successful
- At least one USDC `Transfer` event in the receipt logs
- Optional `--to` recipient match and `--amount` value match (6 decimals)

## Files

- `usdc_verifier.py` — the verifier (stdlib only: urllib/json/hashlib)
- `test_usdc_verifier.py` — 16 unit tests, mocked RPC (no network)
- `sample-report.json` — live report for tx `0x792a2d01…0f228b` (block 54439396, 0.02 USDC)
- `SHA256SUMS.txt` — SHA-256 checksums of all deliverables
