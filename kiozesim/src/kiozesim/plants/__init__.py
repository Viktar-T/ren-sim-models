from kiozesim.plants.base import Plant, PlantParams
from kiozesim.plants.combustion import CombustionPlant
from kiozesim.plants.digester import DigesterPlant
from kiozesim.plants.hawt import HAWTPlant
from kiozesim.plants.heat_store import HeatStorePlant
from kiozesim.plants.pv import PVPlant
from kiozesim.plants.vawt import VAWTPlant

# directory name under kiozesim/tests/golden/ -> plant class
REGISTRY: dict[str, type[Plant]] = {  # type: ignore[type-arg]
    "pv": PVPlant,
    "hawt": HAWTPlant,
    "vawt": VAWTPlant,
    "combustion": CombustionPlant,
    "digester": DigesterPlant,
    "heat_store": HeatStorePlant,
}

__all__ = ["REGISTRY", "Plant", "PlantParams"]
