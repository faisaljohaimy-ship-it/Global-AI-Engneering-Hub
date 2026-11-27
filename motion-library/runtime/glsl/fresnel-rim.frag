precision mediump float;

uniform vec2 u_resolution;
uniform float u_time;

void main() {
  vec2 uv = (gl_FragCoord.xy * 2.0 - u_resolution.xy) / min(u_resolution.x, u_resolution.y);
  float radius = length(uv);
  float sphere = sqrt(max(0.0, 1.0 - radius * radius));
  float fresnel = pow(1.0 - sphere, 2.4);
  float pulse = 0.82 + 0.18 * sin(u_time * 1.7);
  vec3 base = vec3(0.025, 0.06, 0.12);
  vec3 rim = vec3(0.18, 0.78, 1.0) * fresnel * pulse;
  float alpha = smoothstep(1.02, 0.96, radius);
  gl_FragColor = vec4(base + rim, alpha);
}
