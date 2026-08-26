#!/usr/bin/env python3
"""Simple 2D Car Game using pygame - runs on PC, not Android natively.
This is a demonstration source code. An Android APK stub is also included
in this repo for personal use, but a full JBeam-based car game requires
Android SDK/NDK and a game engine, which are not available in this sandbox.
"""

import pygame
import math
import sys

# Initialize pygame
pygame.init()

# Screen dimensions
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Simple Car Demo - PC Version")
clock = pygame.time.Clock()

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)

# Car properties
car_x = WIDTH // 2
car_y = HEIGHT // 2
car_angle = 0
car_speed = 0
acceleration = 0.2
friction = 0.99
turn_speed = 3

# Road settings
road_width = 400

def draw_car(surface, x, y, angle, color):
    """Draw a simple car representation."""
    points = [
        (0, -20),  # nose
        (-15, 15), # rear left
        (-15, -15), # rear right
        (0, 15),   # tail
    ]
    # Rotate points
 rotated_points = []
    for px, py in points:
        rx = px * math.cos(math.radians(angle)) - py * math.sin(math.radians(angle))
        ry = px * math.sin(math.radians(angle)) + py * math.cos(math.radians(angle))
        rotated_points.append((x + rx, y + ry))
    # Draw the car
    pygame.draw.polygon(surface, color, rotated_points)
    # Draw wheels
    wheel_positions = [(-8, 8), (-8, -8), (8, 8), (8, -8)]
    for wx, wy in wheel_positions:
        wx_rotated = wx * math.cos(math.radians(angle)) - wy * math.sin(math.radians(angle))
        wy_rotated = wx * math.sin(math.radians(angle)) + wy * math.cos(math.radians(angle))
        pygame.draw.circle(surface, BLACK, (int(x + wx_rotated), int(y + wy_rotated)), 8)

def main():
    global car_x, car_y, car_angle, car_speed
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        # Input handling
        keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT]:
            car_angle += turn_speed
        if keys[pygame.K_RIGHT]:
            car_angle -= turn_speed
        if keys[pygame.K_UP]:
            car_speed += acceleration
        if keys[pygame.K_DOWN]:
            car_speed -= acceleration

        # Apply friction
        car_speed *= friction

        # Update position
        car_x += car_speed * math.sin(math.radians(car_angle))
        car_y -= car_speed * math.cos(math.radians(car_angle))

        # Keep car in screen bounds (wrap around)
        if car_x < -50: car_x = WIDTH + 50
        if car_x > WIDTH + 50: car_x = -50
        if car_y < -50: car_y = HEIGHT + 50
        if car_y > HEIGHT + 50: car_y = -50

        # Draw everything
        screen.fill((30, 30, 30))  # dark background
        # Draw road outline
        pygame.draw.rect(screen, (50, 50, 50), (WIDTH//2 - road_width//2 - 5, 0, road_width + 10, HEIGHT))
        pygame.draw.rect(screen, (60, 60, 60), (WIDTH//2 - road_width//2, 0, road_width, HEIGHT))
        # Center line
        pygame.draw.line(screen, WHITE, (WIDTH//2, 0), (WIDTH//2, HEIGHT), 2)

        draw_car(screen, car_x, car_y, car_angle, GREEN)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()