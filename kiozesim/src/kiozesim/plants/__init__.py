from kiozesim.plants.base import Plant, PlantParams
from kiozesim.plants.biogas import BiogasPlant
from kiozesim.plants.boiler import BoilerPlant
from kiozesim.plants.hawt import HAWTPlant
from kiozesim.plants.pv import PVPlant
from kiozesim.plants.vawt import VAWTPlant

# directory name under kiozesim/tests/golden/ -> plant class
REGISTRY: dict[str, type[Plant]] = {  # type: ignore[type-arg]
    "pv": PVPlant,
    "hawt": HAWTPlant,
    "vawt": VAWTPlant,
    "biogas": BiogasPlant,
    "boiler": BoilerPlant,
}

__all__ = ["REGISTRY", "Plant", "PlantParams"]
