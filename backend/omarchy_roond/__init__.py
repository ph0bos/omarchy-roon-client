"""The Roon side of Roon for Omarchy.

A long-lived daemon that owns the one thing QML cannot do: a persistent,
authenticated connection to a Roon Core. Discovery is UDP, pairing needs a stored
token, and zone state arrives as server pushes on a subscription that must stay
open -- none of which a QML scene can hold.

Deliberately stdlib-only. The MOO protocol turned out to be small enough to own
outright (a header block and a JSON body over a WebSocket), which is less code
than vendoring and adapting `roonapi` would have been, and it leaves no
unmaintained dependency in the install path.
"""

__version__ = "0.1.0"
