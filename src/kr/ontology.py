
"""
R3 - Knowledge Representation
Defines the ontology of the multi-agent delivery system.

Main entities:
Vehicle, Order, Road, Zone

This file defines domain concepts and their relationships.
Operational Vehicle and Order data structures are owned by R1.
"""

# ==========================================
# 1. ENTITY DEFINITIONS
# ==========================================

ONTOLOGY = {

    "Vehicle": {
        "description": "A delivery vehicle responsible for transporting orders.",
        "attributes": {
            "vehicle_id": "Unique vehicle identifier",
            "capacity_cm3": "Maximum package volume the vehicle can carry",
            "current_load_cm3": "Total volume currently assigned",
            "shift_limit_minutes": "Maximum permitted working duration",
            "vehicle_type": "Type or category of vehicle"
        }
    },

    "Order": {
        "description": "A package or delivery request assigned to a vehicle.",
        "attributes": {
            "order_id": "Unique order identifier",
            "volume_cm3": "Package volume",
            "priority_tier": "Priority category of the order",
            "time_window_start": "Earliest permitted delivery time",
            "time_window_end": "Latest permitted delivery time",
            "service_time_seconds": "Expected time required to complete delivery",
            "zone_id": "Delivery zone associated with the order"
        }
    },

    "Road": {
        "description": "A road segment connecting two locations.",
        "attributes": {
            "road_id": "Unique road identifier",
            "source_node": "Starting road-network node",
            "destination_node": "Ending road-network node",
            "road_class": "Classification of the road",
            "restricted_vehicle_types": "Vehicle types prohibited on this road"
        }
    },

    "Zone": {
        "description": "A geographical delivery area containing delivery locations.",
        "attributes": {
            "zone_id": "Unique zone identifier",
            "zone_type": "Classification of the delivery zone",
            "restricted_vehicle_types": "Vehicle types restricted in this zone",
            "priority_level": "Delivery importance of the zone"
        }
    }
}


# ==========================================
# 2. RELATIONSHIPS
# ==========================================

RELATIONSHIPS = {

    "Vehicle-Order": "A vehicle can be assigned multiple orders.",

    "Order-Zone": "Each order belongs to a delivery zone.",

    "Road-Zone": "A road segment may connect or pass through delivery zones.",

    "Road-Vehicle": "A road may allow or restrict certain vehicle types.",

    "Vehicle-Road": "A vehicle travels through multiple road segments.",

    "Order-Priority": "Orders are classified according to priority tiers."
}


# ==========================================
# 3. PRIORITY DEFINITIONS
# ==========================================

PRIORITY_TIERS = {
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3
}


# ==========================================
# 4. BASIC DOMAIN CONSTANTS
# ==========================================

TIME_UNIT = "minutes"
DISTANCE_UNIT = "meters"
VOLUME_UNIT = "cm3"
SERVICE_TIME_UNIT = "seconds"


# ==========================================
# 5. DISPLAY ONTOLOGY
# ==========================================

def display_ontology():
    """Print the entities and their attributes."""

    for entity, details in ONTOLOGY.items():
        print(f"\nENTITY: {entity}")
        print(details["description"])

        for attribute, description in details["attributes"].items():
            print(f"  - {attribute}: {description}")

    print("\nRELATIONSHIPS:")
    for relation, description in RELATIONSHIPS.items():
        print(f"  - {relation}: {description}")


if __name__ == "__main__":
    display_ontology()
