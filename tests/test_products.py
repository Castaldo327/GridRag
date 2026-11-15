"""Contracts between product definitions, synthetic rows, and interval semantics."""

import copy
import unittest

import numpy as np
import pandas as pd

from gridrag.warehouse import build, product_data, products


class ProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The fall-back day has 25 hours in DST-observing ISOs and 24 in fixed EST.
        day = pd.Timestamp("2025-11-02")
        cls.inputs = {
            iso.code: product_data.ProductInputs(
                iso_id=iso.id,
                solar_peak_mw=iso.solar_peak_mw,
                fuel_ids=build.FUEL_IDS,
                start=day,
                end=day,
                hourly=build._series(iso, day, day, "h"),
                five_minute=build._series(iso, day, day, "5min"),
            )
            for iso in build.ISOS
        }

    def test_rows_match_table_contracts_even_across_repeated_local_hours(self):
        for iso, inputs in self.inputs.items():
            hourly_count = 24 if iso == "MISO" else 25
            self.assertEqual(len(inputs.hourly.keys), hourly_count)
            expected_counts = {
                "lmp_rt_bus_5min": hourly_count * 12 * 3,
                "lmp_rt_hub_5min": hourly_count * 12,
                "lmp_da_hub_hourly": hourly_count,
                "load_forecast_hourly": hourly_count * 4,
                "ancillary_prices_hourly": hourly_count * 3,
                "storage_dispatch_5min": hourly_count * 12,
                "resource_outage_daily": 6,
                "renewable_curtailment_5min": hourly_count * 12 * 2,
            }
            frames = products.frames(iso, inputs)
            for product in products.PRODUCTS:
                with self.subTest(iso=iso, product=product.suffix):
                    frame = frames[products.table_name(iso, product)]
                    self.assertEqual(set(frame.columns), {"iso_id", *(column.name for column in product.columns)})
                    self.assertEqual(len(frame), expected_counts[product.suffix])
                    self.assertFalse(frame.isna().any().any())
                    self.assertFalse(frame.duplicated(subset=list(product.primary_key)).any())
                    self.assertEqual(frame.iso_id.unique().tolist(), [inputs.iso_id])

    def test_generators_are_repeatable_and_leave_shared_inputs_untouched(self):
        inputs = self.inputs["CAISO"]
        original = copy.deepcopy(inputs)
        first = products.frames("CAISO", inputs)
        second = products.frames("CAISO", inputs)
        for table in first:
            pd.testing.assert_frame_equal(first[table], second[table], check_exact=True)
        for cadence in ("hourly", "five_minute"):
            before, after = getattr(original, cadence), getattr(inputs, cadence)
            pd.testing.assert_frame_equal(before.keys, after.keys)
            np.testing.assert_array_equal(before.demand_mw, after.demand_mw)
            for fuel in before.generation_mw:
                np.testing.assert_array_equal(before.generation_mw[fuel], after.generation_mw[fuel])

    def test_price_locations_and_components_agree_with_the_dimension(self):
        dimension = product_data.locations(build.ISO_IDS).set_index("location_id")
        for iso, inputs in self.inputs.items():
            for generate, location_type, location_count in (
                (product_data.real_time_bus_prices, "bus", 3),
                (product_data.real_time_hub_prices, "hub", 1),
                (product_data.day_ahead_hub_prices, "hub", 1),
            ):
                with self.subTest(iso=iso, generator=generate.__name__):
                    frame = generate(inputs)
                    locations = dimension.loc[frame.location_id.unique()]
                    self.assertEqual(len(locations), location_count)
                    self.assertEqual(set(locations.iso_id), {inputs.iso_id})
                    self.assertEqual(set(locations.location_type), {location_type})
                    np.testing.assert_allclose(frame.lmp, frame.energy + frame.congestion + frame.loss, atol=1e-10)

    def test_forecast_cutoff_excludes_hindsight_before_ranking_vintages(self):
        inputs = self.inputs["CAISO"]
        forecasts = product_data.load_forecasts(inputs)
        self.assertTrue((forecasts.publish_time_utc > forecasts.interval_start_utc).any())
        # A query at delivery can use the six-hour forecast; an earlier cutoff
        # must choose the eighteen-hour forecast instead of the hindsight row.
        for cutoff_hours, expected_lead in ((0, 6), (12, 18)):
            with self.subTest(cutoff_hours=cutoff_hours):
                cutoff = forecasts.interval_start_utc - np.timedelta64(cutoff_hours, "h")
                known = forecasts.loc[forecasts.publish_time_utc <= cutoff]
                latest = known.sort_values("publish_time_utc").drop_duplicates("interval_start_utc", keep="last")
                self.assertEqual(len(latest), len(inputs.hourly.keys))
                lead = latest.interval_start_utc - latest.publish_time_utc
                self.assertTrue(lead.eq(np.timedelta64(expected_lead, "h")).all())


if __name__ == "__main__":
    unittest.main()
