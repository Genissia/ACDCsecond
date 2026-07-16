"""GLSL sources for the Thunder Canyon renderer.

Desktop GLSL 330 core, written for moderngl. The raymarching math (noise,
fbm, terrain, lightning, shading) all lives in the fragment shader below;
tune the look here -- there is no separate build step.
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
uniform float uBeat;   // lightning flash env  0..1 (decays), height = strike strength
uniform float uSeed;   // random per-strike
uniform float uEnergy; // slow overall loudness 0..1 (song structure)
uniform float uPulse;  // tempo-synced throb   0..1 (retriggers each beat)
uniform float uSpike;  // spike eruption env   0..1 (rises then recedes)
uniform float uWarm;   // timbral brightness   0..1 (spectral centroid)
uniform float uHue;    // melodic hue          0..1 (chroma pitch class)

// melodic colour: a smooth cosine palette biased toward the stormy family so
// the scene is TINTED by the music, not turned into a rainbow.
vec3 melodyColor(float t){
  vec3 c = 0.5 + 0.5*cos(6.28318*(t + vec3(0.0, 0.33, 0.67)));
  vec3 storm = vec3(0.35, 0.5, 0.9);          // cold storm-blue anchor
  return mix(storm, c, 0.6);                   // pull the hue back toward blue
}

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

// jagged rock spikes that erupt on heavy strikes. amp 0..1 (strike-driven);
// a field of angular shards on a jittered grid, only some cells spawn one.
float spikeField(vec2 xz, float amp){
  if(amp <= 0.001) return 0.0;
  vec2 cell = xz * 1.4;                   // spacing between potential spikes
  vec2 id   = floor(cell);
  vec2 f    = fract(cell);
  float rnd  = hash(id);                  // does this cell erupt? / height
  float rnd2 = hash(id + 7.3);            // radius / jitter
  float rnd3 = hash(id + 3.1);            // extra height variance
  float present = step(0.58, rnd);        // ~42% of cells erupt
  vec2 q = f - (vec2(rnd, rnd2)*0.5 + 0.25);
  // faceted (diamond/chamfer) cross-section -> angular sides, not round blobs
  float rad  = 0.12 + 0.07*rnd2;
  float facet = (abs(q.x) + abs(q.y))*0.62 + max(abs(q.x), abs(q.y))*0.5;
  float body  = pow(clamp(1.0 - facet/rad, 0.0, 1.0), 1.35);
  // a sharp needle tip rising above the faceted base
  float tip   = pow(clamp(1.0 - length(q)/(rad*0.55), 0.0, 1.0), 2.2) * 0.6;
  float tall  = 1.3 + 2.1*rnd3;
  return (body + tip) * tall * present * amp;
}

// terrain / canyon height field.  x,z world coords.
float terrain(vec2 xz){
  float x = xz.x, z = xz.y;
  float dx = abs(x - pathX(z));
  // AUDIO: canyon breathes -- wide & open when calm, clenched narrow when the
  // song is loud, with an extra squeeze on every beat (tempo pulse).
  float halfW = mix(1.9, 1.05, uEnergy) - 0.12 * uPulse;
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

  // AUDIO: spikes erupt on strong strikes (uSpike RISES then recedes) and grow
  // bigger with bass (uLow). They sprout from the MOUNTAIN WALLS on both sides
  // -- never from the canyon floor: the mask is zero near the path and fades
  // in across the wall faces.
  float spikeAmp = uSpike * (0.30 + 0.90*uLow);
  float wallMask = smoothstep(halfW*0.80, halfW*1.02, dx)      // off the floor
                 * (1.0 - smoothstep(halfW*1.7, halfW*2.9, dx)); // concentrate low
  h += spikeField(vec2(x, z), spikeAmp * wallMask) * 2.3;

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
  // AUDIO: branchiness scales with strike strength -- light hits = a single
  // bolt, the heaviest hits fork into extra branches.
  float br = smoothstep(0.45, 0.95, uBeat);
  b += boltPath(uv, seed+3.1, x0 + 0.18) * 0.5 * br;
  b += boltPath(uv, seed+7.7, x0 - 0.22) * 0.4 * br;
  // extra-strong ("mega") strikes (uBeat > 1) fork much more -- a wall of bolts
  float br2 = smoothstep(1.15, 1.8, uBeat);
  b += boltPath(uv, seed+11.3, x0 + 0.34) * 0.45 * br2;
  b += boltPath(uv, seed+17.1, x0 - 0.40) * 0.42 * br2;
  b += boltPath(uv, seed+23.9, x0 + 0.08) * 0.38 * br2;
  return b;
}

// ---------- palette ----------
vec3 skyColor(vec3 rd, float flash, float seed, vec2 uv){
  vec3 tint = melodyColor(uHue);                     // AUDIO: melody -> colour
  float h = clamp(rd.y*1.7 + 0.08, 0.0, 1.0);
  vec3 hor = mix(vec3(0.22, 0.26, 0.35), tint*0.55, 0.35);   // storm horizon, tinted
  vec3 top = mix(vec3(0.02, 0.028, 0.06), tint*0.12, 0.30);
  vec3 col = mix(hor, top, pow(h, 0.55));
  // turbulent storm clouds -- churn faster with the highs (cymbals/shimmer)
  float clv = 1.0 + uHigh*2.2;
  float cl  = fbm(vec2(uv.x*1.8 + seed*0.05, uv.y*3.0 - uTime*0.015*clv));
  float cl2 = fbm(vec2(uv.x*3.6 - 1.7,       uv.y*5.2 - uTime*0.03*clv));
  float clouds = smoothstep(0.42, 0.9, cl*0.6 + cl2*0.4);
  col = mix(col, vec3(0.035, 0.045, 0.08), clouds*0.75);

  // AUDIO: aurora ribbons ripple across the upper sky during loud/sustained
  // sections (uEnergy), shimmering with the highs, coloured by the melody.
  float auroraAmt = smoothstep(0.35, 0.85, uEnergy);
  if(auroraAmt > 0.001){
    float skyMask = smoothstep(0.03, 0.5, uv.y);     // upper sky only
    float ribbon = 0.0;
    for(int k=0; k<3; k++){
      float fk = float(k);
      float y0 = 0.20 + 0.15*fk + 0.04*sin(uTime*0.3 + fk*1.7);
      float w  = fbm(vec2(uv.x*2.2 + fk*3.1, uTime*0.12 + fk));
      ribbon += exp(-pow((uv.y - y0 - 0.13*w)/0.045, 2.0));
    }
    ribbon *= skyMask * (0.5 + 0.6*uHigh);
    vec3 auroraCol = mix(vec3(0.15, 0.9, 0.55), tint, 0.5);  // green + melody hue
    col += ribbon * auroraCol * auroraAmt * 0.9;
  }

  // flash floods the sky (compressed above flash=1 so mega strikes don't blow
  // to pure white); the bolt core keeps the full flash for an intense glow.
  float floodF = flash <= 1.0 ? flash : 1.0 + (flash - 1.0)*0.35;
  col += floodF * vec3(0.42, 0.52, 0.78) * (0.35 + 0.65*(1.0 - h));
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
    vec3 tint = melodyColor(uHue);                     // AUDIO: melody -> colour
    vec3 ld = normalize(vec3(0.35, 0.6, -0.5));
    float diff = clamp(dot(n, ld), 0.0, 1.0);
    float cel  = floor(diff*3.0 + 0.5) / 3.0;          // posterized cel shading
    // fill light from the opposite side lifts the shadowed wall (less black)
    float fill = clamp(dot(n, normalize(vec3(-0.45, 0.35, 0.5))), 0.0, 1.0) * 0.45;
    float upf  = 0.5 + 0.5*n.y;                         // sky-facing amount

    // mid-toned storm-rock, tinted by height
    float hgt = clamp(p.y*0.10 + 0.15, 0.0, 1.0);
    vec3 rock = mix(vec3(0.11,0.15,0.21), vec3(0.36,0.47,0.62), hgt);
    // hemispheric ambient -- brighter floor (lifts dark side) + a melody tint
    vec3 ambient = mix(vec3(0.16,0.19,0.26), vec3(0.32,0.39,0.52), upf);
    ambient = mix(ambient, ambient*tint*1.5, 0.30);
    // key + fill light, tinted by the melody, brighter with timbral warmth
    vec3 lightCol = mix(vec3(0.85,0.90,1.05), tint, 0.45) * (0.85 + 0.5*uWarm);
    vec3 lit  = rock * (ambient + (cel*0.90 + fill) * lightCol);

    // sky rim-light picks out the crests (melody-tinted)
    float rim = pow(1.0 - clamp(n.y, 0.0, 1.0), 3.0);
    lit += rim * mix(vec3(0.08,0.13,0.22), tint*0.35, 0.5) * 0.9;

    // AUDIO: highs -> icy sparkle glinting along the crest edges (cymbals)
    float spark = pow(max(noise(p.xz*9.0 + uTime*2.0), 0.0), 8.0);
    lit += uHigh * spark * rim * vec3(0.55,0.70,0.95) * 3.0;

    // lightning floods the canyon with cold light. Compress the FLOOD above
    // flash=1 so mega strikes keep structure instead of whiting out (normal
    // strikes, flash<=1, are unchanged); the bolt core itself stays full-bright.
    float floodF = flash <= 1.0 ? flash : 1.0 + (flash - 1.0)*0.35;
    lit += floodF * (0.30 + 0.7*diff) * vec3(0.5,0.62,0.9);

    // ---- aerial fog into the storm ----
    // AUDIO: thick & claustrophobic when quiet, clears to open up on the drops
    float fogK = mix(0.055, 0.020, uEnergy);
    float fog = clamp(1.0 - exp(-t*fogK), 0.0, 1.0);
    vec3 sky = skyColor(rd, flash, uSeed, uv);
    col = mix(lit, sky, fog);
  } else {
    col = skyColor(rd, flash, uSeed, uv);
  }

  // ---- grade: contrast S-curve, vignette, faint scanline ----
  col = clamp(col, 0.0, 1.0);
  col = mix(col, col*col*(3.0 - 2.0*col), 0.2);         // gentle contrast
  float vig = smoothstep(1.5, 0.35, length(uv));
  // brighter vignette (base lifted to 0.90) + a subtle beat-synced throb
  col *= (0.90 + 0.10*vig) * (1.0 + 0.05*uPulse);
  col *= 1.0 - 0.025*sin(gl_FragCoord.y*1.7);           // faint scanline
  col += (hash(gl_FragCoord.xy + uTime) - 0.5) * 0.01;  // subtle dither
  col += flash * 0.04;

  fragColor = vec4(clamp(col,0.0,1.0), 1.0);
}
"""
