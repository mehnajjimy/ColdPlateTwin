"""Small JSON configuration, shared by import, demonstration and models."""

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import numpy as np

from .steady import SteadyStateConfig
from .thermal import ThermalInputs
from .hydraulics import HydraulicInputs


@dataclass
class DOEConfig:
    flow_lpm: list[float] = field(default_factory=lambda: [0.5, 1.0, 1.5])
    heater_power_w: list[float] = field(default_factory=lambda: [100, 175, 250])
    replicated_blocks: int = 2
    development_envelope_max_flow_lpm: float = 2.0
    hardware_authorization: bool = False


@dataclass
class AnalysisConfig:
    seed: int = 20260917
    steady_state: SteadyStateConfig = field(default_factory=SteadyStateConfig)
    doe: DOEConfig = field(default_factory=DOEConfig)
    thermal: ThermalInputs = field(default_factory=ThermalInputs)
    hydraulic: HydraulicInputs = field(default_factory=HydraulicInputs)
    monte_carlo_samples: int = 4000
    demo_flow_lpm: float = 1.0
    demo_power_w: float = 180.0
    # Explicit screening allowances for the rounded property table.
    density_relative_standard: float = 0.0003
    enthalpy_relative_standard: float = 0.0007
    comparison_flow_tolerance_lpm: float = 0.02
    comparison_power_tolerance_w: float = 2.0
    comparison_inlet_tolerance_k: float = 0.2
    classification: str = "proposed analysis configuration"

    def validate(self):
        self.steady_state.validate()
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        if type(self.monte_carlo_samples) is not int or self.monte_carlo_samples < 100:
            raise ValueError("monte_carlo_samples must be an integer >= 100")
        if type(self.doe.replicated_blocks) is not int or self.doe.replicated_blocks < 1:
            raise ValueError("DOE replicated_blocks must be a positive integer")
        if self.doe.hardware_authorization is not False:
            raise ValueError("DOE configuration cannot authorize hardware operation")
        for levels in (self.doe.flow_lpm, self.doe.heater_power_w):
            if not levels or not np.isfinite(levels).all() or min(levels) <= 0 or len(set(levels)) != len(levels):
                raise ValueError("DOE levels must be distinct, finite and positive")
        for name in ("demo_flow_lpm", "demo_power_w", "comparison_flow_tolerance_lpm",
                     "comparison_power_tolerance_w", "comparison_inlet_tolerance_k"):
            if not np.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for value in (self.density_relative_standard, self.enthalpy_relative_standard):
            if not np.isfinite(value) or value < 0:
                raise ValueError("Property uncertainty allowances must be nonnegative")
        if not np.isfinite(self.doe.development_envelope_max_flow_lpm) or self.doe.development_envelope_max_flow_lpm < max(self.doe.flow_lpm):
            raise ValueError("Development flow must include the DOE flow levels")
        self.thermal.validate()
        self.hydraulic.validate()

    def as_dict(self):
        return asdict(self)

    @property
    def configuration_hash(self):
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True).encode()).hexdigest()


def load_config(path: str | Path | None = None) -> AnalysisConfig:
    """Read explicit configuration, or configs/demo.json in the current folder.

    Outside a checkout, defaults remain usable and are recorded in every result.
    Explicit missing paths and unknown fields are errors.
    """
    selected = Path(path) if path else Path("configs/demo.json")
    data = json.loads(selected.read_text()) if path or selected.is_file() else {}
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
