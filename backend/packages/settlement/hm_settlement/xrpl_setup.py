"""Create funded XRPL *testnet* wallets for the demo: `python -m hm_settlement.xrpl_setup [--write-env]`.

Creates a payer wallet (XRPL_WALLET_SEED) and a receiving account (XRPL_DESTINATION_ADDRESS) from the
public testnet faucet. The payer wallet also becomes the issuer of a testnet IOU (stablecoin-style token)
and the receiver sets up a trustline for it. With --write-env the values are written to the git-ignored
.env; otherwise they are printed. Testnet XRP has no value, but still never commit seeds.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from hm_core.config import find_env_file
from hm_settlement.settings import get_settlement_settings


def _upsert_env(path: Path, values: dict[str, str]) -> None:
    text = path.read_text() if path.exists() else ""
    for key, value in values.items():
        line = f"{key}={value}"
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        text = pattern.sub(line, text) if pattern.search(text) else text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text)


def _create_trustline(client: Any, receiver_wallet: Any, issuer_address: str, currency: str) -> str:
    """Create a trustline from the receiver to the issuer for the given currency."""
    from xrpl.models.amounts import IssuedCurrencyAmount
    from xrpl.models.transactions import TrustSet
    from xrpl.transaction import submit_and_wait

    limit_amount = IssuedCurrencyAmount(
        currency=currency,
        issuer=issuer_address,
        value="1000000000",  # high limit for testnet demo
    )
    trustline_tx = TrustSet(
        account=receiver_wallet.classic_address,
        limit_amount=limit_amount,
    )
    result = submit_and_wait(trustline_tx, client, receiver_wallet)
    return result.result.get("hash", "")


def main() -> None:
    from xrpl.clients import JsonRpcClient
    from xrpl.wallet import generate_faucet_wallet

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-env", action="store_true", help="write values into .env (git-ignored)")
    parser.add_argument("--currency", default="USD", help="IOU currency code (default: USD)")
    args = parser.parse_args()

    settings = get_settlement_settings()
    client = JsonRpcClient(settings.xrpl_network_url)
    print("requesting two faucet wallets from the XRPL testnet (takes ~20s)...")
    payer = generate_faucet_wallet(client)
    receiver = generate_faucet_wallet(client)

    print(f"payer (also IOU issuer): {payer.classic_address}")
    print(f"receiver:                {receiver.classic_address}")

    print(f"\nsetting up trustline for {args.currency} IOU from receiver to issuer...")
    trustline_hash = _create_trustline(client, receiver, payer.classic_address, args.currency)
    print(f"trustline tx: https://testnet.xrpl.org/transactions/{trustline_hash}")

    values = {
        "SETTLEMENT_ADAPTER": "xrpl",
        "XRPL_WALLET_SEED": payer.seed or "",
        "XRPL_DESTINATION_ADDRESS": receiver.classic_address,
        "XRPL_IOU_ISSUER": payer.classic_address,
        "XRPL_IOU_CURRENCY": args.currency,
        "XRPL_USE_IOU": "true",
    }

    if args.write_env:
        env = Path(find_env_file() or ".env")
        _upsert_env(env, values)
        print("\nwrote SETTLEMENT_ADAPTER, XRPL_WALLET_SEED, XRPL_DESTINATION_ADDRESS,")
        print(f"XRPL_IOU_ISSUER, XRPL_IOU_CURRENCY, XRPL_USE_IOU to {env}")
    else:
        print("\nadd to .env (do not commit):")
        for key, value in values.items():
            print(f"  {key}={value}")


if __name__ == "__main__":
    main()
