"""Where finished rides go.

One static directory holds every recording, as FIT files, and nothing else in the
application writes anywhere near it. What a ride *is* on disk is decided here and
nowhere else, so uploading, listing and deleting all agree by construction.
"""
