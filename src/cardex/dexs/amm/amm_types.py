"""Module providing types and state implementations for automated market maker (AMM) pools."""

from typing import ClassVar

from cardex.dataclasses.models import Assets
from cardex.dexs.amm.amm_base import AbstractPoolState
from cardex.dexs.core.constants import ONE_VALUE


class AbstractConstantProductPoolState(AbstractPoolState):
    """Represents the state of a constant product automated market maker (AMM) pool."""

    def get_amount_out(
        self,
        asset: Assets,
        precise: bool = True,
    ) -> tuple[Assets, float]:
        """Get the output asset amount given an input asset amount.

        Args:
            asset: An asset with a defined quantity.
            precise: Whether to return precise calculations.

        Returns:
            A tuple where the first value is the estimated asset returned from the swap
                and the second value is the price impact ratio.
        """
        if len(asset) != ONE_VALUE:
            error_msg = "Asset should only have one token."
            raise ValueError(error_msg)
        if asset.unit() not in [self.unit_a, self.unit_b]:
            error_msg = (
                f"Asset {asset.unit()} is invalid for pool {self.unit_a}-{self.unit_b}"
            )
            raise ValueError(error_msg)

        if asset.unit() == self.unit_a:
            reserve_in, reserve_out = self.reserve_a, self.reserve_b
            unit_out = self.unit_b
        else:
            reserve_in, reserve_out = self.reserve_b, self.reserve_a
            unit_out = self.unit_a

        # Calculate the amount out
        fee_modifier = 10000 - (self.volume_fee or 0)
        numerator: int = asset.quantity() * fee_modifier * reserve_out
        denominator: int = asset.quantity() * fee_modifier + reserve_in * 10000
        amount_out = Assets(**{unit_out: numerator // denominator})
        if not precise:
            amount_out.root[unit_out] = numerator // denominator

        if amount_out.quantity() == 0:
            return amount_out, 0

        # Calculate the price impact
        price_numerator: int = (
            reserve_out * asset.quantity() * denominator * fee_modifier
            - numerator * reserve_in * 10000
        )
        price_denominator: int = reserve_out * asset.quantity() * denominator * 10000
        price_impact: float = price_numerator / price_denominator

        return amount_out, price_impact

    def get_amount_in(
        self,
        asset: Assets,
        precise: bool = True,
    ) -> tuple[Assets, float]:
        """Get the input asset amount given a desired output asset amount.

        Args:
            asset: An asset with a defined quantity.
            precise: Whether to return precise calculations.

        Returns:
            The estimated asset needed for input in the swap.
        """
        if len(asset) != ONE_VALUE:
            error_msg = "Asset should only have one token."
            raise ValueError(error_msg)
        if asset.unit() not in [self.unit_a, self.unit_b]:
            error_msg = (
                f"Asset {asset.unit()} is invalid for pool {self.unit_a}-{self.unit_b}"
            )
            raise ValueError(error_msg)
        if asset.unit() == self.unit_b:
            reserve_in, reserve_out = self.reserve_a, self.reserve_b
            unit_out = self.unit_a
        else:
            reserve_in, reserve_out = self.reserve_b, self.reserve_a
            unit_out = self.unit_b

        # Estimate the required input
        fee_modifier = 10000 - (self.volume_fee or 0)
        numerator: int = asset.quantity() * 10000 * reserve_in
        denominator: int = (reserve_out - asset.quantity()) * fee_modifier
        amount_in = Assets(**{unit_out: numerator // denominator})
        if not precise:
            amount_in.root[unit_out] = numerator // denominator

        # Estimate the price impact
        price_numerator: int = (
            reserve_out * numerator * fee_modifier
            - asset.quantity() * denominator * reserve_in * 10000
        )
        price_denominator: int = reserve_out * numerator * 10000
        price_impact: float = price_numerator / price_denominator

        return amount_in, price_impact


class AbstractStableSwapPoolState(AbstractPoolState):
    """Represents the state of a stable swap automated market maker (AMM) pool."""

    asset_mulitipliers: ClassVar[list[int]] = [1, 1]

    @property
    def reserve_a(self) -> int:
        """Reserve amount of asset A."""
        return self.assets.quantity(0) * self.asset_mulitipliers[0]

    @property
    def reserve_b(self) -> int:
        """Reserve amount of asset B."""
        return self.assets.quantity(1) * self.asset_mulitipliers[1]

    @property
    def amp(self) -> int:
        """Amplification coefficient used in the stable swap algorithm."""
        return 75

    def _get_ann(self) -> int:
        """The modified amp value.

        This is the derived amp value (ann) from the original stableswap paper. This is
        implemented here as the default, but a common variant of this does not use the
        exponent. The alternative version is provided in the
        AbstractCommonStableSwapPoolState class. WingRiders uses this version.
        """
        n_coins = 2
        return self.amp * n_coins**n_coins

    def _get_d(self) -> float:
        """Regression to learn the stability constant."""
        # TODO: Expand this to operate on pools with more than one stable
        n_coins = 2
        ann = self._get_ann()
        s = self.reserve_a + self.reserve_b
        if s == 0:
            return 0

        # Iterate until the change in value is <1 unit.
        d = s
        for _ in range(256):
            d_p = d**3 / (n_coins**n_coins * self.reserve_a * self.reserve_b)
            d_prev = d
            d = d * (ann * s + d_p * n_coins) / ((ann - 1) * d + (n_coins + 1) * d_p)

            if abs(d - d_prev) < 1:
                break

        return d

    def _get_y(
        self,
        in_assets: Assets,
        out_unit: str,
        precise: bool = True,
        get_input: bool = False,
    ) -> Assets:
        """Calculate the output amount using a regression."""
        n_coins = 2
        ann = self._get_ann()
        d = self._get_d()

        subtract = -1 if get_input else 1

        # Make sure only one input supplied
        if len(in_assets) > ONE_VALUE:
            error_msg = "Only one input asset allowed."
            raise ValueError(error_msg)
        if in_assets.unit() not in [self.unit_a, self.unit_b]:
            error_msg = "Invalid input token."
            raise ValueError(error_msg)
        if out_unit not in [self.unit_a, self.unit_b]:
            error_msg = "Invalid output token."
            raise ValueError(error_msg)

        in_quantity = in_assets.quantity()
        if in_assets.unit() == self.unit_a:
            in_reserve = (
                self.reserve_a + in_quantity * self.asset_mulitipliers[0] * subtract
            )
            out_multiplier = self.asset_mulitipliers[1]
        else:
            in_reserve = (
                self.reserve_b + in_quantity * self.asset_mulitipliers[1] * subtract
            )
            out_multiplier = self.asset_mulitipliers[0]

        s = in_reserve
        c = d**3 / (n_coins**2 * ann * in_reserve)
        b = s + d / ann
        out_prev: float = 0
        out = d

        for _ in range(256):
            out_prev = out
            out = (out**2 + c) / (2 * out + b - d)

            if abs(out - out_prev) < 1:
                break

        out /= out_multiplier
        out_assets = Assets(**{out_unit: int(out)})
        if not precise:
            out_assets.root[out_unit] = int(out)

        return out_assets

    def get_amount_out(
        self,
        asset: Assets,
        precise: bool = True,
        fee_on_input: bool = True,
    ) -> tuple[Assets, float]:
        """Get the output amount for the given input asset in a stable swap pool."""
        if fee_on_input:
            in_asset = Assets(
                **{
                    asset.unit(): int(
                        asset.quantity() * (10000 - (self.volume_fee or 0)) / 10000,
                    ),
                },
            )
        else:
            in_asset = asset
        out_unit = self.unit_a if asset.unit() == self.unit_b else self.unit_b
        out_asset = self._get_y(in_asset, out_unit, precise=precise)
        out_reserve = (
            self.reserve_b / self.asset_mulitipliers[1]
            if out_unit == self.unit_b
            else self.reserve_a / self.asset_mulitipliers[0]
        )

        out_asset.root[out_asset.unit()] = int(out_reserve - out_asset.quantity())
        if not fee_on_input:
            out_asset.root[out_asset.unit()] = int(
                out_asset.quantity() * (10000 - (self.volume_fee or 0)) / 10000,
            )
        if precise:
            out_asset.root[out_asset.unit()] = int(out_asset.quantity())

        return out_asset, 0

    def get_amount_in(
        self,
        asset: Assets,
        precise: bool = True,
        fee_on_input: bool = True,
    ) -> tuple[Assets, float]:
        """Get the input amount needed for the desired output asset in a stable swap pool."""
        if not fee_on_input:
            out_asset = Assets(
                **{
                    asset.unit(): int(
                        asset.quantity() * 10000 / (10000 - (self.volume_fee or 0)),
                    ),
                },
            )
        else:
            out_asset = asset
        in_unit = self.unit_a if asset.unit() == self.unit_b else self.unit_b
        in_asset = self._get_y(out_asset, in_unit, precise=precise, get_input=True)
        in_reserve = (
            (self.reserve_b / self.asset_mulitipliers[1])
            if in_unit == self.unit_b
            else (self.reserve_a / self.asset_mulitipliers[0])
        )
        in_asset.root[in_asset.unit()] = int(in_asset.quantity() - in_reserve)
        if fee_on_input:
            in_asset.root[in_asset.unit()] = int(
                in_asset.quantity() * 10000 / (10000 - (self.volume_fee or 0)),
            )
        if precise:
            in_asset.root[in_asset.unit()] = int(in_asset.quantity())
        return in_asset, 0


class AbstractCommonStableSwapPoolState(AbstractStableSwapPoolState):
    """The common variant of StableSwap.

    This class implements the common variant of the stableswap algorithm. The main
    difference is the
    """

    def _get_ann(self) -> int:
        """The modified amp value.

        This is the ann value in the common stableswap variant.
        """
        n_coins = 2
        return self.amp * n_coins


class AbstractConstantLiquidityPoolState(AbstractPoolState):
    """Represents the state of a constant liquidity pool automated market maker (AMM).

    This class serves as a base for constant liquidity pool implementations, providing
    methods to calculate the input and output asset amounts for swaps.
    """

    def get_amount_out(
        self,
        asset: Assets,  # noqa: ARG002
        precise: bool = True,  # noqa: ARG002
    ) -> tuple[Assets, float]:
        """Raise NotImplementedError as it is not yet implemented."""
        error_msg = "CLPP amount out is not yet implemented."
        raise NotImplementedError(error_msg)

    def get_amount_in(
        self,
        asset: Assets,  # noqa: ARG002
        precise: bool = True,  # noqa: ARG002
    ) -> tuple[Assets, float]:
        """Raise NotImplementedError as it is not yet implemented."""
        error_msg = "CLPP amount in is not yet implemented."
        raise NotImplementedError(error_msg)
