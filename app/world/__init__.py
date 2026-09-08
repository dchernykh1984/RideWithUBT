"""The world the rider moves through.

A world here is a *road network*, not a loop: Sokol has a big ring, a small ring
and a pit lane that share sections and part at junctions. So the model is a graph
of one-way segments joined at nodes, and where a node has more than one exit the
rider chooses.

Nothing in this package imports Panda3D. The network, the rider's position on it
and the junction logic are plain data and arithmetic, which is what lets all of
it be tested without a window - the renderer only draws what it is given.
"""
