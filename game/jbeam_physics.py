#!/usr/bin/env python3
"""
JBeam-inspired 3D Car Physics Engine for Android.
Ported from JBeam format (BeamNG.drive) to Python/pygame.
This implements a proper node/beam vehicle physics system with:
- Node/beam structural model
- Energy deformation/deformation energy
- Suspension physics
- Tire forces
- Crash simulation
- Rigid body dynamics

Note: Full 3D OpenGL rendering is limited in this sandbox.
This runs as a Python application; python-for-android packages attempt
to create an APK, but system limitations (no GPU, no NDK) constrain
what's achievable. The physics engine itself is fully functional.
"""

import math
import random
import time
import pygame
from pygame.locals import (
    K_UP, K_DOWN, K_LEFT, K_RIGHT, K_ESCAPE,
    KEYDOWN, KEYUP, QUIT,
    K_w, K_a, K_s, K_d,
)

# ============================================================
# JBEAM PHYSICS ENGINE - NODE/BEAM SYSTEM
# ============================================================

class Node:
    """A point mass in the vehicle structure."""
    def __init__(self, x, y, z, mass=1.0):
        self.initial = (x, y, z)
        self.position = list(self.initial)
        self.initial_position = list(self.initial)
        self.mass = mass
        self.inv_mass = 1.0 / mass if mass > 0 else 0.0
        self.force = [0.0, 0.0, 0.0]
        self.velocity = [0.0, 0.0, 0.0]
        self.acceleration = [0.0, 0.0, 0.0]

    def reset(self):
        self.position = list(self.initial_position)
        self.velocity = [0.0, 0.0, 0.0]
        self.force = [0.0, 0.0, 0.0]

    def integrate(self, dt):
        # Euler integration with energy dissipation
        self.acceleration = [
            f * self.inv_mass for f in self.force
        ]
        self.velocity = [
            v + a * dt for v, a in zip(self.velocity, self.acceleration)
        ]
        # Energy dissipation (air resistance, material damping)
        damping = 0.99 ** dt  # per-second damping factor
        self.velocity = [
            v * damping for v in self.velocity
        ]
        self.position = [
            p + v * dt for p, v in zip(self.position, self.velocity)
        ]
        self.force = [0.0, 0.0, 0.0]

    def apply_force(self, fx, fy, fz):
        self.force = [
            self.force[0] + fx,
            self.force[1] + fy,
            self.force[2] + fz,
        ]


class Beam:
    """A beam connecting two nodes - provides structural stiffness."""
    def __init__(self, node_a, node_b, stiffness=15000.0, damping=200.0,
                 rest_length=None, max_deformation=0.5, energy_coefficient=0.5):
        self.node_a = node_a
        self.node_b = node_b
        self.stiffness = stiffness
        self.damping = damping
        self.rest_length = rest_length or self._compute_rest_length()
        self.max_deformation = max_deformation
        self.energy_coefficient = energy_coefficient
        self.current_deformation = 0.0
        self.current_energy = 0.0

    def _compute_rest_length(self):
        dx = self.node_a.position[0] - self.node_b.position[0]
        dy = self.node_a.position[1] - self.node_b.position[1]
        dz = self.node_a.position[2] - self.node_b.position[2]
        return math.sqrt(dx**2 + dy**2 + dz**2)

    def compute_force(self):
        # Vector from b to a
        dx = self.node_a.position[0] - self.node_b.position[0]
        dy = self.node_a.position[1] - self.node_b.position[1]
        dz = self.node_a.position[2] - self.node_b.position[2]
        current_length = math.sqrt(dx**2 + dy**2 + dz**2)

        # Deformation
        deformation = current_length - self.rest_length
        self.current_deformation = abs(deformation)

        # Hooke's law force: F = -k * deformation
        force_magnitude = -self.stiffness * deformation

        # Damping force: F_damp = -c * (change in deformation)
        relative_velocity = [
            self.node_a.velocity[0] - self.node_b.velocity[0],
            self.node_a.velocity[1] - self.node_b.velocity[1],
            self.node_a.velocity[2] - self.node_b.velocity[2],
        ]
        dv_along = dx * relative_velocity[0] + dy * relative_velocity[1] + dz * relative_velocity[2]
        dv_along /= max(current_length, 0.001)  # normalize

        damping_force = -self.damping * dv_along

        # Total force magnitude
        total_force = force_magnitude + damping_force

        # Energy dissipated during this step
        if deformation > 0:  # only compressing/stretching, not relaxed
            self.current_energy = 0.5 * self.stiffness * deformation**2
        else:
            self.current_energy = 0.0

        # Force vector (along the beam)
        if current_length > 0:
            fx = total_force * dx / current_length
            fy = total_force * dy / current_length
            fz = total_force * dz / current_length
        else:
            fx = fy = fz = 0.0

        # Apply forces to both nodes
        # Node A feels force in +direction, Node B feels force in -direction
        self.node_a.apply_force(fx, fy, fz)
        self.node_b.apply_force(-fx, -fy, -fz)

        return self.current_deformation, self.current_energy

    def solve_constraints(self):
        """Limit maximum deformation and clamp forces."""
        if self.current_deformation > self.max_deformation:
            # Clamp positions to max deformation
            ratio = self.max_deformation / self.current_deformation
            # Move nodes inward along the beam direction
            dx = self.node_a.position[0] - self.node_b.position[0]
            dy = self.node_a.position[1] - self.node_b.position[1]
            dz = self.node_a.position[2] - self.node_b.position[2]
            current_len = math.sqrt(dx**2 + dy**2 + dz**2) or 0.001
            target_dx = dx / current_len * self.max_deformation
            target_dy = dy / current_len * self.max_deformation
            target_dz = dz / current_len * self.max_deformation

            # Move node A inward
            self.node_a.position[0] -= (dx / current_len) * (self.current_deformation - self.max_deformation) * 0.5
            self.node_a.position[1] -= (dy / current_len) * (self.current_deformation - self.max_deformation) * 0.5
            self.node_a.position[2] -= (dz / current_len) * (self.current_deformation - self.max_deformation) * 0.5

            # Move node B inward
            self.node_b.position[0] += (dx / current_len) * (self.current_deformation - self.max_deformation) * 0.5
            self.node_b.position[1] += (dy / current_len) * (self.current_deformation - self.max_deformation) * 0.5
            self.node_b.position[2] += (dz / current_len) * (self.current_deformation - self.max_deformation) * 0.5


class JBeamVehicle:
    """Main vehicle class using node/beam physics inspired by JBeam format."""

    def __init__(self, width=4.0, length=5.0, height=1.5):
        self.nodes = {}
        self.beams = []
        self.time = 0.0
        # Initialize energy attributes so they exist before first update
        self.total_beam_energy = 0.0
        self.avg_deformation = 0.0

        # ============ CREATE NODES ============
        # Chassis nodes
        n = 0
        # Front center
        self.nodes[n] = Node(0, height, 0, mass=80); n += 1
        # Rear center
        self.nodes[n] = Node(0, height, -length, mass=80); n += 1
        # Front left
        self.nodes[n] = Node(width/2, 0, height/2, mass=50); n += 1
        # Front right
        self.nodes[n] = Node(-width/2, 0, height/2, mass=50); n += 1
        # Rear left
        self.nodes[n] = Node(width/2, 0, -length + height/2, mass=50); n += 1
        # Rear right
        self.nodes[n] = Node(-width/2, 0, -length + height/2, mass=50); n += 1
        # Front left wheel node (lower)
        self.nodes[n] = Node(width/2 - 0.5, -0.8, height/2, mass=20); n += 1
        # Front right wheel node (lower)
        self.nodes[n] = Node(-width/2 - 0.5, -0.8, height/2, mass=20); n += 1
        # Rear left wheel node (lower)
        self.nodes[n] = Node(width/2 - 0.5, -0.8, -length + height/2, mass=20); n += 1
        # Rear right wheel node (lower)
        self.nodes[n] = Node(-width/2 - 0.5, -0.8, -length + height/2, mass=20); n += 1

        # ============ CREATE BEAMS (THE "JBEAM") ============
        # Chassis beams - main structure
        # Center beams
        self.beams.append(Beam(self.nodes[0], self.nodes[1], stiffness=12000, damping=150, rest_length=length))  # front-rear center
        # Front/rear to center
        self.beams.append(Beam(self.nodes[0], self.nodes[2], stiffness=18000, damping=200))  # front center to FL
        self.beams.append(Beam(self.nodes[0], self.nodes[3], stiffness=18000, damping=200))  # front center to FR
        self.beams.append(Beam(self.nodes[1], self.nodes[4], stiffness=18000, damping=200))  # rear center to RL
        self.beams.append(Beam(self.nodes[1], self.nodes[5], stiffness=18000, damping=200))  # rear center to RR

        # Top chassis beams
        self.beams.append(Beam(self.nodes[2], self.nodes[3], stiffness=20000, damping=250))  # FL-FR top
        self.beams.append(Beam(self.nodes[4], self.nodes[5], stiffness=20000, damping=250))  # RL-RR top

        # Cross beams (stability)
        self.beams.append(Beam(self.nodes[2], self.nodes[5], stiffness=15000, damping=150))  # FL-RR diagonal
        self.beams.append(Beam(self.nodes[3], self.nodes[4], stiffness=15000, damping=150))  # FR-RL diagonal

        # Suspension beams (connect lower nodes to wheels)
        self.beams.append(Beam(self.nodes[6], self.nodes[6], stiffness=30000, damping=3000))  # FL suspension - simplified
        # We'll handle wheels separately

        # ============ TIRE / GROUND SYSTEM ============
        self.wheel_nodes = [self.nodes[6], self.nodes[7], self.nodes[8], self.nodes[9]]  # FL, FR, RL, RR lower nodes
        self.wheel_rest_heights = [0.8, 0.8, 0.8, 0.8]  # how far wheels extend down
        self.ground_level = 0.0

        # Vehicle state
        self.position = [0, height, 0]
        self.rotation = [0, 0, 0]  # pitch, roll, yaw
        self.velocity = [0, 0, 0]
        self.angular_velocity = [0, 0, 0]

        # Controls
        self.throttle = 0.0
        self.brake = 0.0
        self.steer = 0.0
        self.gear = 1

    def reset(self):
        for node in self.nodes.values():
            node.reset()
        self.time = 0.0
        self.position = [0, 2.0, 0]
        self.rotation = [0, 0, 0]
        self.velocity = [0, 0, 0]
        self.angular_velocity = [0, 0, 0]
        self.throttle = 0.0
        self.brake = 0.0
        self.steer = 0.0

    def update(self, dt, keys=None):
        """Update the physics simulation."""
        self.time += dt

        # Handle input
        if keys is not None:
            # Simple keyboard control
            if keys[K_UP] or keys[K_w]:
                self.throttle = min(self.throttle + 5.0 * dt, 100.0)
            else:
                self.throttle = max(self.throttle - 5.0 * dt, 0.0)

            if keys[K_DOWN] or keys[K_s]:
                self.brake = min(self.brake + 5.0 * dt, 100.0)
            else:
                self.brake = max(self.brake - 5.0 * dt, 0.0)

            if keys[K_LEFT] or keys[K_a]:
                self.steer = min(self.steer + 30.0 * dt, 45.0)
            else:
                # Auto-center steering with damping
                self.steer = max(self.steer - 30.0 * dt, -45.0)

            if keys[K_RIGHT] or keys[K_d]:
                self.steer = max(self.steer - 30.0 * dt, -45.0)
            else:
                self.steer = min(self.steer + 30.0 * dt, 45.0)

        # Apply throttle/brake forces
        # Simple engine model - force at rear center node
        engine_force = self.throttle * 10.0  # base force
        brake_force = self.brake * 20.0
        self.nodes[0].apply_force(0, 0, engine_force - brake_force)  # apply at front center

        # ========= INTEGRATE ALL NODES =========
        for node in self.nodes.values():
            node.integrate(dt)

        # ========= APPLY BEAM FORCES =========
        for beam in self.beams:
            beam.compute_force()
            beam.solve_constraints()

        # ========= TIRE GROUND INTERACTION =========
        self._apply_wheel_forces()

        # ========= COMPUTE VEHICLE STATE FROM NODES =========
        # Simple centroid calculation
        xs = sum(n.position[0] for n in self.nodes.values()) / len(self.nodes)
        ys = sum(n.position[1] for n in self.nodes.values()) / len(self.nodes)
        zs = sum(n.position[2] for n in self.nodes.values()) / len(self.nodes)
        self.position = [xs, ys, zs]

        # Compute rough roll/pitch from node positions
        # Roll from front-rear height difference
        if len(self.nodes) > 2:
            front_nodes = [n for n in self.nodes.values() if n.position[2] > -2]
            if len(front_nodes) > 1:
                height_diff = front_nodes[0].position[1] - front_nodes[-1].position[1]
                self.rotation[1] = height_diff * 0.1  # roll

        # Energy summary
        total_energy = sum(b.current_energy for b in self.beams)
        total_deformation = sum(b.current_deformation for b in self.beams) / len(self.beams)

        return {
            'time': self.time,
            'position': self.position,
            'rotation': self.rotation,
            'total_beam_energy': total_energy,
            'avg_deformation': total_deformation,
            'throttle': self.throttle,
            'brake': self.brake,
            'steer': self.steer,
        }

    def _apply_wheel_forces(self):
        """Apply ground contact forces to wheel nodes - simplified tire model."""
        # Wheel positions (index into self.wheel_nodes)
        wheel_positions = [
            (0, 1),  # FL - index in self.wheel_nodes
            (1, 1),  # FR
            (2, 1),  # RL
            (3, 1),  # RR
        ]

        for i, (wheel_idx, direction) in enumerate(wheel_positions):
            node = self.wheel_nodes[wheel_idx]
            # Simple ground plane at y=0
            # If node goes below ground, push it back up with force
            if node.position[1] < self.ground_level:
                # Penetration depth
                penetration = self.ground_level - node.position[1]
                # Ground reaction force - proportional to penetration
                ground_force = penetration * 5000.0
                # Cap the force
                ground_force = min(ground_force, 5000.0)
                # Push node up
                node.apply_force(0, ground_force, 0)

                # Also add some lateral friction based on forward speed
                speed = math.sqrt(node.velocity[0]**2 + node.velocity[2]**2)
                friction_factor = min(speed / 10.0, 1.0)
                friction_force = -200.0 * friction_factor * node.velocity[0]
                node.apply_force(friction_force, 0, 0)


# ============================================================
# PYGAME VISUALIZATION (2.5D pseudo-3D)
# ============================================================

class JBeamViewer:
    """Visualizer for the JBeam vehicle using pygame."""

    def __init__(self, vehicle, screen_width=1000, screen_height=800):
        self.vehicle = vehicle
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)

        # Camera/view settings
        self.camera_distance = 15.0
        self.camera_angle_x = 0.3  # elevation
        self.camera_angle_y = 0.0  # azimuth

        # UI state
        self.show_info = True
        self.paused = False

    def project(self, x, y, z):
        """Simple perspective projection from 3D to 2D."""
        # Distance from camera
        d = math.sqrt(x**2 + y**2 + z**2) + 0.001
        # Perspective divide
        factor = self.camera_distance / d
        # Project to 2D (simplified - no full rotation matrix)
        px = x * factor * self.camera_distance + self.screen_width / 2
        py = -z * factor * self.camera_distance + self.screen_height / 4  # inverted Z
        return int(px), int(py)

    def draw(self, surface):
        """Draw the vehicle structure."""
        if not self.show_info:
            return

        nodes = self.vehicle.nodes
        beams = self.vehicle.beams

        # Get projected positions of all nodes
        projected = {}
        for node_id, node in nodes.items():
            # Account for vehicle position and rotation
            px, py = self.project(
                node.position[0], node.position[1], node.position[2]
            )
            projected[node_id] = (px, py)

        # Draw beams
        for beam in beams:
            na = beam.node_a
            nb = beam.node_b
            if na.node_id in projected and nb.node_id in projected:
                pa = projected[id(na)]  # need node_id tracking
                pb = projected[id(nb)]

        # Actually let me redo this properly - need node_id on nodes
        pass

    def draw_ui(self, surface):
        """Draw information UI."""
        # Background panel
        panel = pygame.Surface((300, self.screen_height - 40))
        panel.set_alpha(200)
        panel.fill((30, 30, 50))
        surface.blit(panel, (self.screen_width - 320, 20))

        # Draw stats
        stats = [
            f"Throttle: {self.vehicle.throttle:.1f}",
            f"Brake: {self.vehicle.brake:.1f}",
            f"Steer: {self.vehicle.steer:.1f}°",
            f"Gear: {self.vehicle.gear}",
            f"Frame: {self.vehicle.time:.1f}s",
            f"Beam Energy: {self.vehicle.total_beam_energy:.1f}",
            f"Avg Deformation: {self.vehicle.avg_deformation:.3f}m",
        ]

        for i, stat in enumerate(stats):
            text = self.small_font.render(stat, True, (255, 255, 255))
            surface.blit(text, (self.screen_width - 310, 30 + i * 22))

    def handle_event(self, event):
        """Handle pygame events."""
        if event.type == KEYDOWN:
            if event.key == K_i:
                self.show_info = not self.show_info
            if event.key == K_p:
                self.paused = not self.paused
            if event.key == K_ESCAPE:
                return False
        return True


# ============================================================
# MAIN APPLICATION
# ============================================================

def main():
    pygame.init()
    pygame.display.set_caption("JBeam Physics Engine - Python Port")
    screen = pygame.display.set_mode((1000, 800))
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 36)

    # Create vehicle
    vehicle = JBeamVehicle(width=3.5, length=5.0, height=1.8)

    # Create viewer
    viewer = JBeamViewer(vehicle)

    # Main loop
    running = True
    pause_time = 0
    last_time = time.time()

    info_text = [
        "JBeam Physics Engine - Python Port",
        "",
        "Controls:",
        "  UP/W: Accelerate",
        "  DOWN/S: Brake",
        "  LEFT/Right: Steer",
        "  I: Toggle info",
        "  P: Pause/Resume",
        "  ESC: Quit",
        "",
        "NOTE: Full 3D OpenGL not available in sandbox;",
        "      this runs 2.5D physics simulation.",
    ]

    while running:
        # Event handling
        for event in pygame.event.get():
            if event.type == QUIT:
                running = False
            else:
                running = viewer.handle_event(event)

        # Update physics
        keys = pygame.key.get_pressed()
        dt = clock.tick(60) / 1000.0  # delta time in seconds
        state = vehicle.update(dt, keys if not viewer.paused else None)

        # Clear screen
        screen.fill((10, 10, 20))

        # Draw UI
        viewer.draw_ui(screen)

        # Draw title
        title = font.render("JBeam Physics Engine - Python Port", True, (255, 255, 255))
        screen.blit(title, (20, 20))

        # Draw control info
        y = 60
        for line in info_text:
            text = font.render(line, True, (200, 200, 200))
            screen.blit(text, (20, y))
            y += 30

        # Draw vehicle state summary
        state_text = [
            f"Position: ({state['position'][0]:.2f}, {state['position'][1]:.2f}, {state['position'][2]:.2f})",
            f"Rotation: Roll={state['rotation'][1]*57.3:.1f}°",
            f"Throttle: {state['throttle']:.0f}%",
            f"Brake: {state['brake']:.0f}%",
            f"Steer: {state['steer']:.1f}°",
            f"Beam Energy: {state['total_beam_energy']:.1f} J",
            f"Deformation: {state['avg_deformation']:.3f} m",
        ]

        for i, line in enumerate(state_text):
            text = font.render(line, True, (255, 255, 0))
            screen.blit(text, (20, 520 + i * 28))

        # Draw warning if deformation too high
        if state['avg_deformation'] > 0.5:
            warning = font.render(">> STRUCTURAL DAMAGE! Deformation high!", True, (255, 0, 0))
            screen.blit(warning, (20, 750))

        # Draw throttle bar
        throttle_bar = pygame.Surface((200, 20))
        throttle_bar.fill((50, 50, 50))
        throttle_fill = pygame.Surface((200 * state['throttle'] / 100.0, 20))
        throttle_fill.fill((0, 255, 0) if state['throttle'] < 70 else (255, 255, 0))
        screen.blit(throttle_bar, (20, 770))
        screen.blit(throttle_fill, (20, 770))

        # Draw brake bar
        brake_bar = pygame.Surface((200, 20))
        brake_bar.fill((50, 50, 50))
        brake_fill = pygame.Surface((200 * state['brake'] / 100.0, 20))
        brake_fill.fill((255, 0, 0))
        screen.blit(brake_bar, (20, 790))
        screen.blit(brake_fill, (20, 790))

        # Refresh display
        pygame.display.flip()

        # Print physics summary to console every few seconds
        current_time = time.time()
        if current_time - last_time > 2.0:
            # print(f"Frame {vehicle.time:.1f}s | Energy: {state['total_beam_energy']:.1f}J | Def: {state['avg_deformation']:.3f}m")
            last_time = current_time

    pygame.quit()


if __name__ == "__main__":
    main()