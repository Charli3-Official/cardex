import os
import pytest
from dotenv import load_dotenv
from pycardano import Address, BlockFrostBackend, TransactionBuilder, TransactionOutput, Transaction

from charli3_dendrite.dexs.amm.minswap import MinswapCPPState
from charli3_dendrite.dataclasses.models import Assets

load_dotenv()

@pytest.fixture
def wallet_address():
    return os.getenv("WALLET_ADDRESS")

@pytest.fixture
def blockfrost_project_id():
    return os.getenv("BLOCKFROST_PROJECT_ID")

@pytest.fixture
def minswap_state():
    return MinswapCPPState()

def test_minswap_swap(wallet_address, blockfrost_project_id, minswap_state):
    backend = BlockFrostBackend(project_id=blockfrost_project_id)
    in_assets = Assets(lovelace=1000000)
    out_assets = Assets(lovelace=500000)

    utxos = minswap_state.gather_utxos(wallet_address)
    builder = TransactionBuilder(backend)
    swap_utxo, swap_datum = minswap_state.swap_utxo(
        address_source=Address(wallet_address),
        in_assets=in_assets,
        out_assets=out_assets,
    )
    builder.add_input(utxos[0])
    builder.add_output(swap_utxo)
    redeemer = minswap_state.create_redeemer()
    builder.add_redeemer(redeemer)
    minswap_state.handle_collateral(builder, utxos[1])
    transaction = builder.build()
    signed_transaction = minswap_state.sign_swap_transaction(transaction)

    assert isinstance(signed_transaction, Transaction)
    print(f"Signed transaction: {signed_transaction}")
