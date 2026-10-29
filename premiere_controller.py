"""Legacy import/CLI entry; also works from a source checkout."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from pr_controller import PremiereController,Config,NativeError
if __name__=='__main__':
    from pr_controller.cli import main
    main()
