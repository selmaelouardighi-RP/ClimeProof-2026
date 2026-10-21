"""The single, comprehensive metric catalog (work scope, Section 4).

Every hazard and community factor in the scope is listed here, implemented or not, so every
record has identical fields. A metric with `provider=None` is emitted as NOT_IMPLEMENTED until
a provider is written for it. Adding or renaming a metric is a schema change: bump
schema.SCHEMA_VERSION.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Hazard:
    id: str
    layer: str  # "A" hazard exposure, "B" community context
    name: str


@dataclass(frozen=True)
class Metric:
    id: str  # "<hazard>.<metric>"
    unit: str | None
    description: str
    provider: str | None = None  # key into providers.REGISTRY; None = not implemented yet

    @property
    def hazard(self) -> str:
        return self.id.split(".", 1)[0]


HAZARDS: list[Hazard] = [
    # Layer A - hazard exposure
    Hazard("heat", "A", "Temperature extremes - heat"),
    Hazard("cold", "A", "Temperature extremes - cold"),
    Hazard("winter_storm", "A", "Winter storm / ice storm"),
    Hazard("extreme_precip", "A", "Extreme precipitation"),
    Hazard("flood", "A", "Flood - likelihood and mechanism"),
    Hazard("coastal", "A", "Storm surge & coastal flooding"),
    Hazard("hurricane", "A", "Hurricane / tropical cyclone"),
    Hazard("wind_tornado", "A", "Severe wind & tornado"),
    Hazard("hail", "A", "Hail"),
    Hazard("lightning", "A", "Lightning"),
    Hazard("drought", "A", "Drought"),
    Hazard("wildfire", "A", "Wildfire & smoke"),
    Hazard("air_quality", "A", "Dust storms & non-wildfire air quality"),
    Hazard("grid_stress", "A", "Grid / power stress"),
    Hazard("geologic", "A", "Geological / region-specific"),
    Hazard("dam_levee", "A", "Dam / levee failure inundation"),
    Hazard("tsunami", "A", "Tsunami"),
    Hazard("volcanic", "A", "Volcanic"),
    Hazard("hazmat", "A", "Hazardous-materials proximity"),
    # Layer B - community context
    Hazard("social_vulnerability", "B", "Social vulnerability"),
    Hazard("community_resilience", "B", "Community resilience"),
    Hazard("care_access", "B", "Care access / isolation"),
    Hazard("emergency_services", "B", "Emergency services density"),
    Hazard("drinking_water", "B", "Drinking water quality"),
    Hazard("water_supply", "B", "Water supply - drought vulnerability"),
    Hazard("communications", "B", "Communications infrastructure"),
    Hazard("grid_utility", "B", "Grid / utility context"),
]

# "Recent" = the most recent `periods.recent_years` complete calendar years (config), e.g.
# 2011-2025 for a run in 2026. Each value's `period` field states the exact years used.
_G = "acis_grid"  # ACIS GridData (PRISM grid) at the point, recent window
_S = "acis_station"  # ACIS station period of record through yesterday (GHCN-Daily stations)
_SN = "acis_snow"  # ACIS nearest snow-reporting station, recent window
_W = "open_climate_risk"  # CarbonPlan Open Climate Risk wildfire tensors

METRICS: list[Metric] = [
    # --- heat -----------------------------------------------------------------------------
    Metric(
        "heat.days_ge_90f",
        "days/yr",
        "Mean annual days with Tmax >= 90F, recent years, gridded at the point",
        _G,
    ),
    Metric(
        "heat.days_ge_100f",
        "days/yr",
        "Mean annual days with Tmax >= 100F, recent years, gridded at the point",
        _G,
    ),
    Metric(
        "heat.days_ge_105f",
        "days/yr",
        "Mean annual days with Tmax >= 105F, recent years, gridded at the point",
        _G,
    ),
    Metric(
        "heat.days_ge_100f_trend",
        "days/yr per decade",
        "OLS trend of annual days with Tmax >= 100F over the trend window",
        _G,
    ),
    Metric(
        "heat.heatwave_events_per_year",
        "events/yr",
        "Mean annual heat-wave events, recent years (provisional definition, see config)",
        _G,
    ),
    Metric(
        "heat.record_high_f",
        "degF",
        "Highest daily Tmax in the period of record to date (nearest long-record active station)",
        _S,
    ),
    Metric(
        "heat.cooling_degree_days",
        "degF-days/yr",
        "Mean annual cooling degree days (base 65F), recent years, gridded",
        _G,
    ),
    Metric("heat.design_high_f", "degF", "Design-condition high (e.g. 0.4% cooling dry-bulb)"),
    # --- cold -----------------------------------------------------------------------------
    Metric(
        "cold.freeze_days",
        "days/yr",
        "Mean annual days with Tmin <= 32F, recent years, gridded",
        _G,
    ),
    Metric(
        "cold.hard_freeze_days",
        "days/yr",
        "Mean annual days with Tmin <= 28F, recent years, gridded",
        _G,
    ),
    Metric(
        "cold.days_tmin_le_0f",
        "days/yr",
        "Mean annual days with Tmin <= 0F, recent years, gridded",
        _G,
    ),
    Metric(
        "cold.record_low_f",
        "degF",
        "Lowest daily Tmin in the period of record to date (nearest long-record active station)",
        _S,
    ),
    Metric(
        "cold.heating_degree_days",
        "degF-days/yr",
        "Mean annual heating degree days (base 65F), recent years, gridded",
        _G,
    ),
    Metric("cold.design_low_f", "degF", "Design-condition low (e.g. 99.6% heating dry-bulb)"),
    # --- winter storm ---------------------------------------------------------------------
    Metric(
        "winter_storm.annual_snowfall_in",
        "in/yr",
        "Mean annual snowfall, recent years (nearest snow-reporting station)",
        _SN,
    ),
    Metric(
        "winter_storm.days_snow_depth_ge_1in",
        "days/yr",
        "Mean annual days with snow depth >= 1 in, recent years (nearest station)",
        _SN,
    ),
    Metric("winter_storm.ice_accumulation", None, "Ice accumulation exposure"),
    Metric("winter_storm.snow_load", None, "Ground snow load"),
    Metric("winter_storm.blizzard_frequency", None, "Blizzard frequency"),
    # --- extreme precipitation ------------------------------------------------------------
    Metric(
        "extreme_precip.annual_precip_in",
        "in/yr",
        "Mean annual precipitation, recent years, gridded",
        _G,
    ),
    Metric(
        "extreme_precip.days_ge_1in",
        "days/yr",
        "Mean annual days with precipitation >= 1 in, recent years, gridded",
        _G,
    ),
    Metric(
        "extreme_precip.mean_annual_max_1day_in",
        "in",
        "Mean of annual maximum 1-day precipitation, recent years, gridded",
        _G,
    ),
    Metric(
        "extreme_precip.return_period_100yr_24hr_in",
        "in",
        "100-yr 24-hr precipitation depth (NOAA Atlas 14)",
    ),
    Metric("extreme_precip.atmospheric_river_exposure", None, "Atmospheric-river exposure"),
    # --- flood ----------------------------------------------------------------------------
    Metric("flood.likelihood_score", None, "Flood likelihood score"),
    Metric(
        "flood.dominant_mechanism", None, "Dominant flood type: pluvial / fluvial / flash / surge"
    ),
    Metric("flood.fema_flood_zone", None, "FEMA NFHL flood zone at the point"),
    # --- coastal --------------------------------------------------------------------------
    Metric("coastal.surge_inundation_zone", None, "Storm-surge inundation zone"),
    Metric("coastal.sea_level_rise", None, "Sea-level-rise exposure"),
    Metric("coastal.coastal_erosion", None, "Coastal erosion exposure"),
    # --- hurricane ------------------------------------------------------------------------
    Metric("hurricane.wind_return_period", None, "Hurricane wind return-period speed"),
    Metric("hurricane.track_frequency", None, "Tropical-cyclone track frequency"),
    # --- wind / tornado / hail / lightning ------------------------------------------------
    Metric("wind_tornado.tornado_exposure", None, "Tornado exposure"),
    Metric("wind_tornado.severe_wind_exposure", None, "Severe convective wind exposure"),
    Metric("hail.frequency", None, "Hail frequency"),
    Metric("hail.size", None, "Hail size"),
    Metric("lightning.strike_density", None, "Cloud-to-ground strike density"),
    # --- drought --------------------------------------------------------------------------
    Metric("drought.history", None, "Drought frequency / intensity history"),
    Metric("drought.outlook", None, "Drought outlook"),
    Metric("drought.water_stress", None, "Aquifer and surface-water stress"),
    # --- wildfire -------------------------------------------------------------------------
    Metric(
        "wildfire.burn_probability_2011",
        "probability/yr",
        "Annual burn probability, current conditions (~2011), 30 m",
        _W,
    ),
    Metric(
        "wildfire.burn_probability_2047",
        "probability/yr",
        "Annual burn probability, future conditions (~2047), 30 m",
        _W,
    ),
    Metric(
        "wildfire.risk_to_potential_structures_2011",
        "dimensionless",
        "Risk to a generic potential structure, current conditions",
        _W,
    ),
    Metric("wildfire.smoke_pm25_days", "days/yr", "Wildfire-smoke PM2.5 exposure days"),
    # --- remaining layer A ----------------------------------------------------------------
    Metric("air_quality.dust_storm_frequency", None, "Dust-storm frequency"),
    Metric("air_quality.nonattainment", None, "Ozone / particulate non-attainment status"),
    Metric("grid_stress.outage_frequency", None, "Regional outage-frequency / reliability proxy"),
    Metric(
        "grid_stress.weather_driven_stress", None, "Heat- and storm-driven grid-stress indicator"
    ),
    Metric("geologic.seismic_pga", "g", "Seismic peak ground acceleration (USGS)"),
    Metric("geologic.subsidence", None, "Land subsidence (mining, groundwater pumping)"),
    Metric("geologic.karst_sinkhole", None, "Karst / sinkhole susceptibility"),
    Metric("geologic.landslide", None, "Landslide / debris-flow / avalanche susceptibility"),
    Metric(
        "dam_levee.high_hazard_dam_proximity", "km", "Distance to nearest high-hazard-potential dam"
    ),
    Metric("dam_levee.inundation_zone", None, "Dam / levee failure inundation zone"),
    Metric("tsunami.inundation_zone", None, "Tsunami inundation zone"),
    Metric("volcanic.active_volcano_proximity", "km", "Distance to nearest active volcano"),
    Metric("volcanic.ashfall_exposure", None, "Ashfall exposure"),
    Metric(
        "hazmat.tri_facilities_nearby", "count", "Toxics Release Inventory facilities within radius"
    ),
    Metric(
        "hazmat.pipeline_proximity", "km", "Distance to nearest hazardous-liquid / gas pipeline"
    ),
    Metric("hazmat.rail_proximity", "km", "Distance to nearest rail line"),
    # --- layer B --------------------------------------------------------------------------
    Metric("social_vulnerability.svi", None, "CDC/ATSDR Social Vulnerability Index"),
    Metric("community_resilience.resilience_score", None, "FEMA NRI community resilience score"),
    Metric("community_resilience.expected_annual_loss", None, "FEMA NRI expected annual loss"),
    Metric("care_access.nearest_hospital_km", "km", "Distance to nearest hospital"),
    Metric("care_access.nearest_referral_center_km", "km", "Distance to nearest referral center"),
    Metric("care_access.facilities_per_sq_mi", None, "Healthcare facilities per sq mi"),
    Metric("care_access.facilities_per_1000", None, "Healthcare facilities per 1,000 residents"),
    Metric("emergency_services.per_sq_mi", None, "Emergency services per sq mi"),
    Metric("emergency_services.per_1000", None, "Emergency services per 1,000 residents"),
    Metric("emergency_services.response_time_proxy", None, "Response-time proxy"),
    Metric("drinking_water.violations", None, "Community water-system violations"),
    Metric("drinking_water.source_type", None, "Water source type"),
    Metric("water_supply.source_type", None, "Community water source (groundwater vs surface)"),
    Metric("water_supply.aquifer_stress", None, "Aquifer stress"),
    Metric("water_supply.restriction_history", None, "Drought-restriction history"),
    Metric("communications.broadband", None, "Broadband availability / reliability (FCC)"),
    Metric("grid_utility.reliability", None, "Regional grid reliability / utility context"),
]

METRICS_BY_ID: dict[str, Metric] = {m.id: m for m in METRICS}
HAZARDS_BY_ID: dict[str, Hazard] = {h.id: h for h in HAZARDS}


def metrics_for_provider(provider: str) -> list[Metric]:
    return [m for m in METRICS if m.provider == provider]
