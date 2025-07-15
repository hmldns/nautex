from pathlib import Path



def path2display(path: Path) -> str:
    home = Path.home()
    if path.is_relative_to(home):
        relative = path.relative_to(home)
        return "~/" + str(relative)
    else:
        return str(path)
