from __future__ import annotations

from app.data.database.components import ComponentType
from app.data.database.database import DB
from app.data.database.item_components import ItemComponent, ItemTags
from app.engine import (action, banner, combat_calcs, engine, equations,
                        image_mods, item_funcs, item_system, skill_system)
from app.engine.game_state import game
from app.engine.objects.unit import UnitObject
from app.utilities import utils, static_random

from app.engine.item_components.hit_components import Steal


class DoNothing(ItemComponent):
    nid = 'do_nothing'
    desc = 'does nothing'
    tag = ItemTags.CUSTOM

    expose = ComponentType.Int
    value = 1

class StatusAfterCombat(ItemComponent):
    nid = 'status_after_combat'
    desc = "Target will gain the specified status at the end of combat. Prevents changes being applied mid-combat."
    tag = ItemTags.SPECIAL

    expose = ComponentType.Skill  # Nid

    def end_combat(self, playback, unit, item, target, item2, mode):
        act = action.AddSkill(target, self.value, unit)
        action.do(act)

    def ai_priority(self, unit, item, target, move):
        # Do I add a new status to the target
        return ai_status_priority(unit, target, item, move, self.value)
        
class StealPlus(Steal):
    nid = 'steal_plus'
    desc = "Steal items, weapons, staves if Con > Wt"
    tag = ItemTags.SPECIAL

    def item_restrict(self, unit, item, defender, def_item) -> bool:
        if item_system.unstealable(defender, def_item):
            return False
        if item_funcs.inventory_full(unit, def_item):
            return False
        if defender and defender.get_weapon() and def_item.uid == defender.get_weapon().uid:
            return False
        if item_system.is_weapon(defender, def_item) or item_system.is_spell(defender, def_item):
            return not def_item.weight or unit.get_stat('CON') >= def_item.weight.value
        return True
        
class EvalTargetRestrictOverride(ItemComponent):
    nid = 'eval_target_restrict_override'
    desc = \
"""
Restricts which units or spaces can be targeted. These properties are accessible in the eval body:

- `unit`: the unit using the item
- `target`: the target of the item
- `item`: the item itself
- `position`: the position of the unit
- `target_pos`: the position of the target
"""
    tag = ItemTags.TARGET

    expose = ComponentType.String
    value = 'True'

    def target_restrict(self, unit, item, def_pos, splash) -> bool:
        from app.engine import evaluate
        try:
            target = game.board.get_unit(def_pos)
            unit_pos = unit.position
            target_pos = def_pos
            if evaluate.evaluate(self.value, unit, target, unit_pos, local_args={'target_pos': target_pos, 'item': item}):
                return True
            for s_pos in splash:
                target = game.board.get_unit(s_pos)
                if evaluate.evaluate(self.value, unit, target, unit_pos, local_args={'target_pos': s_pos, 'item': item}):
                    return True
        except Exception as e:
            print("Could not evaluate %s (%s)" % (self.value, e))
            return True
        return False

    def simple_target_restrict(self, unit, item):
        from app.engine import evaluate
        try:
            if evaluate.evaluate(self.value, unit, local_args={'item': item}):
                return True
        except Exception as e:
            print("Could not evaluate %s (%s)" % (self.value, e))
            return True
        return False