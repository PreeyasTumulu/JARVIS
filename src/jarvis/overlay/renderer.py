"""Draws a Scene and its words with OpenGL. The reactor shader is shared with the page."""

from __future__ import annotations

from array import array
from pathlib import Path
from typing import Any, cast

import moderngl
from PIL import Image

from jarvis.overlay.scene import Scene

SHADER = Path(__file__).resolve().parents[1] / "server" / "static" / "reactor.glsl"

FULLSCREEN_VS = """#version 330
void main() {
  vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}"""
CARD_VS = """#version 330
in vec2 a_pos;
in vec2 a_uv;
out vec2 v_uv;
void main() { v_uv = a_uv; gl_Position = vec4(a_pos, 0.0, 1.0); }"""
CARD_FS = """#version 330
uniform sampler2D u_tex;
uniform float u_alpha;
in vec2 v_uv;
out vec4 color;
void main() { color = texture(u_tex, v_uv) * u_alpha; }"""


class Renderer:
    def __init__(self, ctx: moderngl.Context, width: int, height: int) -> None:
        self.ctx = ctx
        self.width = width
        self.height = height
        self.reactor = ctx.program(
            vertex_shader=FULLSCREEN_VS,
            fragment_shader="#version 330\n" + SHADER.read_text(encoding="utf-8"),
        )
        self._quad = ctx.vertex_array(self.reactor, [])
        self.card_program = ctx.program(vertex_shader=CARD_VS, fragment_shader=CARD_FS)
        self._card_buffer = ctx.buffer(reserve=4 * 4 * 4)
        self._card_vao = ctx.vertex_array(
            self.card_program, [(self._card_buffer, "2f 2f", "a_pos", "a_uv")]
        )
        self._texture: Any = None

    def resize(self, width: int, height: int) -> None:
        self.width, self.height = width, height

    def set_card(self, image: Image.Image | None, *, center_y_px: float) -> None:
        """Upload the words. Only on a change: drawing text every frame would be wasted work."""
        if self._texture is not None:
            self._texture.release()
            self._texture = None
        if image is None:
            return
        self._texture = self.ctx.texture(image.size, 4, image.tobytes())
        self._texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        half_w = image.width / self.width
        half_h = image.height / self.height
        y = 2.0 * center_y_px / self.height - 1.0
        corners = [
            (-half_w, y + half_h, 0.0, 0.0),
            (half_w, y + half_h, 1.0, 0.0),
            (-half_w, y - half_h, 0.0, 1.0),
            (half_w, y - half_h, 1.0, 1.0),
        ]
        self._card_buffer.write(array("f", [value for row in corners for value in row]).tobytes())

    def draw(self, scene: Scene) -> None:
        ctx = self.ctx
        ctx.viewport = (0, 0, self.width, self.height)
        ctx.clear(0.0, 0.0, 0.0, 0.0)
        ctx.disable(moderngl.BLEND)
        program = self.reactor
        values = {
            "u_res": (float(self.width), float(self.height)),
            "u_t": scene.time,
            "u_burst": scene.burst,
            "u_dim": scene.dim,
            "u_edge": scene.edge,
            "u_core": scene.core,
            "u_core_pos": (0.0, scene.core_y),
            "u_core_size": scene.core_size,
            "u_level": scene.level,
            "u_sweep": scene.sweep,
            "u_calm": scene.calm,
            "u_color_a": tuple(scene.color_a),
            "u_color_b": tuple(scene.color_b),
            "u_bars": tuple(scene.bars),
        }
        for name, value in values.items():
            if name in program:  # the driver may drop one the shader ends up not using
                cast(moderngl.Uniform, program[name]).value = value
        self._quad.render(moderngl.TRIANGLES, vertices=3)
        if self._texture is not None and scene.text_alpha > 0.004:
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
            self._texture.use(0)
            cast(moderngl.Uniform, self.card_program["u_alpha"]).value = scene.text_alpha
            self._card_vao.render(moderngl.TRIANGLE_STRIP)
