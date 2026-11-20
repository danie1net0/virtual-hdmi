"""python3 -m tests.mutation: the mutation gate of tests/mutation/gate.py."""

import sys

from tests.mutation import gate

if __name__ == "__main__":
    sys.exit(gate.main(sys.argv[1:]))
