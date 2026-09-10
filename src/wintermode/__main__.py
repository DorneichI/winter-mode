"""python -m wintermode — entry point.

The real entry lives in app.main(); this indirection keeps `python -m
wintermode` working from a checkout and from an installed wheel alike.
"""

from wintermode.app import main

if __name__ == "__main__":
    main()
