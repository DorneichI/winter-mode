"""Shared test fixtures for winter-mode.

The app only ever touches hardware through the injected `lcd` and `touch`
seams, so tests substitute fakes here — same philosophy as the ert driver's
FakeBus. Nothing in this file needs a Raspberry Pi.
"""
