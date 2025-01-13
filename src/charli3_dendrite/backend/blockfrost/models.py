"""Pydantic models for the Blockfrost API."""

from typing import Optional

from charli3_dendrite.dataclasses.models import BaseList
from charli3_dendrite.dataclasses.models import DendriteBaseModel


class AssetAmount(DendriteBaseModel):
    """Model for the asset amount in a UTxO."""

    unit: str
    quantity: str


class UTxO(DendriteBaseModel):
    """Model for the UTxO data."""

    address: str
    tx_hash: str
    output_index: int
    amount: list[AssetAmount]
    block: str
    data_hash: Optional[str] = None
    inline_datum: Optional[str] = None
    reference_script_hash: Optional[str] = None


class UTxOList(BaseList):
    """Model for the UTxO list data."""

    root: list[UTxO]


class TransactionInfo(DendriteBaseModel):
    """Model for the transaction info data."""

    block_time: int
    index: int
    block: str


class BlockFrostBlockInfo(DendriteBaseModel):
    """Model for the block info data."""

    time: int
    height: int


class PoolOutput(DendriteBaseModel):
    """Model for the pool output data."""

    address: str
    tx_hash: str
    output_index: int
    amount: list[AssetAmount]
    block: str
    data_hash: Optional[str] = None
    inline_datum: Optional[str] = None
    reference_script_hash: Optional[str] = None


class PoolOutputList(BaseList):
    """Model for the pool output list data."""

    root: list[PoolOutput]


def parse_pool_outputs(data: dict) -> PoolOutputList:
    """Parse pool outputs from the given data."""
    pool_outputs = [PoolOutput(**item) for item in data]
    return PoolOutputList(root=pool_outputs)


def select_utxos_for_swaps(utxos: UTxOList, required_amount: int) -> list[UTxO]:
    """Select UTxOs for swaps based on the required amount."""
    selected_utxos = []
    total_amount = 0

    for utxo in utxos:
        selected_utxos.append(utxo)
        total_amount += int(utxo.amount[0].quantity)  # Assuming the first asset is the one we need

        if total_amount >= required_amount:
            break

    return selected_utxos
