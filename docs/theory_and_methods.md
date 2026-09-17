# Theory and methods

## Scope and evidence classes

ColdPlateTwin combines an experiment-analysis workflow with deliberately limited hydraulic and thermal screening calculations. This document distinguishes five evidence classes:

| Class | Meaning here |
|---|---|
| CAD measurement | Geometry/configuration values in the preserved CadQuery source and exported checks |
| Assumed input | Editable loss coefficients, material/thermal inputs, and stability criteria |
| Derived software result | A calculation from declared inputs, including synthetic-fixture output |
| Synthetic test | Invented fixture data used to exercise software behavior |
| Experimental evidence | Measurements from a calibrated apparatus; no such evidence is included here |

The imported FreeCAD assembly is useful for inspection, but it is an imported assembly rather than a fully parametric native feature history. CadQuery is the source for regeneration. The original screening arithmetic is not machining approval, seal qualification, structural analysis, or a pressure rating; see [departures](../reference/DEPARTURES.md).

## Measured quantities and energy accounting

For each synchronized logger sample, the analysis evaluates water heat uptake before time averaging:

$$
\dot Q_w(t)=\rho(T_\mathrm{loc})\,\dot V(t)\,[h(T_\mathrm{out})-h(T_\mathrm{in})],
$$

where flow is converted from L/min to m³/s and `T_loc` is the declared inlet or outlet flowmeter location. The package obtains density and enthalpy from its rounded pure-water table (`properties.py`) and integrates the accepted samples with trapezoid weights (`metrics.py`, `steady.py`). This is more faithful than applying one mean flow and one mean temperature difference, especially when samples are not perfectly uniform.

Electrical input and hydraulic power are independently calculated as

$$
P_e(t)=V(t)I(t),\qquad P_h(t)=\Delta p(t)\dot V(t).
$$

Time-weighted values are formed only after the sample-wise calculations. The reported residual is `P_e − Q_w` and the closure ratio is `Q_w/P_e`. A small residual is a consistency observation—not proof that every heat path, calibration, or sensor synchronization is correct. Heat entering water is not automatically identical to electrical power: environmental loss, heater/contact paths, stored energy during nonsteady operation, and measurement error can separate them.

The required logger fields are timestamp, flow, inlet/outlet temperature, test-section differential pressure, ambient temperature, heater voltage, and heater current. Optional `surface_reference_*_c` fields participate in stability screening. Pressure is a **section differential pressure** for hydraulic power; it is not maximum local gauge pressure and must never be substituted for a pressure-rating claim.

## Calorimetry, calibration, and synchronization

Raw inputs remain immutable. `calibration.py` applies the recorded affine relation `calibrated = scale × raw + offset`, then validates calibrated values. Metadata records calibration IDs, physical units, a geometry SHA-256 identifier, explicit time zone, flowmeter location, and synchronization assumptions. Unit conversion is intentionally not implicit: the import path accepts the declared contract (L/min, Pa, °C, V, A) or rejects it, preserving provenance.

Accurate calorimetry needs calibrated, paired inlet/outlet sensors, known flowmeter location, synchronized power/flow/temperature time bases, and adequate heater-power bandwidth. Those are hardware and data-acquisition tasks; the package does not fit calibration coefficients from a run. Corrected radiometric matrices are likewise accepted only when parser and camera metadata agree that the temperature export is already corrected, avoiding a second invented emissivity correction.

## Steady-state selection

`steady.py` considers candidate starts in time order. For every candidate it checks a 300 s screen, the following 180 s averaging interval, and their combined 480 s span. The checked configuration defaults are:

| Criterion | Default | Meaning |
|---|---:|---|
| Thermal slope | 0.03 K/min | Applies to inlet, outlet, ambient, and available surface-reference channels |
| Thermal step | 0.3 K | Maximum step in each checked span |
| Flow/power CV | 1% | Requires mean flow > 0.05 L/min and power > 5 W |
| Valid-time coverage | 90% | Complete required-channel rows only |
| Maximum sample gap | 5 s | Long gaps and missing rows break integration segments |

Adjacent complete samples get half-gap trapezoid weights; no samples are interpolated. Boundary-to-nearest-valid-sample gaps count. The first candidate meeting all checks is accepted. These are editable **provisional quality criteria**, not universal scientific thresholds or equipment safety settings. A rejected run still retains diagnostics and its output bundle.

## Hydraulic screening convention

`hydraulics.py` uses the hydraulic diameter for a rectangular channel,

$$
D_h=\frac{2wh}{w+h},
$$

and a fully developed laminar rectangular-duct relation expressed in the Darcy convention,

$$
f_D Re=96\,(1-1.3553\alpha+1.9467\alpha^2-1.7012\alpha^3+0.9564\alpha^4-0.2537\alpha^5),
\quad \alpha=\frac{\min(w,h)}{\max(w,h)}.
$$

For a channel, the implemented relation is

$$
\Delta p=\left(f_D\frac{L}{D_h}+\sum K\right)\frac{\rho u^2}{2},\qquad
Re=\frac{\rho uD_h}{\mu}.
$$

FI-100 uses the configured 1.120399 m centerline route (nine 96 mm passes, eight semicircular R6 returns, and two diagonal transitions), not an assumed 1.5 m route. FI-200/FI-300 solve a symmetric, two-central-feed header/channel network: each header segment and channel is represented as `Δp = Rq + Bq|q|`, and every node receives equal-and-opposite branch contributions. FI-000 is a coarse port/plenum minor-loss screen. The solver rejects unsuccessful or nonphysical solutions and reports normalized nodal residuals.

The correlation is a laminar convention, so a result above the model's Reynolds applicability is explicitly flagged rather than extended with an unverified turbulent model. At the default 1 L/min, FI-100 is flagged outside the laminar range (about Re 3112). Parallel predictions omit common transfer-port losses, detailed junction flow, roughness, bypass, and manufacturing variation. The loss coefficients (`K`) are analyst-selected assumptions with no established confidence ranges. Consequently these values are comparative screening outputs, not a pump selection, pressure rating, or validated flow prediction.

The rectangular-duct correlation follows the Darcy/Fanning convention described by R. K. Shah and A. L. London, *Laminar Flow Forced Convection in Ducts*, Academic Press, 1978; the package uses the Darcy product (four times the referenced Fanning product). This book citation is retained without a DOI because none is established in the project source. The [IAPWS viscosity release](https://iapws.org/technical-guidance/release/viscosity) is a primary transport-property reference, but this code uses rounded offline values rather than a full IAPWS implementation.

## Thermal stack and observability

`thermal.py` solves a steady two-layer finite-volume model over the common 160 mm payload disk. Each active cell has payload and cover temperatures. For a cell of area `A=Δx²`, neighboring cells receive in-plane conductance `k t`; the layer-to-layer contact conductance is `A/R''_c`; payload-to-ambient conductance is `h_env A`; and cover-to-coolant conductance is `h(x,y)A`. In compact form, each payload row balances neighbor conduction, contact, ambient loss, and its heater share; each cover row balances neighbor conduction, contact, prescribed coolant convection, and its heater share. The sparse linear system is solved directly.

The heater mask is the CAD-configured circular footprint. Every active heater cell receives `P_requested/N_heater`, split by the configured payload fraction, so the total injected power is exactly the requested value on every grid. The outer region of the square cover is omitted and its cut boundary is adiabatic.

The baseline is an editable sensitivity scenario: aluminum conductivity 167 W/(m·K), contact resistance 2×10⁻⁴ m²K/W, mean coolant-side `h` 1800 W/(m²·K), environmental `h` 8 W/(m²·K), and a 50/50 heater split. It is not a fitted model. Broad and fine imposed-`h` patterns test thermal spreading: in-plane conduction and contact resistance attenuate fine coolant-side variation before it reaches the observed upper surface.

That attenuation creates an identifiability limit. An IR surface map alone cannot uniquely determine fine coolant-side `h`, because a similar map can arise from contact resistance, uncertain heater deposition, spatial emissivity/reflection correction, registration/occlusion, environmental loss, or a different imposed pattern. A credible inference would need independent constraints and held-out checks, alongside direct flow/temperature/pressure measurements. This project therefore exports sensitivity scenarios rather than per-insert `h` predictions or a winning insert.

Energy conservation in the finite-volume solve is checked from boundary heat sums. It verifies the numerical linear-system bookkeeping, not a physical calibration. Grid tests compare hotspot and uniformity metrics across 45, 61, and 81 grids; because this is a steady solver, no time-step convergence is claimed.

## ROI statistics and thermal resistance definitions

`roi.py` makes a circular mask from supplied physical diameter, pixel size, optional center, and optional occlusion mask. It reports usable-pixel count, mean, maximum, population standard deviation, and peak-to-peak temperature. These are statistics for the specified camera ROI—not automatically the full payload.

When a corrected, time-qualified IR mean is available, the package also forms two reported resistance normalizations:

$$
R_{e}=\frac{T_{ROI}-\bar T_{in}}{\bar P_e},\qquad
R_{w}=\frac{T_{ROI}-\bar T_{in}}{\bar Q_w}.
$$

They answer different questions because electrical input and heat entering water can differ. Point resistance metrics are available when IR and a nonweak denominator are available. Their propagated uncertainty is withheld if the required camera absolute uncertainty is absent. Both are apparatus/measurement quantities, not intrinsic material properties or proof of coolant-side `h`.

The IR aggregator forms an equal-weight mean of available, timestamped maps inside the accepted interval. Sparse frames therefore support ROI statistics for that sampled mean map, not continuous surface-stability evidence. Camera NETD is not the same thing as absolute accuracy: the current resistance-uncertainty path requires the latter; NETD alone does not establish an absolute temperature uncertainty.

## Uncertainty and comparisons

The main pipeline uses metadata sensor specifications after calibration: flow, inlet temperature, outlet temperature, voltage, current, and pressure. A stated `standard` or `normal` value is one standard uncertainty; a `rectangular` bound becomes bound/√3. Correlated rectangular inputs are rejected. Declared pair correlations must use compatible calibration IDs and form a positive-semidefinite covariance matrix.

For metrics $y=g(x)$, the analytical standard uncertainty is $u(y)=\sqrt{J C J^T}$, where `J` differentiates the same time-weighted, sample-wise estimator and `C` is built from the recorded standard uncertainties and allowed correlations. The error vector has nine shared components: flow, inlet temperature, outlet temperature, voltage, current, pressure, ROI mean, relative density, and relative enthalpy. Calibration effects are treated as run-constant shared errors, not independent sample noise, so they do not automatically shrink with row count. The default deterministic Monte Carlo uses the configuration's 4,000 seeded draws and the same estimator.

Draws that leave the 15–70 °C property table or positive-flow domain cause the Monte Carlo standard uncertainty to be withheld rather than extrapolated. Sensor specifications missing from a run make uncertainty explicitly unavailable. Camera absolute accuracy is required for resistance uncertainty. Matched A−B comparisons preserve covariance associated with a shared calibration ID/channel.

This follows the general covariance and Monte Carlo framework in the [JCGM GUM publications](https://www.bipm.org/en/committees/jc/jcgm/publications), but it is not a complete hardware uncertainty qualification: repeatability, drift, synchronization error, property-table error, camera calibration, and correlation structure must be supported by actual evidence.

## Corrected tolerance and plate screening

`screening.py` writes a separately versioned arithmetic correction without changing the Rev A CAD release. It identifies three discrepancies:

| Screen | Corrected statement |
|---|---|
| Main O-ring squeeze | A numeric worst-case interval is withheld because the AS568-166 cross-section tolerance is absent from the available Rev A brief. The conditional nominal-cross-section minimum is 17.18%; it is not a qualified worst case. |
| Rib gasket compression | Incorporating 1.95–2.05 mm free thickness and 1.35–1.75 mm service gap gives 10.26–34.15%, rather than the nominal-thickness 12.5–32.5% arithmetic. |
| Cover deflection screen | With a 5.45 mm minimum cover and the 83 mm span/radius assumption in the Rev A brief, the simply-supported-to-clamped factor is $(5+\nu)/(1+\nu)=4.0075$. The ideal small-deflection values are 0.02130 mm clamped and 0.08535 mm simply supported. |

These are classical linear, uniform-load circular-plate idealizations. They do not model gasket reaction, preload, contact, square boundaries, nonlinear response, or hardware variation; they are not a seal qualification, structural release, or pressure rating.

## Software verification and boundaries

The corrected suite exercised invalid units/provenance, missing and gapped data, averaging-interval disturbances, uncertainty scaling/covariance, IR time selection, configurable generation, geometry sensitivity, solver residuals, dashboard bundles, and a full CLI demo invoked outside the checkout with explicit CAD/configuration paths. Full-suite evidence is 48 passed in 25.61 s. A minimum non-editable wheel environment (Python 3.12.14; NumPy 1.26.4, SciPy 1.12.0, pandas 2.2.0, Matplotlib 3.8.0) achieved 47 passed and 1 optional Streamlit test skipped, with 14 dependency deprecation warnings and `pip check` succeeding. These are software checks; they do not validate instruments, hardware, materials, or the physical model.

Water-property reference basis: [IAPWS-95](https://iapws.org/technical-guidance/release/IAPWS-95) and the [NIST Chemistry WebBook fluid-property interface](https://webbook.nist.gov/chemistry/fluid/). The repository has no independently certified interpolation-error budget or full IAPWS solver. The [NumPy trapezoid documentation](https://numpy.org/doc/2.2/reference/generated/numpy.trapezoid.html) documents the NumPy 2.0 API change avoided by the compatible segmentwise integration in this package.
