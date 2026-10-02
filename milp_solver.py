import threading
import itertools
import math
import functools
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import networkx as nx
import numpy as np
import pulp
import highspy

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
SCALE_FACTOR = 16
VERBOSE = True

COLORS = colors = matplotlib.cm.Set1(range(20))


class ComputeThread(threading.Thread):
    """Thread that actually runs the MILP solver and updates the graph"""

    def __init__(
        self,
        measured_shs: list[tuple],
        player_count: int,
        threads: int,
        time_limit: int,
        callback=None,
    ):
        super().__init__(daemon=True)
        self.graph = nx.DiGraph()
        self.original_measured_shs = measured_shs.copy()
        self.player_count = player_count
        self.threads = threads
        self.time_limit = time_limit
        self.callback = callback
        self.elapsed_time = 0
        self.iteration = -1
        self.problem = pulp.LpProblem("RingStarProblem", pulp.LpMinimize)

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
        all_shs = sum(sh_rings[:-1], [measured_shs.pop(-2)])

        self.ORIGIN = -1
        self.ROOT = 1
        self.FIRST_RING_1 = self.ROOT + 1
        self.FIRST_RING_2 = self.FIRST_RING_1 + 1

        SEVENTH_RING_IDX = [self.ROOT] + list(
            range(
                len(all_shs) - len(sh_rings[-2]) + self.ROOT, len(all_shs) + self.ROOT
            )
        )
        EIGTH_RING_IDX = range(
            len(all_shs) + self.ROOT, len(all_shs) + self.ROOT + len(sh_rings[-1])
        )

        NODE_COUNT = len(all_shs)
        self.POINTS_IDX = list(range(self.ROOT, NODE_COUNT + self.ROOT))
        self.NON_ROOT_POINTS_IDX = self.POINTS_IDX[1:]

        for idx, sh in enumerate(sh_rings[-1], start=NODE_COUNT + 1):
            self.graph.add_node(idx, pos=np.array(sh), color="pink")

        for idx, sh in enumerate(all_shs, start=self.ROOT):
            self.graph.add_node(
                idx, pos=np.array(sh), color="red" if idx == self.ROOT else "#1f78b4"
            )

        for i, measured_sh in enumerate(measured_shs, start=1):
            self.graph.add_node(-i, pos=np.array(measured_sh), color="red")

        # precompute the set of arcs that always prefer travel through the origin
        self.origin_reset_arcs = set(
            (point1, point2)
            for point1 in self.POINTS_IDX
            for point2 in self.NON_ROOT_POINTS_IDX
            if self.euclidean_distance(point1, point2)
            > self.euclidean_distance(self.ORIGIN, point2)
            and point1 != point2
        )
        # precompute the closest 7th ring stronghold for each 8th ring stronghold
        # these strongholds must never be assigned to another stronghold as the 8th ring will always be assigned to them
        self.unassigned_7th_ring_strongholds = {
            eigth: min(
                (
                    seventh
                    for seventh in itertools.chain(SEVENTH_RING_IDX, (self.ROOT,))
                ),
                key=functools.partial(self.euclidean_distance, pos2=eigth),
            )
            for eigth in EIGTH_RING_IDX
        }
        # special case for when there is only one player, origin resetting assumption should hold
        if self.player_count == 1:
            self.origin_reset_arcs = set(
                (point1, first_ring_stronghold)
                for point1 in self.POINTS_IDX
                for first_ring_stronghold in (self.FIRST_RING_1, self.FIRST_RING_2)
                if point1 != first_ring_stronghold
            )

        # $A$ is the set of all arcs
        # $c_{ij}$ is the cost of arc $(i,j)$ (self.arc_cost(i, j))
        # $m$ is the number of travelers (the number of paths, self.player_count)
        # $x_{ij}$ is a binary variable equal to 1 iff arc $(i,j)$ is in a path in the solution
        self.arc_var = {
            point1: {
                point2: pulp.LpVariable(f"x_{point1}_{point2}", cat=pulp.LpBinary)
                for point2 in self.POINTS_IDX
                if point1 != point2
            }
            for point1 in self.POINTS_IDX
        }
        # $y_{ij}$ is a binary variable equal to 1 iff arc $(i,j)$ is an assignment in the solution
        self.assignment_var = {
            point1: {
                point2: pulp.LpVariable(f"y_{point1}_{point2}", cat=pulp.LpBinary)
                for point2 in self.POINTS_IDX
                if point1 != point2
            }
            for point1 in self.POINTS_IDX
        }
        # $z_i$ is a binary variable equal to 0 (assignment) iff node $i$ is assigned to another node, and 1 (arc) iff node $i$ is in a path
        self.node_type_var = {
            point: pulp.LpVariable(f"z_{point}", cat=pulp.LpBinary)
            for point in self.POINTS_IDX
        }
        # $u_i$ is the number of nodes visited on a traveler's path before visiting node $i$
        self.path_length_var = {
            point: pulp.LpVariable(f"u_{point}", lowBound=0, cat=pulp.LpContinuous)
            for point in self.POINTS_IDX
        }
        # $L$ is the maximum number of nodes a traveler can visit (maximum path length)
        self.maximum_path_length = (len(self.POINTS_IDX) - 1) // self.player_count
        # $K$ is the minimum number of nodes a traveler must visit (minimum path length)
        self.minimum_path_length = 4
        M_LARGE = self.maximum_path_length

        assert (
            2 <= self.minimum_path_length <= len(self.POINTS_IDX) // self.player_count
        ), f"Minimum path length must be between 2 and {len(self.POINTS_IDX) // self.player_count}"
        assert self.minimum_path_length <= self.maximum_path_length

        # minimize $$\sum_{(i,j) \in A}c_{ij}(x_{ij}+y_{ij})$$

        # the total cost of the path

        self.problem += pulp.lpSum(
            self.arc_cost(point1, point2)
            * (self.arc_var[point1][point2] + self.assignment_var[point1][point2])
            for point1 in self.POINTS_IDX
            for point2 in self.POINTS_IDX
            if point1 != point2
        )

        # such that

        # - $\sum_{j=2}^{n}x_{1j}=m$

        # there are exactly $m$ paths leaving the root node

        self.problem += (
            pulp.lpSum(
                self.arc_var[self.ROOT][point] for point in self.NON_ROOT_POINTS_IDX
            )
            == self.player_count
        )

        # - $\sum_{j=2}^{n}x_{j1}=m$

        # there are exactly $m$ paths returning to the root node

        self.problem += (
            pulp.lpSum(
                self.arc_var[point][self.ROOT] for point in self.NON_ROOT_POINTS_IDX
            )
            == self.player_count
        )

        # if A->B is most efficiently traveled through the origin, B cannot be assigned to A
        for origin_reset_arc in self.origin_reset_arcs:
            self.problem += (
                self.assignment_var[origin_reset_arc[0]][origin_reset_arc[1]] == 0
            )

        # all 8th ring strongholds must be assigned to their closest 7th ring stronghold
        # -> these closest 7th ring strongholds cannot be assigned to any other stronghold
        # -> these closest 7th ring strongholds must be in a path (node type 1)
        for (
            unassigned_7th_ring_stronghold
        ) in self.unassigned_7th_ring_strongholds.values():
            if unassigned_7th_ring_stronghold == self.ROOT:
                continue
            self.problem += self.node_type_var[unassigned_7th_ring_stronghold] == 1

        # - $\sum_{i=1}^{n}x_{ij}+y_{ij}=1, j=2,...,n$

        # each non root node can only have exactly one incoming arc or assignment, but not both

        for point2 in self.NON_ROOT_POINTS_IDX:
            self.problem += (
                pulp.lpSum(
                    self.arc_var[point1][point2] + self.assignment_var[point1][point2]
                    for point1 in self.POINTS_IDX
                    if point1 != point2
                )
                == 1
            )

        # - $\sum_{i=1}^{n}y_{ij}=1-z_{j}, j=2,...,n$

        # if a node is assigned to another node, it must have node type 0 (assignment)
        # if a node is not assigned to another node, it must have node type 1 (arc)
        for point2 in self.NON_ROOT_POINTS_IDX:
            self.problem += (
                pulp.lpSum(
                    self.assignment_var[point1][point2]
                    for point1 in self.POINTS_IDX
                    if point1 != point2
                )
                == 1 - self.node_type_var[point2]
            )

        # - $\sum_{j=1}^{n}x_{ij} = z_i, i=2,...,n$

        # if a node has any outgoing arcs, it must have node type 1 (arc)
        for point1 in self.NON_ROOT_POINTS_IDX:
            self.problem += (
                pulp.lpSum(
                    self.arc_var[point1][point2]
                    for point2 in self.POINTS_IDX
                    if point1 != point2
                )
                == self.node_type_var[point1]
            )

        # - $\sum_{j=1}^{n}y_{ij} \leq z_i * M, i=2,...,n$

        # an assignment node can have at most 0 outgoing assignments,
        # and an arc node can have at most M outgoing assignments
        for point1 in self.POINTS_IDX:
            self.problem += (
                pulp.lpSum(
                    self.assignment_var[point1][point2]
                    for point2 in self.POINTS_IDX
                    if point1 != point2
                )
                <= self.node_type_var[point1] * M_LARGE
            )

        # MTZ subtour elimination

        # - $u_i + (L - 2)x_{1i} - x_{i1} \leq L - 1, i=2,...,n$
        for point in self.NON_ROOT_POINTS_IDX:
            self.problem += (
                self.path_length_var[point]
                + (self.maximum_path_length - self.ROOT - 1)
                * self.arc_var[self.ROOT][point]
                - self.arc_var[point][self.ROOT]
            ) <= self.maximum_path_length - self.ROOT
        # - $u_i + x_{1i} + (2-K)x_{i1} \geq 2, i=2,...,n$
        for point in self.NON_ROOT_POINTS_IDX:
            self.problem += (
                self.path_length_var[point]
                + self.arc_var[self.ROOT][point]
                + (2 - self.minimum_path_length) * self.arc_var[point][self.ROOT]
            ) >= self.ROOT + 1
        assert self.minimum_path_length >= 4

        # - $u_i - u_j + Lx_{ij} + (L-2)x_{ji} \leq L-1, 2 \leq i \neq j \leq n$
        for point1 in self.NON_ROOT_POINTS_IDX:
            for point2 in self.NON_ROOT_POINTS_IDX:
                if point1 == point2:
                    continue
                self.problem += (
                    self.path_length_var[point1]
                    - self.path_length_var[point2]
                    + self.maximum_path_length * self.arc_var[point1][point2]
                    + (self.maximum_path_length - self.ROOT - 1)
                    * self.arc_var[point2][point1]
                ) <= self.maximum_path_length - self.ROOT + M_LARGE * (
                    self.assignment_var[point1][point2]
                )

        self.running = True
        self.upper_bound = float("inf")
        self.lower_bound = 0
        self.gap = 1
        self.node_count = 0

    def pos(self, point_index):
        """Position of a point"""
        if point_index == self.ORIGIN:
            return np.array((0, 0))
        return self.graph.nodes[point_index]["pos"]

    def euclidean_distance(self, pos1, pos2):
        """Euclidean distance between two points"""
        if isinstance(pos1, int):
            pos1 = self.pos(pos1)
        if isinstance(pos2, int):
            pos2 = self.pos(pos2)
        return np.sqrt(np.sum((pos1 - pos2) ** 2))

    def arc_cost(self, point1_index, point2_index):
        """Real travel cost between two points"""
        # root is always free to return to to reduce a path to a cycle
        if point2_index == self.ROOT:
            return 0
        # special case for when there is only one player
        # only allow origin resetting optimization for the first ring
        if self.player_count == 1:
            if point2_index in (self.FIRST_RING_1, self.FIRST_RING_2):
                return self.euclidean_distance(self.ORIGIN, point2_index)
            return self.euclidean_distance(point1_index, point2_index)
        # minimum of direct travel and origin reset travel
        return min(
            self.euclidean_distance(
                point1_index,
                point2_index,
            ),
            self.euclidean_distance(self.ORIGIN, point2_index),
        )

    def update_solution(self, solution_vector: np.ndarray | None = None):
        solution = {}
        if solution_vector is not None:
            for var, value in zip(self.problem.variables(), solution_vector):
                solution[var] = value

        self.graph.clear_edges()

        def arc_var(point1, point2):
            if solution_vector is None:
                val = self.arc_var[point1][point2].value()
                assert val is not None
                return round(val)
            else:
                return round(solution[self.arc_var[point1][point2]])

        def assignment_var(point1, point2):
            if solution_vector is None:
                val = self.assignment_var[point1][point2].value()
                assert val is not None
                return round(val)
            else:
                return round(solution[self.assignment_var[point1][point2]])

        route_count = 0
        unvisited = self.NON_ROOT_POINTS_IDX.copy()

        for eigth_ring, seventh_ring in self.unassigned_7th_ring_strongholds.items():
            self.graph.add_edge(
                seventh_ring,
                eigth_ring,
                color="red",
                thickness=2,
            )

        assignments = {v: [k] for k, v in self.unassigned_7th_ring_strongholds.items()}
        for point1 in self.POINTS_IDX:
            temp = unvisited.copy()
            for point2 in temp:
                if point1 == point2:
                    continue
                if assignment_var(point1, point2) == 1:
                    assert arc_var(point1, point2) != 1
                    if point1 not in assignments:
                        assignments[point1] = []
                    assignments[point1].append(point2)
                    self.graph.add_edge(point1, point2, color="red", thickness=2)
                    unvisited.remove(point2)
                if arc_var(point1, point2) == 1:
                    assert assignment_var(point1, point2) != 1
        base_path = [self.ROOT]
        for first_point in self.NON_ROOT_POINTS_IDX:
            if arc_var(self.ROOT, first_point) == 1:
                route_count += 1
                color = COLORS[route_count]
                # don't draw origin resets
                if (self.ROOT, first_point) not in self.origin_reset_arcs:
                    self.graph.add_edge(
                        self.ROOT, first_point, color=color, thickness=2
                    )
                unvisited.remove(first_point)
                base_path.append(first_point)
                complete = False
                while not complete:
                    for point in itertools.chain(unvisited, (self.ROOT,)):
                        if arc_var(first_point, point) == 1:
                            if point == self.ROOT:
                                complete = True
                            else:
                                # don't draw origin resets
                                if (first_point, point) not in self.origin_reset_arcs:
                                    self.graph.add_edge(
                                        first_point, point, color=color, thickness=2
                                    )
                                unvisited.remove(point)
                                base_path.append(point)
                                first_point = point
                            break
                    else:
                        assert False
        assert route_count == self.player_count
        assert len(unvisited) == 0

        path = []
        base_path_iter = iter(base_path)
        while True:
            node = next(base_path_iter, None)
            if node is None:
                break
            if node in (self.FIRST_RING_1, self.FIRST_RING_2):
                path.append(["origin", node - 1])
            elif node == 0:
                continue
            else:
                path.append(["goto", node - 1])
            for assigned_node in assignments.get(node, []):
                path.append(["reset", assigned_node - 1])
        if self.callback is not None:
            self.callback(self, path)
        print(self)

    def __str__(self) -> str:
        return (
            f"Iteration: {self.iteration}"
            f" | {self.elapsed_time:.2f} seconds elapsed"
            f" | Upper bound: {self.upper_bound:.2f}"
            f" | Lower bound: {self.lower_bound:.2f}"
            f" | Gap: {self.gap * 100:.2f}%"
            f" | Node count: {self.node_count}"
            f" | State: {'Solving' if self.running else 'Solved'}"
        )

    def highs_callback(self, callback_type, _message, data_out, data_in, _user_data):
        """Generic HiGHS callback handler"""
        if callback_type == highspy.cb.HighsCallbackType.kCallbackMipSolution:
            self.update_solution(data_out.mip_solution)
        if callback_type == highspy.cb.HighsCallbackType.kCallbackMipLogging:
            self.upper_bound = data_out.mip_primal_bound
            self.lower_bound = data_out.mip_dual_bound
            self.gap = data_out.mip_gap
            self.node_count = data_out.mip_node_count
            self.elapsed_time = data_out.running_time
            self.iteration += 1
        if callback_type == highspy.cb.HighsCallbackType.kCallbackMipInterrupt:
            if not self.running:
                data_in.user_interrupt = True

    def run(self):
        self.problem.solve(
            pulp.HiGHS(
                threads=self.threads,
                gapRel=0,
                callbackTuple=(self.highs_callback, None),
                callbacksToActivate=[
                    highspy.cb.HighsCallbackType.kCallbackMipSolution,
                    highspy.cb.HighsCallbackType.kCallbackMipLogging,
                    highspy.cb.HighsCallbackType.kCallbackMipInterrupt,
                ],
                timeLimit=self.time_limit,
                msg=VERBOSE,
            )
        )
        self.update_solution()
        self.running = False


def solve(
    data: list[tuple] | None,
    threads: int,
    time_limit: int,
    player_count: int = 1,
    headless: bool = False,
    callback=None,
):
    # generate test data
    if data is None:
        seed = np.random.randint(2**30)
        np.random.seed(seed)
        print(f"{seed=:08X}")

        sh_rings = []
        for count, minimum, maximum in STRONGHOLD_DATA:
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
        measured_shs = [(sh[0] / SCALE_FACTOR, sh[1] / SCALE_FACTOR) for sh in data]

    compute_thread = ComputeThread(
        measured_shs,
        player_count=player_count,
        threads=threads,
        time_limit=time_limit,
        callback=callback,
    )
    if headless:
        compute_thread.run()
        return

    compute_thread.start()

    def draw_graph(_):
        """FuncAnimation function to constantly redraw the graph"""
        graph = compute_thread.graph
        plt.gca().clear()
        edge_thickness = [graph[u][v].get("thickness", 1) for u, v in graph.edges]
        node_colors = [
            graph.nodes[node].get("color", "#1f78b4") for node in graph.nodes
        ]
        edge_colors = [graph[u][v].get("color", "#1f78b4") for u, v in graph.edges]
        nx.draw(
            graph,
            pos=nx.get_node_attributes(graph, "pos"),
            node_color=node_colors,
            edge_color=edge_colors,
            width=edge_thickness,
            with_labels=True,
        )
        plt.title(str(compute_thread))
        plt.axis("equal")

    _func_anim = FuncAnimation(
        plt.gcf(), draw_graph, interval=100, repeat=True, cache_frame_data=False
    )

    plt.show()
    compute_thread.running = False
    compute_thread.join(2)
