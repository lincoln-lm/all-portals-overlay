"""Exact All Portals solver via formulating the problem as the ring star problem and solving that
with a MILP solver.

AP paths and this solver differ slightly from ring star as they require only a path and not a cycle.
AP paths additionally can make use of the world spawn point (origin) which technically makes most
edge weights asymmetrical.

The cycle issue is resolved by using a dummy root as the root that has a cost of 0 but must always
connect to the real root.
The edge from the last real node to the dummy root is then just not drawn.

To solve the origin issue the assertion is made that in an optimal solution the origin will only be
used to connect to the first ring of strongholds.
The first ring of strongholds are guaranteed to be closer to the origin than to any other
stronghold.
This means that the fastest path to a first ring stronghold is always via the origin.
It also means that the first ring of strongholds will never be assigned to another node because a
path that assigns them to any other node will always be worse than an identical path that returns
to the origin at the end and picks up the first ring of strongholds then.
This means that an optimal solution will always access the first ring via the origin which will cost
a constant value.
Since this constant amount does not impact the comparison between solutions it can be treated as 0.
Because the only time the origin is used is to access the first ring, dummy nodes can be created for
each first ring stronghold that have a cost of 0 but must always connect to the real stronghold.
"""

import threading
import time
import itertools
import math
import json
import pathlib
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import networkx as nx
import numpy as np
import pulp
import requests

STRONGHOLD_DATA = (
    (3, 1280, 2816),
    (6, 4352, 5888),
    (10, 7424, 8960),
    (15, 10496, 12032),
    (21, 13568, 15104),
    (28, 16640, 18176),
    (36, 19712, 21248),
    (10, 22784, 24320),
)
# how much to scale coordinates down by
SCALE_FACTOR = 16
# verbose MILP solver output
VERBOSE = False

# simulate AP measurement and prediction of strongholds
TEST_DATA = False

if TEST_DATA:
    seed = np.random.randint(2**30)
    np.random.seed(seed)
    print(f"{seed=:08X}")

    sh_rings = []
    for i, (count, minimum, maximum) in enumerate(STRONGHOLD_DATA):
        first_angle = np.random.rand() * 2 * np.pi
        ring = []
        for sh in range(0, count):
            angle = first_angle + 2 * np.pi * sh / count
            # scale down to make things easier
            distance = (maximum + minimum) / 2 / SCALE_FACTOR
            x = np.cos(angle) * distance
            y = np.sin(angle) * distance
            ring.append((x, y))
        sh_rings.append(ring)

    # select the closest stronghold from the next ring to measure
    measured_shs = [sh_rings[0].pop(0)]
    for ring in sh_rings[1:]:
        closest = 1 << 60, None
        for sh in ring:
            distance_squared = (measured_shs[-1][0] - sh[0]) ** 2 + (
                measured_shs[-1][1] - sh[1]
            ) ** 2
            if distance_squared < closest[0]:
                closest = distance_squared, sh
        ring.remove(closest[1])
        measured_shs.append(closest[1])
else:
    # open strongholds.json in this folder
    measured_shs = json.loads(
        (pathlib.Path(__file__).parent / "strongholds.json").read_text()
    )
    measured_shs = [(sh[0] / SCALE_FACTOR, sh[1] / SCALE_FACTOR) for sh in measured_shs]

# rebuild rings in proper order
sh_rings = []
for i, (count, minimum, maximum) in enumerate(STRONGHOLD_DATA):
    first = measured_shs[i]
    first_angle = math.atan2(first[1], first[0])
    ring = []
    for sh in range(1, count):
        angle = first_angle + 2 * np.pi * sh / count
        # scale down to make things easier
        distance = (maximum + minimum) / 2 / SCALE_FACTOR
        x = np.cos(angle) * distance
        y = np.sin(angle) * distance
        ring.append((x, y))
    sh_rings.append(ring)

measured_copy = measured_shs.copy()

# start from the 7th ring measured sh
all_shs = sum(sh_rings, [measured_shs.pop(-2)])

# useful constant indexes
# dummy nodes
DUMMY_ROOT = 0
DUMMY_RING_1_1 = DUMMY_ROOT + 1
DUMMY_RING_1_2 = DUMMY_RING_1_1 + 1

# 7th ring measured stronghold
REAL_ROOT = DUMMY_RING_1_2 + 1

# first ring strongholds
REAL_RING_1_1 = REAL_ROOT + 1
REAL_RING_1_2 = REAL_RING_1_1 + 1

graph = nx.Graph()
for idx, sh in enumerate(all_shs, start=REAL_ROOT):
    graph.add_node(
        idx, pos=np.array(sh), color="red" if idx == REAL_ROOT else "#1f78b4"
    )

NODE_COUNT = len(graph.nodes) + REAL_ROOT
POINTS_IDX = list(range(NODE_COUNT))
ALL_ROUTES = [(p1, p2) for p1 in POINTS_IDX for p2 in POINTS_IDX if p1 != p2]

for i, measured_sh in enumerate(measured_shs, start=1):
    graph.add_node(-i, pos=np.array(measured_sh), color="red")


class ComputeThread(threading.Thread):
    """Thread that actually runs the MILP solver and updates the graph"""

    def __init__(self, graph: nx.Graph):
        super().__init__(daemon=True)
        self.graph = graph
        self.elapsed_time = 0
        self.iteration = -1
        self.problem = pulp.LpProblem("RingStarProblem", pulp.LpMinimize)
        # define binary variables x_i_j that equal 1
        # if and only if the edge i <-> j is part of the cycle
        self.cycle_vars = {
            point1: {
                point2: pulp.LpVariable(f"x_{point1}_{point2}", cat=pulp.LpBinary)
                for point2 in POINTS_IDX[point1 + 1 :]
            }
            for point1 in POINTS_IDX
        }
        # define binary variables y_i_j that equal 1
        # if and only if the node v_i is assigned to the node v_j as an arm
        # for only nodes v_i on the cycle y_i_i == 1 i.e. the node is assigned to itself
        self.assignment_vars = {
            point1: {
                point2: pulp.LpVariable(f"y_{point1}_{point2}", cat=pulp.LpBinary)
                for point2 in POINTS_IDX
            }
            for point1 in POINTS_IDX
        }

        # enforce that each node has exactly 2 cycle connections
        # if and only if that node is on the cycle
        # and otherwise has 0 cycle connections
        for point1 in POINTS_IDX:
            self.problem += (
                pulp.lpSum(
                    self.cycle_vars[min(point1, point2)][max(point1, point2)]
                    for point2 in POINTS_IDX
                    if point2 != point1
                )
                == 2 * self.assignment_vars[point1][point1]
            )

        # enforce that every real node is assigned to exactly 1 other node
        # this means nodes on the cycle cannot be assigned to any other nodes
        # (they are assigned to themselves)
        # and that nodes external to the cycle are only assigned to 1 other node
        for point1 in POINTS_IDX[REAL_ROOT:]:
            self.problem += (
                pulp.lpSum(
                    self.assignment_vars[point1][point2] for point2 in POINTS_IDX
                )
                == 1
            )

        # enforce that the first node and the dummy nodes are only assigned to themselves
        # (root is always on the cycle)
        self.problem += self.assignment_vars[DUMMY_ROOT][DUMMY_ROOT] == 1
        self.problem += self.assignment_vars[DUMMY_RING_1_1][DUMMY_RING_1_1] == 1
        self.problem += self.assignment_vars[DUMMY_RING_1_2][DUMMY_RING_1_2] == 1

        # dummy nodes & the root are implicitly never going to be assigned to other nodes
        # but this can be an added condition here if it helps solving

        # enforce that nothing is ever assigned to the dummy nodes
        for point in POINTS_IDX[REAL_ROOT:]:
            for dummy_point in (DUMMY_ROOT, DUMMY_RING_1_1, DUMMY_RING_1_2):
                self.problem += self.assignment_vars[point][dummy_point] == 0

        # enforce that the first ring nodes cannot connect to each other
        self.problem += self.cycle_vars[REAL_RING_1_1][REAL_RING_1_2] == 0
        self.problem += self.cycle_vars[DUMMY_RING_1_1][REAL_RING_1_2] == 0
        self.problem += self.cycle_vars[DUMMY_RING_1_2][REAL_RING_1_1] == 0

        # enforce that the fake nodes always connect to their real counterpart
        self.problem += self.cycle_vars[DUMMY_ROOT][REAL_ROOT] == 1
        self.problem += self.cycle_vars[DUMMY_RING_1_1][REAL_RING_1_1] == 1
        self.problem += self.cycle_vars[DUMMY_RING_1_2][REAL_RING_1_2] == 1

        # define the objective function
        # minimize the sum of the distances between all edges on the cycle (cycle length)
        # and the sum of the distances between all edges assigned to those on the cycle
        # from their assigned cycle node (total arm length)
        self.problem += pulp.lpSum(
            self.euclidean_distance(point1, point2) * self.cycle_vars[point1][point2]
            for point1 in POINTS_IDX
            for point2 in POINTS_IDX[point1 + 1 :]
        ) + pulp.lpSum(
            self.euclidean_distance(point1, point2)
            * self.assignment_vars[point1][point2]
            for point1 in POINTS_IDX
            for point2 in POINTS_IDX
            if point2 != point1
        )
        self.running = True

    def delta_edges(self, set_of_points):
        """Defines the set of all undirected edges between all points within the set
        and all points outside of the set"""
        for point1 in set_of_points:
            for point2 in POINTS_IDX:
                if point2 not in set_of_points:
                    yield point1, point2

    def euclidean_distance(self, point1_index, point2_index):
        """Euclidean distance between two points"""
        # dummy points are always free
        if point1_index < REAL_ROOT or point2_index < REAL_ROOT:
            return 0
        return np.sqrt(
            np.sum(
                (
                    self.graph.nodes[point1_index]["pos"]
                    - self.graph.nodes[point2_index]["pos"]
                )
                ** 2
            )
        )

    def run(self):
        start_time = time.time()
        last_solution = None
        while self.running:
            self.problem.solve(pulp.PULP_CBC_CMD(msg=VERBOSE))
            self.graph.clear_edges()
            cycle_edges = {}
            assignments = {}
            for point1 in POINTS_IDX:
                for point2 in POINTS_IDX[point1 + 1 :]:
                    if self.cycle_vars[point1][point2].value() == 1:
                        cycle_edges[point1] = cycle_edges.get(point1, []) + [point2]
                        cycle_edges[point2] = cycle_edges.get(point2, []) + [point1]
                        p1 = point1
                        p2 = point2

                        # if it is real draw it thick
                        # if it is not a real edge then draw it lightly
                        thickness = 5
                        if p1 == DUMMY_ROOT:
                            p1 = REAL_ROOT
                            thickness = 0.5
                        elif p1 == DUMMY_RING_1_1:
                            p1 = REAL_RING_1_1
                            thickness = 0.5
                        elif p1 == DUMMY_RING_1_2:
                            p1 = REAL_RING_1_2
                            thickness = 0.5
                        if p2 == DUMMY_ROOT:
                            p2 = REAL_ROOT
                            thickness = 0.5
                        elif p2 == DUMMY_RING_1_1:
                            p2 = REAL_RING_1_1
                            thickness = 0.5
                        elif p2 == DUMMY_RING_1_2:
                            p2 = REAL_RING_1_2
                            thickness = 0.5

                        if p1 != p2:
                            self.graph.add_edge(p1, p2, thickness=thickness)
            for point1 in POINTS_IDX:
                for point2 in POINTS_IDX:
                    if self.assignment_vars[point1][point2].value() == 1:
                        if point1 != point2:
                            self.graph.add_edge(point1, point2)
                        assignments[point1] = point2
            # find all subcycles including the nodes assigned to them
            unvisited_nodes = set(POINTS_IDX)
            cycles = []
            while cycle_edges:
                start = list(cycle_edges.keys())[0]
                cycle = [start]
                cycle_assignments = []
                while True:
                    unvisited_nodes.discard(cycle[-1])
                    for assigned_node, assigned_to_node in assignments.items():
                        if assigned_node == assigned_to_node:
                            continue
                        if assigned_to_node == cycle[-1]:
                            unvisited_nodes.discard(assigned_node)
                            cycle_assignments.append(assigned_node)
                    connected_edges = cycle_edges.pop(cycle[-1])
                    next_point = next(
                        (p for p in connected_edges if p not in cycle), start
                    )
                    cycle.append(next_point)
                    if next_point == start:
                        break
                cycles.append((cycle, cycle_assignments))
            # nodes that arent assigned to a cycle node can be considered on their own
            for node in unvisited_nodes:
                cycles.append(([], [node, assignments[node]]))
            # validate directionality of dummy & real nodes
            invalid_paths = []
            all_paths_valid = True
            for cycle_, _ in cycles:
                for start, end in (
                    ((REAL_RING_1_1, DUMMY_RING_1_1), (DUMMY_RING_1_2, REAL_RING_1_2)),
                    ((REAL_RING_1_1, DUMMY_RING_1_1), (DUMMY_ROOT, REAL_ROOT)),
                    ((REAL_RING_1_2, DUMMY_RING_1_2), (DUMMY_ROOT, REAL_ROOT)),
                ):
                    if start[0] not in cycle_ or end[0] not in cycle_:
                        continue
                    path_is_valid = False
                    cycle = itertools.cycle(cycle_)
                    invalid_path = [start[0]]
                    for point in cycle:
                        if point == start[0]:
                            break
                    search_point = end[0]
                    invalid_point = end[1]
                    # dummy and real nodes must alternate throughout the cycle
                    # D1->R1->...->D2->R2 is valid
                    # D1->R1->...->R2->D2 is invalid
                    # R1->D1->...->D2->R2 is invalid
                    # R1->D1->...->R2->D2 is valid
                    for point in cycle:
                        invalid_path.append(point)
                        if point == start[1]:
                            invalid_path = [start[1]]
                            search_point = end[1]
                            invalid_point = end[0]
                        elif point == invalid_point:
                            path_is_valid = False
                            break
                        elif point == search_point:
                            path_is_valid = True
                            break
                    if not path_is_valid:
                        all_paths_valid = False
                        invalid_paths.append(invalid_path)
                        # lazily apply invalidation constraint
                        # TODO: is this constraint optimal/always correct
                        # it is essentially trying to invalidate the specific group of nodes from
                        # forming a contiguous path by requiring > 2 delta edges
                        self.problem += (
                            pulp.lpSum(
                                self.cycle_vars[min(point1, point2)][
                                    max(point1, point2)
                                ]
                                for point1, point2 in self.delta_edges(
                                    set(invalid_path)
                                )
                            )
                            >= 3
                        )
            # if there is only one cycle & it is valid then an optimal solution has been found
            # and we can stop
            if len(cycles) == 1:
                print("Found single cycle solution")
                if all_paths_valid:
                    print("Found valid single cycle solution")
                    self.running = False
                else:
                    print(f"Invalid due to {invalid_paths=}")

            # lazily apply the subcycle elimination constraints on every subcycle found
            for cycle, raw_assignments in cycles:
                if DUMMY_ROOT in cycle:
                    continue
                subcycle_set = set(cycle) | set(raw_assignments)
                for v_i in subcycle_set:
                    self.problem += pulp.lpSum(
                        self.cycle_vars[min(point1, point2)][max(point1, point2)]
                        for point1, point2 in self.delta_edges(subcycle_set)
                    ) >= 2 * pulp.lpSum(
                        self.assignment_vars[v_i][v_j] for v_j in subcycle_set
                    )
            self.elapsed_time = time.time() - start_time
            self.iteration += 1
            print(
                f"Iteration: {self.iteration}"
                f" | {self.elapsed_time:.2f} seconds elapsed"
                f" | State: {'Solving' if self.running else 'Solved'}"
            )
            if self.running and cycles == last_solution:
                print("ERROR: No new solution despite new constraints")
                self.running = False
            last_solution = cycles

            paths = []
            path_assignments = {}
            for node in graph.nodes:
                parent = assignments.get(node, node)
                if parent == node:
                    continue
                if parent not in path_assignments:
                    path_assignments[parent] = []
                path_assignments[parent].append(node)
            for cycle, _ in cycles:
                path = []
                cycle_iter = iter(cycle)
                while True:
                    node = next(cycle_iter, None)
                    if node is None:
                        break
                    if node in (1, 2):
                        after_origin = next(cycle_iter, None)
                        if after_origin is None:
                            break
                        path.append(["origin", after_origin - 3])
                    elif node == 0:
                        continue
                    else:
                        path.append(["goto", node - 3])
                    for assigned_node in path_assignments.get(node, []):
                        path.append(["reset", assigned_node - 3])
                paths.append(path)

            data = {
                "message": json.dumps(
                    {
                        "type": "path",
                        "paths": [path for path in paths],
                        "measured": measured_copy,
                        "message": f"iteration: {self.iteration}\n{self.elapsed_time:.2f} seconds elapsed",
                    }
                )
            }
            print(data)

            requests.post("http://localhost:5002/message", data=data, timeout=1)
        data = {
            "message": json.dumps(
                {
                    "type": "solved",
                }
            )
        }
        print(data)
        requests.post("http://localhost:5002/message", data=data, timeout=1)


compute_thread = ComputeThread(graph)
compute_thread.start()


def draw_graph(_):
    """FuncAnimation function to constantly redraw the graph"""
    plt.gca().clear()
    edge_thickness = [graph[u][v].get("thickness", 1) for u, v in graph.edges]
    node_colors = [graph.nodes[node].get("color", "#1f78b4") for node in graph.nodes]
    nx.draw(
        graph,
        pos=nx.get_node_attributes(graph, "pos"),
        node_color=node_colors,
        width=edge_thickness,
        with_labels=True,
    )
    plt.title(
        f"Iteration: {compute_thread.iteration}"
        f" | {compute_thread.elapsed_time:.2f} seconds elapsed"
        f" | State: {'Solving' if compute_thread.running else 'Solved'}"
    )
    plt.axis("equal")


func_anim = FuncAnimation(
    plt.gcf(), draw_graph, interval=100, repeat=True, cache_frame_data=False
)
plt.show()
compute_thread.running = False
