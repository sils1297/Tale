"""
Unit tests for the Soul

'Tale' mud driver, mudlib and interactive fiction framework
Copyright by Irmen de Jong (irmen@razorvine.net)
"""

from __future__ import print_function, division, unicode_literals, absolute_import
import unittest
import tale
import tale.base
import tale.soul
import tale.player
import tale.npc
import tale.errors
from tests.supportstuff import TestDriver


class TestSoul(unittest.TestCase):
    def setUp(self):
        tale.mud_context.driver = TestDriver()

    def testSpacify(self):
        self.assertEqual("", tale.soul.spacify(""))
        self.assertEqual(" abc", tale.soul.spacify("abc"))
        self.assertEqual(" abc", tale.soul.spacify(" abc"))
        self.assertEqual(" abc", tale.soul.spacify("  abc"))
        self.assertEqual(" abc", tale.soul.spacify("  \t\tabc"))
        self.assertEqual(" \nabc", tale.soul.spacify("  \nabc"))

    def testUnknownVerb(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        with self.assertRaises(tale.soul.UnknownVerbException) as ex:
            parsed = tale.soul.ParseResult("_unknown_verb_")
            soul.process_verb_parsed(player, parsed)
        self.assertEqual("_unknown_verb_", str(ex.exception))
        self.assertEqual("_unknown_verb_", ex.exception.verb)
        self.assertEqual(None, ex.exception.words)
        self.assertEqual(None, ex.exception.qualifier)
        with self.assertRaises(tale.soul.UnknownVerbException) as ex:
            soul.process_verb(player, "fail _unknown_verb_ herp derp")
        self.assertEqual("_unknown_verb_", ex.exception.verb)
        self.assertEqual("fail", ex.exception.qualifier)
        self.assertEqual(["_unknown_verb_", "herp", "derp"], ex.exception.words)
        self.assertTrue(soul.is_verb("bounce"))
        self.assertFalse(soul.is_verb("_unknown_verb_"))

    def testAdverbWithoutVerb(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        with self.assertRaises(tale.soul.UnknownVerbException) as ex:
            soul.parse(player, "forg")     # forgetfully etc.
        self.assertEqual("forg", ex.exception.verb)
        with self.assertRaises(tale.errors.ParseError) as ex:
            soul.parse(player, "giggle forg")     # forgetfully etc.
        self.assertEqual("What adverb did you mean: forgetfully or forgivingly?", str(ex.exception))

    def testExternalVerbs(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        with self.assertRaises(tale.soul.UnknownVerbException):
            soul.process_verb(player, "externalverb")
        verb, _ = soul.process_verb(player, "sit", external_verbs=set())
        self.assertEqual("sit", verb)
        with self.assertRaises(tale.soul.NonSoulVerb) as x:
            soul.process_verb(player, "sit", external_verbs={"sit"})
        self.assertEqual("sit", str(x.exception))
        self.assertEqual("sit", x.exception.parsed.verb)
        with self.assertRaises(tale.soul.NonSoulVerb) as x:
            soul.process_verb(player, "externalverb", external_verbs={"externalverb"})
        self.assertIsInstance(x.exception.parsed, tale.soul.ParseResult)
        self.assertEqual("externalverb", x.exception.parsed.verb)
        with self.assertRaises(tale.soul.NonSoulVerb) as x:
            soul.process_verb(player, "who who", external_verbs={"who"})
        self.assertEqual("who", x.exception.parsed.verb, "who as external verb needs to be processed as normal arg, not as adverb")
        self.assertEqual(["who"], x.exception.parsed.args, "who as external verb needs to be processed as normal arg, not as adverb")

    def testExternalVerbUnknownWords(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        with self.assertRaises(tale.soul.ParseError) as x:
            soul.process_verb(player, "sit door1")
        self.assertEqual("It's not clear what you mean by 'door1'.", str(x.exception))
        with self.assertRaises(tale.soul.NonSoulVerb) as x:
            soul.process_verb(player, "sit door1 zen", external_verbs={"sit"})
        parsed = x.exception.parsed
        self.assertEqual("sit", parsed.verb)
        self.assertEqual(["door1", "zen"], parsed.args)
        self.assertEqual(["door1", "zen"], parsed.unrecognized)

    def testWho(self):
        player = tale.player.Player("fritz", "m")
        julie = tale.base.Living("julie", "f", race="human")
        harry = tale.base.Living("harry", "m", race="human")
        self.assertEqual("yourself", tale.soul.who_replacement(player, player, player))  # you kick yourself
        self.assertEqual("himself", tale.soul.who_replacement(player, player, julie))   # fritz kicks himself
        self.assertEqual("harry", tale.soul.who_replacement(player, harry, player))   # you kick harry
        self.assertEqual("harry", tale.soul.who_replacement(player, harry, julie))    # fritz kicks harry
        self.assertEqual("harry", tale.soul.who_replacement(player, harry, None))     # fritz kicks harry
        self.assertEqual("you", tale.soul.who_replacement(julie, player, player))  # julie kicks you
        self.assertEqual("Fritz", tale.soul.who_replacement(julie, player, harry))   # julie kicks fritz
        self.assertEqual("harry", tale.soul.who_replacement(julie, harry, player))   # julie kicks harry
        self.assertEqual("you", tale.soul.who_replacement(julie, harry, harry))    # julie kicks you
        self.assertEqual("harry", tale.soul.who_replacement(julie, harry, None))     # julie kicks harry

    def testPoss(self):
        player = tale.player.Player("fritz", "m")
        julie = tale.base.Living("julie", "f", race="human")
        harry = tale.base.Living("harry", "m", race="human")
        self.assertEqual("your own", tale.soul.poss_replacement(player, player, player))  # your own foot
        self.assertEqual("his own", tale.soul.poss_replacement(player, player, julie))   # his own foot
        self.assertEqual("harry's", tale.soul.poss_replacement(player, harry, player))   # harrys foot
        self.assertEqual("harry's", tale.soul.poss_replacement(player, harry, julie))    # harrys foot
        self.assertEqual("harry's", tale.soul.poss_replacement(player, harry, None))     # harrys foot
        self.assertEqual("your", tale.soul.poss_replacement(julie, player, player))   # your foot
        self.assertEqual("Fritz's", tale.soul.poss_replacement(julie, player, harry))    # fritz' foot
        self.assertEqual("harry's", tale.soul.poss_replacement(julie, harry, player))    # harrys foot
        self.assertEqual("your", tale.soul.poss_replacement(julie, harry, harry))     # your foot
        self.assertEqual("harry's", tale.soul.poss_replacement(julie, harry, None))      # harrys foot

    def testGender(self):
        soul = tale.soul.Soul()
        with self.assertRaises(KeyError):
            tale.player.Player("player", "x")
        player = tale.player.Player("julie", "f")
        parsed = tale.soul.ParseResult("stomp")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("Julie stomps her foot.", room_msg)
        player = tale.player.Player("fritz", "m")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("Fritz stomps his foot.", room_msg)
        player = tale.player.Player("zyzzy", "n")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("Zyzzy stomps its foot.", room_msg)

    def testIgnorewords(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("fritz", "m")
        with self.assertRaises(tale.errors.ParseError):
            soul.parse(player, "in")
        with self.assertRaises(tale.errors.ParseError):
            soul.parse(player, "and")
        with self.assertRaises(tale.errors.ParseError):
            soul.parse(player, "fail")
        with self.assertRaises(tale.errors.ParseError):
            soul.parse(player, "fail in")
        with self.assertRaises(tale.soul.UnknownVerbException) as x:
            soul.parse(player, "in fail")
        self.assertEqual("fail", x.exception.verb)
        parsed = soul.parse(player, "in sit")
        self.assertIsNone(parsed.qualifier)
        self.assertIsNone(parsed.adverb)
        self.assertEqual("sit", parsed.verb)
        parsed = soul.parse(player, "fail in sit")
        self.assertEqual("fail", parsed.qualifier)
        self.assertIsNone(parsed.adverb)
        self.assertEqual("sit", parsed.verb)

    def testMultiTarget(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        philip = tale.npc.NPC("philip", "m")
        kate = tale.npc.NPC("kate", "f", title="Kate")
        cat = tale.npc.NPC("cat", "n", title="hairy cat")
        targets = [philip, kate, cat]
        # peer
        parsed = tale.soul.ParseResult("peer", who_order=targets)
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual(set(targets), who)
        self.assertTrue(player_msg.startswith("You peer at "))
        self.assertTrue("philip" in player_msg and "hairy cat" in player_msg and "Kate" in player_msg)
        self.assertTrue(room_msg.startswith("Julie peers at "))
        self.assertTrue("philip" in room_msg and "hairy cat" in room_msg and "Kate" in room_msg)
        self.assertEqual("Julie peers at you.", target_msg)
        # all/everyone
        player.move(tale.base.Location("somewhere"))
        livings = set(targets)
        livings.add(player)
        player.location.livings = livings
        verb, (who, player_msg, room_msg, target_msg) = soul.process_verb(player, "smile confusedly at everyone")
        self.assertEqual("smile", verb)
        self.assertEqual(3, len(who))
        self.assertEqual(set(targets), set(who), "player should not be in targets")
        self.assertTrue("philip" in player_msg and "hairy cat" in player_msg and "Kate" in player_msg and "yourself" not in player_msg)
        self.assertTrue("philip" in room_msg and "hairy cat" in room_msg and "Kate" in room_msg and "herself" not in room_msg)
        self.assertEqual("Julie smiles confusedly at you.", target_msg)

    def testWhoInfo(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        kate = tale.npc.NPC("kate", "f", title="Kate")
        cat = tale.npc.NPC("cat", "n", title="hairy cat")
        player.move(tale.base.Location("somewhere"))
        cat.move(player.location)
        kate.move(player.location)
        parsed = soul.parse(player, "smile at cat and kate and myself")
        self.assertEqual(["cat", "kate", "myself"], parsed.args)
        self.assertEqual(3, len(parsed.who_order))
        self.assertEqual(3, len(parsed.who_info))
        self.assertTrue(cat in parsed.who_info and kate in parsed.who_info and player in parsed.who_info)
        self.assertEqual(0, parsed.who_info[cat].sequence)
        self.assertEqual(1, parsed.who_info[kate].sequence)
        self.assertEqual(2, parsed.who_info[player].sequence)
        self.assertEqual("at", parsed.who_info[cat].previous_word)
        self.assertEqual("and", parsed.who_info[kate].previous_word)
        self.assertEqual("and", parsed.who_info[player].previous_word)
        self.assertEqual([cat, kate, player], parsed.who_order)
        parsed = soul.parse(player, "smile at myself and kate and cat")
        self.assertEqual(["myself", "kate", "cat"], parsed.args)
        self.assertEqual([player, kate, cat], parsed.who_order)
        parsed = soul.parse(player, "smile at kate, cat and cat")
        self.assertEqual(["kate", "cat", "cat"], parsed.args, "deal with multiple occurences")
        self.assertEqual([kate, cat, cat], parsed.who_order, "deal with multiple occurrences")
        parsed = soul.parse(player, "smile at kate cat myself")
        self.assertEqual("at", parsed.who_info[kate].previous_word, "ony kate has a previous word")
        self.assertEqual(None, parsed.who_info[cat].previous_word, "cat doesn't have a previous word")
        self.assertEqual(None, parsed.who_info[player].previous_word, "player doesn't have a previous word")

    def testVerbTarget(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        player.title = "the great Julie, destroyer of worlds"
        player.move(tale.base.Location("somewhere"))
        npc_max = tale.npc.NPC("max", "m")
        player.location.livings = {npc_max, player}
        verb, (who, player_msg, room_msg, target_msg) = soul.process_verb(player, "grin")
        self.assertEqual("grin", verb)
        self.assertTrue(len(who) == 0)
        self.assertIsInstance(who, (set, frozenset), "targets must be a set for O(1) lookups")
        self.assertEqual("You grin evilly.", player_msg)
        self.assertEqual("The great Julie, destroyer of worlds grins evilly.", room_msg)
        verb, (who, player_msg, room_msg, target_msg) = soul.process_verb(player, "grin at max")
        self.assertEqual("grin", verb)
        self.assertTrue(len(who) == 1)
        self.assertIsInstance(who, (set, frozenset), "targets must be a set for O(1) lookups")
        self.assertEqual("max", list(who)[0].name)
        self.assertEqual("You grin evilly at max.", player_msg)
        self.assertEqual("The great Julie, destroyer of worlds grins evilly at max.", room_msg)
        self.assertEqual("The great Julie, destroyer of worlds grins evilly at you.", target_msg)
        # parsed results
        parsed = soul.parse(player, "grin at all")
        self.assertEqual("grin", parsed.verb)
        self.assertEqual([npc_max], parsed.who_order, "parse('all') must result in only the npc, not the player")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertTrue(len(who) == 1)
        self.assertIsInstance(who, (set, frozenset), "targets must be a set for O(1) lookups")
        self.assertEqual("max", list(who)[0].name)
        self.assertEqual("You grin evilly at max.", player_msg)
        parsed = soul.parse(player, "grin at all and me")
        self.assertEqual("grin", parsed.verb)
        self.assertEqual([npc_max, player], parsed.who_order, "parse('all and me') must include npc and the player")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual({npc_max}, who, "player should no longer be part of the remaining targets")
        self.assertTrue("yourself" in player_msg and "max" in player_msg)

    def testMessageQuote(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        # babble
        parsed = tale.soul.ParseResult("babble")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You babble something incoherently.", player_msg)
        self.assertEqual("Julie babbles something incoherently.", room_msg)
        # babble with message
        parsed.message = "blurp"
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You babble 'blurp' incoherently.", player_msg)
        self.assertEqual("Julie babbles 'blurp' incoherently.", room_msg)

    def testMessageQuoteParse(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        player.move(tale.base.Location("somewhere"))
        player.location.livings = {tale.npc.NPC("max", "m"), player}
        # whisper
        verb, (who, player_msg, room_msg, target_msg) = soul.process_verb(player, "whisper \"hello there\"")
        self.assertEqual("You whisper 'hello there'.", player_msg)
        self.assertEqual("Julie whispers 'hello there'.", room_msg)
        # whisper to a person
        verb, (who, player_msg, room_msg, target_msg) = soul.process_verb(player, "whisper to max \"hello there\"")
        self.assertEqual("You whisper 'hello there' to max.", player_msg)
        self.assertEqual("Julie whispers 'hello there' to max.", room_msg)
        # whisper to a person with adverb
        verb, (who, player_msg, room_msg, target_msg) = soul.process_verb(player, "whisper softly to max \"hello there\"")
        self.assertEqual("You whisper 'hello there' softly to max.", player_msg)
        self.assertEqual("Julie whispers 'hello there' softly to max.", room_msg)

    def testBodypart(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        targets = [tale.npc.NPC("max", "m")]
        parsed = tale.soul.ParseResult("beep", who_order=targets)
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You triumphantly beep max on the nose.", player_msg)
        self.assertEqual("Julie triumphantly beeps max on the nose.", room_msg)
        self.assertEqual("Julie triumphantly beeps you on the nose.", target_msg)
        parsed.bodypart = "arm"
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You triumphantly beep max on the arm.", player_msg)
        self.assertEqual("Julie triumphantly beeps max on the arm.", room_msg)
        self.assertEqual("Julie triumphantly beeps you on the arm.", target_msg)
        # check handling of more than one bodypart
        with self.assertRaises(tale.errors.ParseError) as ex:
            soul.process_verb(player, "kick max side knee")
        self.assertEqual("You can't do that both in the side and on the knee.", str(ex.exception))

    def testQualifier(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        targets = [tale.npc.NPC("max", "m")]
        parsed = tale.soul.ParseResult("tickle", qualifier="fail", who_order=targets)
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You try to tickle max, but fail miserably.", player_msg)
        self.assertEqual("Julie tries to tickle max, but fails miserably.", room_msg)
        self.assertEqual("Julie tries to tickle you, but fails miserably.", target_msg)
        parsed.qualifier = "don't"
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You don't tickle max.", player_msg)
        self.assertEqual("Julie doesn't tickle max.", room_msg)
        self.assertEqual("Julie doesn't tickle you.", target_msg)
        parsed.qualifier = "suddenly"
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You suddenly tickle max.", player_msg)
        self.assertEqual("Julie suddenly tickles max.", room_msg)
        self.assertEqual("Julie suddenly tickles you.", target_msg)
        parsed = tale.soul.ParseResult("scream", qualifier="don't", message="I have no idea")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You don't scream 'I have no idea' loudly.", player_msg)
        self.assertEqual("Julie doesn't scream 'I have no idea' loudly.", room_msg)
        self.assertEqual("Julie doesn't scream 'I have no idea' loudly.", target_msg)

    def testQualifierParse(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        verb, (who, player_msg, room_msg, target_msg) = soul.process_verb(player, "dont scream")
        self.assertEqual("don't scream", verb, "expected spell-corrected qualifier")
        self.assertEqual("You don't scream loudly.", player_msg)
        self.assertEqual("Julie doesn't scream loudly.", room_msg)
        self.assertEqual("Julie doesn't scream loudly.", target_msg)
        verb, (who, player_msg, room_msg, target_msg) = soul.process_verb(player, "don't scream")
        self.assertEqual("don't scream", verb)
        self.assertEqual("You don't scream loudly.", player_msg)
        self.assertEqual("Julie doesn't scream loudly.", room_msg)
        self.assertEqual("Julie doesn't scream loudly.", target_msg)
        verb, (who, player_msg, room_msg, target_msg) = soul.process_verb(player, "don't scream \"I have no idea\"")
        self.assertEqual("don't scream", verb)
        self.assertEqual("You don't scream 'I have no idea' loudly.", player_msg)
        self.assertEqual("Julie doesn't scream 'I have no idea' loudly.", room_msg)
        self.assertEqual("Julie doesn't scream 'I have no idea' loudly.", target_msg)
        verb, (who, player_msg, room_msg, target_msg) = soul.process_verb(player, "fail sit")
        self.assertEqual("fail sit", verb)
        self.assertEqual("You try to sit down, but fail miserably.", player_msg)
        self.assertEqual("Julie tries to sit down, but fails miserably.", room_msg)

    def testAdverbs(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f", "human")
        # check handling of more than one adverb
        with self.assertRaises(tale.errors.ParseError) as ex:
            soul.process_verb(player, "cough sickly and noisily")
        self.assertEqual("You can't do that both sickly and noisily.", str(ex.exception))
        # check handling of adverb prefix where there is 1 unique result
        verb, (who, player_msg, room_msg, target_msg) = soul.process_verb(player, "cough sic")
        self.assertEqual("You cough sickly.", player_msg)
        self.assertEqual("Julie coughs sickly.", room_msg)
        # check handling of adverb prefix where there are more results
        with self.assertRaises(tale.errors.ParseError) as ex:
            soul.process_verb(player, "cough si")
        self.assertEqual("What adverb did you mean: sickly, sideways, signally, significantly, or silently?", str(ex.exception))

    def testUnrecognisedWord(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f", "human")
        with self.assertRaises(tale.errors.ParseError):
            soul.process_verb(player, "cough hubbabubba")

    def testCheckNameWithSpaces(self):
        livings = {"rat": "RAT", "brown bird": "BROWN BIRD"}
        items = {"paper": "PAPER", "blue gem": "BLUE GEM", "dark red crystal": "DARK RED CRYSTAL"}
        result = tale.soul.check_name_with_spaces(["give", "the", "blue", "gem", "to", "rat"], 0, livings, items)
        self.assertEqual((None, None, 0), result)
        result = tale.soul.check_name_with_spaces(["give", "the", "blue", "gem", "to", "rat"], 1, livings, items)
        self.assertEqual((None, None, 0), result)
        result = tale.soul.check_name_with_spaces(["give", "the", "blue", "gem", "to", "rat"], 4, livings, items)
        self.assertEqual((None, None, 0), result)
        result = tale.soul.check_name_with_spaces(["give", "the", "blue", "gem", "to", "rat"], 2, livings, items)
        self.assertEqual(("BLUE GEM", "blue gem", 2), result)
        result = tale.soul.check_name_with_spaces(["give", "the", "dark", "red", "crystal", "to", "rat"], 2, livings, items)
        self.assertEqual(("DARK RED CRYSTAL", "dark red crystal", 3), result)
        result = tale.soul.check_name_with_spaces(["give", "the", "dark", "red", "paper", "to", "rat"], 2, livings, items)
        self.assertEqual((None, None, 0), result)
        result = tale.soul.check_name_with_spaces(["give", "paper", "to", "brown", "bird"], 3, livings, items)
        self.assertEqual(("BROWN BIRD", "brown bird", 2), result)

    def testCheckNamesWithSpacesParsing(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        bird = tale.npc.NPC("brown bird", "f")
        room = tale.base.Location("somewhere")
        gate = tale.base.Exit("gate", room, "the gate")
        door1 = tale.base.Exit("door one", room, "door number one")
        door2 = tale.base.Exit("door two", room, "door number two")
        room.add_exits([gate, door1, door2])
        bird.move(room)
        player.move(room)
        with self.assertRaises(tale.errors.ParseError) as x:
            soul.parse(player, "hug bird")
        self.assertEqual("It's not clear what you mean by 'bird'.", str(x.exception))
        parsed = soul.parse(player, "hug brown bird affection")
        self.assertEqual("hug", parsed.verb)
        self.assertEqual("affectionately", parsed.adverb)
        self.assertEqual([bird], parsed.who_order)
        # check spaces in exit names
        parsed = soul.parse(player, "gate", external_verbs=frozenset(room.exits))
        self.assertEqual("gate", parsed.verb)
        parsed = soul.parse(player, "frobnizz gate", external_verbs={"frobnizz"})
        self.assertEqual("frobnizz", parsed.verb)
        self.assertEqual(["gate"], parsed.args)
        self.assertEqual([gate], parsed.who_order)
        with self.assertRaises(tale.soul.UnknownVerbException):
            soul.parse(player, "door")
        parsed = soul.parse(player, "enter door two", external_verbs={"enter"})
        self.assertEqual("enter", parsed.verb)
        self.assertEqual(["door two"], parsed.args)
        self.assertEqual([door2], parsed.who_order)
        with self.assertRaises(tale.soul.NonSoulVerb) as x:
            soul.parse(player, "door one")
        parsed = x.exception.parsed
        self.assertEqual("door one", parsed.verb)
        self.assertEqual([door1], parsed.who_order)
        with self.assertRaises(tale.soul.NonSoulVerb) as x:
            soul.parse(player, "door two")
        parsed = x.exception.parsed
        self.assertEqual("door two", parsed.verb)
        self.assertEqual([door2], parsed.who_order)

    def testEnterExits(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        room = tale.base.Location("somewhere")
        gate = tale.base.Exit("gate", room, "gate")
        east = tale.base.Exit("east", room, "east")
        door1 = tale.base.Exit("door one", room, "door number one")
        room.add_exits([gate, door1, east])
        player.move(room)
        # known actions: enter/go/climb/crawl
        with self.assertRaises(tale.soul.NonSoulVerb) as x:
            soul.parse(player, "enter door one")
        parsed = x.exception.parsed
        self.assertEqual("door one", parsed.verb)
        self.assertEqual([door1], parsed.who_order)
        with self.assertRaises(tale.soul.NonSoulVerb) as x:
            soul.parse(player, "climb gate")
        parsed = x.exception.parsed
        self.assertEqual("gate", parsed.verb)
        with self.assertRaises(tale.soul.NonSoulVerb) as x:
            soul.parse(player, "go east")
        parsed = x.exception.parsed
        self.assertEqual("east", parsed.verb)
        with self.assertRaises(tale.soul.NonSoulVerb) as x:
            soul.parse(player, "crawl east")
        parsed = x.exception.parsed
        self.assertEqual("east", parsed.verb)
        parsed = soul.parse(player, "jump west")
        self.assertEqual("jump", parsed.verb)
        self.assertEqual("westwards", parsed.adverb)

    def testParse(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f", "human")
        room = tale.base.Location("somewhere")
        south_exit = tale.base.Exit("south", room, "a door to the south")
        east_exit = tale.base.Exit("east", room, "a door to the east")
        room.add_exits([east_exit, south_exit])
        player.move(room)
        max_npc = tale.npc.NPC("max", "m")
        kate_npc = tale.npc.NPC("kate", "f")
        dino_npc = tale.npc.NPC("dinosaur", "n")
        targets = [max_npc, kate_npc, dino_npc]
        targets_with_player = targets + [player]
        player.location.livings = targets
        newspaper = tale.base.Item("newspaper")
        player.location.insert(newspaper, player)
        parsed = soul.parse(player, "fail grin sickly at everyone head")
        self.assertEqual("fail", parsed.qualifier)
        self.assertEqual("grin", parsed.verb)
        self.assertEqual("sickly", parsed.adverb)
        self.assertEqual("head", parsed.bodypart)
        self.assertEqual("", parsed.message)
        self.assertTrue(len(parsed.who_order) == 3)
        self.assertTrue(all(isinstance(x, tale.base.Living) for x in parsed.who_order), "parse must return Livings in 'who'")
        self.assertEqual(targets, parsed.who_order)
        parsed = soul.parse(player, "slap myself")
        self.assertEqual(None, parsed.qualifier)
        self.assertEqual("slap", parsed.verb)
        self.assertEqual(None, parsed.adverb)
        self.assertEqual(None, parsed.bodypart)
        self.assertEqual("", parsed.message)
        self.assertEqual([player], parsed.who_order, "myself should be player")
        parsed = soul.parse(player, "slap all")
        self.assertEqual(None, parsed.qualifier)
        self.assertEqual("slap", parsed.verb)
        self.assertEqual(None, parsed.adverb)
        self.assertEqual(None, parsed.bodypart)
        self.assertEqual("", parsed.message)
        self.assertEqual(3, len(parsed.who_info), "all should not include player")
        self.assertEqual(targets, parsed.who_order, "all should not include player")
        parsed = soul.parse(player, "slap all but kate")
        self.assertEqual(2, len(parsed.who_info), "all but kate should only be max and the dino")
        self.assertEqual([max_npc, dino_npc], parsed.who_order, "all but kate should only be max and the dino")
        parsed = soul.parse(player, "slap all and myself")
        self.assertEqual(targets_with_player, parsed.who_order, "all and myself should include player")
        parsed = soul.parse(player, "slap newspaper")
        self.assertEqual([newspaper], parsed.who_order, "must be able to perform soul verb on item")
        with self.assertRaises(tale.errors.ParseError) as x:
            soul.parse(player, "slap dino")
        self.assertEqual("Perhaps you meant dinosaur?", str(x.exception), "must suggest living with prefix")
        with self.assertRaises(tale.errors.ParseError) as x:
            soul.parse(player, "slap news")
        self.assertEqual("Perhaps you meant newspaper?", str(x.exception), "must suggest item with prefix")
        with self.assertRaises(tale.errors.ParseError) as x:
            soul.parse(player, "slap undefined")
        self.assertEqual("It's not clear what you mean by 'undefined'.", str(x.exception))
        parsed = soul.parse(player, "smile west")
        self.assertEqual("westwards", parsed.adverb)
        with self.assertRaises(tale.errors.ParseError) as x:
            soul.parse(player, "smile north")
        self.assertEqual("What adverb did you mean: northeastwards, northwards, or northwestwards?", str(x.exception))
        parsed = soul.parse(player, "smile south")
        self.assertEqual(["south"], parsed.args, "south must be parsed as a normal arg because it's an exit in the room")
        parsed = soul.parse(player, "smile kate dinosaur and max")
        self.assertEqual(["kate", "dinosaur", "max"], parsed.args, "must be able to skip comma")
        self.assertEqual(3, len(parsed.who_order), "must be able to skip comma")
        parsed = soul.parse(player, "reply kate ofcourse,  darling.")
        self.assertEqual(["kate", "ofcourse,", "darling."], parsed.args, "must be able to skip comma")
        self.assertEqual(1, len(parsed.who_order))
        # check movement parsing for room exits
        with self.assertRaises(tale.soul.NonSoulVerb) as x:
            soul.parse(player, "crawl south")
        self.assertEqual("south", x.exception.parsed.verb, "just the exit is the verb, not the movement action")
        self.assertEqual([south_exit], x.exception.parsed.who_order, "exit must be in the who set")
        parsed_str = str(x.exception.parsed)
        self.assertTrue("verb=south" in parsed_str)
        with self.assertRaises(tale.errors.ParseError) as x:
            soul.parse(player, "crawl somewherenotexisting")
        self.assertEqual("You can't crawl there.", str(x.exception))
        with self.assertRaises(tale.errors.ParseError) as x:
            soul.parse(player, "crawl")
        self.assertEqual("Crawl where?", str(x.exception))
        room = tale.base.Location("somewhere")  # no exits in this new room
        player.move(room)
        with self.assertRaises(tale.soul.UnknownVerbException):
            soul.parse(player, "crawl")   # must raise unknownverb if there are no exits in the room

    def testUnparsed(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f", "human")
        parsed = soul.parse(player, "fart")
        self.assertEqual("", parsed.unparsed)
        parsed = soul.parse(player, "grin sadistically")
        self.assertEqual("sadistically", parsed.unparsed)
        parsed = soul.parse(player, "fail sit zen")
        self.assertEqual("zen", parsed.unparsed)
        parsed = soul.parse(player, "pat myself comfortingly on the shoulder")
        self.assertEqual("myself comfortingly on the shoulder", parsed.unparsed)
        parsed = soul.parse(player, "take the watch and the key from the box", external_verbs={"take"})
        self.assertEqual("the watch and the key from the box", parsed.unparsed)
        parsed = soul.parse(player, "fail to _undefined_verb_ on the floor", external_verbs={"_undefined_verb_"})
        self.assertEqual("on the floor", parsed.unparsed)
        parsed = soul.parse(player, "say 'red or blue'", external_verbs={"say"})
        self.assertEqual("'red or blue'", parsed.unparsed)
        parsed = soul.parse(player, "say red or blue", external_verbs={"say"})
        self.assertEqual("red or blue", parsed.unparsed)
        parsed = soul.parse(player, "say hastily red or blue", external_verbs={"say"})
        self.assertEqual("hastily red or blue", parsed.unparsed)
        parsed = soul.parse(player, "fail say hastily red or blue on your head", external_verbs={"say"})
        self.assertEqual("hastily red or blue on your head", parsed.unparsed)

    def testDEFA(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        targets = [tale.npc.NPC("max", "m")]
        # grin
        parsed = tale.soul.ParseResult("grin")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You grin evilly.", player_msg)
        self.assertEqual("Julie grins evilly.", room_msg)
        # drool
        parsed = tale.soul.ParseResult("drool", who_order=targets)
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You drool on max.", player_msg)
        self.assertEqual("Julie drools on max.", room_msg)
        self.assertEqual("Julie drools on you.", target_msg)

    def testPREV(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        targets = [tale.npc.NPC("max", "m")]
        # peer
        parsed = tale.soul.ParseResult("peer", who_order=targets)
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You peer at max.", player_msg)
        self.assertEqual("Julie peers at max.", room_msg)
        self.assertEqual("Julie peers at you.", target_msg)
        # tease
        parsed = tale.soul.ParseResult("tease", who_order=targets)
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You tease max.", player_msg)
        self.assertEqual("Julie teases max.", room_msg)
        self.assertEqual("Julie teases you.", target_msg)
        # turn
        parsed = tale.soul.ParseResult("turn", who_order=targets)
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You turn your head towards max.", player_msg)
        self.assertEqual("Julie turns her head towards max.", room_msg)
        self.assertEqual("Julie turns her head towards you.", target_msg)

    def testPHYS(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        targets = [tale.npc.NPC("max", "m")]
        # require person
        with self.assertRaises(tale.errors.ParseError):
            parsed = tale.soul.ParseResult("bonk")
            soul.process_verb_parsed(player, parsed)
        # pounce
        parsed = tale.soul.ParseResult("pounce", who_order=targets)
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You pounce max playfully.", player_msg)
        self.assertEqual("Julie pounces max playfully.", room_msg)
        self.assertEqual("Julie pounces you playfully.", target_msg)
        # hold
        parsed = tale.soul.ParseResult("hold", who_order=targets)
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You hold max in your arms.", player_msg)
        self.assertEqual("Julie holds max in her arms.", room_msg)
        self.assertEqual("Julie holds you in her arms.", target_msg)

    def testSHRT(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        # faint
        parsed = tale.soul.ParseResult("faint", adverb="slowly")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You faint slowly.", player_msg)
        self.assertEqual("Julie faints slowly.", room_msg)
        # cheer
        parsed = tale.soul.ParseResult("cheer")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You cheer enthusiastically.", player_msg)
        self.assertEqual("Julie cheers enthusiastically.", room_msg)

    def testPERS(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        targets = [tale.npc.NPC("max", "m")]
        # fear1
        parsed = tale.soul.ParseResult("fear")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You shiver with fear.", player_msg)
        self.assertEqual("Julie shivers with fear.", room_msg)
        # fear2
        parsed.who_order = targets
        parsed.recalc_who_info()
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You fear max.", player_msg)
        self.assertEqual("Julie fears max.", room_msg)
        self.assertEqual("Julie fears you.", target_msg)

    def testSIMP(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        targets = [tale.npc.NPC("max", "m")]

        # scream 1
        parsed = tale.soul.ParseResult("scream")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You scream loudly.", player_msg)
        self.assertEqual("Julie screams loudly.", room_msg)
        # scream 2
        parsed.who_order = targets
        parsed.recalc_who_info()
        parsed.adverb = "angrily"
        parsed.message = "why"
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You scream 'why' angrily at max.", player_msg)
        self.assertEqual("Julie screams 'why' angrily at max.", room_msg)
        self.assertEqual("Julie screams 'why' angrily at you.", target_msg)
        # ask
        parsed = tale.soul.ParseResult("ask", message="are you happy", who_order=targets)
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You ask max: are you happy?", player_msg)
        self.assertEqual("Julie asks max: are you happy?", room_msg)
        self.assertEqual("Julie asks you: are you happy?", target_msg)
        # puzzle1
        parsed = tale.soul.ParseResult("puzzle")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You look puzzled.", player_msg)
        self.assertEqual("Julie looks puzzled.", room_msg)
        # puzzle2
        parsed.who_order = targets
        parsed.recalc_who_info()
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You look puzzled at max.", player_msg)
        self.assertEqual("Julie looks puzzled at max.", room_msg)
        self.assertEqual("Julie looks puzzled at you.", target_msg)
        # chant1
        parsed = tale.soul.ParseResult("chant", adverb="merrily", message="tralala")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You merrily chant: tralala.", player_msg)
        self.assertEqual("Julie merrily chants: tralala.", room_msg)
        # chant2
        parsed = tale.soul.ParseResult("chant")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You chant: Hare Krishna Krishna Hare Hare.", player_msg)
        self.assertEqual("Julie chants: Hare Krishna Krishna Hare Hare.", room_msg)

    def testDEUX(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        # die
        parsed = tale.soul.ParseResult("die", adverb="suddenly")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You suddenly fall down and play dead.", player_msg)
        self.assertEqual("Julie suddenly falls to the ground, dead.", room_msg)
        # ah
        parsed = tale.soul.ParseResult("ah", adverb="rudely")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You go 'ah' rudely.", player_msg)
        self.assertEqual("Julie goes 'ah' rudely.", room_msg)
        # verb needs a person
        with self.assertRaises(tale.errors.ParseError) as x:
            soul.process_verb(player, "touch")
        self.assertEqual("The verb touch needs a person.", str(x.exception))

    def testQUAD(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f")
        targets = [tale.npc.NPC("max", "m")]
        # watch1
        parsed = tale.soul.ParseResult("watch")
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You watch the surroundings carefully.", player_msg)
        self.assertEqual("Julie watches the surroundings carefully.", room_msg)
        # watch2
        parsed.who_order = targets
        parsed.recalc_who_info()
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual("You watch max carefully.", player_msg)
        self.assertEqual("Julie watches max carefully.", room_msg)
        self.assertEqual("Julie watches you carefully.", target_msg)
        # ayt
        parsed.verb = "ayt"
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertEqual(set(targets), who)
        self.assertEqual("You wave your hand in front of max's face, is he there?", player_msg)
        self.assertEqual("Julie waves her hand in front of max's face, is he there?", room_msg)
        self.assertEqual("Julie waves her hand in front of your face, are you there?", target_msg)
        # ayt
        targets2 = [tale.npc.NPC("max", "m"), player]
        parsed.who_order = targets2
        parsed.recalc_who_info()
        who, player_msg, room_msg, target_msg = soul.process_verb_parsed(player, parsed)
        self.assertTrue(player_msg.startswith("You wave your hand in front of "))
        self.assertTrue("max's" in player_msg and "your own" in player_msg)
        self.assertTrue(room_msg.startswith("Julie waves her hand in front of "))
        self.assertTrue("max's" in room_msg and "her own" in room_msg)
        self.assertEqual("Julie waves her hand in front of your face, are you there?", target_msg)

    def testFULL(self):
        pass  # FULL is not yet used

    def testPronounReferences(self):
        soul = tale.soul.Soul()
        player = tale.player.Player("julie", "f", "human")
        room = tale.base.Location("somewhere")
        room2 = tale.base.Location("somewhere else")
        player.move(room)
        max_npc = tale.npc.NPC("Max", "m")
        kate_npc = tale.npc.NPC("Kate", "f")
        dino_npc = tale.npc.NPC("dinosaur", "n")
        targets = [max_npc, kate_npc, dino_npc]
        player.location.livings = targets
        newspaper = tale.base.Item("newspaper")
        player.location.insert(newspaper, player)
        # her
        parsed = soul.parse(player, "hug kate")
        soul.previously_parsed = parsed
        parsed = soul.parse(player, "kiss her")
        self.assertEqual(["(By 'her', it is assumed you mean Kate.)\n"], player.test_get_output_paragraphs())
        self.assertEqual(kate_npc, parsed.who_order[0])
        # it
        parsed = soul.parse(player, "hug dinosaur")
        soul.previously_parsed = parsed
        parsed = soul.parse(player, "kiss it")
        self.assertEqual(["(By 'it', it is assumed you mean dinosaur.)\n"], player.test_get_output_paragraphs())
        self.assertEqual(dino_npc, parsed.who_order[0])
        with self.assertRaises(tale.errors.ParseError) as x:
            parsed = soul.parse(player, "kiss her")
        self.assertEqual("It is not clear who you're referring to.", str(x.exception))
        # them
        parsed = soul.parse(player, "hug kate and dinosaur")
        soul.previously_parsed = parsed
        parsed = soul.parse(player, "kiss them")
        self.assertEqual(["(By 'them', it is assumed you mean: Kate and dinosaur.)\n"], player.test_get_output_paragraphs())
        self.assertEqual([kate_npc, dino_npc], parsed.who_order)
        # when no longer around
        parsed = soul.parse(player, "hug kate")
        soul.previously_parsed = parsed
        player.move(room2)
        with self.assertRaises(tale.errors.ParseError) as x:
            parsed = soul.parse(player, "kiss her")
        self.assertEqual("She is no longer around.", str(x.exception))

    def test_adjust_verbs(self):
        allowed = ["hug", "ponder", "sit", "kick", "cough", "greet", "poke", "yawn"]
        remove = ["hug", "kick"]
        verbs = {"frobnizificate": (tale.soul.SIMP, None, "frobnizes \nHOW \nAT", "at")}
        # keep original values to put back after tests
        ORIG_VERBS = tale.soul.VERBS.copy()
        ORIG_AGGRESSIVE_VERBS = tale.soul.AGGRESSIVE_VERBS.copy()
        ORIG_NONLIVING_OK_VERBS = tale.soul.NONLIVING_OK_VERBS.copy()
        ORIG_MOVEMENT_VERBS = tale.soul.MOVEMENT_VERBS.copy()
        try:
            tale.soul.adjust_available_verbs(allowed_verbs=allowed, remove_verbs=remove, add_verbs=verbs)
            self.assertEqual({"poke"}, tale.soul.AGGRESSIVE_VERBS)
            self.assertEqual({"yawn"}, tale.soul.NONLIVING_OK_VERBS)
            self.assertEqual(set(), tale.soul.MOVEMENT_VERBS)
            remaining = sorted(tale.soul.VERBS.keys())
            self.assertEqual(["cough", "frobnizificate", "greet", "poke", "ponder", "sit", "yawn"], remaining)
        finally:
            # restore original values
            tale.soul.VERBS = ORIG_VERBS
            tale.soul.AGGRESSIVE_VERBS = ORIG_AGGRESSIVE_VERBS
            tale.soul.NONLIVING_OK_VERBS = ORIG_NONLIVING_OK_VERBS
            tale.soul.MOVEMENT_VERBS = ORIG_MOVEMENT_VERBS


if __name__ == "__main__":
    # import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
