// webapp/static/rain.js
// =====================
// Lluvia de texto arcoiris de fondo para la caja de estado mientras se procesa.
// Reproduce la tecnica de github.com/kokiyodesu/Matrix-Rain (katakana, digitos y letras;
// dos capas: un rastro que se desvanece y las cabezas, que se redibujan y se difuminan),
// con un tono arcoiris por columna. Es decorativa (aria-hidden): el estado real sigue
// siendo el texto de la caja.

const statusRain = (() => {
  const GLYPHS =
    "アァカサタナハマヤャラワガザダバパイィキシチニヒミリヰギジヂビピウゥクスツヌフムユュルグズブヅプエェケセテネヘメレヱゲゼデベペオォコソトノホモヨョロヲゴゾドボポヴッン0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const FONT = '"IBM Plex Mono", monospace'; // el katakana cae a la tipografia del sistema
  const CELL = 14; // px por caracter (tamano de fuente y ancho de columna)
  const STEP = 0.9; // filas que avanza cada cabeza por cuadro
  const FADE = 0.07; // cuanto se desvanece el rastro en cada cuadro
  const TICK = 60; // ms entre cuadros (~17 fps): la caja es baja y asi la caida dura mas

  let timer = null;
  let observer = null;

  function stop() {
    clearInterval(timer);
    timer = null;
    if (observer) observer.disconnect();
    observer = null;
  }

  // Crea la capa dentro de `host` (la antepone) y empieza a llover.
  function mount(host) {
    stop();
    const wrap = document.createElement("div");
    wrap.className = "status-rain";
    wrap.setAttribute("aria-hidden", "true");
    const trail = document.createElement("canvas");
    trail.className = "rain-trail";
    const head = document.createElement("canvas");
    head.className = "rain-head";
    wrap.append(trail, head);
    host.prepend(wrap);

    const tctx = trail.getContext("2d");
    const hctx = head.getContext("2d");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0;
    let h = 0;
    let cols = 0;
    let drops = [];
    let tick = 0;

    function step() {
      if (!w || !h) return;
      // El rastro se desvanece borrando un poco de alfa en cada cuadro
      tctx.globalCompositeOperation = "destination-out";
      tctx.fillStyle = `rgba(0, 0, 0, ${FADE})`;
      tctx.fillRect(0, 0, w, h);
      tctx.globalCompositeOperation = "source-over";
      hctx.clearRect(0, 0, w, h);
      hctx.fillStyle = "#111";
      tick += 1;
      for (let c = 0; c < cols; c += 1) {
        const glyph = GLYPHS.charAt(Math.floor(Math.random() * GLYPHS.length));
        const x = c * CELL + CELL / 2;
        const y = drops[c] * CELL;
        tctx.fillStyle = `hsl(${((c / cols) * 360 + tick * 1.5) % 360} 100% 42%)`;
        tctx.fillText(glyph, x, y);
        hctx.fillText(glyph, x, y);
        if (y > h && Math.random() > 0.85) drops[c] = 0;
        else drops[c] += STEP;
      }
    }

    function size() {
      w = wrap.offsetWidth;
      h = wrap.offsetHeight;
      if (!w || !h) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      for (const c of [tctx, hctx]) {
        c.canvas.width = Math.round(w * dpr);
        c.canvas.height = Math.round(h * dpr);
        c.setTransform(dpr, 0, 0, dpr, 0, 0);
        c.font = `${CELL}px ${FONT}`;
        c.textAlign = "center";
        c.textBaseline = "top";
      }
      cols = Math.ceil(w / CELL);
      drops = new Array(cols).fill(0); // todas arrancan arriba: cae como una cortina y se desfasa sola
      if (reduce) for (let i = 0; i < 30; i += 1) step(); // sin movimiento: un cuadro fijo
    }

    observer = new ResizeObserver(size);
    observer.observe(wrap);
    size();
    if (!reduce) timer = setInterval(step, TICK);
  }

  return { mount, stop };
})();
