"""核心规则和无窗口渲染检查：python3 -m unittest test_main.py"""
import os
import math
from pathlib import Path
import random
import tempfile
import unittest

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame

from main import LEFT, FLOOR, STEP, Ball, GameState, Renderer, contact_between


class GameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1060, 760))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = GameState(Path(self.temp.name) / 'score.json', random.Random(1))

    def tearDown(self):
        self.temp.cleanup()

    def test_drop_rebounds_and_stays_in_container(self):
        self.assertTrue(self.state.drop())
        self.assertFalse(self.state.drop())  # 投放间隔
        ball = self.state.balls[0]
        previous_vy = 0
        bounced = False
        for _ in range(250):
            self.state.step(STEP)
            bounced |= previous_vy > 200 and ball.vy < -100
            previous_vy = ball.vy
        self.assertTrue(bounced)
        self.assertLessEqual(ball.y + ball.half_height, FLOOR + 0.1)

    def test_ellipse_rotation_changes_contact(self):
        circle = Ball(1, 200, 250)
        oval = Ball(2, 200, 294)
        self.assertIsNone(contact_between(circle, oval))
        oval.angle = math.pi / 2
        self.assertIsNotNone(contact_between(circle, oval))

    def test_non_touching_ellipses_do_not_merge(self):
        game = self.state
        a, b = Ball(2, 200, 220), Ball(2, 200, 270)
        game.balls = [a, b]
        game.resolve_pairs()
        self.assertEqual(game.balls, [a, b])
        self.assertEqual(game.score, 0)
        a.angle = b.angle = math.pi / 2
        game.resolve_pairs()
        self.assertEqual([ball.level for ball in game.balls], [3])

    def test_rotated_ellipse_wall_and_floor_bounds(self):
        oval = Ball(4, LEFT + 5, FLOOR, vx=-100, vy=200, angle=math.pi / 4)
        self.state.collide_walls(oval)
        self.assertGreaterEqual(oval.x - oval.half_width, LEFT - 1e-8)
        self.assertLessEqual(oval.y + oval.half_height, FLOOR + 1e-8)
        self.assertTrue(math.isfinite(oval.spin))

    def test_off_center_collision_imparts_rotation(self):
        oval = Ball(2, 200, 250, vx=100)
        circle = Ball(3, 239, 278, vx=-100)
        self.state.balls = [oval, circle]
        self.state.resolve_pairs()
        self.assertGreater(abs(oval.spin) + abs(circle.spin), 1e-4)

    def test_mixed_contact_normal_passes_through_circle_center(self):
        circle = Ball(1, 125.77723815539623, 302.3617816414195)
        oval = Ball(7, 230, 300)
        for a, b in ((circle, oval), (oval, circle)):
            nx, ny, _, cx, cy = contact_between(a, b)
            normal_lever = (cx - circle.x) * ny - (cy - circle.y) * nx
            self.assertAlmostEqual(normal_lever, 0, places=6)

    def test_pause_stops_physics(self):
        self.state.balls = [Ball(2, 200, 250, vy=100, spin=1)]
        self.state.paused = True
        self.state.step()
        self.assertEqual(self.state.elapsed, 0)
        self.assertEqual(self.state.balls[0].y, 250)
        self.assertEqual(self.state.balls[0].angle, 0)

    def test_danger_line_uses_rotated_height(self):
        game = self.state
        oval = Ball(2, 230, 165, age=1)
        game.balls = [oval]
        game.step()
        self.assertEqual(game.warning, 0)
        oval.angle = math.pi / 2
        game.warning = 1.999
        game.step()
        self.assertTrue(game.ended)

    def test_crowded_stack_does_not_remain_deeply_embedded(self):
        game = self.state
        game.balls = [Ball(level, 100 + (level % 3) * 90,
                           200 + (level // 3) * 60, angle=0.17 * level)
                      for level in range(1, 9)]
        maximum = 0
        for step in range(2400):
            game.ended = False
            game.warning = 0
            game.step()
            if step >= 1800:
                for index, a in enumerate(game.balls):
                    for b in game.balls[index + 1:]:
                        contact = contact_between(a, b)
                        if contact:
                            maximum = max(maximum, contact[2])
        self.assertLess(maximum, 1.0)

    def test_merge_combo_and_high_score(self):
        game = self.state
        game.balls = [game.make_ball(1, 180, 420), game.make_ball(1, 210, 420)]
        game.step()
        self.assertEqual([ball.level for ball in game.balls], [2])
        first_score = game.score
        game.balls.extend([game.make_ball(1, 270, 420), game.make_ball(1, 300, 420)])
        game.step()
        self.assertEqual(game.combo, 2)
        self.assertGreater(game.score - first_score, first_score)
        self.assertEqual(game.best, game.score)
        self.assertTrue(game.score_path.exists())

    def test_overflow_countdown_and_render(self):
        game = self.state
        game.balls = [game.make_ball(8, 230, 200)]
        for _ in range(380):
            game.balls[0].y = 200
            game.balls[0].vy = 0
            game.step()
        self.assertTrue(game.ended)
        renderer = Renderer()
        self.assertEqual(renderer.draw(game, False).get_size(), (1060, 760))


if __name__ == '__main__':
    unittest.main()
