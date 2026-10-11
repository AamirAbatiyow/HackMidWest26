"""Create funded XRPL *testnet* wallets for the demo: `python -m hm_settlement.xrpl_setup [--write-env]`.

Creates a payer wallet (XRPL_WALLET_SEED) and a receiving account (XRPL_DESTINATION_ADDRESS) from the
public testnet faucet. With --write-env the values are written to the git-ignored .env; otherwise
they are printed. Testnet XRP has no value, but still never commit seeds.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from hm_core.config import find_env_file
from hm_settlement.settings import get_settlement_settings


def _upsert_env(path: Path, values: dict[str, str]) -> None:
    text = path.read_text() if path.exists() else ""
    for key, value in values.items():
        line = f"{key}={value}"
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        text = pattern.sub(line, text) if pattern.search(text) else text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text)


def main() -> None:
    from xrpl.clients import JsonRpcClient
    from xrpl.wallet import generate_faucet_wallet

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-env", action="store_true", help="write values into .env (git-ignored)")
    args = parser.parse_args()

    client = JsonRpcClient(get_settlement_settings().xrpl_network_url)
    print("requesting two faucet wallets from the XRPL testnet (takes ~20s)...")
    payer = generate_faucet_wallet(client)
    receiver = generate_faucet_wallet(client)
    values = {
        "SETTLEMENT_ADAPTER": "xrpl",
        "XRPL_WALLET_SEED": payer.seed or "",
        "XRPL_DESTINATION_ADDRESS": receiver.classic_address,
    }
    print(f"payer:    {payer.classic_address}")
    print(f"receiver: {receiver.classic_address}")
    if args.write_env:
        env = Path(find_env_file() or ".env")
        _upsert_env(env, values)
        print(f"wrote SETTLEMENT_ADAPTER, XRPL_WALLET_SEED, XRPL_DESTINATION_ADDRESS to {env}")
    else:
        print("add to .env (do not commit):")
        for key, value in values.items():
            print(f"  {key}={value}")


if __name__ == "__main__":
    main()
