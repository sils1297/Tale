"""
The house, where the player starts the game

'Tale' mud driver, mudlib and interactive fiction framework
Copyright by Irmen de Jong (irmen@razorvine.net)
"""

from __future__ import absolute_import, print_function, division, unicode_literals
import datetime
import random
from tale.base import Location, Exit, Door, Item
from tale.npc import NPC
from tale.globalcontext import mud_context
from tale.lang import capital

livingroom = Location("Living room", "The living room in your home in the outskirts of the city.")
closet = Location("Closet", "A small room.")

livingroom.exits["closet"] = Exit(closet, "There's a small closet in your house.")
closet.exits["living room"] = Exit(livingroom, "You can see the living room.")

class GameEnd(Location):
    def init(self):
        pass

    def notify_player_arrived(self, player, previous_location):
        # player has entered!
        player.story_completed()

outside = GameEnd("Outside", "You escaped the house.")
door = Door(outside, "A door leads to the garden.", "There's a heavy door here that leads to the garden outside the house.", locked=True, opened=False)
door.door_code = 1
livingroom.exits["garden"] = livingroom.exits["door"] = door

key = Item("key", "small rusty key", "This key is small and rusty. It has a label attached, reading \"garden door\".")
key.door_code = 1
closet.insert(key, None)

class Cat(NPC):
    def init(self):
        self.aliases={"cat"}
        due = mud_context.driver.game_clock.plus_realtime(datetime.timedelta(seconds=2))
        mud_context.driver.defer(due, self, self.do_purr)

    def do_purr(self, driver):
        if random.random() > 0.5:
            self.location.tell("%s purrs happily." % capital(self.title))
        else:
            self.location.tell("%s yawns sleepily." % capital(self.title))
        due = driver.game_clock.plus_realtime(datetime.timedelta(seconds=random.randint(5, 20)))
        driver.defer(due, self, self.do_purr)

    def notify_action(self, parsed, actor):
        if parsed.verb in ("pet", "stroke", "tickle", "cuddle", "hug"):
            self.tell_others("{Title} curls up in a ball and purrs contently.")
        elif parsed.verb in ("hello", "hi", "greet"):
            self.tell_others("{Title} stares at you incomprehensibly.")


cat = Cat("garfield", "m", race="cat", description="A very obese cat, orange and black. It looks tired, but glances at you happily.")
cat.move(livingroom)
