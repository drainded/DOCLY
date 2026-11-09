// webapp/static/splash.js
// ========================
// Pantalla de carga de inicio (logo multicolor + porcentaje) y aviso de servidor dormido.
//
// En un hosting gratuito el servidor se duerme tras un rato sin visitas y tarda en despertar.
// Mientras el navegador espera la pagina, es el propio hosting quien muestra su pantalla de
// espera; esta pantalla se ve cuando la pagina ya llego y comprueba que el servidor responde
// (GET /health). El porcentaje avanza con una curva suave mientras se espera y salta a 100 cuando
// el servidor contesta, las fuentes cargaron y paso un minimo de tiempo (para que el logo se vea).
//
// Si el servidor no contesta en SLOW_MS (p. ej. se durmio con la pestana abierta), la pantalla se
// quita igualmente para que la pagina sea utilizable, y el primer clic muestra un aviso (app.js)
// mientras este script sigue sondeando hasta que el servidor despierte.
//
// Expone `window.serverState = { awake, whenAwake(callback) }`.

(function () {
  const MIN_MS = 1000; // minimo visible: que el logo y el porcentaje se aprecien
  const SLOW_MS = 6000; // pasado esto, se muestra la pagina aunque el servidor no conteste
  const PING_EVERY_MS = 500;
  const BACKGROUND_PING_EVERY_MS = 3000;
  const TICK_MS = 60;

  const splash = document.getElementById("splash");
  const pctEl = document.getElementById("splash-pct");
  const barEl = document.getElementById("splash-bar-fill");
  const msgEl = document.getElementById("splash-msg");

  const waiting = [];
  let awake = false;

  window.serverState = {
    get awake() {
      return awake;
    },
    whenAwake(callback) {
      if (awake) callback();
      else waiting.push(callback);
    },
  };

  function markAwake() {
    if (awake) return;
    awake = true;
    for (const callback of waiting.splice(0)) callback();
  }

  async function ping() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetch("/health", { cache: "no-store", signal: controller.signal });
      return response.ok;
    } catch (_) {
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  // Sondea hasta que el servidor conteste (cada `every` ms) y entonces lo marca despierto.
  async function pollUntilAwake(every) {
    while (!awake) {
      if (await ping()) markAwake();
      else await new Promise((resolve) => setTimeout(resolve, every));
    }
  }

  const fontsReady = (document.fonts && document.fonts.ready) || Promise.resolve();
  let fontsDone = false;
  fontsReady.then(() => (fontsDone = true), () => (fontsDone = true));

  pollUntilAwake(PING_EVERY_MS);

  if (!splash) return;

  const started = performance.now();
  let pct = 0;
  let leaving = false;

  function paint() {
    const shown = Math.min(100, Math.round(pct));
    pctEl.textContent = String(shown);
    barEl.style.transform = `scaleX(${shown / 100})`;
  }

  function leave() {
    if (leaving) return;
    leaving = true;
    clearInterval(timer);
    splash.classList.add("leaving");
    const finish = () => {
      document.documentElement.classList.remove("splash-on");
      splash.remove();
    };
    splash.addEventListener("transitionend", finish, { once: true });
    setTimeout(finish, 600); // por si la transicion no corre (movimiento reducido, pestana oculta)
    // Servidor aun dormido: el sondeo sigue en segundo plano (el aviso del primer clic lo usa).
    if (!awake) pollUntilAwake(BACKGROUND_PING_EVERY_MS);
  }

  const timer = setInterval(() => {
    const elapsed = performance.now() - started;
    const ready = awake && fontsDone && elapsed >= MIN_MS;
    // Mientras espera, el porcentaje se acerca a 90 sin llegar; al estar listo, sube a 100.
    const goal = ready ? 100 : 90 * (1 - Math.exp(-elapsed / 1500));
    pct = Math.min(goal, pct + Math.max(1, (goal - pct) * 0.2));
    paint();

    if (!awake && elapsed > 2500) msgEl.textContent = "El servidor está despertando…";
    if (pct >= 100) setTimeout(leave, 150);
    else if (elapsed >= SLOW_MS && !awake) leave();
  }, TICK_MS);

  paint();
})();
