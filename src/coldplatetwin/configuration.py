"""small JSON configuration, shared by import, demonstration and models."""

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import numpy as np

from .steady import SteadyStateConfig
from .thermal import ThermalInputs
from .hydraulics import HydraulicInputs


# ---- configuration records ----

@dataclass
class DOEConfig:
    """flow and heater-power levels for the proposed design of experiments."""

    flow_lpm: list[float] = field(default_factory=lambda: [0.5, 1.0, 1.5])
    heater_power_w: list[float] = field(default_factory=lambda: [100, 175, 250])
    replicated_blocks: int = 2
    development_envelope_max_flow_lpm: float = 2.0
    hardware_authorization: bool = False


@dataclass
class AnalysisConfig:
    """every analysis, demo and model setting, recorded with each result."""

    seed: int = 20260917
    steady_state: SteadyStateConfig = field(default_factory=SteadyStateConfig)
    doe: DOEConfig = field(default_factory=DOEConfig)
    thermal: ThermalInputs = field(default_factory=ThermalInputs)
    hydraulic: HydraulicInputs = field(default_factory=HydraulicInputs)
    monte_carlo_samples: int = 4000
    demo_flow_lpm: float = 1.0
    demo_power_w: float = 180.0
    # explicit screening allowances for the rounded property table.
    density_relative_standard: float = 0.0003
    enthalpy_relative_standard: float = 0.0007
    comparison_flow_tolerance_lpm: float = 0.02
    comparison_power_tolerance_w: float = 2.0
    comparison_inlet_tolerance_k: float = 0.2
    classification: str = "proposed analysis configuration"

    def validate(self):
        """raise ValueError when any setting is out of range."""

        self.steady_state.validate()

        # whole-number settings. a bool is rejected because its type is not exactly int.
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        if type(self.monte_carlo_samples) is not int or self.monte_carlo_samples < 100:
            raise ValueError("monte_carlo_samples must be an integer >= 100")
        if type(self.doe.replicated_blocks) is not int or self.doe.replicated_blocks < 1:
            raise ValueError("DOE replicated_blocks must be a positive integer")

        # a config may never authorize hardware operation
        if self.doe.hardware_authorization is not False:
            raise ValueError("DOE configuration cannot authorize hardware operation")

        # doe levels must be present, distinct, finite and positive
        for levels in (self.doe.flow_lpm, self.doe.heater_power_w):
            if not levels or not np.isfinite(levels).all() or min(levels) <= 0 or len(set(levels)) != len(levels):
                raise ValueError("DOE levels must be distinct, finite and positive")

        # demo targets and comparison tolerances must be positive and finite
        for name in ("demo_flow_lpm", "demo_power_w", "comparison_flow_tolerance_lpm",
                     "comparison_power_tolerance_w", "comparison_inlet_tolerance_k"):
            value = getattr(self, name)
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")

        # property allowances may be zero but not negative
        for value in (self.density_relative_standard, self.enthalpy_relative_standard):
            if not np.isfinite(value) or value < 0:
                raise ValueError("Property uncertainty allowances must be nonnegative")

        # the wider development flow must cover every doe flow level
        development_flow = self.doe.development_envelope_max_flow_lpm
        if not np.isfinite(development_flow) or development_flow < max(self.doe.flow_lpm):
            raise ValueError("Development flow must include the DOE flow levels")

        self.thermal.validate()
        self.hydraulic.validate()

    def as_dict(self):
        """return the configuration as nested plain dictionaries."""

        return asdict(self)

    @property
    def configuration_hash(self):
        """sha256 of the sorted JSON form, used to trace results back to settings."""

        text = json.dumps(self.as_dict(), sort_keys=True)
        return hashlib.sha256(text.encode()).hexdigest()


# ---- loading ----

def load_config(path: str | Path | None = None) -> AnalysisConfig:
    """read an explicit config, or configs/demo.json in the current folder.

    outside a checkout the defaults stay usable and are recorded in every
    result. an explicit missing path or an unknown field is an error.
    """

    # an explicit path must exist. the default file is optional.
    if path:
        selected = Path(path)
    else:
        selected = Path("configs/demo.json")
    if path or selected.is_file():
        data = json.loads(selected.read_text())
    else:
        data = {}

    # build the nested records. an unknown field raises TypeError, reported as ValueError.
    try:
        data["steady_state"] = SteadyStateConfig(**data.get("steady_state", {}))
        data["doe"] = DOEConfig(**data.get("doe", {}))
        data["thermal"] = ThermalInputs(**data.get("thermal", {}))
        data["hydraulic"] = HydraulicInputs(**data.get("hydraulic", {}))
        config = AnalysisConfig(**data)
    except TypeError as error:
        raise ValueError(f"Unknown or invalid configuration field: {error}") from error
    config.validate()
    return config
