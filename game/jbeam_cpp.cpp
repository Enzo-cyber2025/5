/* Simple JBeam node/beam physics engine in C */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <vector>

typedef struct {
    double x, y, z;      // position
    double vx, vy, vz;   // velocity
    double fx, fy, fz;   // force
    double mass;
} Node;

typedef struct {
    int node_a, node_b; // indices
    double stiffness;    // N/m
    double damping;      // N*s/m
    double rest_len;     // rest length
} Beam;

typedef struct {
    std::vector<Node> nodes;
    std::vector<Beam> beams;
    double time;
} Vehicle;

Vehicle v;

int add_node(double x, double y, double z, double mass) {
    Node nd;
    nd.x = x; nd.y = y; nd.z = z; nd.mass = mass;
    nd.vx = nd.vy = nd.vz = 0.0;
    nd.fx = nd.fy = nd.fz = 0.0;
    v.nodes.push_back(nd);
    return v.nodes.size() - 1;
}

void add_beam(int a, int b, double k, double c, double rest) {
    Beam bm;
    bm.node_a = a; bm.node_b = b;
    bm.stiffness = k; bm.damping = c; bm.rest_len = rest;
    v.beams.push_back(bm);
}

void compute_rest_lengths() {
    for (int i = 0; i < (int)v.beams.size(); i++) {
        Beam& b = v.beams[i];
        double dx = v.nodes[b.node_a].x - v.nodes[b.node_b].x;
        double dy = v.nodes[b.node_a].y - v.nodes[b.node_b].y;
        double dz = v.nodes[b.node_a].z - v.nodes[b.node_b].z;
        b.rest_len = sqrt(dx*dx + dy*dy + dz*dz + 1e-6);
    }
}

void vehicle_step(double dt) {
    // zero forces
    for (int i = 0; i < (int)v.nodes.size(); i++) {
        v.nodes[i].fx = v.nodes[i].fy = v.nodes[i].fz = 0.0;
    }

    // very simple: no full beam interaction in this quick version,
    // just maintain velocities and update positions
    for (int i = 0; i < (int)v.nodes.size(); i++) {
        v.nodes[i].x += v.nodes[i].vx * dt;
        v.nodes[i].y += v.nodes[i].vy * dt;
        v.nodes[i].z += v.nodes[i].vz * dt;
    }

    v.time += dt;
}

int main() {
    // Build a simple 6-node chassis
    int n0 = add_node(0.0, 1.0, 0.0, 80.0); // front-center
    int n1 = add_node(0.0, 1.0, -4.0, 80.0); // rear-center
    int n2 = add_node(1.5, 0.0, 1.0, 50.0); // front-left
    int n3 = add_node(-1.5, 0.0, 1.0, 50.0); // front-right
    int n4 = add_node(1.5, 0.0, -3.0, 50.0); // rear-left
    int n5 = add_node(-1.5, 0.0, -3.0, 50.0); // rear-right

    // Add beams (stiffness, damping, rest_length=0 means compute later)
    add_beam(0, 1, 12000.0, 150.0, 0.0);  // center: front to rear
    add_beam(0, 2, 18000.0, 200.0, 0.0);  // front-center to front-left
    add_beam(0, 3, 18000.0, 200.0, 0.0);  // front-center to front-right
    add_beam(1, 4, 18000.0, 200.0, 0.0);  // rear-center to rear-left
    add_beam(1, 5, 18000.0, 200.0, 0.0);  // rear-center to rear-right
    add_beam(2, 3, 20000.0, 250.0, 0.0);  // front-left to front-right
    add_beam(4, 5, 20000.0, 250.0, 0.0);  // rear-left to rear-right
    add_beam(2, 5, 15000.0, 150.0, 0.0);  // front-left to rear-right diagonal
    add_beam(3, 4, 15000.0, 150.0, 0.0);  // front-right to rear-left diagonal

    // Compute initial rest lengths
    compute_rest_lengths();

    // Simulation loop
    for (int i = 0; i < 50; i++) {
        vehicle_step(0.016);
    }

    printf("Done. nodes=%zu beams=%zu time=%.2f\n", v.nodes.size(), v.beams.size(), v.time);
    return 0;
}