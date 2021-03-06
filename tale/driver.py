# coding=utf-8
"""
Mud driver (server).

'Tale' mud driver, mudlib and interactive fiction framework
Copyright by Irmen de Jong (irmen@razorvine.net)
"""

from __future__ import absolute_import, print_function, division, unicode_literals
import collections
from functools import total_ordering
import datetime
import sys
import time
import os
import heapq
import argparse
import pickle
import inspect
import threading
import types
import traceback
import appdirs
import distutils.version
import pkgutil
from . import mud_context, errors, util, soul, cmds, player, base, npc, pubsub, charbuilder, lang, races
from . import __version__ as tale_version_str
from .tio import vfs, DEFAULT_SCREEN_WIDTH, DEFAULT_SCREEN_DELAY
from .base import Stats


topic_pending_actions = pubsub.topic("driver-pending-actions")
topic_pending_tells = pubsub.topic("driver-pending-tells")
topic_async_dialogs = pubsub.topic("driver-async-dialogs")


class Driver(pubsub.Listener):
    """
    The Mud 'driver'.
    Reads story file and config, initializes game state.
    Handles main game loop, player connections, and loading/saving of game state.
    """
    def __init__(self):
        self.heartbeat_objects = set()
        self.unbound_exits = []
        self.deferreds = []  # heapq
        self.deferreds_lock = threading.Lock()
        self.server_started = datetime.datetime.now().replace(microsecond=0)
        self.config = None
        self.server_loop_durations = collections.deque(maxlen=10)
        self.commands = Commands()
        cmds.register_all(self.commands)
        self.all_players = {}   # maps playername to player connection object
        self.zones = None
        self.moneyfmt = None
        self.resources = self.user_resources = None
        self.story = None
        self.game_clock = None
        self.__stop_mainloop = True
        self.waiting_for_input = {}   # maps playerconnection to tuple (dialog, validator, echo_input)
        topic_pending_actions.subscribe(self)
        topic_pending_tells.subscribe(self)
        topic_async_dialogs.subscribe(self)

    def start(self, command_line_args):
        """Parse the command line arguments and start the driver accordingly."""
        parser = argparse.ArgumentParser(description="""
            Tale framework %s game driver. Use this to launch a game and specify some settings.
            Sometimes the game will provide its own startup script that invokes this automatically.
            If it doesn't, refer to the options to see how to launch it manually instead.
            """ % tale_version_str)
        parser.add_argument('-g', '--game', type=str, help='path to the game directory', required=True)
        parser.add_argument('-d', '--delay', type=int, help='screen output delay for IF mode (milliseconds, 0=no delay)', default=DEFAULT_SCREEN_DELAY)
        parser.add_argument('-m', '--mode', type=str, help='game mode, default=if', default="if", choices=["if", "mud"])
        parser.add_argument('-i', '--gui', help='gui interface', action='store_true')
        parser.add_argument('-w', '--web', help='web browser interface', action='store_true')
        parser.add_argument('-v', '--verify', help='only verify the story files, dont run it', action='store_true')
        parser.add_argument('-z', '--wizard', help='force wizard mode on if story character (for debug purposes)', action='store_true')
        args = parser.parse_args(command_line_args)
        try:
            self.__start(args)
        except Exception:
            if args.gui:
                tb = traceback.format_exc()
                from .tio import tkinter_io
                tkinter_io.show_error_dialog("Exception during start", "An error occurred while starting up the game:\n\n" + tb)
            raise

    def __start(self, args):
        """Start the driver from a parsed set of arguments"""
        if os.path.isdir(args.game):
            # cd into the game directory (we can import it then), and load its config and zones
            os.chdir(args.game)
            sys.path.insert(0, os.curdir)
        elif os.path.isfile(args.game):
            # the game argument points to a file, assume it is a zipfile, add it to the import path
            sys.path.insert(0, args.game)
        else:
            raise IOError("Cannot find specified game")
        story = __import__("story", level=0)
        self.story = story.Story()
        if len(self.story.config.supported_modes) == 1 and args.mode != "mud":
            # There's only one mode this story runs in. Just select that one.
            args.mode = list(self.story.config.supported_modes)[0]
        if args.mode not in self.story.config.supported_modes:
            raise ValueError("driver mode '%s' not supported by this story. Valid modes: %s" % (args.mode, list(self.story.config.supported_modes)))
        self.config = StoryConfig.copy_from(self.story.config)
        self.config.mud_host = self.config.mud_host or "localhost"
        self.config.mud_port = self.config.mud_port or 8180
        self.config.server_mode = args.mode  # if/mud driver mode ('if' = single player interactive fiction, 'mud'=multiplayer)
        if self.config.server_mode != "if" and self.config.server_tick_method == "command":
            raise ValueError("'command' tick method can only be used in 'if' game mode")
        # Register the driver and some other stuff in the global context.
        mud_context.driver = self
        mud_context.config = self.config
        self.resources = vfs.VirtualFileSystem(root_package="story")   # read-only story resources
        try:
            pkgutil.get_loader("cmds")
        except AttributeError:
            # workaround for http://bugs.python.org/issue14710 in python 3.4.0/3.4.1
            pass
        else:
            if pkgutil.get_loader("cmds"):   # check for existence of cmds package in the story root
                story_cmds = __import__("cmds", level=0)
                story_cmds.register_all(self.commands)
        self.commands.adjust_available_commands(self.config.server_mode)
        tale_version = distutils.version.LooseVersion(tale_version_str)
        tale_version_required = distutils.version.LooseVersion(self.config.requires_tale)
        if tale_version < tale_version_required:
            raise RuntimeError("The game requires tale " + self.config.requires_tale + " but " + tale_version_str + " is installed.")
        self.game_clock = util.GameDateTime(self.config.epoch or self.server_started, self.config.gametime_to_realtime)
        self.moneyfmt = util.MoneyFormatter(self.config.money_type) if self.config.money_type else None
        user_data_dir = appdirs.user_data_dir("Tale-" + util.storyname_to_filename(self.config.name), "Razorvine", roaming=True)
        if not os.path.isdir(user_data_dir):
            try:
                os.makedirs(user_data_dir, mode=0o700)
            except os.error:
                pass
        self.user_resources = vfs.VirtualFileSystem(root_path=user_data_dir, readonly=False)  # r/w to the local 'user data' directory
        self.story.init(self)
        import zones
        self.zones = zones
        self.config.startlocation_player = self.__lookup_location(self.config.startlocation_player)
        self.config.startlocation_wizard = self.__lookup_location(self.config.startlocation_wizard)
        if self.config.server_tick_method == "command":
            # If the server tick is synchronized with player commands, this factor needs to be 1,
            # because at every command entered the game time simply advances 1 x server_tick_time.
            self.config.gametime_to_realtime = 1
        assert self.config.server_tick_time > 0
        assert self.config.max_wait_hours >= 0
        self.game_clock = util.GameDateTime(self.config.epoch or self.server_started, self.config.gametime_to_realtime)
        # convert textual exit strings to actual exit object bindings
        for x in self.unbound_exits:
            x._bind_target(self.zones)
        del self.unbound_exits
        if args.verify:
            print("Story: '%s' v%s, by %s." % (self.story.config.name, self.story.config.version, self.story.config.author))
            print("Verified, all seems to be fine.")
            return
        if args.delay < 0 or args.delay > 100:
            raise ValueError("invalid delay, valid range is 0-100")
        if self.config.server_mode == "if":
            # create the single player mode player automatically
            if args.gui:
                player_io = "gui"
            elif args.web:
                player_io = "web"
            else:
                player_io = "console"
            connection = self._connect_if_player(player_io, args.delay, args.wizard)
            # create the login dialog
            topic_async_dialogs.send((connection, self.__login_dialog_if(connection)))
            # the driver mainloop runs in a background thread, the io-loop/gui-event-loop runs in the main thread
            driver_thread = threading.Thread(name="driver", target=self.__startup_main_loop, args=(connection,))
            driver_thread.daemon = True
            driver_thread.start()
            connection.singleplayer_mainloop()
        else:
            # mud mode: driver runs as main thread, wsgi webserver runs in background thread
            base._limbo.init_inventory([LimboReaper()])  # add the grim reaper to Limbo
            self.mud_accounts = player.MudAccounts()
            from .tio.mud_browser_io import TaleMudWsgiApp
            wsgi_server = TaleMudWsgiApp.create_app_server(self)
            wsgi_thread = threading.Thread(name="wsgi", target=wsgi_server.serve_forever)
            wsgi_thread.daemon = True
            wsgi_thread.start()
            self.__print_game_intro(None)
            print("Web server url:   http://%s:%d/tale/" % wsgi_server.server_address, end="\n\n")
            self.__startup_main_loop(None)

    def __startup_main_loop(self, conn):
        # Kick off the appropriate driver main event loop.
        # This may or may not run in a background thread depending on the driver mode.
        self.__stop_mainloop = False
        try:
            if self.config.server_mode == "if":
                # single player interactive fiction event loop
                while not self.__stop_mainloop:
                    self.__main_loop_singleplayer(conn)
            else:
                # multi player mud event loop
                while not self.__stop_mainloop:
                    self.__main_loop_multiplayer()
        except:
            for conn in self.all_players.values():
                conn.critical_error()
            self.__stop_mainloop = True
            raise

    def _connect_if_player(self, player_io, line_delay, wizard_override):
        connection = player.PlayerConnection()
        connect_name = "<connecting_%d>" % id(connection)  # unique temporary name
        new_player = player.Player(connect_name, "n", "elemental", "This player is still connecting to the game.")
        if player_io == "gui":
            from .tio.tkinter_io import TkinterIo
            io = TkinterIo(self.config, connection)
        elif player_io == "web":
            from .tio.if_browser_io import HttpIo, TaleWsgiApp
            wsgi_server = TaleWsgiApp.create_app_server(self, connection)
            io = HttpIo(connection, wsgi_server)
        elif player_io == "console":
            from .tio.console_io import ConsoleIo
            io = ConsoleIo(connection)
            io.install_tab_completion(self)
        else:
            raise ValueError("invalid io type")
        if wizard_override:
            new_player.privileges.add("wizard")
        connection.player = new_player
        connection.io = io
        self.all_players[new_player.name] = connection
        new_player.output_line_delay = line_delay
        connection.clear_screen()
        self.__print_game_intro(connection)
        return connection

    def _connect_mud_player(self):
        connection = player.PlayerConnection()
        connect_name = "<connecting_%d>" % id(connection)  # unique temporary name
        new_player = player.Player(connect_name, "n", "elemental", "This player is still connecting to the game.")
        connection.player = new_player
        from .tio.mud_browser_io import MudHttpIo
        connection.io = MudHttpIo(connection)
        self.all_players[new_player.name] = connection
        connection.clear_screen()
        self.__print_game_intro(connection)
        connection.output("\n")
        # check if we have at least 1 admin user
        all_accounts = self.mud_accounts.all_accounts()
        if not any("wizard" in acc["privileges"] for acc in all_accounts.values()):
            # there is no wizard, create a dialog to construct the initial admin user
            topic_async_dialogs.send((connection, self.__login_dialog_mud_create_admin(connection)))
            return connection
        # create the login dialog
        topic_async_dialogs.send((connection, self.__login_dialog_mud(connection)))
        return connection

    def _disconnect_mud_player(self, conn_or_player):
        if type(conn_or_player) is player.PlayerConnection:
            name = conn_or_player.player.name
            conn = conn_or_player
        elif type(conn_or_player) is player.Player:
            name = conn_or_player.name
            conn = self.all_players[name]
        else:
            raise TypeError("connection or player object expected")
        assert self.all_players[name] is conn
        conn.player.tell_others("{Title} suddenly shimmers and fades from sight. %s left the game." % lang.capital(conn.player.subjective))
        del self.all_players[name]
        conn.write_output()
        self.defer(1, conn.destroy)     # wait a little to allow the player's screen to display the last goodbye message before killing the connection

    def __login_dialog_mud_create_admin(self, conn):
        assert self.config.server_mode == "mud"
        conn.write_output()
        conn.output("<bright>Welcome. There is no admin user registered. You'll have to create the initial admin user to be able to start the mud.</>")
        while True:
            conn.output("Creating new admin user.")
            name = yield "input-noecho", ("Please type in the admin's player name.", player.MudAccounts.accept_name)
            password = yield "input-noecho", ("Please type in the admin password.", player.MudAccounts.accept_password)
            email = yield "input", ("Please type in the admin's email address.", player.MudAccounts.accept_email)
            conn.output("You can choose one of the following races: ", lang.join(races.player_races))
            race = yield "input", ("Player race?", charbuilder.validate_race)
            gender = yield "input", ("What is your gender (m/f/n)?", lang.validate_gender)
            # review the account
            conn.player.tell("<bright>Please review your new character.</>", end=True)
            conn.player.tell("<dim> name:</> %s,  <dim>gender:</> %s,  <dim>race:</> %s,  <dim>email:</> %s" % (name, lang.GENDERS[gender], race, email), end=True)
            if not (yield "input", ("You cannot change your name later. Do you want to create this admin account?", lang.yesno)):
                continue
            else:
                break
        self.mud_accounts.create(name, password, email, gender[0], Stats.from_race(race), privileges={"wizard"})
        conn.output("\n")
        conn.output("\n")
        topic_async_dialogs.send((conn, self.__login_dialog_mud(conn)))   # continue with the normal login dialog

    def __login_dialog_mud(self, conn):
        assert self.config.server_mode == "mud"
        conn.write_output()
        conn.output("<bright>Welcome. We would like to know your player name before you can continue.</>")
        conn.output("<dim>If you are not yet known with us, you can simply type in a new name. Otherwise use the name you registered with.</>\n")
        conn.output("\n")
        while True:
            name = yield "input-noecho", ("Please type in your player name.", player.MudAccounts.accept_name)
            existing_player = self.search_player(name)
            if existing_player:
                conn.player.tell("That player is already logged in elsewhere. Their current location is", existing_player.location.name)
                conn.player.tell("and their idle time is %d seconds." % existing_player.idle_time)
                if existing_player.idle_time < 30:
                    conn.player.tell("They are still active.")
                    continue
                if not (yield "input", ("Do you want to kick them out and take over?", lang.yesno)):
                    conn.player.tell("Okay, leaving them in peace.")
                    continue
            try:
                self.mud_accounts.get(name)
                password = yield "input-noecho", "Please type in your password."
            except KeyError:
                conn.player.tell("'<player>%s</>' is the name of a new character." % name)
                if not (yield "input", ("Do you want to create a new character with this name?", lang.yesno)):
                    continue
                # self-service account creation
                conn.player.tell("\n")
                conn.player.tell("<ul><bright>New character creation: '%s'.</>" % name, end=True)
                password = yield "input-noecho", ("Please type in the desired password.", player.MudAccounts.accept_password)
                email = yield "input", ("Please type in your email address.", player.MudAccounts.accept_email)
                gender = yield "input", ("What is the gender of your player character (m/f/n)?", lang.validate_gender)
                conn.player.tell("You can choose one of the following races: ", lang.join(races.player_races))
                race = yield "input", ("What should be the race of your player character?", charbuilder.validate_race)
                # review the account
                conn.player.tell("<bright>Please review your new character.</>", end=True)
                conn.player.tell("<dim> name:</> %s,  <dim>gender:</> %s,  <dim>race:</> %s" % (name, lang.GENDERS[gender], race), end=True)
                conn.player.tell("<dim> email:</> " + email, end=True)
                if not (yield "input", ("You cannot change your name later. Do you want to create this character?", lang.yesno)):
                    # abort
                    conn.player.tell("Ok, let's get back to the beginning then.", end=True)
                    continue
                account = self.mud_accounts.create(name, password, email, gender[0], Stats.from_race(race))
                conn.player.tell("\n<bright>Your new account has been created!</>  It will now be used to log in.", end=True)
                conn.player.tell("\n")
            try:
                self.mud_accounts.valid_password(name, password)
            except ValueError as x:
                conn.output("<it>%s</it>" % x)
                continue
            else:
                if existing_player:
                    existing_player.tell("\n")
                    existing_player.tell("<it><rev>You are kicked from the game. Your account is now logged in from elsewhere.</>")
                    existing_player.tell("\n")
                    state = existing_player.__getstate__()
                    state["name"] = conn.player.name   # we properly rename it just below
                    existing_player_location = existing_player.location
                    self._disconnect_mud_player(existing_player)
                    ctx = util.Context(self, self.game_clock, self.config, None)
                    # mr smith move: delete the other player and restore its properties in us
                    existing_player.destroy(ctx)
                    conn.player.__setstate__(state)
                    name_info = charbuilder.PlayerNaming()
                    name_info.money = state["money"]
                    name_info.name = state["name"]
                    name_info.gender = state["gender"]
                    name_info.stats = state["stats"]
                    self.__rename_player(conn.player, name_info)
                    conn.output("\n")
                    conn.player.move(existing_player_location)
                    break
                # get the account and log in
                account = self.mud_accounts.get(name)
                self.mud_accounts.logged_in(name)
                if account["logged_in"]:
                    conn.output("Last login: " + account["logged_in"])
                break
        if not existing_player:
            # for a new login, we need to rename the transitional player object
            # to the proper account name, and move the player to the starting location.
            name_info = charbuilder.PlayerNaming()
            name_info.name = account["name"]
            name_info.gender = account["gender"]
            name_info.stats = account["stats"]
            self.__rename_player(conn.player, name_info)
            conn.player.privileges = set(account["privileges"])
            conn.output("\n")
            if "wizard" in conn.player.privileges:
                conn.player.move(self.config.startlocation_wizard)
            else:
                conn.player.move(self.config.startlocation_player)
        prompt = self.story.welcome(conn.player)
        if prompt:
            yield "input", "\n" + prompt
        self.story.init_player(conn.player)
        conn.output("\n")
        self.show_motd(conn.player, True)
        conn.player.look(short=False)  # force a 'look' command to get our bearings
        # after this, the generator (dialog) ends and we drop down into the regular command loop

    def _stop_driver(self):
        """
        Stop the driver mainloop in an orderly fashion.
        Flushes any pending output to the players, then closes down.
        """
        self.__stop_mainloop = True
        for conn in self.all_players.values():
            conn.write_output()
            conn.destroy()
        self.all_players.clear()
        time.sleep(0.1)

    def __continue_dialog(self, conn, dialog, message):
        # Notice that the try...except structure is very similar to
        # the one in __server_loop_process_player_input
        # That's no surprise because also in this async case, we need
        # to handle any parse errors and such that may be thrown from the
        # generator. The reguar player input function has to deal with
        # them as well, caused by normal player commands.
        try:
            why, what = dialog.send(message)
        except StopIteration:
            if conn.player:
                conn.write_output()   # immediately give feedback (if any) once the dialog ends
        except errors.ActionRefused as x:
            conn.player.remember_parsed()
            conn.player.tell(str(x))
            conn.write_output()
        except errors.ParseError as x:
            conn.player.tell(str(x))
            conn.write_output()
        else:
            if why in ("input", "input-noecho"):
                if type(what) is tuple:
                    prompt, validator = what
                else:
                    prompt, validator = what, None
                if prompt:
                    if not prompt.endswith(" "):
                        prompt += " "
                    conn.write_output()
                    conn.output_no_newline(prompt)  # the input prompt
                assert conn not in self.waiting_for_input, "can only run one async dialog at the same time"
                conn.io.dont_echo_next_cmd = why == "input-noecho"  # this avoids echoing of the password
                self.waiting_for_input[conn] = (dialog, validator, why != "input-noecho")
            else:
                raise ValueError("invalid generator wait reason: " + why)

    def __print_game_intro(self, player_connection):
        try:
            # print game banner as supplied by the game
            banner = self.resources["messages/banner.txt"].data
            if player_connection:
                player_connection.player.tell("<bright>" + banner + "</>", format=False)
                player_connection.player.tell("\n")
            else:
                print(banner)
        except IOError:
            # no banner provided by the game, print default game header
            if player_connection:
                o = player_connection.output
                o("")
                o("")
                o("<monospaced><bright>")
                o(("'%s'" % self.config.name).center(DEFAULT_SCREEN_WIDTH))
                o(("v" + self.config.version).center(DEFAULT_SCREEN_WIDTH))
                o("")
                o(("written by " + self.config.author).center(DEFAULT_SCREEN_WIDTH))
                if self.config.author_address:
                    o(self.config.author_address.center(DEFAULT_SCREEN_WIDTH))
                o("</></monospaced>")
                o("")
                o("")
        if not player_connection:
            print("\n")
            print("Tale library:", tale_version_str)
            print("MudLib:       %s, v%s" % (self.config.name, self.config.version))
            if self.config.author:
                print("Written by:   %s - %s" % (self.config.author, self.config.author_address or ""))
            print("Driver start:", time.ctime())
            print("\n")

    def __rename_player(self, player, name_info):
        conn = self.all_players[player.name]
        del self.all_players[player.name]
        old_wiretap = player.get_wiretap()
        old_wiretap.destroy()
        self.all_players[name_info.name] = conn
        name_info.apply_to(player)

    def __login_dialog_if(self, conn):
        # Interactive fiction (singleplayer): create a player. This is a generator function (async input).
        # Initialize it directly from the story's configuration, load a saved game,
        # or let the user create a new player manually.
        # Be sure to always reference conn.player here (and not get a cached copy),
        # because it will get replaced when loading a saved game!
        assert self.config.server_mode == "if"
        if not self.config.savegames_enabled:
            load_saved_game = False
        else:
            conn.player.tell("\n")
            load_saved_game = yield "input", ("Do you want to load a saved game ('<bright>n</>' will start a new game)?", lang.yesno)
        conn.player.tell("\n")
        if load_saved_game:
            loaded_player = self.__load_saved_game(conn.player)
            if loaded_player:
                conn.player = loaded_player
                conn.player.tell("\n")
                prompt = self.story.welcome_savegame(conn.player)
                if prompt:
                    yield "input", "\n" + prompt
                conn.player.tell("\n")
            else:
                load_saved_game = False

        if load_saved_game:
            self.story.init_player(conn.player)
            conn.player.look(short=False)   # force a 'look' command to get our bearings
            return

        if self.config.player_name:
            # story config provides a name etc.
            name_info = charbuilder.PlayerNaming()
            name_info.name = self.config.player_name
            name_info.stats.race = self.config.player_race
            name_info.gender = self.config.player_gender
            name_info.money = self.config.player_money or 0.0
            name_info.wizard = "wizard" in conn.player.privileges
            self.__login_dialog_if_2(conn, name_info)   # finish the login dialog
        else:
            # No story player config: create a character with the builder
            # This is unusual though, normally any 'if' story should provide a player config
            builder = charbuilder.CharacterBuilder(conn, lambda name_info: self.__login_dialog_if_2(conn, name_info))
            topic_async_dialogs.send((conn, builder.build_async()))

    def __login_dialog_if_2(self, conn, name_info):
        # Second part of the if login dialog, this has been split to be able
        # to put in the character builder dialog that continues with this one.
        player = conn.player
        self.__rename_player(player, name_info)
        player.tell("\n")
        # move the player to the starting location:
        if "wizard" in player.privileges:
            player.move(self.config.startlocation_wizard)
        else:
            player.move(self.config.startlocation_player)
        player.tell("\n")
        prompt = self.story.welcome(player)
        if prompt:
            conn.input_direct("\n" + prompt)   # blocks  (note: cannot use yield here)
        player.tell("\n")
        self.story.init_player(player)
        player.look(short=False)  # force a 'look' command to get our bearings
        conn.write_output()

    def __main_loop_singleplayer(self, conn):
        """
        The game loop, for the single player Interactive Fiction game mode.
        Until the game is exited, it processes player input, and prints the resulting output.
        """
        conn.write_output()
        loop_duration = 0
        previous_server_tick = 0
        while not self.__stop_mainloop:
            pubsub.sync("driver-async-dialogs")
            if conn not in self.waiting_for_input:
                conn.write_input_prompt()
            if self.config.server_tick_method == "command":
                conn.player.input_is_available.wait()   # blocking wait until playered entered something
                has_input = True
            elif self.config.server_tick_method == "timer":
                # server tick goes on a timer, wait a limited time for player input before going on
                input_wait_time = max(0.01, self.config.server_tick_time - loop_duration)
                has_input = conn.player.input_is_available.wait(input_wait_time)
            else:
                raise ValueError("invalid tick method")

            loop_start = time.time()
            if has_input:
                conn.need_new_input_prompt = True
                try:
                    if conn in self.waiting_for_input:
                        # this connection is processing direct input, rather than regular commands
                        dialog, validator, echo_input = self.waiting_for_input.pop(conn)
                        response = conn.player.get_pending_input()[0]
                        if validator:
                            try:
                                response = validator(response)
                            except ValueError as x:
                                prompt = conn.last_output_line
                                conn.io.dont_echo_next_cmd = not echo_input
                                conn.output(str(x) or "That is not a valid answer.")
                                conn.output_no_newline(prompt)   # print the input prompt again
                                self.waiting_for_input[conn] = (dialog, validator, echo_input)   # reschedule
                                continue
                        self.__continue_dialog(conn, dialog, response)
                    else:
                        # normal command processing
                        self.__server_loop_process_player_input(conn)
                except (KeyboardInterrupt, EOFError):
                    continue
                except errors.SessionExit:
                    self.story.goodbye(conn.player)
                    self._stop_driver()
                    break
                except Exception:
                    txt = "* internal error:\n" + traceback.format_exc()
                    conn.player.tell(txt, format=False)
            # sync pubsub events
            pubsub.sync("driver-pending-tells")
            # server TICK
            now = time.time()
            if now - previous_server_tick >= self.config.server_tick_time:
                self.__server_tick()
                previous_server_tick = now
            if self.config.server_tick_method == "command":
                # Even though the server tick may be skipped, the pubsub events
                # should be processed every player command no matter what.
                pubsub.sync()
            # check if player reached the end of the story
            loop_duration = time.time() - loop_start
            self.server_loop_durations.append(loop_duration)
            if conn.player:
                if conn.player.story_complete:
                    conn.player.tell("\n")
                    self.story.completion(conn.player)
                    conn.player.tell("\n")
                    conn.input_direct("\nPress enter to continue. ")  # blocks
                    conn.player.tell("\n")
                    self._stop_driver()
                else:
                    conn.write_output()

    def __server_loop_process_player_input(self, conn):
        p = conn.player
        assert p.input_is_available.is_set()
        for cmd in p.get_pending_input():
            if not cmd:
                continue
            try:
                p.tell("\n")
                self.__process_player_command(cmd, conn)
                p.remember_parsed()
                # to avoid flooding/abuse, we stop the loop after processing one command.
                break
            except soul.UnknownVerbException as x:
                if x.verb in {"north", "east", "south", "west", "northeast", "northwest", "southeast", "southwest",
                              "north east", "north west", "south east", "south west", "up", "down"}:
                    p.tell("You can't go in that direction.")
                else:
                    p.tell("The verb '%s' is unrecognized." % x.verb)
            except errors.ActionRefused as x:
                p.remember_parsed()
                p.tell(str(x))
            except errors.ParseError as x:
                p.tell(str(x))

    def __main_loop_multiplayer(self):
        """
        The game loop, for the multiplayer MUD mode.
        Until the server is shut down, it processes player input, and prints the resulting output.
        """
        loop_duration = 0
        previous_server_tick = 0
        while not self.__stop_mainloop:
            pubsub.sync("driver-async-dialogs")
            for conn in self.all_players.values():
                conn.write_output()
                if conn not in self.waiting_for_input:
                    conn.write_input_prompt()

            # server tick goes on a timer
            wait_time = max(0.01, self.config.server_tick_time - loop_duration)
            while wait_time > 0:
                if any(conn.player.input_is_available.is_set() for conn in self.all_players.values()):
                    # there was player input, abort the wait loop and deal with it
                    break
                sub_wait = min(0.1, wait_time)  # keep things responsive
                time.sleep(sub_wait)
                wait_time -= sub_wait

            loop_start = time.time()
            for conn in list(self.all_players.values()):
                if conn.player.input_is_available.is_set():
                    conn.need_new_input_prompt = True
                    try:
                        if conn in self.waiting_for_input:
                            # this connection is processing direct input, rather than regular commands
                            dialog, validator, echo_input = self.waiting_for_input.pop(conn)
                            response = conn.player.get_pending_input()[0]
                            if validator:
                                try:
                                    response = validator(response)
                                except ValueError as x:
                                    prompt = conn.last_output_line
                                    conn.io.dont_echo_next_cmd = not echo_input
                                    conn.output(str(x) or "That is not a valid answer.")
                                    conn.output_no_newline(prompt)   # print the input prompt again
                                    self.waiting_for_input[conn] = (dialog, validator, echo_input)   # reschedule
                                    continue
                            self.__continue_dialog(conn, dialog, response)
                        else:
                            # normal command processing
                            self.__server_loop_process_player_input(conn)
                    except (KeyboardInterrupt, EOFError):
                        continue
                    except errors.SessionExit:
                        self.story.goodbye(conn.player)
                        topic_pending_tells.send(lambda conn=conn: self._disconnect_mud_player(conn))
                    except Exception:
                        txt = "* internal error:\n" + traceback.format_exc()
                        conn.player.tell(txt, format=False)
            pubsub.sync("driver-pending-tells")
            # server TICK
            now = time.time()
            if now - previous_server_tick >= self.config.server_tick_time:
                self.__server_tick()
                previous_server_tick = now
            loop_duration = time.time() - loop_start
            self.server_loop_durations.append(loop_duration)

    def __server_tick(self):
        """
        Do everything that the server needs to do every tick (timer configurable in story)
        1) game clock
        2) heartbeats
        3) deferreds
        4) pending pubsub events
        5) write buffered output
        6) verify validity and idle state of connected players
        7) remove idle wiretaps
        """
        self.game_clock.add_realtime(datetime.timedelta(seconds=self.config.server_tick_time))
        ctx = util.Context(self, self.game_clock, self.config, None)
        for obj in self.heartbeat_objects:
            obj.heartbeat(ctx)
        while self.deferreds:
            deferred = None
            with self.deferreds_lock:
                if self.deferreds:
                    deferred = self.deferreds[0]
                    if deferred.due <= self.game_clock.clock:
                        deferred = heapq.heappop(self.deferreds)
                    else:
                        deferred = None
                        break
            if deferred:
                # calling the deferred needs to be outside the lock because it can reschedule a new deferred
                try:
                    deferred(ctx=ctx)  # call the deferred and provide a context object
                except Exception:
                    self.__report_deferred_exception(deferred)
        pubsub.sync()
        for name, conn in list(self.all_players.items()):
            if conn.player and conn.io and conn.player.location:
                idle_limit = 3 * 60 * 60 if "wizard" in conn.player.privileges else 30 * 60
                if self.config.server_mode == "mud" and conn.idle_time > idle_limit:
                    idle_limit_minutes = int(idle_limit / 60)
                    conn.player.tell("\n")
                    conn.player.tell("<it><rev>Automatic logout:  You have been logged out because you've been idle for too long (%d minutes)</>" % idle_limit_minutes, end=True)
                    conn.player.tell("\n")
                    conn.player.tell_others("{Title} has been idling around for too long.")
                    self._disconnect_mud_player(conn)   # remove players who stay idle too long
                conn.write_output()
            else:
                # disconnect corrupt player connection
                self._disconnect_mud_player(conn)
        # clean up idle wiretap topics
        topicinfo = pubsub.pending()
        for topicname in topicinfo:
            if isinstance(topicname, tuple) and topicname[0].startswith("wiretap-"):
                events, idle_time, subbers = topicinfo[topicname]
                if events == 0 and not subbers and idle_time > 30:
                    pubsub.topic(topicname).destroy()

    def __report_deferred_exception(self, deferred):
        print("\n* Exception while executing deferred action {0}:".format(deferred), file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        print("(continuing...)", file=sys.stderr)

    def __process_player_command(self, cmd, conn):
        if not cmd:
            return
        if cmd and cmd[0] in cmds.abbreviations and not cmd[0].isalpha():
            # insert a space to separate the first char such as ' or ?
            cmd = cmd[0] + u" " + cmd[1:]
        # check for an abbreviation, replace it with the full verb if present
        _verb, _sep, _rest = cmd.partition(u" ")
        if _verb in cmds.abbreviations:
            _verb = cmds.abbreviations[_verb]
            cmd = u"".join([_verb, _sep, _rest])

        player = conn.player
        # We pass in all 'external verbs' (non-soul verbs) so it will do the
        # parsing for us even if it's a verb the soul doesn't recognise by itself.
        command_verbs = self.commands.get(player.privileges)
        custom_verbs = set(self.current_custom_verbs(player))
        try:
            if _verb in self.commands.no_soul_parsing:
                # don't use the soul to parse it further
                player.turns += 1
                raise soul.NonSoulVerb(soul.ParseResult(_verb, unparsed=_rest.strip()))
            else:
                # Parse the command by using the soul.
                all_verbs = set(command_verbs) | custom_verbs
                parsed = player.parse(cmd, external_verbs=all_verbs)
            # If parsing went without errors, it's a soul verb, handle it as a socialize action
            player.turns += 1
            player.do_socialize_cmd(parsed)
        except soul.NonSoulVerb as x:
            parsed = x.parsed
            if parsed.qualifier:
                # for now, qualifiers are only supported on soul-verbs (emotes).
                raise errors.ParseError("That action doesn't support qualifiers.")
            # Execute non-soul verb. First try directions, then the rest.
            player.turns += 1
            try:
                # Check if the verb is a custom verb and try to handle that.
                # If it remains unhandled, check if it is a normal verb, and handle that.
                # If it's not a normal verb, abort with "please be more specific".
                parse_error = "That doesn't make much sense."
                handled = False
                if parsed.verb in custom_verbs:
                    # note: can't deal with yields directly, use errors.AsyncDialog in handle_verb to initiate a dialog
                    handled = player.location.handle_verb(parsed, player)
                    if handled:
                        topic_pending_actions.send(lambda actor=player: actor.location.notify_action(parsed, actor))
                    else:
                        parse_error = "Please be more specific."
                if not handled:
                    if parsed.verb in player.location.exits:
                        self._go_through_exit(player, parsed.verb)
                    elif parsed.verb in command_verbs:
                        # Here, one of the commands as annotated with @cmd (or @wizcmd) is executed
                        func = command_verbs[parsed.verb]
                        ctx = util.Context(self, self.game_clock, self.config, conn)
                        if getattr(func, "is_generator", False):
                            dialog = func(player, parsed, ctx)
                            topic_async_dialogs.send((conn, dialog))    # enqueue as async, and continue
                        else:
                            func(player, parsed, ctx)
                        if func.enable_notify_action:
                            topic_pending_actions.send(lambda actor=player: actor.location.notify_action(parsed, actor))
                    else:
                        raise errors.ParseError(parse_error)
            except errors.RetrySoulVerb:
                # cmd decided it can't deal with the parsed stuff and that it needs to be retried as soul emote.
                player.validate_socialize_targets(parsed)
                player.do_socialize_cmd(parsed)
            except errors.RetryParse as x:
                return self.__process_player_command(x.command, conn)   # try again but with new command string
            except errors.AsyncDialog as x:
                # the player command ended but signaled that an async dialog should be initiated
                topic_async_dialogs.send((conn, x.dialog))

    def _go_through_exit(self, player, direction):
        xt = player.location.exits[direction]
        xt.allow_passage(player)
        player.move(xt.target)
        player.look()

    def __lookup_location(self, location_name, only_module=False):
        location = self.zones
        modulename = "zones"
        for name in location_name.split('.'):
            if hasattr(location, name):
                location = getattr(location, name)
            else:
                modulename = modulename + "." + name
                try:
                    imported_module = __import__(modulename)
                    if only_module:
                        return getattr(imported_module, name)
                    location = getattr(location, name)
                except (ImportError, AttributeError):
                    raise ValueError("location not found: " + location_name)
        return location

    def load_zones(self, zone_names):
        """Pre-load the provided zones (essentially, load the named modules from the zones package"""
        for zone in zone_names:
            module = self.__lookup_location(zone, only_module=True)
            module.init(self)

    def __load_saved_game(self, player):
        assert self.config.server_mode == "if", "games can only be loaded in single player 'if' mode"
        assert len(self.all_players) == 1
        conn = list(self.all_players.values())[0]
        try:
            savegame = self.user_resources[util.storyname_to_filename(self.config.name) + ".savegame"].data
            state = pickle.loads(savegame)
            del savegame
        except (pickle.PickleError, ValueError, TypeError) as x:
            print("There was a problem loading the saved game data:")
            print(type(x).__name__, x)
            self._stop_driver()
            raise SystemExit(10)
        except IOError:
            player.tell("No saved game data found.", end=True)
            return None
        else:
            if state["version"] != self.config.version:
                player.tell("This saved game data was from a different version of the game and cannot be used.")
                player.tell("(Current game version: %s  Saved game data version: %s)" % (self.config.version, state["version"]))
                player.tell("\n")
                return None
            # Because loading a complete saved game is strictly for single player 'if' mode,
            # we load a new player and simply replace all players with this one.
            player = state["player"]
            self.all_players = {player.name: conn}
            self.deferreds = state["deferreds"]
            self.game_clock = state["clock"]
            self.heartbeat_objects = state["heartbeats"]
            self.config = state["config"]
            self.waiting_for_input = {}   # can't keep the old waiters around
            player.tell("\n")
            player.tell("Game loaded.")
            if self.config.display_gametime:
                player.tell("Game time:", self.game_clock)
            player.tell("\n")
            return player

    def current_custom_verbs(self, player):
        """returns dict of the currently recognised custom verbs (verb->helptext mapping)"""
        verbs = player.verbs.copy()
        verbs.update(player.location.verbs)
        for living in player.location.livings:
            verbs.update(living.verbs)
        for item in player.inventory:
            verbs.update(item.verbs)
        for item in player.location.items:
            verbs.update(item.verbs)
        for exit in set(player.location.exits.values()):
            verbs.update(exit.verbs)
        return verbs

    def current_verbs(self, player):
        """return a dict of all currently recognised verbs, and their help text"""
        normal_verbs = self.commands.get(player.privileges)
        verbs = {v: (f.__doc__ or "") for v, f in normal_verbs.items()}
        verbs.update(self.current_custom_verbs(player))
        return verbs

    def show_motd(self, player, notify_no_motd=False):
        """Prints the Message-Of-The-Day file, if present. Does nothing in IF mode."""
        try:
            motd = self.resources["messages/motd.txt"]
            message = motd.data.rstrip()
        except IOError:
            message = None
        if message:
            player.tell("<bright>Message-of-the-day:</>", end=True)
            player.tell("\n")
            player.tell(message, end=True, format=True)  # for now, the motd is displayed *with* formatting
            player.tell("\n")
            player.tell("\n")
        elif notify_no_motd:
            player.tell("There's currently no message-of-the-day.", end=True)
            player.tell("\n")

    def search_player(self, name):
        """
        Look through all the logged in players for one with the given name.
        Returns None if no one is known with that name.
        """
        conn = self.all_players.get(name)
        return conn.player if conn else None

    def do_wait(self, duration):
        # let time pass, duration is in game time (not real time).
        # We do let the game tick for the correct number of times.
        # @todo be able to detect if something happened during the wait
        assert self.config.server_mode == "if"
        if self.config.gametime_to_realtime == 0:
            # game is running with a 'frozen' clock
            # simply advance the clock, and perform a single server_tick
            self.game_clock.add_gametime(duration)
            self.__server_tick()
            return True, None      # uneventful
        num_ticks = int(duration.seconds / self.config.gametime_to_realtime / self.config.server_tick_time)
        if num_ticks < 1:
            return False, "It's no use waiting such a short while."
        for _ in range(num_ticks):
            self.__server_tick()
        return True, None     # wait was uneventful. (@todo return False if something happened)

    def do_save(self, player):
        if not self.config.savegames_enabled:
            player.tell("It is not possible to save your progress.")
            return
        state = {
            "version": self.config.version,
            "player": player,
            "deferreds": self.deferreds,
            "clock": self.game_clock,
            "heartbeats": self.heartbeat_objects,
            "config": self.config
        }
        savedata = pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL)
        self.user_resources[util.storyname_to_filename(self.config.name) + ".savegame"] = savedata
        player.tell("Game saved.")
        if self.config.display_gametime:
            player.tell("Game time:", self.game_clock)
        player.tell("\n")

    def register_heartbeat(self, mudobj):
        self.heartbeat_objects.add(mudobj)

    def unregister_heartbeat(self, mudobj):
        self.heartbeat_objects.discard(mudobj)

    def register_exit(self, exit):
        if not exit.bound:
            self.unbound_exits.append(exit)

    def defer(self, due, action, *vargs, **kwargs):
        """
        Register a deferred callable action (optionally with arguments).
        The vargs and the kwargs all must be serializable.
        Note that the due time is datetime.datetime *in game time* (not real time!)
        when the deferred should trigger. It can also be a number, meaning the number
        of real-time seconds after the current time.
        Also note that the deferred gets a kwarg 'ctx' set to a Context object, if it has
        a 'ctx' argument in its signature. (If not, that's okay too)
        Receiving the context is often useful, for instance you can register a new
        deferred on the ctx.driver without having to access a global driver object.
        """
        assert callable(action)
        if isinstance(due, datetime.datetime):
            assert due >= self.game_clock.clock
        else:
            due = float(due)
            assert due >= 0.0
            due = self.game_clock.plus_realtime(datetime.timedelta(seconds=due))
        deferred = Deferred(due, action, vargs, kwargs)
        with self.deferreds_lock:
            heapq.heappush(self.deferreds, deferred)

    def pubsub_event(self, topicname, event):
        if topicname == "driver-pending-actions":
            assert callable(event), "the driver-pending-actions events should be callables"
            event()
        elif topicname == "driver-pending-tells":
            assert callable(event), "the driver-pending-tells events should be callables"
            event()
        elif topicname == "driver-async-dialogs":
            assert type(event) is tuple
            conn, dialog = event
            assert type(conn) is player.PlayerConnection
            assert inspect.isgenerator(dialog)
            self.__continue_dialog(conn, dialog, None)
        else:
            raise ValueError("unknown topic: " + topicname)

    def remove_deferreds(self, owner):
        with self.deferreds_lock:
            self.deferreds = [d for d in self.deferreds if d.owner is not owner]
            heapq.heapify(self.deferreds)

    @property
    def uptime(self):
        """gives the server uptime in a (hours, minutes, seconds) tuple"""
        realtime = datetime.datetime.now()
        realtime = realtime.replace(microsecond=0)
        uptime = realtime - self.server_started
        hours, seconds = divmod(uptime.total_seconds(), 3600)
        minutes, seconds = divmod(seconds, 60)
        return hours, minutes, seconds


class StoryConfig(object):
    """Container for the configuration settings for a Story"""
    config_items = {
        "name",
        "author",
        "author_address",
        "version",
        "requires_tale",
        "supported_modes",
        "player_name",
        "player_gender",
        "player_race",
        "player_money",
        "money_type",
        "server_tick_method",
        "server_tick_time",
        "gametime_to_realtime",
        "max_wait_hours",
        "display_gametime",
        "epoch",
        "startlocation_player",
        "startlocation_wizard",
        "savegames_enabled",
        "show_exits_in_look",
        "license_file",
        "mud_host",
        "mud_port"
    }

    def __init__(self, **kwargs):
        difference = self.config_items ^ set(kwargs)
        if difference:
            raise ValueError("invalid story config; mismatch in config arguments: "+str(difference))
        for k, v in kwargs.items():
            if k in self.config_items:
                setattr(self, k, v)
            else:
                raise AttributeError("unrecognised config attribute: " + k)

    def __eq__(self, other):
        return vars(self) == vars(other)

    @staticmethod
    def copy_from(config):
        assert isinstance(config, StoryConfig)
        return StoryConfig(**vars(config))


@total_ordering
class Deferred(object):
    """
    Represents a callable action that will be invoked (with the given arguments) sometime in the future.
    This object captures the action that must be invoked in a way that is serializable.
    That means that you can't pass all types of callables, there are a few that are not
    serializable (lambda's and scoped functions). They will trigger an error if you use those.
    """
    def __init__(self, due, action, vargs, kwargs):
        assert due is None or isinstance(due, datetime.datetime)
        assert callable(action)
        self.due = due   # in game time
        self.owner = getattr(action, "__self__", None)
        if isinstance(self.owner, types.ModuleType):
            # encode a module simply by its name
            self.owner = "module:" + self.owner.__name__
        if self.owner is None:
            action_module = getattr(action, "__module__", None)
            if action_module:
                if hasattr(sys.modules[action_module], action.__name__):
                    self.owner = "module:" + action_module
                else:
                    # a callable was passed that we cannot serialize.
                    raise ValueError("cannot use scoped functions or lambdas as deferred: " + str(action))
            else:
                raise ValueError("cannot determine action's owner object: " + str(action))
        self.action = action.__name__    # store name instead of object, to make this serializable
        self.vargs = vargs
        self.kwargs = kwargs

    def __eq__(self, other):
        return self.due == other.due and type(self.owner) == type(other.owner)\
            and self.action == other.action and self.vargs == other.vargs and self.kwargs == other.kwargs

    def __lt__(self, other):
        return self.due < other.due   # deferreds must be sortable

    def when_due(self, game_clock, realtime=False):
        """
        In what time is this deferred due to occur? (timedelta)
        Normally it is in terms of game-time, but if you pass realtime=True,
        you will get the real-time timedelta.
        """
        secs = (self.due - game_clock.clock).total_seconds()
        if realtime:
            secs = int(secs / game_clock.times_realtime)
        return datetime.timedelta(seconds=secs)

    def __call__(self, *args, **kwargs):
        self.kwargs = self.kwargs or {}
        if callable(self.action):
            func = self.action
        else:
            # deferred action is stored as the name of the function to call,
            # so we need to obtain the actual function from the owner object.
            if isinstance(self.owner, util.basestring_type):
                if self.owner.startswith("module:"):
                    # the owner refers to a module
                    self.owner = sys.modules[self.owner[7:]]
                else:
                    raise RuntimeError("invalid owner specifier: " + self.owner)
            func = getattr(self.owner, self.action)
        if "ctx" in inspect.getargspec(func).args:
            self.kwargs["ctx"] = kwargs["ctx"]  # add a 'ctx' keyword argument to the call for convenience
        func(*self.vargs, **self.kwargs)
        # our lifetime has ended, remove references:
        del self.owner
        del self.action
        del self.kwargs
        del self.vargs


class Commands(object):
    """
    Some utility functions to manage the registered commands.
    """
    def __init__(self):
        self.commands_per_priv = {None: {}}
        self.no_soul_parsing = set()

    def add(self, verb, func, privilege=None):
        self.validateFunc(func)
        for commands in self.commands_per_priv.values():
            if verb in commands:
                raise ValueError("command defined more than once: " + verb)
        self.commands_per_priv.setdefault(privilege, {})[verb] = func

    def override(self, verb, func, privilege=None):
        self.validateFunc(func)
        if verb in self.commands_per_priv[privilege]:
            existing = self.commands_per_priv[privilege][verb]
            self.commands_per_priv[privilege][verb] = func
            return existing
        raise KeyError("command not defined: " + verb)

    def validateFunc(self, func):
        if not hasattr(func, "is_tale_command_func"):
            raise ValueError("the function '%s' is not a proper command function (did you forget the decorator?)" % func.__name__)

    def get(self, privileges):
        result = dict(self.commands_per_priv[None])  # always include the cmds for None
        for priv in privileges:
            if priv in self.commands_per_priv:
                result.update(self.commands_per_priv[priv])
        return result

    def adjust_available_commands(self, server_mode):
        # disable commands flagged with the given game_mode
        # disable soul verbs flagged with override
        # mark non-soul commands
        for commands in self.commands_per_priv.values():
            for cmd, func in list(commands.items()):
                disabled_mode = getattr(func, "disabled_in_mode", None)
                if server_mode == disabled_mode:
                    del commands[cmd]
                elif getattr(func, "overrides_soul", False):
                    del soul.VERBS[cmd]
                if getattr(func, "no_soul_parse", False):
                    self.no_soul_parsing.add(cmd)


@base.heartbeat
class LimboReaper(npc.NPC):
    """The Grim Reaper hangs about in Limbo, and makes sure no one stays there for too long."""
    def __init__(self):
        super(LimboReaper, self).__init__(
            "reaper", "m", "elemental", "Grim Reaper",
            description="He wears black robes with a hood. Where a face should be, there is only nothingness. "
                        "He is carrying a large omnious scythe that looks very, very sharp.",
            short_description="A figure clad in black, carrying a scythe, is also present.")
        self.aliases = {"figure", "death"}
        self.candidates = {}    # player --> (first_seen, texts shown)

    def notify_action(self, parsed, actor):
        if parsed.verb == "say":
            actor.tell("%s just stares blankly at you, not saying a word." % lang.capital(self.title))
        else:
            actor.tell("%s stares blankly at you." % lang.capital(self.title))

    def heartbeat(self, ctx):
        # consider all livings currently in Limbo or having their location set to Limbo
        if self.location is not base._limbo:
            # we somehow got misplaced, teleport back to limbo
            self.tell_others("{Title} looks around in wonder and says, \"I'm not supposed to be here.\"")
            self.move(base._limbo, self)
            return
        in_limbo = {living for living in self.location.livings if living is not self}
        in_limbo.update({conn.player for conn in ctx.driver.all_players.values() if conn.player.location is base._limbo})
        now = time.time()
        for candidate in in_limbo:
            if candidate not in self.candidates:
                self.candidates[candidate] = (now, 0)   # a new player first seen
        for candidate in list(self.candidates):
            if candidate not in in_limbo:
                del self.candidates[candidate]   # player no longer present in limbo
                continue
            first_seen, shown = self.candidates[candidate]
            duration = now - first_seen
            # Depending on how long the candidate is being observed, show increasingly threateningly warnings,
            # and eventually killing the candidate (and closing their connection).
            if duration >= 30 and shown < 1:
                candidate.tell(self.title + " whispers: \"Greetings. Be aware that you must not linger here... Decide swiftly...\"")
                shown = 1
            elif duration >= 50 and shown < 2:
                candidate.tell(self.title + " looms over you and warns: \"You really cannot stay here much longer!\"")
                shown = 2
            elif duration >= 60 and shown < 3:
                candidate.tell(self.title + " menacingly raises his scythe!")
                shown = 3
            elif duration >= 62 and shown < 4:
                candidate.tell(self.title + " swings down his scythe and slices your soul cleanly in half. You are destroyed.")
                shown = 4
            elif duration >= 63:
                try:
                    conn = ctx.driver.all_players[candidate.name]
                except KeyError:
                    pass   # already gone
                else:
                    ctx.driver._disconnect_mud_player(conn)
            self.candidates[candidate] = (first_seen, shown)


if __name__ == "__main__":
    print("Use module tale.main instead.")
    raise SystemExit(1)
