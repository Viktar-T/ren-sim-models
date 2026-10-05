from kioze_sim.plants.base import Plant, PlantParams
from kioze_sim.plants.biogas import BiogasPlant
from kioze_sim.plants.boiler import BoilerPlant
from kioze_sim.plants.hawt import HAWTPlant
from kioze_sim.plants.pv import PVPlant
from kioze_sim.plants.vawt import VAWTPlant

# directory name under tests/golden/ -> plant class
REGISTRY: dict[str, type[Plant]] = {  # type: ignore[type-arg]
    "pv": PVPlant,
    "hawt": HAWTPlant,
    "vawt": VAWTPlant,
    "biogas": BiogasPlant,
    "boiler": BoilerPlant,
}

__all__ = ["REGISTRY", "Plant", "PlantParams"]
