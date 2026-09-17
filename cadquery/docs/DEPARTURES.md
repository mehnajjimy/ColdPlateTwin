# Rev A departures and interpretations

This file is the editable record paired with the validation PDF.

| Item | Departure or interpretation | Engineering reason |
|---|---|---|
| References | No separate engineering review or original project plan was attached; the pasted Rev A brief is the controlling input. | Avoid inventing absent requirements. |
| FI-100 feeds | Two diagonal feed transitions join the x=+/-70 transfer centers to the first and last 96 mm passes. | Preserves one continuous route inside the usable disk without crossing intermediate passages. |
| FI-100 path length | The modeled screening centerline is 1120.4 mm, not 1.5 m. | Measured from the routing definition: nine 96 mm passes, eight semicircular R6 returns and two diagonal transitions. |
| Static taps | Two 1.5 mm bores with provisional 5 mm thread envelopes run from the front edge to the transfer centers. | Defines flush upstream/downstream measurement locations without penetrating CP-002. |
| Locator | A round pin at y=+70 and a radial slot/pin at y=-70 replace the preferred central locator. | Avoids the active central flow/ROI while retaining one constrained and one expansion-permitting datum. |
| CL-001 | Only an envelope-level ring with three adjustment slots is modeled. | Heater thickness, lead exit and mounting are unresolved; false detail is intentionally omitted. |
| NPT fittings | The package includes a conservative cylindrical/hex candidate envelope, not supplier-specific thread geometry. | No actual fitting was selected. |
| Gasket corners | DXF cutting outlines are nominal planar geometry without die-cut corner compensation. | Supplier/process-specific compensation is not available. |
| PETG | STL meshes are explicitly prototype geometry only. | Printed PETG does not inherit POM-C machining tolerances or conditioning behavior. |

No other intentional dimensional departure from the supplied Rev A specification
is known in this package. Unresolved selections are identified as release blockers,
not silently treated as released design inputs.
