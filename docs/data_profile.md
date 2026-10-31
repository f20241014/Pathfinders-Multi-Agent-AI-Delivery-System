# Amazon Last Mile Dataset — Data Profile

**Role:** R3 — Knowledge Representation & Reasoning and Real-Demand Scenario Engineering  
**Dataset:** Amazon Last Mile Routing Research Challenge 2021  
**Purpose:** Analyse historical delivery demand characteristics to support realistic order generation and constraint modelling.

## 1. Dataset Overview

The Amazon Last Mile Routing dataset contains historical delivery route, stop and package information.

The dataset is used to understand:
- Delivery route characteristics.
- Number of stops per route.
- Vehicle capacity.
- Package dimensions.
- Planned package service times.
- Availability and width of delivery time windows.
- Delivery zones and stop types.

The original geographical coordinates are obfuscated. Therefore, they are not treated as actual Hyderabad delivery locations. The dataset is used to learn statistical demand characteristics, while Hyderabad locations are obtained from the project's road network.

## 2. Route-Level Analysis

The route dataset contains 6,112 routes and 904,527 total stops, including station stops.

| Metric | Value |
|---|---:|
| Total routes | 6,112 |
| Total stops | 904,527 |
| Dropoff stops | 898,415 |
| Station stops | 6,112 |
| Distinct zones | 8,963 |
| Mean stops per route | 147.99 |
| Median stops per route | 151 |
| Minimum stops | 33 |
| Maximum stops | 238 |
| First quartile (Q1) | 129 |
| Third quartile (Q3) | 170 |

The average number of dropoff stops per route is approximately 147.

### Route Score Distribution

| Route Score | Number of Routes |
|---|---:|
| High | 2,718 |
| Medium | 3,292 |
| Low | 102 |

## 3. Vehicle Capacity Analysis

Vehicle capacity is represented by `executor_capacity_cm3`.

| Metric | Value (cm³) |
|---|---:|
| Mean | 3,607,177.98 |
| Median | 3,313,071 |
| Minimum | 3,114,853.25 |
| Maximum | 4,247,527 |
| Q1 | 3,313,071 |
| Q3 | 4,247,527 |

These values provide an initial reference for modelling vehicle capacity constraints.

## 4. Package-Level Analysis

A total of 1,457,175 packages were analysed.

### Planned Service Time

| Metric | Value (seconds) |
|---|---:|
| Mean | 68.24 |
| Median | 53 |
| Minimum | 0.7 |
| Maximum | 8,007 |
| Q1 | 36.5 |
| Q3 | 78 |

### Package Dimensions

| Dimension | Mean (cm) | Median (cm) | Minimum (cm) | Maximum (cm) |
|---|---:|---:|---:|---:|
| Depth | 34.09 | 32.7 | 0.8 | 132.1 |
| Height | 10.2 | 7.6 | 0 | 83.8 |
| Width | 24.79 | 24.3 | 0.2 | 101.6 |

The package dimension and service-time distributions will be used to generate realistic package attributes.

Extreme values should be investigated before applying any filtering or clipping.

## 5. Time-Window Analysis

Time windows are represented by `start_time_utc` and `end_time_utc`.

| Metric | Value |
|---|---:|
| Total packages | 1,457,175 |
| Complete time windows | 113,993 |
| Missing time windows | 1,343,182 |
| Invalid time windows | 0 |
| Complete time-window share | 7.82% |
| Missing time-window share | 92.18% |

### Time-Window Width

| Metric | Value (hours) |
|---|---:|
| Mean | 9 |
| Median | 8 |
| Minimum | 3.5 |
| Maximum | 23.98 |
| Q1 | 7 |
| Q3 | 8.5 |

Most packages do not have explicit delivery time windows. The order generator must preserve this characteristic rather than assigning time windows to every order.

## 6. Important Findings for R3

1. The dataset contains 6,112 historical routes.
2. The average route contains approximately 147 dropoff stops.
3. Vehicle capacities vary and must be considered during feasibility checking.
4. Package dimensions are important for calculating volume-based capacity requirements.
5. Planned service time must be included in delivery scheduling.
6. Only 7.82% of packages have complete time windows.
7. Most packages have no explicit time-window restriction.
8. The dataset contains 8,963 distinct delivery zones.
9. Extreme service-time and dimension values should be investigated before filtering.
10. Obfuscated coordinates cannot be interpreted as actual Hyderabad geography.

## 7. Assumptions and Limitations

- Amazon's geographical coordinates are obfuscated.
- Amazon package and route statistics are used as demand-distribution references, not as direct Hyderabad delivery records.
- Hyderabad delivery locations will be obtained from the project's road network.
- Missing time windows will be represented as unrestricted time-window fields, subject to the project's scheduling rules.
- Package volume can be estimated using depth × height × width.
- Vehicle capacity and package volume will use consistent cubic-centimetre units.
- Statistical distributions will be used to generate synthetic orders.

## 8. Conclusion

The dataset provides useful information about delivery demand, vehicle capacities, package dimensions, service times and time-window characteristics.

These findings form the statistical foundation for R3's realistic order generator and Knowledge Representation and Reasoning module.

The next stage is to develop the delivery ontology, define business rules and implement a rule-based feasibility engine.
