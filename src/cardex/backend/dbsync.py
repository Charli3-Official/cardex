# noqa
import os

import psycopg_pool
from dotenv import load_dotenv
from psycopg.rows import dict_row
from pycardano import Address

from cardex.dataclasses.models import BlockList
from cardex.dataclasses.models import PoolStateList
from cardex.dataclasses.models import SwapTransactionList

load_dotenv()

DBSYNC_USER = os.environ.get("DBSYNC_USER", None)
DBSYNC_PASS = os.environ.get("DBSYNC_PASS", None)
DBSYNC_HOST = os.environ.get("DBSYNC_HOST", None)
DBSYNC_PORT = os.environ.get("DBSYNC_PORT", None)

if DBSYNC_HOST is not None:
    conninfo = (
        f"host={DBSYNC_HOST} port={DBSYNC_PORT} dbname=cexplorer "
        + f"user={DBSYNC_USER} password={DBSYNC_PASS}"
    )
    pool = psycopg_pool.ConnectionPool(
        conninfo=conninfo,
        open=False,
        min_size=1,
        max_size=10,
    )
    pool.open()
    pool.wait()


def db_query(query: str, args: tuple | None = None) -> list[tuple]:
    """Fetch results from a query."""
    with pool.connection() as conn:  # noqa: SIM117
        with conn.cursor(row_factory=dict_row) as cursor:
            # with conn.cursor() as cursor:
            cursor.execute(query, args)
            return cursor.fetchall()


POOL_SELECTOR = """
SELECT txo.address,
ENCODE(tx.hash, 'hex') as "tx_hash",
txo.index as "tx_index",
EXTRACT(
	epoch
	FROM block.time
)::INTEGER AS "block_time",
tx.block_index as "block_index",
ENCODE(block.hash,'hex') as "block_hash",
ENCODE(datum.hash,'hex') as "datum_hash",
ENCODE(datum.bytes,'hex') as "datum_cbor",
COALESCE (
    json_build_object('lovelace',txo.value::TEXT)::jsonb || (
        SELECT json_agg(
            json_build_object(
                CONCAT(encode(ma.policy, 'hex'), encode(ma.name, 'hex')),
                mto.quantity::TEXT
            )
        )
        FROM ma_tx_out mto
        JOIN multi_asset ma ON (mto.ident = ma.id)
        WHERE mto.tx_out_id = txo.id
    )::jsonb,
    jsonb_build_array(json_build_object('lovelace',txo.value::TEXT)::jsonb)
) AS "assets",
(txo.inline_datum_id IS NOT NULL OR txo.reference_script_id IS NOT NULL) as "plutus_v2"
"""

ORDER_SELECTOR = """
SELECT (
	SELECT array_agg(DISTINCT txo.address)
	FROM tx_out txo
	LEFT JOIN tx_in txi ON txo.tx_id = txi.tx_out_id AND txo.index = txi.tx_out_index
	WHERE txi.tx_in_id = txo_stake.tx_id
) AS "submit_address_inputs",
ENCODE(tx.hash, 'hex') as "submit_tx_hash",
txo_stake.index as "submit_tx_index",
ENCODE(block.hash,'hex') as "submit_block_hash",
EXTRACT(
	epoch
	FROM block.time
)::INTEGER AS "submit_block_time",
tx.block_index AS "submit_block_index",
(
	SELECT array_agg(tx_metadata.json)
	FROM tx_metadata
	WHERE tx.id = tx_metadata.tx_id
) AS "submit_metadata",
COALESCE(
	json_build_object('lovelace',txo_stake.value::TEXT)::jsonb || (
		SELECT json_agg(
			json_build_object(
				CONCAT(encode(ma.policy, 'hex'), encode(ma.name, 'hex')),
				mto.quantity::TEXT
			)
		)
		FROM ma_tx_out mto
		JOIN multi_asset ma ON (mto.ident = ma.id)
		WHERE mto.tx_out_id = txo_stake.id
	)::jsonb,
	jsonb_build_array(json_build_object('lovelace',txo_stake.value::TEXT)::jsonb)
) AS "submit_assets",
ENCODE(datum.hash,'hex') as "submit_datum_hash",
ENCODE(datum.bytes,'hex') as "submit_datum_cbor",
txo_output.address,
ENCODE(txo_output.tx_hash, 'hex') as "tx_hash",
txo_output.tx_index as "tx_index",
EXTRACT(
	epoch
	FROM txo_output.block_time
)::INTEGER AS "block_time",
txo_output.block_index AS "block_index",
ENCODE(txo_output.block_hash,'hex') AS "block_hash",
ENCODE(txo_output.datum_hash, 'hex') AS "datum_hash",
ENCODE(txo_output.datum_bytes, 'hex') AS "datum_cbor",
COALESCE(
	json_build_object('lovelace',txo_output.value::TEXT)::jsonb || (
		SELECT json_agg(
			json_build_object(
				CONCAT(encode(ma.policy, 'hex'), encode(ma.name, 'hex')),
				mto.quantity::TEXT
			)
		)
		FROM ma_tx_out mto
		JOIN multi_asset ma ON (mto.ident = ma.id)
		WHERE mto.tx_out_id = txo_output.tx_id
	)::jsonb,
	jsonb_build_array(json_build_object('lovelace',txo_stake.value::TEXT)::jsonb)
) AS "assets",
(txo_output.inline_datum_id IS NOT NULL OR txo_output.reference_script_id IS NOT NULL) as "plutus_v2"
"""


def get_pool_utxos(
    assets: list[str] | None = None,
    addresses: list[str] | None = None,
    limit: int = 1000,
    page: int = 0,
    historical: bool = True,
) -> PoolStateList:
    """Get transactions by policy or address."""
    error_msg = "Either policies or addresses must be defined, not both."
    if assets is None and addresses is None:
        raise ValueError(error_msg)

    if assets is not None and addresses is not None:
        raise ValueError(error_msg)

    # Use the pool selector to format the output
    datum_selector = POOL_SELECTOR

    # If assets are specified, select assets
    if assets is not None:
        datum_selector += """FROM (
    SELECT ma.policy, ma.name, ma.id
    FROM multi_asset ma
    WHERE policy = ANY(%(policies)b) AND name = ANY(%(names)b)
) as ma
JOIN ma_tx_out mtxo ON ma.id = mtxo.ident
LEFT JOIN tx_out txo ON mtxo.tx_out_id = txo.id
"""

    # If address is specified, select addresses
    else:
        datum_selector += """FROM (
    SELECT *
    FROM tx_out
    WHERE tx_out.address = ANY(%(addresses)s)
) as txo"""

    datum_selector += """
LEFT JOIN tx ON txo.tx_id = tx.id
LEFT JOIN datum ON txo.data_hash = datum.hash
LEFT JOIN block ON tx.block_id = block.id"""

    if not historical:
        datum_selector += """
LEFT JOIN tx_in ON tx_in.tx_out_id = txo.tx_id AND tx_in.tx_out_index = txo.index
WHERE tx_in.tx_in_id IS NULL AND datum.hash IS NOT NULL
"""
    else:
        datum_selector += """
WHERE datum.hash IS NOT NULL
"""

    datum_selector += """
LIMIT %(limit)s
OFFSET %(offset)s
"""

    values = {"limit": limit, "offset": page * limit}
    if assets is not None:
        values.update({"policies": [bytes.fromhex(p[:56]) for p in assets]})
        values.update({"names": [bytes.fromhex(p[56:]) for p in assets]})

    elif addresses is not None:
        values.update({"addresses": addresses})

    r = db_query(datum_selector, values)

    return PoolStateList.model_validate(r)


def get_pool_in_tx(
    tx_hash: str,
    assets: list[str] | None = None,
    addresses: list[str] | None = None,
) -> PoolStateList:
    """Get transactions by policy or address."""
    error_msg = "Either policies or addresses must be defined, not both."
    if assets is None and addresses is None:
        raise ValueError(error_msg)

    if assets is not None and addresses is not None:
        raise ValueError(error_msg)

    # Use the pool selector to format the output
    datum_selector = POOL_SELECTOR

    # If assets are specified, select assets
    if assets is not None:
        datum_selector += """FROM (
    SELECT ma.policy, ma.name, ma.id
    FROM multi_asset ma
    WHERE policy = ANY(%(policies)b) AND name = ANY(%(names)b)
) as ma
JOIN ma_tx_out mtxo ON ma.id = mtxo.ident
LEFT JOIN tx_out txo ON mtxo.tx_out_id = txo.id
"""

    # If address is specified, select addresses
    else:
        datum_selector += """FROM (
    SELECT *
    FROM tx_out
    WHERE tx_out.address = ANY(%(addresses)s)
) as txo"""

    datum_selector += """
LEFT JOIN tx ON txo.tx_id = tx.id
LEFT JOIN datum ON txo.data_hash = datum.hash
LEFT JOIN block ON tx.block_id = block.id
WHERE datum.hash IS NOT NULL AND tx.hash = DECODE(%(tx_hash)s, 'hex')
"""

    values = {"tx_hash": tx_hash}
    if assets is not None:
        values.update({"policies": [bytes.fromhex(p[:56]) for p in assets]})
        values.update({"names": [bytes.fromhex(p[56:]) for p in assets]})

    elif addresses is not None:
        values.update({"addresses": addresses})

    r = db_query(datum_selector, values)

    return PoolStateList.model_validate(r)


def last_block(last_n_blocks: int = 2) -> BlockList:
    """Get the last n blocks."""
    r = db_query(
        """
SELECT epoch_slot_no,
block_no,
tx_count,
EXTRACT(
	epoch
	FROM block.time
)::INTEGER AS "block_time"
FROM block
WHERE block_no IS NOT null
ORDER BY block_no DESC
LIMIT %(last_n_blocks)s""",
        {"last_n_blocks": last_n_blocks},
    )
    return BlockList.model_validate(r)


def get_pool_utxos_in_block(block_no: int) -> PoolStateList:
    """Get pool utxos in block."""
    # Use this for gathering all assets for multiple addresses
    datum_selector = (
        POOL_SELECTOR
        + """
FROM tx_out txo
LEFT JOIN tx ON txo.tx_id = tx.id
LEFT JOIN datum ON txo.data_hash = datum.hash
LEFT JOIN block ON tx.block_id = block.id
WHERE block.block_no = %(block_no)s AND datum.hash IS NOT NULL
"""
    )
    r = db_query(datum_selector, {"block_no": block_no})

    return PoolStateList.model_validate(r)


def get_script_from_address(address: Address):
    SCRIPT_SELECTOR = """
SELECT ENCODE(bytes, 'hex') as "script"
FROM script s
WHERE s.hash = %(address)b
"""
    r = db_query(SCRIPT_SELECTOR, {"address": bytes.fromhex(str(address.payment_part))})

    return r


def get_order_utxos(
    stake_addresses: list[str],
    block_no: int | None = None,
    after_block: int | None = None,
    limit: int = 1000,
    page: int = 0,
):
    utxo_selector = ORDER_SELECTOR
    utxo_selector += """FROM (
	SELECT *
	FROM tx_out txo
	WHERE txo.address = ANY(%(addresses)s) AND txo.data_hash IS NOT NULL
) txo_stake
LEFT JOIN tx ON tx.id = txo_stake.tx_id
LEFT JOIN block ON tx.block_id = block.id
LEFT JOIN datum ON txo_stake.data_hash = datum.hash
LEFT JOIN (
	SELECT tx.hash AS "tx_hash",
	txo.index AS "tx_index",
	txo.value,
	txo.id as "tx_id",
	block.hash AS "block_hash",
	block.time AS "block_time",
    block.block_no,
	tx.block_index AS "block_index",
	tx_in.tx_out_id,
	tx_in.tx_out_index,
    txo.inline_datum_id,
    txo.reference_script_id,
    txo.address,
    datum.hash as "datum_hash",
    datum.bytes as "datum_bytes"
	FROM tx_in
	LEFT JOIN tx ON tx.id = tx_in.tx_in_id
	LEFT JOIN tx_out txo ON tx.id = txo.tx_id
	LEFT JOIN block ON tx.block_id = block.id
	LEFT JOIN datum ON txo.data_hash = datum.hash
) txo_output ON txo_output.tx_out_id = txo_stake.tx_id AND txo_output.tx_out_index = txo_stake.index
LEFT JOIN tx_metadata ON tx.id = tx_metadata.tx_id
WHERE datum.hash IS NOT NULL"""

    if block_no is not None:
        utxo_selector += """
    AND (block.block_no = %(block_no)s OR txo_output.block_no = %(block_no_rep)s)"""

    elif after_block is not None:
        utxo_selector += """
    AND block.block_no >= %(after_block)s OR txo_output.block_no >= %(after_block_rep)s"""

    utxo_selector += """
ORDER BY tx.id ASC
LIMIT %(limit)s
OFFSET %(offset)s"""

    r = db_query(
        utxo_selector,
        {
            "addresses": stake_addresses,
            "limit": limit,
            "offset": page * limit,
            "block_no": block_no,
            "block_no_rep": block_no,
            "after_block": after_block,
            "after_block_rep": after_block,
        },
    )

    return SwapTransactionList.model_validate(r)
