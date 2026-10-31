# R3 — Knowledge Representation and Reasoning Rules

These rules define the conditions under which delivery orders can be assigned to vehicles.

## A. Vehicle Capacity Rules

**R1 — Capacity Constraint**

The total volume of all orders assigned to a vehicle must not exceed the vehicle's maximum capacity.

**R2 — Non-negative Load**

The total assigned package volume must be non-negative and cannot exceed the vehicle capacity.

## B. Road Restriction Rules

**R3 — Restricted Road Access**

A vehicle must not travel through a road segment that prohibits its vehicle type.

**R4 — Zone Access Restriction**

A vehicle must not enter a delivery zone if that vehicle type is prohibited in the zone.

## C. Priority Rules

**R5 — High Priority First**

High-priority orders should be considered before medium- and low-priority orders when constructing a delivery sequence.

**R6 — Priority Preservation**

An assigned order must retain its original priority classification throughout the delivery process.

## D. Time Window Rules

**R7 — Earliest Delivery Time**

An order with a specified time window must not be delivered before its earliest permitted delivery time.

**R8 — Latest Delivery Time**

An order with a specified time window must be delivered no later than its specified deadline.

**R9 — Missing Time Window**

If an order does not have a specified time window, it should not be rejected solely because of a missing time-window constraint.

## E. Vehicle Shift Rules

**R10 — Maximum Shift Duration**

The total working duration of a vehicle must not exceed its maximum permitted shift duration.

**R11 — Service Time Inclusion**

The service time required to complete each delivery must be included when calculating the vehicle's schedule and shift duration.

## F. Order Assignment Rules

**R12 — Valid Order Assignment**

An order can only be assigned to a vehicle if the vehicle satisfies all applicable capacity, road access, zone access, time-window and shift-duration constraints.

## Summary

The twelve rules provide the initial knowledge base for the R3 rule engine. They will subsequently be translated into executable conditions and actions, with positive and negative unit tests.
