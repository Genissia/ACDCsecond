"""GLSL sources for the Thunder Canyon renderer.

Ported from ../index.html's <script id="vs"/"fs"> blocks (WebGL1 / GLSL ES
100) to desktop GLSL 330 core for moderngl. The raymarching math (noise,
fbm, terrain, lightning, shading) is byte-for-byte the same algorithm as the
browser version -- only the shader-stage boilerplate changed:
  - `attribute` / `varying` -> `in` / `out`
  - `gl_FragColor` -> a declared `out vec4 fragColor`
  - added an explicit `#version 330` + precision line

Keep this in sync with index.html's shaders by hand if you tune the look
in one place -- there is no build step that shares them.
"""

VERTEX_SRC = """
#version 330
in vec2 aPos;
void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }
"""

FRAGMENT_SRC = """
#version 330
precision highp float;
out vec4 fragColor;

uniform vec2  uRes;
uniform float uTime;
uniform float uMove;   // camera distance travelled down the canyon
uniform float uLow;    // bass / beat energy   0..~1.5
uniform float uMid;    // mids / melody        0..~1.5
uniform float uHigh;   // highs / shimmer      0..~1.5
uniform float uBeat;   // lightning flash env  0..1 (decays)
uniform float uSeed;   // random per-strike

// ---------- hash / value noise / fbm ----------
float hash(vec2 p){
  p = fract(p*vec2(123.34, 456.21));
  p += dot(p, p+45.32);
  return fract(p.x*p.y);
}
float noise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  f = f*f*(3.0-2.0*f);
  float a = hash(i);
  float b = hash(i+vec2(1.0,0.0));
  float c = hash(i+vec2(0.0,1.0));
  float d = hash(i+vec2(1.0,1.0));
  return mix(mix(a,b,f.x), mix(c,d,f.x), f.y);
}
float fbm(vec2 p){
  float v = 0.0, a = 0.5;
  for(int i=0;i<5;i++){ v += a*noise(p); p = p*2.03 + 7.1; a *= 0.5; }
  return v;
}
// ridged fbm -> crisp mountain crestlines
float ridged(vec2 p){
  float v = 0.0, a = 0.5, f = 1.0;
  for(int i=0;i<5;i++){
    float n = noise(p*f);
    n = 1.0 - abs(n*2.0 - 1.0);
    v += a*n*n;
    f *= 2.0; a *= 0.5;
  }
  return v;
}

// winding path the camera follows down the canyon
float pathX(float z){
  return 1.7*sin(z*0.10) + 0.7*sin(z*0.043 + 1.3);
}
float pathSlope(float z){
  return 1.7*0.10*cos(z*0.10) + 0.7*0.043*cos(z*0.043 + 1.3);
}

// terrain / canyon height field.  x,z world coords.
float terrain(vec2 xz){
  float x = xz.x, z = xz.y;
  float dx = abs(x - pathX(z));
  float halfW = 1.5;                 // narrow gap the camera threads
  float t = max(0.0, dx - halfW);
  float wall = t*t*0.6 + t*0.9;      // canyon walls

  // ridged noise -> crisp mountain crestlines
  float m  = ridged(vec2(x*0.26, z*0.26)) * 2.7;
  m += ridged(vec2(x*0.62 + 13.0, z*0.62)) * 1.1;
  m += fbm(vec2(x*1.7, z*1.7)) * 0.25;          // fine roughness

  // AUDIO: low -> mountains grow / breathe;  mid -> crest detail (melody)
  float grow = 1.0 + uLow*1.15;
  float h = (wall + m*(0.45 + uMid*0.9)) * grow;

  // smooth low canyon floor near the path (the "road")
  float floorMask = smoothstep(halfW*0.1, halfW*1.25, dx);
  h *= floorMask + 0.012;
  return h - 0.3;
}

vec3 terrainNormal(vec2 xz){
  float e = 0.05;
  float h  = terrain(xz);
  float hx = terrain(xz + vec2(e,0.0));
  float hz = terrain(xz + vec2(0.0,e));
  return normalize(vec3(h-hx, e, h-hz));
}

// jagged lightning bolt in the sky, uv = aspect-corrected screen coords (y up)
float boltPath(vec2 uv, float seed, float xbase){
  // near-vertical channel from horizon (y~0) up to top (y~0.6), jittering horizontally
  float y = clamp(uv.y, -0.05, 0.75);
  float jag  = (fbm(vec2(y*7.0, seed*23.0)) - 0.5) * 0.9;
  jag += (fbm(vec2(y*19.0 + seed*4.0, seed*5.0)) - 0.5) * 0.35; // finer kinks
  float xline = xbase + jag * (uv.y + 0.15);
  float d = abs(uv.x - xline);
  float core = smoothstep(0.014, 0.0, d);
  float glow = smoothstep(0.14, 0.0, d) * 0.35;
  float above = smoothstep(-0.02, 0.06, uv.y);      // only above the horizon
  return (core + glow) * above;
}
float lightning(vec2 uv, float seed){
  float x0 = (hash(vec2(seed, 1.7))*2.0 - 1.0) * 0.55;
  float b  = boltPath(uv, seed, x0);
  // a couple of branches
  b += boltPath(uv, seed+3.1, x0 + 0.18) * 0.5;
  b += boltPath(uv, seed+7.7, x0 - 0.22) * 0.4;
  return b;
}

// ---------- palette ----------
vec3 skyColor(vec3 rd, float flash, float seed, vec2 uv){
  float h = clamp(rd.y*1.7 + 0.08, 0.0, 1.0);
  vec3 hor = vec3(0.22, 0.26, 0.35);   // storm horizon light
  vec3 top = vec3(0.02, 0.028, 0.06);
  vec3 col = mix(hor, top, pow(h, 0.55));
  // turbulent storm clouds
  float cl  = fbm(vec2(uv.x*1.8 + seed*0.05, uv.y*3.0 - uTime*0.015));
  float cl2 = fbm(vec2(uv.x*3.6 - 1.7,       uv.y*5.2 - uTime*0.03));
  float clouds = smoothstep(0.42, 0.9, cl*0.6 + cl2*0.4);
  col = mix(col, vec3(0.035, 0.045, 0.08), clouds*0.75);
  // flash floods the sky, strongest low and near the bolt
  col += flash * vec3(0.42, 0.52, 0.78) * (0.35 + 0.65*(1.0 - h));
  float bolt = lightning(uv, seed);
  col += bolt * flash * vec3(0.9, 0.95, 1.0) * 4.0;
  return col;
}

void main(){
  vec2 uv = (gl_FragCoord.xy - 0.5*uRes) / uRes.y;   // y up, aspect correct

  // ---- camera: thread forward along the winding canyon ----
  float camZ = uMove;
  float shake = uBeat * 0.03;
  vec3 ro = vec3(pathX(camZ) + sin(uTime*17.0)*shake, 1.05 + cos(uTime*13.0)*shake, camZ);
  vec3 fwd = normalize(vec3(pathSlope(camZ)*1.1, -0.09, 1.0));
  vec3 rgt = normalize(cross(vec3(0.0,1.0,0.0), fwd));
  vec3 upv = cross(fwd, rgt);
  vec3 rd  = normalize(fwd + uv.x*rgt*1.2 + uv.y*upv*1.2);

  float flash = uBeat*uBeat;   // punchy flash envelope

  // ---- raymarch the height field ----
  float t = 0.4;
  float hit = -1.0;
  for(int i=0;i<150;i++){
    vec3 p = ro + rd*t;
    float d = p.y - terrain(p.xz);
    if(d < 0.0016*t){ hit = t; break; }
    t += max(0.02, d*0.42);
    if(t > 85.0) break;
  }

  vec3 col;
  if(hit > 0.0){
    vec3 p = ro + rd*hit;
    vec3 n = terrainNormal(p.xz);
    vec3 ld = normalize(vec3(0.35, 0.6, -0.5));
    float diff = clamp(dot(n, ld), 0.0, 1.0);
    float cel  = floor(diff*3.0 + 0.5) / 3.0;          // posterized cel shading
    float upf  = 0.5 + 0.5*n.y;                         // sky-facing amount

    // mid-toned storm-rock, tinted by height
    float hgt = clamp(p.y*0.10 + 0.15, 0.0, 1.0);
    vec3 rock = mix(vec3(0.07,0.10,0.15), vec3(0.30,0.40,0.55), hgt);
    vec3 ambient = mix(vec3(0.06,0.08,0.12), vec3(0.20,0.26,0.36), upf); // hemispheric
    vec3 lit  = rock * (ambient + cel*0.75);

    // sky rim-light picks out the crests
    float rim = pow(1.0 - clamp(n.y, 0.0, 1.0), 3.0);
    lit += rim * vec3(0.08,0.13,0.22) * 0.8;

    // lightning floods the canyon with cold light
    lit += flash * (0.30 + 0.7*diff) * vec3(0.5,0.62,0.9);

    // ---- aerial fog into the storm ----
    float fog = clamp(1.0 - exp(-t*0.03), 0.0, 1.0);
    vec3 sky = skyColor(rd, flash, uSeed, uv);
    col = mix(lit, sky, fog);
  } else {
    col = skyColor(rd, flash, uSeed, uv);
  }

  // ---- grade: contrast S-curve, vignette, faint scanline ----
  col = clamp(col, 0.0, 1.0);
  col = mix(col, col*col*(3.0 - 2.0*col), 0.2);         // gentle contrast
  float vig = smoothstep(1.5, 0.35, length(uv));
  col *= 0.68 + 0.32*vig;
  col *= 1.0 - 0.025*sin(gl_FragCoord.y*1.7);           // faint scanline
  col += (hash(gl_FragCoord.xy + uTime) - 0.5) * 0.01;  // subtle dither
  col += flash * 0.04;

  fragColor = vec4(clamp(col,0.0,1.0), 1.0);
}
"""
