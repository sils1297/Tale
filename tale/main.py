"""
Main startup class

'Tale' mud driver, mudlib and interactive fiction framework
Copyright by Irmen de Jong (irmen@razorvine.net)
"""
import sys
from .driver import Driver


def run_story(story_path, gui=False):
    """convenience helper function to launch the game from story script files"""
    args = ["--game", story_path]
    if gui:
        args.append("--gui")
    Driver().start(args)
    raise SystemExit(0)


if __name__ == "__main__":
    # module is started as a script, run the driver
    Driver().start(sys.argv[1:])
    raise SystemExit(0)